from __future__ import annotations

import pytest

from app.services.audit import append_event, verify_chain


@pytest.mark.asyncio
async def test_chain_is_intact_after_many_appends(session):
    for i in range(10):
        await append_event(
            session,
            who=f"actor-{i}",
            kind="job.run" if i % 2 == 0 else "mcp.run",
            target=f"t-{i}",
            src="web" if i % 3 == 0 else "mcp",
            ip="127.0.0.1",
            result="OK",
        )
    await session.commit()
    ok, broken = await verify_chain(session)
    assert ok is True
    assert broken is None


@pytest.mark.asyncio
async def test_tampering_breaks_chain(session):
    for i in range(3):
        await append_event(session, who=f"a{i}", kind="k", target="t", src="web", result="OK")
    await session.commit()
    # Tamper row 2: change the `who` field without recomputing hash
    from sqlalchemy import select, update

    from app.models import AuditEvent

    await session.execute(update(AuditEvent).where(AuditEvent.id == 2).values(who="attacker"))
    await session.commit()

    ok, broken = await verify_chain(session)
    assert ok is False
    assert broken == 2
