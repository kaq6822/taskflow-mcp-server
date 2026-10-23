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

import uvicorn

from app.config import settings


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

    api = uvicorn.Server(
        uvicorn.Config(api_app, host=settings.api_host, port=settings.api_port)
    )
    mcp = uvicorn.Server(
        uvicorn.Config(build_asgi(), host=settings.mcp_host, port=settings.mcp_port)
    )

    # The API's lifespan creates tables and finalizes orphaned runs. MCP must
    # not accept a run_job before that, or startup would fail a fresh run.
    tasks = [asyncio.create_task(_serve(api))]
    while not api.started and not tasks[0].done():
        await asyncio.sleep(0.05)
    if api.started:
        tasks.append(asyncio.create_task(_serve(mcp)))

    # A signal reaches only one server's handler, and a failed start ends only
    # that server. Either way, stop the other one too.
    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    api.should_exit = mcp.should_exit = True
    return max(await asyncio.gather(*tasks))


def run() -> None:
    code = 0
    with contextlib.suppress(KeyboardInterrupt):
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
