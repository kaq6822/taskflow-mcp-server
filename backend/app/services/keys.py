from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from collections import defaultdict, deque
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Key, utcnow

_RATE_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


def _hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def _mint_plaintext() -> str:
    return "mcp_tk_live_" + secrets.token_urlsafe(32)


async def issue_key(
    session: AsyncSession,
    *,
    label: str,
    scopes: list[str],
    expires_days: int,
    rate_limit: str,
) -> tuple[Key, str]:
    plaintext = _mint_plaintext()
    key = Key(
        id="k_" + uuid.uuid4().hex[:12],
        label=label,
        key_hash=_hash_token(plaintext),
        key_prefix=plaintext[:16],
        key_suffix=plaintext[-4:],
        scopes=list(scopes),
        expires=utcnow() + timedelta(days=expires_days),
        rate_limit=rate_limit,
        state="ACTIVE",
    )
    session.add(key)
    await session.flush()
    return key, plaintext


async def revoke_key(session: AsyncSession, key: Key) -> None:
    key.state = "REVOKED"
    key.scopes = []
    await session.flush()


def scope_allows(scopes: list[str], required: str) -> bool:
    """`required` like 'run:deploy-web' / 'read:jobs' / 'write:uploads'.

    Matching rules (docs/02 §7.3): exact > wildcard. `run:<id>` covered by `run:*` or exact.
    `read:*` covers any `read:*`. Write scopes must be exact.
    """
    if required in scopes:
        return True
    ns, _, target = required.partition(":")
    if f"{ns}:*" in scopes:
        return True
    return False


def parse_rate_limit(rate: str) -> int:
    """'30/min' → 30. Unknown → 30."""
    try:
        return int(rate.split("/", 1)[0])
    except Exception:
        return 30


def rate_limit_ok(key_id: str, rate: str) -> tuple[bool, int]:
    """Token bucket over rolling 60s window. Returns (ok, retry_after_seconds)."""
    allowed = parse_rate_limit(rate)
    now = time.monotonic()
    window_start = now - 60.0
    bucket = _RATE_BUCKETS[key_id]
    while bucket and bucket[0] < window_start:
        bucket.popleft()
    if len(bucket) >= allowed:
        retry = int(60 - (now - bucket[0])) + 1
        return False, max(retry, 1)
    bucket.append(now)
    return True, 0


async def find_active_by_plaintext(session: AsyncSession, plaintext: str) -> Key | None:
    """Return the ACTIVE/EXPIRING key whose hash matches, else None."""
    from sqlalchemy import select

    th = _hash_token(plaintext)
    rows = (
        await session.execute(select(Key).where(Key.key_hash == th))
    ).scalars().all()
    for k in rows:
        if k.state in ("ACTIVE", "EXPIRING"):
            return k
    return None
