"""REST surface for multi-artifact jobs: alias validation and error mapping."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_session
from app.main import app
from app.models import Job
from app.services.artifacts import save_upload_bytes


async def _client(session):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _job_body(consumes: list[dict]) -> dict:
    return {
        "id": "deploy-app",
        "name": "Deploy App",
        "owner": "ops",
        "consumes_artifacts": consumes,
        "steps": [{"id": "deploy", "cmd": ["echo", "ok"], "timeout": 1, "deps": []}],
    }


@pytest.mark.asyncio
async def test_create_job_with_aliases_round_trips(session):
    client = await _client(session)
    try:
        async with client:
            res = await client.post(
                "/api/jobs",
                json=_job_body(
                    [{"alias": "jar", "name": "myapp"}, {"alias": "conf", "name": "myapp-config"}]
                ),
            )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 201
    assert res.json()["consumes_artifacts"] == [
        {"alias": "jar", "name": "myapp"},
        {"alias": "conf", "name": "myapp-config"},
    ]


@pytest.mark.asyncio
async def test_create_job_rejects_duplicate_alias(session):
    client = await _client(session)
    try:
        async with client:
            res = await client.post(
                "/api/jobs",
                json=_job_body(
                    [{"alias": "jar", "name": "a"}, {"alias": "jar", "name": "b"}]
                ),
            )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 400
    assert "duplicate alias" in res.text
    assert await session.get(Job, "deploy-app") is None


@pytest.mark.asyncio
async def test_create_job_rejects_alias_that_is_not_env_safe(session):
    client = await _client(session)
    try:
        async with client:
            res = await client.post(
                "/api/jobs", json=_job_body([{"alias": "my-jar", "name": "myapp"}])
            )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 400
    assert "invalid alias" in res.text


@pytest.mark.asyncio
async def test_run_with_missing_artifact_returns_404(session):
    session.add(Job(**_job_body([{"alias": "jar", "name": "ghost"}])))
    await session.commit()

    client = await _client(session)
    try:
        async with client:
            res = await client.post("/api/jobs/deploy-app/runs", json={})
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 404
    assert res.json()["detail"]["error"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_run_with_scanning_artifact_returns_409(session):
    art = await save_upload_bytes(
        session=session, name="myapp", version="v1", ext="jar", uploader="t", data=b"x"
    )
    art.status = "SCANNING"
    session.add(Job(**_job_body([{"alias": "jar", "name": "myapp"}])))
    await session.commit()

    client = await _client(session)
    try:
        async with client:
            res = await client.post("/api/jobs/deploy-app/runs", json={})
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 409
    assert res.json()["detail"]["error"] == "NOT_READY"


@pytest.mark.asyncio
async def test_run_with_undeclared_alias_returns_400(session):
    await save_upload_bytes(
        session=session, name="myapp", version="v1", ext="jar", uploader="t", data=b"x"
    )
    session.add(Job(**_job_body([{"alias": "jar", "name": "myapp"}])))
    await session.commit()

    client = await _client(session)
    try:
        async with client:
            res = await client.post(
                "/api/jobs/deploy-app/runs",
                json={"artifact_refs": {"conf": "uploads://myapp@v1"}},
            )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 400
    assert res.json()["detail"]["error"] == "UNKNOWN_ALIAS"
