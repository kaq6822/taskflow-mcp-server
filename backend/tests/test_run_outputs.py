"""Run outputs: steps publish `::output key=value`, the run record keeps them."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_session
from app.engine.run_engine import RunEngine
from app.engine.worker import WorkerResult
from app.main import app
from app.models import Job, Run
from app.services.outputs import OutputLineError, parse_output_line

# ---- parsing ---------------------------------------------------------------


@pytest.mark.parametrize(
    "line,expected",
    [
        ("::output commit=9535057abc", ("commit", "9535057abc")),
        ("::output branch=feature/x=y", ("branch", "feature/x=y")),  # first `=` splits
        ("::output commit=abc\r", ("commit", "abc")),
        ("building cms.jar", None),
        ("  ::output commit=abc", None),  # must start the line
    ],
)
def test_parse_output_line(line, expected):
    assert parse_output_line(line) == expected


@pytest.mark.parametrize(
    "line",
    ["::output commit", "::output =abc", "::output 1st=x", "::output commit=", "::output k=a\x1bb"],
)
def test_malformed_output_line_is_reported(line):
    with pytest.raises(OutputLineError):
        parse_output_line(line)


# ---- engine ----------------------------------------------------------------


def _job(steps: list[dict]) -> Job:
    return Job(id="deploy", name="deploy", owner="t", tags=[], consumes_artifacts=[], params=[], steps=steps)


async def _run_with_lines(session, monkeypatch, lines_by_step: dict, states: dict | None = None):
    """Drive the real run loop; each step "prints" the given (stream, line) pairs."""
    states = states or {}
    steps = []
    prev = None
    for sid in lines_by_step:
        steps.append({"id": sid, "cmd": ["echo", sid], "timeout": 5, "deps": [prev] if prev else []})
        prev = sid
    job = _job(steps)
    session.add(job)
    await session.flush()
    engine = RunEngine()
    run = await engine.start(session, job=job, trigger="manual", actor="t")
    await session.commit()

    async def fake_execute_argv(cmd, **kwargs):
        sid = cmd[1]
        for stream, line in lines_by_step[sid]:
            kwargs["on_line"](stream, line)
        state = states.get(sid, "SUCCESS")
        return WorkerResult(state=state, elapsed=0.0, exit_code=0 if state == "SUCCESS" else 1)

    monkeypatch.setattr("app.engine.run_engine.execute_argv", fake_execute_argv)
    await engine._run_loop_body(job.id, run.id)
    await session.refresh(run)
    return run


@pytest.mark.asyncio
async def test_outputs_from_all_steps_are_merged_and_later_wins(session, monkeypatch):
    run = await _run_with_lines(
        session,
        monkeypatch,
        {
            "source": [("stdout", "::output commit=aaa"), ("stdout", "::output branch=dev")],
            "deploy": [("stdout", "deploy OK"), ("stdout", "::output commit=bbb")],
        },
    )
    assert run.status == "SUCCESS"
    assert run.outputs == {"commit": "bbb", "branch": "dev"}


@pytest.mark.asyncio
async def test_stderr_and_malformed_lines_are_not_recorded(session, monkeypatch):
    run = await _run_with_lines(
        session,
        monkeypatch,
        {"s1": [("stderr", "::output commit=from-stderr"), ("stdout", "::output bad line")]},
    )
    assert run.outputs == {}


@pytest.mark.asyncio
async def test_outputs_of_a_failed_step_are_kept_with_the_failed_status(session, monkeypatch):
    """Readers pick runs by status; the record still shows what was attempted."""
    run = await _run_with_lines(
        session, monkeypatch, {"s1": [("stdout", "::output commit=ccc")]}, states={"s1": "FAILED"}
    )
    assert run.status == "FAILED"
    assert run.outputs == {"commit": "ccc"}


# ---- API -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_last_successful_run_outputs_are_readable(session):
    """The read a deploy gate relies on: newest SUCCESS run of a job, with outputs."""
    session.add(_job([{"id": "s1", "cmd": ["echo"], "timeout": 1, "deps": []}]))
    session.add(Run(job_id="deploy", status="SUCCESS", actor="t", outputs={"commit": "old"}))
    session.add(Run(job_id="deploy", status="SUCCESS", actor="t", outputs={"commit": "new"}))
    session.add(Run(job_id="deploy", status="FAILED", actor="t", outputs={"commit": "broken"}))
    await session.commit()

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            res = await c.get("/api/runs", params={"job_id": "deploy", "status": "SUCCESS", "limit": 1})
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200
    assert [r["outputs"] for r in res.json()] == [{"commit": "new"}]
