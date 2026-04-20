from __future__ import annotations

import pytest

from app.engine.policies import AllowlistError, check_allowlist, reload_allowlist


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
