"""Run-trigger REST surface: idempotency replay."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_session
from app.main import app
from app.models import Job


async def _client(session):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _job() -> Job:
    return Job(
        id="idem-job",
        name="Idem",
        owner="ops",
        tags=[],
        consumes_artifacts=[],
        steps=[{"id": "s1", "cmd": ["echo", "hi"], "timeout": 5, "deps": []}],
    )


@pytest.mark.asyncio
async def test_replayed_idempotency_key_returns_the_same_run(session):
    """The replay path returns an existing Run row. `RunOut` includes `steps`, so
    it must be eager-loaded — a lazy load here raises MissingGreenlet and 500s
    the trigger, which is exactly the retry a caller uses the key to make safe."""
    session.add(_job())
    await session.commit()

    client = await _client(session)
    try:
        async with client:
            first = await client.post(
                "/api/jobs/idem-job/runs", json={"idempotency_key": "deploy-1"}
            )
            replay = await client.post(
                "/api/jobs/idem-job/runs", json={"idempotency_key": "deploy-1"}
            )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 201
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == first.json()["id"]
    assert [s["step_id"] for s in replay.json()["steps"]] == ["s1"]


@pytest.mark.asyncio
async def test_idempotency_key_reused_across_jobs_is_rejected(session):
    """`Run.idempotency_key` is unique table-wide. Replaying one under a second
    job must not hand back the first job's run — the caller would see 201 for a
    deploy that never ran. CI reusing one key per commit across several deploy
    jobs is exactly that shape."""
    session.add(_job())
    other = _job()
    other.id = "other-job"
    session.add(other)
    await session.commit()

    client = await _client(session)
    try:
        async with client:
            first = await client.post(
                "/api/jobs/idem-job/runs", json={"idempotency_key": "deploy-abc"}
            )
            cross = await client.post(
                "/api/jobs/other-job/runs", json={"idempotency_key": "deploy-abc"}
            )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 201
    assert cross.status_code == 409, cross.text
    assert cross.json()["detail"]["error"] == "CONFLICT"
    # `current_run_id` is part of the documented 409 contract, and the other
    # job's id must not leak to a caller scoped to this one.
    assert cross.json()["detail"]["current_run_id"] is None
    # The id at risk of leaking is the *other* job's — the one holding the
    # key — not the caller's own, which it already knows.
    assert "idem-job" not in cross.text
