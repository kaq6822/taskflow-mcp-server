from __future__ import annotations

import os

import pytest

from app.engine.worker import OutputAssertions, execute_argv


@pytest.mark.asyncio
async def test_missing_executable_fails_instead_of_hanging(tmp_path):
    log_path = tmp_path / "missing.log"

    result = await execute_argv(
        ["definitely-not-a-taskflow-command"],
        cwd=tmp_path / "runtime",
        timeout=1,
        env=dict(os.environ),
        log_path=log_path,
    )

    assert result.state == "FAILED"
    assert result.exit_code == 127
    assert result.err_message == "executable not found: definitely-not-a-taskflow-command"
    assert log_path.read_text() == result.err_message + "\n"


@pytest.mark.asyncio
async def test_missing_explicit_cwd_fails_instead_of_creating_it(tmp_path):
    missing_cwd = tmp_path / "missing"
    log_path = tmp_path / "missing-cwd.log"

    result = await execute_argv(
        ["echo", "hello"],
        cwd=missing_cwd,
        timeout=1,
        env=dict(os.environ),
        log_path=log_path,
        create_cwd=False,
    )

    assert result.state == "FAILED"
    assert result.exit_code == 126
    assert result.err_message == f"cwd not found: {missing_cwd}"
    assert not missing_cwd.exists()


@pytest.mark.asyncio
async def test_success_contains_requires_matching_output(tmp_path):
    result = await execute_argv(
        ["printf", "deploy complete\n"],
        cwd=tmp_path / "runtime",
        timeout=1,
        env=dict(os.environ),
        log_path=tmp_path / "success.log",
        assertions=OutputAssertions(success_contains=["deploy complete"], failure_contains=[]),
    )

    assert result.state == "SUCCESS"
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_missing_success_contains_fails_even_with_exit_zero(tmp_path):
    result = await execute_argv(
        ["printf", "started\n"],
        cwd=tmp_path / "runtime",
        timeout=1,
        env=dict(os.environ),
        log_path=tmp_path / "missing-success.log",
        assertions=OutputAssertions(success_contains=["deploy complete"], failure_contains=[]),
    )

    assert result.state == "FAILED"
    assert result.exit_code == 0
    assert result.err_message == "output assertion failed: missing required text 'deploy complete'"


@pytest.mark.asyncio
async def test_non_zero_exit_takes_precedence_over_missing_success_contains(tmp_path):
    result = await execute_argv(
        ["false"],
        cwd=tmp_path / "runtime",
        timeout=1,
        env=dict(os.environ),
        log_path=tmp_path / "non-zero.log",
        assertions=OutputAssertions(success_contains=["deploy complete"], failure_contains=[]),
    )

    assert result.state == "FAILED"
    assert result.exit_code == 1
    assert result.err_message == "non-zero exit 1"


@pytest.mark.asyncio
async def test_failure_contains_fails_even_with_exit_zero(tmp_path):
    result = await execute_argv(
        ["printf", "ERROR: bad deploy\n"],
        cwd=tmp_path / "runtime",
        timeout=1,
        env=dict(os.environ),
        log_path=tmp_path / "failure.log",
        assertions=OutputAssertions(success_contains=[], failure_contains=["ERROR"]),
    )

    assert result.state == "FAILED"
    assert result.exit_code == 0
    assert result.err_message == "output assertion failed: found forbidden text 'ERROR'"
