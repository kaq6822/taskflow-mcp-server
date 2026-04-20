from __future__ import annotations

from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.db import SessionLocal
from app.models import utcnow
from app.services.audit import append_event
from app.services.keys import find_active_by_plaintext, rate_limit_ok


@dataclass
class AuthContext:
    key_id: str
    label: str
    scopes: list[str]
    rate: str


async def _audit_auth_fail(who: str, ip: str, target: str) -> None:
    async with SessionLocal() as session:
        await append_event(
            session,
            who=who,
            kind="auth.fail",
            target=target,
            src="mcp",
            ip=ip,
            result="DENY",
        )


class McpAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate every MCP request via Bearer. Store AuthContext on
    request.state.mcp_auth for downstream tool handlers to read."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path.startswith("/mcp"):
            auth = request.headers.get("authorization", "")
            if not auth.lower().startswith("bearer "):
                await _audit_auth_fail("unknown", _ip(request), "missing bearer")
                return JSONResponse({"error": "UNAUTH", "detail": "missing bearer"}, status_code=401)
            token = auth[7:].strip()
            async with SessionLocal() as session:
                key = await find_active_by_plaintext(session, token)
                if not key:
                    await _audit_auth_fail("unknown", _ip(request), "invalid key")
                    return JSONResponse(
                        {"error": "UNAUTH", "detail": "invalid key"}, status_code=401
                    )
                if key.expires and key.expires < utcnow().replace(tzinfo=key.expires.tzinfo):
                    await _audit_auth_fail(key.label, _ip(request), "expired key")
                    return JSONResponse(
                        {"error": "UNAUTH", "detail": "expired key"}, status_code=401
                    )
                ok, retry = rate_limit_ok(key.id, key.rate_limit)
                if not ok:
                    await append_event(
                        session,
                        who=key.label,
                        kind="mcp.rate_limit",
                        target="",
                        src="mcp",
                        ip=_ip(request),
                        result="DENY",
                    )
                    return JSONResponse(
                        {"error": "RATE_LIMIT", "retry_after": retry},
                        status_code=429,
                        headers={"Retry-After": str(retry)},
                    )
                key.last_used = utcnow()
                await session.commit()  # commits the last_used bump (no audit row)
                request.state.mcp_auth = AuthContext(
                    key_id=key.id,
                    label=key.label,
                    scopes=list(key.scopes),
                    rate=key.rate_limit,
                )
                request.state.mcp_ip = _ip(request)
        return await call_next(request)


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def auth_from_context(ctx) -> AuthContext | None:
    """Extract AuthContext from FastMCP Context via request_context.request.state."""
    try:
        req = ctx.request_context.request  # type: ignore[attr-defined]
        return getattr(req.state, "mcp_auth", None)
    except Exception:
        return None


def ip_from_context(ctx) -> str:
    try:
        req = ctx.request_context.request  # type: ignore[attr-defined]
        return getattr(req.state, "mcp_ip", "")
    except Exception:
        return ""
