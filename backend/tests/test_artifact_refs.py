"""Multi-artifact consumption: alias resolution, pinning, and env projection."""
from __future__ import annotations

import pytest

from app.engine.run_engine import RunEngine
from app.engine.worker import WorkerResult
from app.models import Job
from app.services.artifacts import (
    ArtifactResolutionError,
    ArtifactValidationError,
    artifact_env,
    parse_reference,
    resolve_reference,
    save_upload_bytes,
    validate_consumes,
)


async def _upload(session, name: str, version: str, body: bytes = b"x") -> None:
    await save_upload_bytes(
        session=session, name=name, version=version, ext="jar", uploader="test", data=body
    )
    await session.flush()


def _job(job_id: str, consumes: list[dict]) -> Job:
    return Job(
        id=job_id,
        name=job_id,
        owner="test",
        tags=[],
        consumes_artifacts=consumes,
        steps=[{"id": "s1", "cmd": ["echo", "hi"], "timeout": 5, "deps": []}],
    )


@pytest.mark.asyncio
async def test_omitted_alias_resolves_latest_and_pins(session):
    await _upload(session, "myapp", "v1.0.0")
    await _upload(session, "myapp", "v1.1.0")  # moves the latest pointer
    job = _job("deploy", [{"alias": "jar", "name": "myapp"}])
    session.add(job)
    await session.flush()

    run = await RunEngine().start(session, job=job, trigger="manual", actor="test")

    # `@latest` must be recorded as the concrete version, not as "latest".
    assert run.artifact_refs["jar"]["ref"] == "uploads://myapp@v1.1.0"
    assert run.artifact_refs["jar"]["sha256"]


@pytest.mark.asyncio
async def test_explicit_version_overrides_latest(session):
    await _upload(session, "myapp", "v1.0.0")
    await _upload(session, "myapp", "v1.1.0")
    job = _job("deploy", [{"alias": "jar", "name": "myapp"}])
    session.add(job)
    await session.flush()

    run = await RunEngine().start(
        session,
        job=job,
        trigger="manual",
        actor="test",
        artifact_refs={"jar": "uploads://myapp@v1.0.0"},
    )
    assert run.artifact_refs["jar"]["ref"] == "uploads://myapp@v1.0.0"


@pytest.mark.asyncio
async def test_multiple_aliases_resolve_independently(session):
    await _upload(session, "myapp", "v2.0.0")
    await _upload(session, "myapp-config", "v6")
    await _upload(session, "myapp-config", "v7")
    job = _job(
        "deploy",
        [{"alias": "jar", "name": "myapp"}, {"alias": "conf", "name": "myapp-config"}],
    )
    session.add(job)
    await session.flush()

    # jar omitted → latest; conf pinned explicitly to the older version.
    run = await RunEngine().start(
        session,
        job=job,
        trigger="manual",
        actor="test",
        artifact_refs={"conf": "uploads://myapp-config@v6"},
    )
    assert run.artifact_refs["jar"]["ref"] == "uploads://myapp@v2.0.0"
    assert run.artifact_refs["conf"]["ref"] == "uploads://myapp-config@v6"


@pytest.mark.asyncio
async def test_pin_survives_a_later_upload(session):
    await _upload(session, "myapp", "v1.0.0")
    job = _job("deploy", [{"alias": "jar", "name": "myapp"}])
    session.add(job)
    await session.flush()

    first = await RunEngine().start(session, job=job, trigger="manual", actor="test")
    await _upload(session, "myapp", "v2.0.0")  # latest moves after the run started
    second = await RunEngine().start(session, job=job, trigger="manual", actor="test")

    assert first.artifact_refs["jar"]["ref"] == "uploads://myapp@v1.0.0"
    assert second.artifact_refs["jar"]["ref"] == "uploads://myapp@v2.0.0"


@pytest.mark.asyncio
async def test_unknown_alias_is_rejected(session):
    await _upload(session, "myapp", "v1.0.0")
    job = _job("deploy", [{"alias": "jar", "name": "myapp"}])
    session.add(job)
    await session.flush()

    with pytest.raises(ArtifactResolutionError) as e:
        await RunEngine().start(
            session,
            job=job,
            trigger="manual",
            actor="test",
            artifact_refs={"nope": "uploads://myapp@v1.0.0"},
        )
    assert e.value.code == "UNKNOWN_ALIAS"


@pytest.mark.asyncio
async def test_alias_pointing_at_a_different_artifact_is_rejected(session):
    await _upload(session, "myapp", "v1.0.0")
    await _upload(session, "otherapp", "v1.0.0")
    job = _job("deploy", [{"alias": "jar", "name": "myapp"}])
    session.add(job)
    await session.flush()

    with pytest.raises(ArtifactResolutionError) as e:
        await RunEngine().start(
            session,
            job=job,
            trigger="manual",
            actor="test",
            artifact_refs={"jar": "uploads://otherapp@v1.0.0"},
        )
    assert e.value.code == "MISMATCH"


