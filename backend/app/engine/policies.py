from __future__ import annotations

from pathlib import Path

SHELL_FALSE = True  # 상수 — 변경 불가
STEP_USER = "taskflow"
_FORBIDDEN_STATE_COMMANDS = {"cd", "pushd", "popd"}


class PolicyError(ValueError):
    pass


def check_argv_shape(argv: object) -> None:
    """Reject anything that is not a non-empty list of strings.

    `validate_steps` already enforces this when a Job is saved. This is the
    run-start re-check: a `steps` blob that reached the DB by another route
    (direct edit, backup restore) must not make it to `subprocess.Popen`,
    where an empty list raises IndexError and a bare string would be split
    into characters.
    """
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise PolicyError("cmd must be a non-empty list of strings (argv only, shell=False)")


def check_forbidden_state_command(argv: list[str]) -> None:
    """Reject shell/process state commands that cannot affect later steps.

    Directory changes are represented by Step.cwd, not by a standalone `cd`
    process. A subprocess cannot mutate the TaskFlow worker's cwd or the next
    subprocess' cwd.
    """
    if not argv:
        return
    name = Path(argv[0]).name
    if name in _FORBIDDEN_STATE_COMMANDS:
        raise PolicyError(f"{name} is not a step command; set step.cwd instead")


def filter_env(env: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Return (env, masked_keys). Keys starting with SECRET_ are kept but logged as masked."""
    masked = [k for k in env if k.startswith("SECRET_")]
    return dict(env), masked
