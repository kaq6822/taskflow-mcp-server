"""A job has at most one run in progress, however the triggers interleave.

The backend and the MCP server are separate processes, each with its own
`RunEngine`. Two engine instances on separate sessions stand in for them here:
in-memory state cannot see across, so only the database index can refuse the
second start.
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.db import SessionLocal, get_session
from app.engine.run_engine import JobBusyError, RunEngine
from app.main import app
from app.models import Job, Run


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


@pytest.mark.asyncio
async def test_concurrent_starts_from_two_processes_create_one_run(session):
    session.add(_job())
    await session.commit()

    results = await asyncio.gather(
        _trigger(RunEngine()), _trigger(RunEngine()), return_exceptions=True
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
async def test_rest_trigger_conflicts_with_a_run_owned_by_the_other_process(session):
    """A run started through MCP lives only in the MCP process's engine. The
    REST trigger must still answer 409 with that run's id."""
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
async def test_startup_recovery_finalizes_only_this_process_runs(session):
    """After a restart a RUNNING row has no task behind it and would block the
    job forever. Each process finalizes its own; the other process may still
    be executing its runs."""
    session.add(_job())
    other_job = _job()
    other_job.id = "mcp-job"
    session.add(other_job)
    await session.commit()

    mine = await _trigger(RunEngine("api"))
    async with SessionLocal() as s:
        theirs = (
            await RunEngine("mcp").start(
                s, job=await s.get(Job, "mcp-job"), trigger="mcp", actor="t"
            )
        ).id
        await s.commit()

    recovered = await RunEngine("api").recover_orphans()

    assert recovered == [mine]
    async with SessionLocal() as s:
        assert (await s.get(Run, mine)).status == "FAILED"
        assert (await s.get(Run, theirs)).status == "RUNNING"
    # The job accepts a new run again.
    assert await _trigger(RunEngine("api")) != mine
