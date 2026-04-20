from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Key
from app.schemas import KeyCreate, KeyIssued, KeyOut
from app.services.audit import append_event
from app.services.keys import issue_key, revoke_key

router = APIRouter(prefix="/api/keys", tags=["keys"])


@router.get("", response_model=list[KeyOut])
async def list_keys(session: AsyncSession = Depends(get_session)) -> list[Key]:
    return list(
        (await session.execute(select(Key).order_by(Key.created.desc()))).scalars().all()
    )


@router.post("", response_model=KeyIssued, status_code=201)
async def create_key(
    body: KeyCreate, request: Request, session: AsyncSession = Depends(get_session)
) -> KeyIssued:
    key, plaintext = await issue_key(
        session,
        label=body.label,
        scopes=body.scopes,
        expires_days=body.expires_days,
        rate_limit=body.rate_limit,
    )
    await append_event(
        session,
        who=request.headers.get("X-Actor", "admin"),
        kind="mcp.key.issue",
        target=body.label,
        src="web",
        ip=request.client.host if request.client else "",
        result="OK",
    )
    await session.refresh(key)
    out = KeyIssued(plaintext=plaintext, **KeyOut.model_validate(key).model_dump())
    return out


@router.delete("/{key_id}", status_code=204)
async def revoke(
    key_id: str, request: Request, session: AsyncSession = Depends(get_session)
) -> None:
    row = await session.get(Key, key_id)
    if not row:
        raise HTTPException(404, "key not found")
    await revoke_key(session, row)
    await append_event(
        session,
        who=request.headers.get("X-Actor", "admin"),
        kind="mcp.key.revoke",
        target=row.label,
        src="web",
        ip=request.client.host if request.client else "",
        result="OK",
    )
