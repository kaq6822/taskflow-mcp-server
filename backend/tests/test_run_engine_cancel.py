from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.run_engine import CANCELLED_MESSAGE, RunEngine
from app.models import Job, Run, RunStep, utcnow


@pytest.mark.asyncio
async def test_cancel_finished_run_returns_none(session: AsyncSession):
    job = Job(
        id="deploy-api",
        name="Deploy API",
        owner="admin",
        steps=[],
    )
    run = Run(
        job_id=job.id,
        status="SUCCESS",
        trigger="manual",
        actor="admin",
        order=[],
        finished_at=utcnow(),
    )
    session.add_all([job, run])
    await session.flush()

    result = await RunEngine().cancel(session, run.id)

    assert result is None
    await session.refresh(run)
    assert run.status == "SUCCESS"
    assert run.err_message is None


@pytest.mark.asyncio
async def test_cancel_running_run_without_task_finalizes_run_and_step(
    session: AsyncSession,
):
    started_at = utcnow() - timedelta(seconds=5)
    job = Job(
        id="deploy-api",
        name="Deploy API",
        owner="admin",
        steps=[
            {"id": "build", "cmd": ["echo", "build"], "deps": []},
            {"id": "deploy", "cmd": ["echo", "deploy"], "deps": ["build"]},
        ],
    )
    run = Run(
        job_id=job.id,
        status="RUNNING",
        trigger="manual",
        actor="admin",
        order=["build", "deploy"],
        started_at=started_at,
    )
    session.add_all([job, run])
    await session.flush()
    running_step = RunStep(
        run_id=run.id,
        step_id="build",
        state="RUNNING",
        started_at=started_at,
    )
    pending_step = RunStep(run_id=run.id, step_id="deploy", state="PENDING")
    session.add_all([running_step, pending_step])
    await session.flush()

    engine = RunEngine()
    engine._live[job.id] = run.id

    result = await engine.cancel(session, run.id)

    assert result is run
    await session.flush()
    await session.refresh(run)
    await session.refresh(running_step)
    await session.refresh(pending_step)
    assert engine.live_run_for(job.id) is None
    assert run.status == "FAILED"
    assert run.err_message == CANCELLED_MESSAGE
    assert run.finished_at is not None
    assert run.duration_sec >= 5
    assert run.failed_step == "build"
    assert running_step.state == "FAILED"
    assert running_step.finished_at is not None
    assert running_step.elapsed_sec >= 5
    assert pending_step.state == "PENDING"
