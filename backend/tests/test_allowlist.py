from __future__ import annotations

import pytest

from app.engine.policies import (
    AllowlistError,
    check_allowlist,
    check_forbidden_state_command,
    reload_allowlist,
)


def test_echo_is_allowed():
    reload_allowlist()
    check_allowlist(["echo", "anything"])


def test_rm_is_denied():
    reload_allowlist()
    with pytest.raises(AllowlistError):
        check_allowlist(["rm", "-rf", "/"])


def test_non_list_argv_is_denied():
    reload_allowlist()
    with pytest.raises(AllowlistError):
        check_allowlist("echo hello")  # type: ignore[arg-type]


def test_cd_is_denied_as_state_command():
    with pytest.raises(AllowlistError, match="set step.cwd"):
        check_forbidden_state_command(["cd", "/cms/cms_api"])
