from __future__ import annotations

import hashlib
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session


async def ensure_admin_session(session: AsyncSession) -> str | None:
    """On first boot, mint a local admin session token and print it to stdout.

    Returns the plaintext token if a new one was created, None if one already exists.
    This is *not* seed data — it is a single security artefact required for UI use.
    """
    existing = (await session.execute(select(Session).limit(1))).scalar_one_or_none()
    if existing:
        return None
    plaintext = "tf_session_" + secrets.token_urlsafe(24)
    row = Session(
        id="s_" + uuid.uuid4().hex[:12],
        token_hash=hashlib.sha256(plaintext.encode()).hexdigest(),
        label="admin",
    )
    session.add(row)
    await session.flush()
    await session.commit()
    return plaintext
