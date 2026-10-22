"""REST surface for run parameters: declaration on save, values on trigger."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_session
from app.engine.run_engine import RunEngine
from app.main import app
from app.models import Job

BRANCH = {"name": "branch", "default": "dev", "pattern": r"[A-Za-z0-9._/-]+"}


@pytest.fixture(autouse=True)
def fresh_engine(monkeypatch):
    """Only the trigger is under test. A fresh engine per test with `launch`
    stubbed keeps the background task from running, and keeps the live-run
    bookkeeping it would have cleared from leaking into the next test as 409."""
    engine = RunEngine()
    monkeypatch.setattr(engine, "launch", lambda run_id: None)
    monkeypatch.setattr("app.api.runs.get_engine", lambda: engine)


async def _client(session):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _job_body(params: list[dict]) -> dict:
    return {
        "id": "be-deploy",
        "name": "Backend deploy",
        "owner": "ops",
        "params": params,
        "steps": [{"id": "build", "cmd": ["echo", "ok"], "timeout": 1, "deps": []}],
    }


@pytest.mark.asyncio
async def test_create_job_with_params_round_trips(session):
    client = await _client(session)
    try:
        async with client:
            res = await client.post("/api/jobs", json=_job_body([BRANCH, {"name": "tag"}]))
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 201
    # Omitted `default`/`pattern` come back as explicit nulls.
    assert res.json()["params"] == [BRANCH, {"name": "tag", "default": None, "pattern": None}]


@pytest.mark.asyncio
async def test_create_job_rejects_default_outside_pattern(session):
    client = await _client(session)
    try:
        async with client:
            res = await client.post(
                "/api/jobs",
                json=_job_body([{"name": "branch", "default": "a b", "pattern": "[a-z]+"}]),
            )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 400
    assert await session.get(Job, "be-deploy") is None


@pytest.mark.asyncio
async def test_patch_params_stores_the_full_shape(session):
    """`exclude_unset` recurses into list entries; a partial entry must still
    be stored with every key."""
    session.add(Job(**_job_body([])))
    await session.commit()

    client = await _client(session)
    try:
        async with client:
            res = await client.patch("/api/jobs/be-deploy", json={"params": [{"name": "branch"}]})
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200
    assert (await session.get(Job, "be-deploy")).params == [
        {"name": "branch", "default": None, "pattern": None}
    ]


@pytest.mark.asyncio
async def test_patch_rejects_invalid_param_name(session):
    session.add(Job(**_job_body([BRANCH])))
    await session.commit()

    client = await _client(session)
    try:
        async with client:
            res = await client.patch(
                "/api/jobs/be-deploy", json={"params": [{"name": "my-branch"}]}
            )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 400
    assert (await session.get(Job, "be-deploy")).params == [BRANCH]


@pytest.mark.asyncio
async def test_patch_with_explicit_null_params_is_ignored(session):
    session.add(Job(**_job_body([BRANCH])))
    await session.commit()

    client = await _client(session)
    try:
        async with client:
            res = await client.patch("/api/jobs/be-deploy", json={"params": None})
            listed = await client.get("/api/jobs")
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200
    assert listed.status_code == 200
    assert (await session.get(Job, "be-deploy")).params == [BRANCH]


@pytest.mark.asyncio
async def test_run_records_given_params(session):
    session.add(Job(**_job_body([BRANCH])))
    await session.commit()

    client = await _client(session)
    try:
        async with client:
            res = await client.post(
                "/api/jobs/be-deploy/runs", json={"params": {"branch": "feature/x"}}
            )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 201
    assert res.json()["params"] == {"branch": "feature/x"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params,code",
    [
        ({"branch": "bad branch"}, "INVALID_PARAM"),
        ({"branch": 3}, "INVALID_PARAM"),
        ({"target": "x"}, "UNKNOWN_PARAM"),
    ],
)
async def test_run_with_bad_params_returns_400(session, params, code):
    session.add(Job(**_job_body([BRANCH])))
    await session.commit()

    client = await _client(session)
    try:
        async with client:
            res = await client.post("/api/jobs/be-deploy/runs", json={"params": params})
            audit = await client.get("/api/audit", params={"result": "DENY"})
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 400
    assert res.json()["detail"]["error"] == code
    assert any(e["kind"] == "job.run" and e["target"] == "be-deploy" for e in audit.json())
