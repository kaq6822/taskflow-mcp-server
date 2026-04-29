from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from dataclasses import dataclass
from io import BufferedReader
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
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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
    loop = asyncio.get_running_loop()
    write_lock = threading.Lock()

    def _drain(stream: BufferedReader, name: str, f) -> None:
        try:
            while True:
                line = stream.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip("\n")
                with write_lock:
                    matcher.observe(text)
                    f.write(line)
                    f.flush()
                if on_line is not None:
                    loop.call_soon_threadsafe(_safe_on_line, on_line, name, text)
        except (OSError, ValueError):
            pass

    with log_path.open("ab") as f:
        stdout = proc.stdout
        stderr = proc.stderr
        assert stdout is not None and stderr is not None
        streams = [stdout, stderr]
        threads = [
            threading.Thread(
                target=_drain,
                args=(stdout, "stdout", f),
                daemon=True,
                name="taskflow-drain-stdout",
            ),
            threading.Thread(
                target=_drain,
                args=(stderr, "stderr", f),
                daemon=True,
                name="taskflow-drain-stderr",
            ),
        ]
        for t in threads:
            t.start()
        try:
            exit_code = await _wait_for_process(proc, timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await _wait_for_process(proc, 5)
            await asyncio.to_thread(_finish_reader_threads, threads, streams)
            elapsed = time.monotonic() - start
            return WorkerResult(
                state="TIMEOUT",
                elapsed=elapsed,
                exit_code=None,
                err_message=f"step timeout after {timeout}s",
            )
        except asyncio.CancelledError:
            proc.kill()
            await _wait_for_process(proc, 5)
            await asyncio.to_thread(_finish_reader_threads, threads, streams)
            raise
        await asyncio.to_thread(_finish_reader_threads, threads, streams)

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


async def _wait_for_process(proc: subprocess.Popen, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    while proc.poll() is None:
        if time.monotonic() >= deadline:
            raise asyncio.TimeoutError
        await asyncio.sleep(0.05)
    return int(proc.returncode)


def _finish_reader_threads(
    threads: list[threading.Thread],
    streams: list[BufferedReader],
    grace: float = 0.5,
) -> None:
    """Give pipe readers a short grace period, then stop waiting.

    Daemon-style scripts can spawn a background process that keeps inherited
    stdout/stderr descriptors open after the script itself exits. The step
    result follows the main process exit, not a long-lived child pipe.
    """
    deadline = time.monotonic() + grace
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))

    if not any(thread.is_alive() for thread in threads):
        return

    for stream in streams:
        _close_reader_stream(stream)
    for thread in threads:
        if thread.is_alive():
            thread.join(0.1)


def _close_reader_stream(stream: BufferedReader) -> None:
    try:
        stream.raw.close()
    except (OSError, ValueError):
        pass


def _safe_on_line(callback: Callable[[str, str], None], name: str, text: str) -> None:
    try:
        callback(name, text)
    except Exception:
        pass


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
