from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class OutputAssertions:
    success_contains: list[str]
    failure_contains: list[str]


@dataclass
class WorkerResult:
    state: str  # SUCCESS | FAILED | TIMEOUT
    elapsed: float
    exit_code: int | None
    err_message: str | None = None


async def execute_argv(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int,
    env: dict[str, str],
    log_path: Path,
    on_line: Callable[[str, str], None] | None = None,
    create_cwd: bool = True,
    assertions: OutputAssertions | None = None,
) -> WorkerResult:
    """Execute argv with shell=False semantics, stream stdout+stderr.

    - `argv` MUST be a list (enforced by Policies elsewhere).
    - `cwd` is the step working directory.
    - `create_cwd` keeps the default runtime directory bootstrap behavior.
    - Output lines are appended to `log_path` and mirrored via `on_line(stream, text)`.
    """
    start = time.monotonic()
    if create_cwd:
        cwd.mkdir(parents=True, exist_ok=True)
    elif not cwd.exists():
        return _spawn_failure(
            start,
            log_path,
            on_line,
            exit_code=126,
            message=f"cwd not found: {cwd}",
        )
    elif not cwd.is_dir():
        return _spawn_failure(
            start,
            log_path,
            on_line,
            exit_code=126,
            message=f"cwd is not a directory: {cwd}",
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=env,
        )
    except FileNotFoundError:
        return _spawn_failure(
            start,
            log_path,
            on_line,
            exit_code=127,
            message=f"executable not found: {argv[0]}",
        )
    except PermissionError:
        return _spawn_failure(
            start,
            log_path,
            on_line,
            exit_code=126,
            message=f"permission denied: {argv[0]}",
        )
    except OSError as e:
        return _spawn_failure(
            start,
            log_path,
            on_line,
            exit_code=126,
            message=f"failed to start process: {e}",
        )

    matcher = _OutputMatcher(assertions or OutputAssertions([], []))

    async def _drain(stream: asyncio.StreamReader, name: str, f):
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip("\n")
            matcher.observe(text)
            f.write(line)
            if on_line is not None:
                try:
                    on_line(name, text)
                except Exception:
                    pass

    with log_path.open("ab") as f:
        drain_out = asyncio.create_task(_drain(proc.stdout, "stdout", f))
        drain_err = asyncio.create_task(_drain(proc.stderr, "stderr", f))
        try:
            exit_code = await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            await asyncio.gather(drain_out, drain_err, return_exceptions=True)
            elapsed = time.monotonic() - start
            return WorkerResult(
                state="TIMEOUT",
                elapsed=elapsed,
                exit_code=None,
                err_message=f"step timeout after {timeout}s",
            )
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            await asyncio.gather(drain_out, drain_err, return_exceptions=True)
            raise
        await asyncio.gather(drain_out, drain_err, return_exceptions=True)

    elapsed = time.monotonic() - start
    forbidden_error = matcher.forbidden_failure_message()
    if forbidden_error is not None:
        return WorkerResult(
            state="FAILED",
            elapsed=elapsed,
            exit_code=exit_code,
            err_message=forbidden_error,
        )
    if exit_code == 0:
        required_error = matcher.required_failure_message()
        if required_error is not None:
            return WorkerResult(
                state="FAILED",
                elapsed=elapsed,
                exit_code=0,
                err_message=required_error,
            )
        return WorkerResult(state="SUCCESS", elapsed=elapsed, exit_code=0)
    return WorkerResult(
        state="FAILED",
        elapsed=elapsed,
        exit_code=exit_code,
        err_message=f"non-zero exit {exit_code}",
    )


def _spawn_failure(
    start: float,
    log_path: Path,
    on_line: Callable[[str, str], None] | None,
    *,
    exit_code: int,
    message: str,
) -> WorkerResult:
    elapsed = time.monotonic() - start
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as f:
        f.write((message + "\n").encode())
    if on_line is not None:
        try:
            on_line("stderr", message)
        except Exception:
            pass
    return WorkerResult(
        state="FAILED",
        elapsed=elapsed,
        exit_code=exit_code,
        err_message=message,
    )


class _OutputMatcher:
    def __init__(self, assertions: OutputAssertions) -> None:
        self._required = list(assertions.success_contains)
        self._forbidden = list(assertions.failure_contains)
        self._found_required: set[str] = set()
        self._found_forbidden: str | None = None

    def observe(self, text: str) -> None:
        if self._found_forbidden is None:
            for pattern in self._forbidden:
                if pattern in text:
                    self._found_forbidden = pattern
                    break
        for pattern in self._required:
            if pattern in text:
                self._found_required.add(pattern)

    def forbidden_failure_message(self) -> str | None:
        if self._found_forbidden is not None:
            return f"output assertion failed: found forbidden text {self._found_forbidden!r}"
        return None

    def required_failure_message(self) -> str | None:
        missing = [p for p in self._required if p not in self._found_required]
        if missing:
            return f"output assertion failed: missing required text {missing[0]!r}"
        return None
