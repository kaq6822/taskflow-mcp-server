from __future__ import annotations

import pytest

from app.engine.policies import PolicyError, check_argv_shape, check_forbidden_state_command


def test_cd_is_denied_as_state_command():
    with pytest.raises(PolicyError, match="set step.cwd"):
        check_forbidden_state_command(["cd", "/cms/cms_api"])


def test_pushd_popd_are_denied_by_basename():
    for argv in (["pushd", "/tmp"], ["/usr/bin/popd"]):
        with pytest.raises(PolicyError):
            check_forbidden_state_command(argv)


def test_ordinary_commands_pass():
    # No allowlist: any command other than the state commands above is accepted.
    for argv in (["echo", "hi"], ["rm", "-rf", "./build"], ["/bin/bash", "deploy.sh"]):
        check_forbidden_state_command(argv)


def test_empty_argv_is_a_noop():
    check_forbidden_state_command([])


@pytest.mark.parametrize("argv", [[], "echo hello", ["echo", 1], None, ()])
def test_argv_shape_rejects_non_argv(argv):
    """Run-start re-check: nothing but a non-empty list of strings reaches Popen."""
    with pytest.raises(PolicyError):
        check_argv_shape(argv)


def test_argv_shape_accepts_argv_lists():
    check_argv_shape(["echo", "hello"])
    check_argv_shape(["/bin/bash", "/opt/taskflow/scripts/deploy.sh"])
