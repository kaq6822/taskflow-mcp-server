from __future__ import annotations

import logging
from pathlib import Path

import yaml

from app.config import settings

SHELL_FALSE = True  # 상수 — 변경 불가
STEP_USER = "taskflow"

_log = logging.getLogger(__name__)


class AllowlistError(ValueError):
    pass


_ALLOW: list[list[str]] | None = None


def _resolve_path() -> Path:
    """Choose the allowlist file to load.

    Resolution order:
      1. `settings.allowlist_path` (defaults to `./app/dev/allowlist.yaml`,
         overridable via `TASKFLOW_ALLOWLIST_PATH` — the per-environment copy,
         which is .gitignored).
      2. `backend/app/dev/allowlist.yaml` resolved relative to this module
         (handles pytest / alternate cwd setups).
      3. `backend/app/dev/allowlist.example.yaml` — the tracked template
         shipped with the repo. Falling back to this means the user has not
         yet bootstrapped their local copy (e.g. fresh clone before
         `make setup`); we warn so the operator knows to copy + customize.
    """
    primary = settings.allowlist_path
    if primary.exists():
        return primary

    module_dev = Path(__file__).resolve().parent.parent / "dev"
    local_copy = module_dev / "allowlist.yaml"
    if local_copy.exists():
        return local_copy

    example = module_dev / "allowlist.example.yaml"
    _log.warning(
        "allowlist.yaml not found at %s — falling back to shipped template %s. "
        "Run `make bootstrap-allowlist` to create a per-environment copy.",
        primary,
        example,
    )
    return example


def _load() -> list[list[str]]:
    global _ALLOW
    if _ALLOW is not None:
        return _ALLOW
    path = _resolve_path()
    with path.open("r") as f:
        data = yaml.safe_load(f) or {}
    _ALLOW = [list(entry) for entry in data.get("allow", [])]
    return _ALLOW


def _matches(entry: list[str], argv: list[str]) -> bool:
    if not entry:
        return False
    # entry may be a prefix (e.g. ['echo']) that covers any argv starting with 'echo'
    if len(entry) > len(argv):
        return False
    for a, b in zip(entry, argv):
        if b == "*" or a == "*":
            continue
        if a != b:
            return False
    return True


def check_allowlist(argv: list[str]) -> None:
    """Raise AllowlistError unless argv matches a declared prefix."""
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise AllowlistError("argv must be a non-empty list of strings (shell=False)")
    for entry in _load():
        if _matches(entry, argv):
            return
    raise AllowlistError(f"argv not in allowlist: {argv[0]}")


def reload_allowlist() -> None:
    """For tests: force re-read of the yaml file."""
    global _ALLOW
    _ALLOW = None


def filter_env(env: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Return (env, masked_keys). Keys starting with SECRET_ are kept but logged as masked."""
    masked = [k for k in env if k.startswith("SECRET_")]
    return dict(env), masked