@pytest.mark.asyncio
async def test_missing_artifact_is_rejected(session):
    job = _job("deploy", [{"alias": "jar", "name": "ghost"}])
    session.add(job)
    await session.flush()

    with pytest.raises(ArtifactResolutionError) as e:
        await RunEngine().start(session, job=job, trigger="manual", actor="test")
    assert e.value.code == "NOT_FOUND"


@pytest.mark.asyncio
async def test_not_ready_artifact_is_rejected(session):
    await _upload(session, "myapp", "v1.0.0")
    art = await resolve_reference(session, "uploads://myapp@v1.0.0")
    art.status = "SCANNING"
    await session.flush()

    job = _job("deploy", [{"alias": "jar", "name": "myapp"}])
    session.add(job)
    await session.flush()

    with pytest.raises(ArtifactResolutionError) as e:
        await RunEngine().start(session, job=job, trigger="manual", actor="test")
    assert e.value.code == "NOT_READY"


@pytest.mark.asyncio
async def test_job_without_consumes_ignores_artifacts(session):
    job = _job("plain", [])
    session.add(job)
    await session.flush()

    run = await RunEngine().start(session, job=job, trigger="manual", actor="test")
    assert run.artifact_refs == {}


@pytest.mark.asyncio
async def test_artifact_env_projection(session):
    await _upload(session, "myapp", "v1.0.0")
    art = await resolve_reference(session, "uploads://myapp@latest")

    env = artifact_env("jar", art)
    assert env["ARTIFACT_JAR_PATH"] == art.blob_path
    assert env["ARTIFACT_JAR_NAME"] == "myapp"
    assert env["ARTIFACT_JAR_VERSION"] == "v1.0.0"
    assert env["ARTIFACT_JAR_SHA256"] == art.sha256
    assert env["ARTIFACT_JAR_REF"] == "uploads://myapp@v1.0.0"


async def _run_step_capturing_env(session, monkeypatch, step_spec: dict) -> dict:
    """Drive `_execute_step` with a stubbed worker and return the env it built."""
    await _upload(session, "myapp", "v1.0.0")
    job = _job("deploy", [{"alias": "jar", "name": "myapp"}])
    job.steps = [step_spec]
    session.add(job)
    await session.flush()
    run = await RunEngine().start(session, job=job, trigger="manual", actor="test")
    # `_execute_step` opens its own SessionLocal, so the RunStep rows must be
    # committed rather than merely flushed.
    await session.commit()

    captured: dict = {}

    async def fake_execute_argv(cmd, **kwargs):
        captured.update(kwargs["env"])
        return WorkerResult(state="SUCCESS", elapsed=0.0, exit_code=0)

    monkeypatch.setattr("app.engine.run_engine.execute_argv", fake_execute_argv)

    art = await resolve_reference(session, "uploads://myapp@v1.0.0")
    await RunEngine()._execute_step(
        run_id=run.id,
        step_id=step_spec["id"],
        step_spec=step_spec,
        actor="test",
        trigger="manual",
        artifact_vars=artifact_env("jar", art),
    )
    return captured


@pytest.mark.asyncio
async def test_artifact_env_reaches_the_worker(session, monkeypatch):
    env = await _run_step_capturing_env(
        session, monkeypatch, {"id": "s1", "cmd": ["echo", "hi"], "timeout": 5, "deps": []}
    )
    art = await resolve_reference(session, "uploads://myapp@v1.0.0")
    assert env["ARTIFACT_JAR_PATH"] == art.blob_path
    assert env["ARTIFACT_JAR_VERSION"] == "v1.0.0"


@pytest.mark.asyncio
async def test_step_env_cannot_override_pinned_artifact_vars(session, monkeypatch):
    env = await _run_step_capturing_env(
        session,
        monkeypatch,
        {
            "id": "s1",
            "cmd": ["echo", "hi"],
            "timeout": 5,
            "deps": [],
            "env": {"ARTIFACT_JAR_PATH": "/tmp/evil.jar", "HARMLESS": "1"},
        },
    )
    art = await resolve_reference(session, "uploads://myapp@v1.0.0")
    assert env["ARTIFACT_JAR_PATH"] == art.blob_path  # not /tmp/evil.jar
    assert env["HARMLESS"] == "1"  # unrelated step env still applies


@pytest.mark.parametrize(
    "ref",
    ["myapp@v1", "uploads://myapp", "uploads://@v1", "uploads://myapp@"],
)
def test_malformed_references_are_rejected(ref):
    with pytest.raises(ArtifactResolutionError) as e:
        parse_reference(ref)
    assert e.value.code == "INVALID_ARTIFACT"


def test_duplicate_alias_is_rejected():
    with pytest.raises(ArtifactValidationError):
        validate_consumes(
            [{"alias": "jar", "name": "a"}, {"alias": "JAR", "name": "b"}]
        )


@pytest.mark.parametrize("alias", ["", "1jar", "my-jar", "my.jar", "my jar"])
def test_invalid_alias_is_rejected(alias):
    with pytest.raises(ArtifactValidationError):
        validate_consumes([{"alias": alias, "name": "myapp"}])


def test_traversal_in_artifact_name_is_rejected():
    with pytest.raises(ArtifactValidationError):
        validate_consumes([{"alias": "jar", "name": "../../etc/passwd"}])
