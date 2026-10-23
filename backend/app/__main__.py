"""Serve the REST API and the MCP endpoint from one process.

    python -m app            # API on TASKFLOW_API_PORT, MCP on TASKFLOW_MCP_PORT
    python -m app --reload   # dev: restart on changes under app/

Both share one RunEngine and one log_bus. Run in separate processes they could
not see each other's runs: a job could run twice at once, a cancel sent to the
other side never reached the running step, and the UI's live stream stayed
silent for runs started over MCP.

They still listen on separate ports. `/api/*` has no authentication while MCP
requires a Bearer key, so each can be bound to a different interface
(TASKFLOW_API_HOST / TASKFLOW_MCP_HOST).
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys

import uvicorn

from app.config import settings

# How long a stop waits for open connections (e.g. an MCP client's stream)
# before closing them. uvicorn's default is to wait forever.
GRACEFUL_SHUTDOWN_SEC = 10

_SIGNALS = [signal.SIGINT, signal.SIGTERM]
if sys.platform == "win32":
    _SIGNALS.append(signal.SIGBREAK)


class _Server(uvicorn.Server):
    """uvicorn.Server without its own signal handling.

    Each server would install handlers over the other's, so a signal reached
    only the last one and the API kept serving while MCP shut down. `serve()`
    below handles signals once, for both.
    """

    @contextlib.contextmanager
    def capture_signals(self):
        yield


async def _serve(server: uvicorn.Server) -> int:
    """Run `server` to completion; return a non-zero code if it failed.

    uvicorn calls sys.exit() when it cannot start (e.g. the port is taken).
    Raised inside a task, that escapes the event loop and skips the other
    server's shutdown, so turn it into a return value instead.
    """
    try:
        await server.serve()
    except SystemExit as e:
        return e.code if isinstance(e.code, int) and e.code else 1
    return 0 if server.started else 1


async def serve() -> int:
    from app.main import app as api_app
    from app.mcp_server.server import build_asgi

    def server(app, host: str, port: int) -> _Server:
        return _Server(
            uvicorn.Config(
                app, host=host, port=port, timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SEC
            )
        )

    api = server(api_app, settings.api_host, settings.api_port)
    mcp = server(build_asgi(), settings.mcp_host, settings.mcp_port)
    servers = (api, mcp)

    def on_signal(_sig, _frame) -> None:
        # First signal: graceful stop. Another one: stop waiting.
        stopping = api.should_exit
        for s in servers:
            s.should_exit = True
            s.force_exit = s.force_exit or stopping

    previous = {sig: signal.signal(sig, on_signal) for sig in _SIGNALS}
    try:
        # The API's lifespan creates tables and finalizes orphaned runs. MCP
        # must not accept a run_job before that, or startup would fail a fresh
        # run.
        tasks = [asyncio.create_task(_serve(api))]
        while not api.started and not tasks[0].done():
            await asyncio.sleep(0.05)
        if api.started and not api.should_exit:
            tasks.append(asyncio.create_task(_serve(mcp)))

        # A failed start ends only that server; stop the other one too.
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for s in servers:
            s.should_exit = True
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    for r in results:
        if isinstance(r, BaseException):
            raise r
    return max(results)


def run() -> None:
    code = asyncio.run(serve())
    if code:
        raise SystemExit(code)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app")
    parser.add_argument("--reload", action="store_true", help="restart on code changes (dev)")
    args = parser.parse_args()
    if args.reload:
        import watchfiles

        watchfiles.run_process("app", target="app.__main__.run")
    else:
        run()


if __name__ == "__main__":
    main()
