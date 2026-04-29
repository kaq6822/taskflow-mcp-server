from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


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

    async def _drain(stream: asyncio.StreamReader, name: str, f):
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip("\n")
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
    if exit_code == 0:
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
