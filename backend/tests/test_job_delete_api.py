from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_session
from app.main import app
from app.models import Job, Run


@pytest.mark.asyncio
async def test_delete_job_denies_running_run(session):
    job = Job(
        id="running-job",
        name="Running Job",
        owner="ops",
        steps=[{"id": "deploy", "cmd": ["echo", "ok"], "timeout": 1, "deps": []}],
    )
    session.add(job)
    await session.flush()
    run = Run(
        job_id=job.id,
        status="RUNNING",
        trigger="manual",
        actor="tester",
        order=["deploy"],
    )
    session.add(run)
    await session.commit()

    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.delete(f"/api/jobs/{job.id}")
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 409
    assert res.json()["detail"] == {"error": "CONFLICT", "current_run_id": run.id}
    assert await session.get(Job, job.id) is not None
