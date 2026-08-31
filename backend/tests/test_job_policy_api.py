from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import AuditEvent


def _payload(job_id: str, cmd: list[str]) -> dict:
    return {
        "id": job_id,
        "name": job_id,
        "owner": "ops",
        "steps": [{"id": "s1", "cmd": cmd, "timeout": 1, "deps": []}],
    }


async def _post_job(session, payload: dict):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/jobs", json=payload)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cmd",
    [
        ["/bin/bash", "/opt/taskflow/scripts/deploy.sh"],
        ["rm", "-rf", "./build"],
        ["docker", "compose", "up", "-d"],
    ],
)
async def test_any_command_can_be_saved(session, cmd):
    """No argv allowlist: a step may run any command."""
    res = await _post_job(session, _payload(f"job-{cmd[0].strip('/').replace('/', '-')}", cmd))
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_cd_is_still_rejected_and_audited(session):
    res = await _post_job(session, _payload("job-cd", ["cd", "/srv/app"]))
    assert res.status_code == 400
    assert "step.cwd" in res.json()["detail"]

    events = (await session.execute(select(AuditEvent).where(AuditEvent.target == "job-cd"))).scalars().all()
    assert [(e.kind, e.result) for e in events] == [("policy.violation", "DENY")]
