from __future__ import annotations

from pathlib import Path

SHELL_FALSE = True  # 상수 — 변경 불가
STEP_USER = "taskflow"
_FORBIDDEN_STATE_COMMANDS = {"cd", "pushd", "popd"}


class PolicyError(ValueError):
    pass


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
