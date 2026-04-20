from __future__ import annotations

from pathlib import Path

import yaml

from app.config import settings

SHELL_FALSE = True  # 상수 — 변경 불가
STEP_USER = "taskflow"


class AllowlistError(ValueError):
    pass


_ALLOW: list[list[str]] | None = None


def _load() -> list[list[str]]:
    global _ALLOW
    if _ALLOW is not None:
        return _ALLOW
    path = settings.allowlist_path
    if not path.exists():
        path = Path(__file__).resolve().parent.parent / "dev" / "allowlist.yaml"
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
