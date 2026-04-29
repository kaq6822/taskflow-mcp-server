from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.db import get_session
from app.main import app
from app.models import Job, Run, RunStep


@pytest.mark.asyncio
async def test_get_run_logs_returns_step_log_tail(session):
    job = Job(
        id="log-job",
        name="Log Job",
        owner="ops",
        steps=[{"id": "deploy", "cmd": ["echo", "ok"], "timeout": 1, "deps": []}],
    )
    session.add(job)
    await session.flush()

    run = Run(
        job_id=job.id,
        status="FAILED",
        trigger="manual",
        actor="tester",
        order=["deploy"],
        failed_step="deploy",
        err_message="non-zero exit 1",
    )
    session.add(run)
    await session.flush()

    log_path = settings.logs_dir / str(run.id) / "deploy.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("line 1\nline 2\nline 3\n")
    session.add(
        RunStep(
            run_id=run.id,
            step_id="deploy",
            state="FAILED",
            elapsed_sec=0.1,
            logs_path=str(log_path),
            exit_code=1,
        )
    )
    await session.commit()

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get(f"/api/runs/{run.id}/logs/deploy?tail=2")
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200
    assert res.text == "line 2\nline 3\n"
