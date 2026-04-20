from __future__ import annotations

import uvicorn

from app.config import settings


def main() -> None:
    uvicorn.run(
        "app.mcp_server.server:build_asgi",
        host=settings.mcp_host,
        port=settings.mcp_port,
        factory=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
