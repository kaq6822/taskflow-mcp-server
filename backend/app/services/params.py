from __future__ import annotations

import re
from typing import Any

# Parameter names become environment-variable fragments (`PARAM_<NAME>`), so
# they share the artifact alias alphabet for the same reason: `.`/`-` would
# have to be folded to `_` and two names could collide on one env key.
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

# Values end up in a process environment and verbatim in the step log. Control
# characters (NUL cannot exist in an env at all; a newline would forge extra
# log lines) and unbounded lengths are never a legitimate branch name or tag.
_MAX_VALUE_LEN = 1024
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class ParamValidationError(ValueError):
    """A Job's `params` declaration is malformed (raised at save time)."""


class ParamResolutionError(Exception):
    """Trigger-time values could not be resolved against a Job's declaration.

    `code` follows the same vocabulary style as `ArtifactResolutionError` so
    the REST and MCP layers can map both through one table.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _value_problem(value: Any, pattern: str | None) -> str | None:
    if not isinstance(value, str):
        return f"must be a string, got {type(value).__name__}"
    # Same rule as an explicitly blank artifact ref: an empty value would let a
    # script quietly act on whatever its fallback is (`git checkout origin/`).
    if not value.strip():
        return "must not be empty"
    if _CONTROL.search(value):
        return "must not contain control characters"
    try:
        # JSON accepts lone surrogates; the env encoding at spawn time does
        # not, and that failure would leave the run stuck in RUNNING.
        value.encode("utf-8")
    except UnicodeEncodeError:
        return "must be valid UTF-8"
    if len(value) > _MAX_VALUE_LEN:
        return f"must be at most {_MAX_VALUE_LEN} characters"
    # fullmatch, not search: a pattern written as `[a-z]+` must not accept
    # `main; rm -rf` just because a prefix matches.
    if pattern is not None and re.fullmatch(pattern, value) is None:
        return f"does not match pattern {pattern!r}"
    return None


def validate_params(entries: list[dict]) -> None:
    """Validate a Job's `params` list: `[{"name", "default", "pattern"}, …]`.

    A `default` of None makes the parameter required at trigger time. A
    non-None default must itself satisfy `pattern`, otherwise every run that
    relies on it would be rejected.
    """
    seen: set[str] = set()
    for entry in entries:
        name = entry.get("name") or ""
        # fullmatch: `$` alone also matches before a trailing newline.
        if not _NAME.fullmatch(name):
            raise ParamValidationError(
                f"invalid param name: {name!r} (must start with a letter; letters, digits, underscore only)"
            )
        key = name.upper()
        if key in seen:
            raise ParamValidationError(f"duplicate param: {name!r}")
        seen.add(key)
        pattern = entry.get("pattern")
        if pattern is not None:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ParamValidationError(f"param {name!r}: invalid pattern: {e}") from e
        default = entry.get("default")
        if default is not None:
            problem = _value_problem(default, pattern)
            if problem:
                raise ParamValidationError(f"param {name!r}: default {problem}")


def resolve_params(declared: list[dict], requested: dict[str, Any]) -> dict[str, str]:
    """Turn trigger-time values into the concrete map pinned on the Run.

    Names match case-insensitively, like artifact aliases, so a caller who saw
    `PARAM_BRANCH` can pass `BRANCH`. Omitted parameters fall back to their
    default; a parameter with no default must be supplied.
    """
    by_key = {e["name"].upper(): e for e in declared}
    given: dict[str, Any] = {}
    unknown: list[str] = []
    for name, value in requested.items():
        entry = by_key.get(name.upper())
        if entry is None:
            unknown.append(name)
            continue
        if entry["name"] in given:
            raise ParamResolutionError(
                "INVALID_PARAM", f"param {entry['name']!r} was given more than once"
            )
        given[entry["name"]] = value
    if unknown:
        raise ParamResolutionError(
            "UNKNOWN_PARAM", f"job does not declare param(s): {', '.join(sorted(unknown))}"
        )
    resolved: dict[str, str] = {}
    for entry in declared:
        name = entry["name"]
        # Key presence, not the value: an explicit null must be rejected as a
        # non-string rather than quietly replaced by the default.
        if name in given:
            value = given[name]
        elif entry.get("default") is not None:
            value = entry["default"]
        else:
            raise ParamResolutionError("INVALID_PARAM", f"param {name!r} is required")
        problem = _value_problem(value, entry.get("pattern"))
        if problem:
            raise ParamResolutionError("INVALID_PARAM", f"param {name!r} {problem}")
        resolved[name] = value
    return resolved


def param_env(values: dict[str, str]) -> dict[str, str]:
    """Environment variables handed to every step: `PARAM_<NAME>`."""
    return {f"PARAM_{name.upper()}": value for name, value in values.items()}
