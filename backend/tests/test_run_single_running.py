"""A job has at most one run in progress, however the triggers interleave.

The REST API and the MCP endpoint share one `RunEngine` (`python -m app`), but
its lookup and insert are not atomic: two triggers on separate sessions can
both pass the lookup. The database index is what refuses the second insert.
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.db import SessionLocal, get_session
from app.engine.run_engine import INTERRUPTED_MESSAGE, JobBusyError, RunEngine, get_engine
from app.main import app
from app.models import Job, Run, RunStep


def _job() -> Job:
    return Job(
        id="once-job",
        name="Once",
        owner="ops",
        tags=[],
        consumes_artifacts=[],
        steps=[{"id": "s1", "cmd": ["echo", "hi"], "timeout": 5, "deps": []}],
    )


async def _trigger(engine: RunEngine) -> int:
    async with SessionLocal() as s:
        job = await s.get(Job, "once-job")
        run = await engine.start(s, job=job, trigger="manual", actor="t")
        await s.commit()
        return run.id


async def _running_count() -> int:
    async with SessionLocal() as s:
        return (
            await s.execute(
                select(func.count()).where(Run.job_id == "once-job", Run.status == "RUNNING")
            )
        ).scalar_one()


async def _step_state(run_id: int) -> str | None:
    async with SessionLocal() as s:
        return (
            await s.execute(select(RunStep.state).where(RunStep.run_id == run_id))
        ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_concurrent_starts_create_one_run(session, monkeypatch):
    session.add(_job())
    await session.commit()

    # Hold both triggers after their lookup until both have looked, so both
    # see a free job — the interleaving that used to start two runs.
    engine = RunEngine()
    real = RunEngine.running_run_id
    looked = 0
    both_looked = asyncio.Event()

    async def lookup_then_wait(s, job_id):
        nonlocal looked
        found = await real(s, job_id)
        looked += 1
        if looked == 2:
            both_looked.set()
        if looked <= 2:
            await both_looked.wait()
        return found

    monkeypatch.setattr(engine, "running_run_id", lookup_then_wait)
    results = await asyncio.gather(
        _trigger(engine), _trigger(engine), return_exceptions=True
    )

    started = [r for r in results if isinstance(r, int)]
    busy = [r for r in results if isinstance(r, JobBusyError)]
    assert len(started) == 1, results
    assert len(busy) == 1, results
    assert busy[0].current_run_id == started[0]
    assert await _running_count() == 1


@pytest.mark.asyncio
async def test_insert_rejects_a_start_that_slipped_past_the_lookup(session, monkeypatch):
    """The up-front lookup is only an early answer. A start that passes it
    while another trigger's run is being inserted must still be refused."""
    session.add(_job())
    await session.commit()
    first = await _trigger(RunEngine())

    late = RunEngine()
    calls = 0
    real = RunEngine.running_run_id

    async def stale_first_lookup(s, job_id):
        nonlocal calls
        calls += 1
        return None if calls == 1 else await real(s, job_id)

    monkeypatch.setattr(late, "running_run_id", stale_first_lookup)

    with pytest.raises(JobBusyError) as exc:
        await _trigger(late)
    assert exc.value.current_run_id == first
    assert await _running_count() == 1


@pytest.mark.asyncio
async def test_finished_run_frees_the_job(session):
    session.add(_job())
    await session.commit()
    first = await _trigger(RunEngine())
    async with SessionLocal() as s:
        (await s.get(Run, first)).status = "SUCCESS"
        await s.commit()

    second = await _trigger(RunEngine())
    assert second != first


@pytest.mark.asyncio
async def test_rest_trigger_conflicts_with_a_run_started_elsewhere(session):
    """A run started by any engine — here one the REST handler has never seen —
    makes the REST trigger answer 409 with that run's id."""
    session.add(_job())
    await session.commit()
    other = await _trigger(RunEngine())

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/jobs/once-job/runs", json={})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == {"error": "CONFLICT", "current_run_id": other}


@pytest.mark.asyncio
async def test_idempotency_replay_still_wins_over_busy(session):
    """While the job runs, its own key replays the run (201) and any other key
    is a conflict (409) — the busy check must not shadow the replay."""
    session.add(_job())
    await session.commit()

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await client.post(
                "/api/jobs/once-job/runs", json={"idempotency_key": "k1"}
            )
            replay = await client.post(
                "/api/jobs/once-job/runs", json={"idempotency_key": "k1"}
            )
            other = await client.post(
                "/api/jobs/once-job/runs", json={"idempotency_key": "k2"}
            )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 201, first.text
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == first.json()["id"]
    if other.status_code == 409:
        assert other.json()["detail"]["current_run_id"] == first.json()["id"]
    else:
        # `echo` can finish before the third request lands; then the job is
        # free again and a new run is the correct answer.
        assert other.status_code == 201, other.text


@pytest.mark.asyncio
async def test_startup_recovery_finalizes_leftover_runs(session):
    """After a restart a RUNNING row has no task behind it and would block the
    job forever. Startup fails every such run, since all runs belong to this
    one process."""
    session.add(_job())
    await session.commit()
    left = await _trigger(RunEngine())

    recovered = await RunEngine().recover_orphans()

    assert recovered == [left]
    async with SessionLocal() as s:
        run = await s.get(Run, left)
        assert run.status == "FAILED"
        assert run.err_message == INTERRUPTED_MESSAGE
    # The job accepts a new run again.
    assert await _trigger(RunEngine()) != left


@pytest.mark.asyncio
async def test_rest_cancel_stops_a_run_started_over_mcp(session):
    """MCP's run_job and the REST cancel use the same engine, so the cancel
    reaches the running step instead of only marking the row."""
    import sys
    import time

    job = _job()
    job.steps = [
        {
            "id": "s1",
            "cmd": [sys.executable, "-c", "import time; time.sleep(30)"],
            "timeout": 60,
            "deps": [],
        }
    ]
    session.add(job)
    await session.commit()

    engine = get_engine()
    run_id = await _trigger(engine)  # what tools.run_job does
    engine.launch(run_id)
    task = engine._tasks[run_id]
    for _ in range(50):
        if await _step_state(run_id) == "RUNNING":
            break
        await asyncio.sleep(0.1)

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    began = time.monotonic()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(f"/api/runs/{run_id}/cancel")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200, resp.text
    await asyncio.wait_for(task, timeout=10)

    assert time.monotonic() - began < 10
    async with SessionLocal() as s:
        assert (await s.get(Run, run_id)).status == "FAILED"
    assert await _step_state(run_id) == "FAILED"
    assert engine.live_run_for("once-job") is None
