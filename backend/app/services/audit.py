from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, utcnow

# P1-1: serialize every chain append. Two concurrent requests otherwise read the
# same latest row and the later commit ends up with a prev_hash that skips the
# earlier event, breaking `/api/audit/verify`. The lock covers the critical
# section from `prev_hash` read through commit, so a subscriber can never see a
# partially-appended chain.
_AUDIT_LOCK = asyncio.Lock()


def _canonical(event: dict) -> str:
    return json.dumps(event, sort_keys=True, default=str, separators=(",", ":"))


def _hash(event: dict) -> str:
    return hashlib.sha256(_canonical(event).encode()).hexdigest()


async def append_event(
    session: AsyncSession,
    *,
    who: str,
    kind: str,
    target: str = "",
    src: str = "web",
    ip: str = "",
    result: str = "OK",
    at: datetime | None = None,
) -> AuditEvent:
    """Append one event to the hash-chained audit log.

    Commits the current session (including any pending work the caller has
    flushed/added) so that the audit row and the business change land atomically
    and no other writer can interleave its own chain link between prev-hash read
    and commit."""
    async with _AUDIT_LOCK:
        row_prev = (
            await session.execute(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1))
        ).scalar_one_or_none()
        prev_hash = row_prev.content_hash if row_prev else ""
        when = at or utcnow()
        if when.tzinfo is not None:
            when = when.astimezone(timezone.utc).replace(tzinfo=None)
        body = {
            "at": when.isoformat(),
            "who": who,
            "kind": kind,
            "target": target,
            "src": src,
            "ip": ip,
            "result": result,
            "prev_hash": prev_hash,
        }
        content_hash = _hash(body)
        ev = AuditEvent(
            at=when,
            who=who,
            kind=kind,
            target=target,
            src=src,
            ip=ip,
            result=result,
            prev_hash=prev_hash,
            content_hash=content_hash,
        )
        session.add(ev)
        await session.commit()
        await session.refresh(ev)
        return ev


async def verify_chain(session: AsyncSession) -> tuple[bool, int | None]:
    """Walk the full audit chain. Returns (ok, broken_row_id).

    (True, None) if the chain is intact.
    (False, id) of the first row whose recomputed hash does not match."""
    rows = (await session.execute(select(AuditEvent).order_by(AuditEvent.id.asc()))).scalars().all()
    prev = ""
    for row in rows:
        at_naive = row.at.astimezone(timezone.utc).replace(tzinfo=None) if row.at.tzinfo else row.at
        body = {
            "at": at_naive.isoformat(),
            "who": row.who,
            "kind": row.kind,
            "target": row.target,
            "src": row.src,
            "ip": row.ip,
            "result": row.result,
            "prev_hash": prev,
        }
        if row.prev_hash != prev or row.content_hash != _hash(body):
            return False, row.id
        prev = row.content_hash
    return True, None
