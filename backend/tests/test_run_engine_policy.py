from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.run_engine import RunEngine, _fmt_argv
from app.models import AuditEvent, Job, Run, RunStep


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        (["echo", "hello"], "echo hello"),
        ([], ""),
        (["echo", 1], "['echo', 1]"),
        ("echo hello", "'echo hello'"),
        (None, "None"),
    ],
)
def test_fmt_argv_never_raises(cmd, expected):
    """Log rendering must survive a malformed cmd so the policy check can run."""
    assert _fmt_argv(cmd) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd", [[], ["echo", 1], "echo hello", None])
async def test_malformed_cmd_is_denied_not_crashed(session: AsyncSession, cmd):
    """A steps blob that reached the DB by another route must fail as a policy
    DENY — not as an unhandled exception out of the step task."""
    job = Job(id="job-shape", name="job-shape", owner="ops", steps=[])
    run = Run(
        job_id=job.id, status="RUNNING", trigger="manual", actor="admin", order=["s1"]
    )
    session.add_all([job, run])
    await session.flush()
    session.add(RunStep(run_id=run.id, step_id="s1", state="PENDING"))
    await session.commit()

    result = await RunEngine()._execute_step(
        run_id=run.id,
        step_id="s1",
        step_spec={"id": "s1", "cmd": cmd, "timeout": 1},
        actor="admin",
        trigger="manual",
    )

    assert result.state == "FAILED"
    assert result.exit_code == -1
    assert "non-empty list of strings" in result.err_message

    rs = (
        await session.execute(
            select(RunStep).where(RunStep.run_id == run.id, RunStep.step_id == "s1")
        )
    ).scalar_one()
    assert rs.state == "FAILED"

    events = (
        await session.execute(
            select(AuditEvent).where(AuditEvent.target == f"run #{run.id} step s1")
        )
    ).scalars().all()
    assert [(e.kind, e.result) for e in events] == [("policy.violation", "DENY")]
