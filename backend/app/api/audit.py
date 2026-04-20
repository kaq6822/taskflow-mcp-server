from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import AuditEvent
from app.schemas import AuditOut
from app.services.audit import verify_chain

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditOut])
async def list_audit(
    kind: str | None = Query(None),
    result: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(200, le=2000),
    session: AsyncSession = Depends(get_session),
) -> list[AuditEvent]:
    query = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    if kind and kind != "all":
        query = query.where(AuditEvent.kind == kind)
    if result and result != "all":
        query = query.where(AuditEvent.result == result)
    if q:
        pat = f"%{q}%"
        query = query.where(
            or_(
                AuditEvent.who.like(pat),
                AuditEvent.target.like(pat),
                AuditEvent.kind.like(pat),
            )
        )
    return list((await session.execute(query)).scalars().all())


@router.get("/verify", response_class=PlainTextResponse)
async def verify(session: AsyncSession = Depends(get_session)) -> str:
    ok, broken = await verify_chain(session)
    if ok:
        return "OK: audit chain intact"
    return f"FAIL: broken at id={broken}"


@router.get("/export.csv", response_class=PlainTextResponse)
async def export_csv(session: AsyncSession = Depends(get_session)) -> str:
    rows = (await session.execute(select(AuditEvent).order_by(AuditEvent.id.desc()))).scalars().all()
    lines = ["at,who,kind,target,src,ip,result"]
    for r in rows:
        lines.append(
            ",".join(
                _csv(v)
                for v in [r.at.isoformat(), r.who, r.kind, r.target, r.src, r.ip, r.result]
            )
        )
    return "\n".join(lines)


def _csv(v: str) -> str:
    s = str(v)
    if "," in s or '"' in s or "\n" in s:
        return '"' + s.replace('"', '""') + '"'
    return s
