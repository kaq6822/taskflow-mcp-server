from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# aiosqlite's default busy timeout is 5s. Under concurrent workers + the audit
# lock, brief waits up to ~10s can happen before the writer yields, so raise
# the driver timeout and enable WAL so readers never block writers.
engine = create_async_engine(
    settings.db_url,
    future=True,
    connect_args={"timeout": 30} if settings.db_url.startswith("sqlite") else {},
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


if settings.db_url.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()


async def get_session() -> AsyncIterator[AsyncSession]:  # noqa: D401 (FastAPI dep)
    async with SessionLocal() as session:
        yield session
