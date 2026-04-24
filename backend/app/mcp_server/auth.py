from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import update
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.db import SessionLocal
from app.models import Key, utcnow
from app.services.audit import append_event
from app.services.keys import find_active_by_plaintext, rate_limit_ok

# Every MCP call hits this middleware. Turning each call into a DB writer
# (last_used UPDATE) makes auth compete with the engine for the SQLite writer
# lock and amplifies contention. We throttle per-key and dispatch the write
# in the background so auth itself stays read-only on the request path.
_LAST_USED_MIN_INTERVAL_SEC = 60.0
_last_used_flushed: dict[str, float] = {}


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


async def _bump_last_used_bg(key_id: str, at: datetime) -> None:
    """Fire-and-forget UPDATE on the `keys` row. Kept off the request path
    so auth never blocks on the SQLite writer lock."""
    try:
        async with SessionLocal() as s:
            await s.execute(update(Key).where(Key.id == key_id).values(last_used=at))
            await s.commit()
    except Exception:
        # Bookkeeping write — failure must never affect request handling.
        pass


def _maybe_bump_last_used(key_id: str) -> None:
    """Schedule a background last_used bump at most once per
    `_LAST_USED_MIN_INTERVAL_SEC` per key. 60s resolution is plenty for the
    "last seen" UI column.

    A missing entry means "never seen in this process" — always flush on the
    first observation. `time.monotonic()`'s reference point is implementation-
    defined (typically boot time), so comparing against 0.0 would suppress
    the first bump whenever uptime is below the throttle interval.
    """
    now_mono = time.monotonic()
    prev = _last_used_flushed.get(key_id)
    if prev is None or now_mono - prev >= _LAST_USED_MIN_INTERVAL_SEC:
        _last_used_flushed[key_id] = now_mono
        asyncio.create_task(_bump_last_used_bg(key_id, utcnow()))


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
                # Off the request path: throttled background bump. The auth
                # session itself performs no writes, so it never takes the
                # SQLite writer lock and can't contend with the engine.
                _maybe_bump_last_used(key.id)
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
