"""Trigger-time run parameters: declaration rules, resolution, pinning, env."""
from __future__ import annotations

import pytest

from app.engine.run_engine import RunEngine
from app.engine.worker import WorkerResult
from app.models import Job, Run
from app.services.params import (
    ParamResolutionError,
    ParamValidationError,
    param_env,
    resolve_params,
    validate_params,
)

BRANCH = {"name": "branch", "default": "dev", "pattern": r"[A-Za-z0-9._/-]+"}


def _job(job_id: str, params: list[dict], steps: list[dict] | None = None) -> Job:
    return Job(
        id=job_id,
        name=job_id,
        owner="test",
        tags=[],
        consumes_artifacts=[],
        params=params,
        steps=steps or [{"id": "s1", "cmd": ["echo", "hi"], "timeout": 5, "deps": []}],
    )


# ---- declaration -----------------------------------------------------------


def test_valid_declaration_passes():
    validate_params([BRANCH, {"name": "tag", "default": None, "pattern": None}])


@pytest.mark.parametrize("name", ["", "1st", "my-branch", "a.b", "has space", "branch\n"])
def test_param_name_must_be_env_safe(name):
    with pytest.raises(ParamValidationError):
        validate_params([{"name": name}])


def test_duplicate_param_is_rejected_case_insensitively():
    with pytest.raises(ParamValidationError, match="duplicate"):
        validate_params([{"name": "branch"}, {"name": "BRANCH"}])


def test_invalid_regex_is_rejected():
    with pytest.raises(ParamValidationError, match="invalid pattern"):
        validate_params([{"name": "branch", "pattern": "[unclosed"}])


def test_default_must_satisfy_its_own_pattern():
    """Otherwise every run relying on the default would be rejected."""
    with pytest.raises(ParamValidationError, match="default"):
        validate_params([{"name": "branch", "default": "bad branch", "pattern": r"[a-z]+"}])


def test_empty_default_is_rejected():
    """Blank is not a usable value, so it cannot be the fallback either."""
    with pytest.raises(ParamValidationError, match="default"):
        validate_params([{"name": "branch", "default": ""}])


# ---- resolution ------------------------------------------------------------


def test_omitted_param_uses_default():
    assert resolve_params([BRANCH], {}) == {"branch": "dev"}


def test_given_value_overrides_default():
    assert resolve_params([BRANCH], {"branch": "feature/x"}) == {"branch": "feature/x"}


def test_name_lookup_ignores_case():
    """A caller who saw PARAM_BRANCH may pass `BRANCH`; the record keeps the declared name."""
    assert resolve_params([BRANCH], {"BRANCH": "main"}) == {"branch": "main"}


def test_same_param_in_two_casings_is_rejected():
    with pytest.raises(ParamResolutionError) as e:
        resolve_params([BRANCH], {"branch": "a", "BRANCH": "b"})
    assert e.value.code == "INVALID_PARAM"


def test_required_param_must_be_given():
    with pytest.raises(ParamResolutionError) as e:
        resolve_params([{"name": "branch", "default": None, "pattern": None}], {})
    assert e.value.code == "INVALID_PARAM"
    assert "required" in e.value.message


def test_undeclared_param_is_rejected():
    """Before this feature `params` was accepted and silently dropped, so a
    caller asking for a branch got the default deployed. Now it must fail."""
    with pytest.raises(ParamResolutionError) as e:
        resolve_params([], {"branch": "feature/x"})
    assert e.value.code == "UNKNOWN_PARAM"


def test_pattern_is_matched_against_the_whole_value():
    with pytest.raises(ParamResolutionError) as e:
        resolve_params(
            [{"name": "branch", "default": None, "pattern": r"[a-z]+"}], {"branch": "main; rm -rf /"}
        )
    assert e.value.code == "INVALID_PARAM"


@pytest.mark.parametrize(
    "value",
    [None, 3, ["dev"], "", "   ", "a\x00b", "a\nforged log line", "\ud800", "x" * 1025],
)
def test_unusable_values_are_rejected(value):
    """An explicit null must not quietly fall back to the default either. A
    lone surrogate passes JSON parsing but cannot be encoded into the step env,
    which would otherwise strand the run in RUNNING."""
    with pytest.raises(ParamResolutionError) as e:
        resolve_params([{"name": "branch", "default": "dev", "pattern": None}], {"branch": value})
    assert e.value.code == "INVALID_PARAM"


def test_param_env_projection():
    assert param_env({"branch": "dev", "Tag": "v1"}) == {"PARAM_BRANCH": "dev", "PARAM_TAG": "v1"}


# ---- engine ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolved_params_are_pinned_on_the_run(session):
    job = _job("deploy", [BRANCH, {"name": "profile", "default": "dev", "pattern": None}])
    session.add(job)
    await session.flush()

    run = await RunEngine().start(
        session, job=job, trigger="manual", actor="test", params={"branch": "feature/x"}
    )

    # Defaults are recorded too, so the run shows everything it actually used.
    assert run.params == {"branch": "feature/x", "profile": "dev"}


@pytest.mark.asyncio
async def test_rejected_params_create_no_run(session):
    job = _job("deploy", [BRANCH])
    session.add(job)
    await session.flush()

    with pytest.raises(ParamResolutionError):
        await RunEngine().start(
            session, job=job, trigger="manual", actor="test", params={"branch": "bad branch"}
        )
    assert (await session.get(Run, 1)) is None


@pytest.mark.asyncio
async def test_pinned_params_reach_every_step_and_beat_step_env(session, monkeypatch):
    """Drives the real run loop: the env must come from the Run record, and a
    step's own `env` must not be able to swap the branch behind the record."""
    job = _job(
        "deploy",
        [BRANCH],
        steps=[
            {"id": "s1", "cmd": ["echo", "1"], "timeout": 5, "deps": []},
            {
                "id": "s2",
                "cmd": ["echo", "2"],
                "timeout": 5,
                "deps": ["s1"],
                "env": {"PARAM_BRANCH": "main", "HARMLESS": "1"},
            },
        ],
    )
    session.add(job)
    await session.flush()
    engine = RunEngine()
    run = await engine.start(
        session, job=job, trigger="manual", actor="test", params={"branch": "feature/x"}
    )
    # The run loop opens its own SessionLocal, so rows must be committed.
    await session.commit()

    seen: list[dict] = []

    async def fake_execute_argv(cmd, **kwargs):
        seen.append(dict(kwargs["env"]))
        return WorkerResult(state="SUCCESS", elapsed=0.0, exit_code=0)

    monkeypatch.setattr("app.engine.run_engine.execute_argv", fake_execute_argv)

    await engine._run_loop_body(job.id, run.id)

    assert [e["PARAM_BRANCH"] for e in seen] == ["feature/x", "feature/x"]
    assert seen[1]["HARMLESS"] == "1"


@pytest.mark.asyncio
async def test_job_without_params_runs_with_an_empty_map(session):
    job = _job("plain", [])
    session.add(job)
    await session.flush()

    run = await RunEngine().start(session, job=job, trigger="manual", actor="test")
    assert run.params == {}
