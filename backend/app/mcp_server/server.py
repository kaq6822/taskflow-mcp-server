from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.config import settings
from app.mcp_server.auth import McpAuthMiddleware
from app.mcp_server.tools import register_tools


def build_mcp() -> FastMCP:
    mcp = FastMCP(
        name="TaskFlow",
        instructions=(
            "TaskFlow MCP server. Authenticate with Authorization: Bearer <mcp_tk_live_...>. "
            "Each tool call checks the key's scopes against required scope. "
            "Run results follow TaskFlow's Agent schema (docs/02 §10.4)."
        ),
        host=settings.mcp_host,
        port=settings.mcp_port,
        stateless_http=True,
        json_response=True,
    )
    register_tools(mcp)
    return mcp


def build_asgi():
    """Return a Starlette ASGI app wrapped with Bearer auth middleware."""
    mcp = build_mcp()
    app = mcp.streamable_http_app()
    app.add_middleware(McpAuthMiddleware)
    return app
