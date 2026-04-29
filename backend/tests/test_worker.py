from __future__ import annotations

import os

import pytest

from app.engine.worker import execute_argv


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
