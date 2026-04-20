from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# isolate each test run with a fresh SQLite file + storage dir
_TMP = Path(tempfile.mkdtemp(prefix="tf-test-"))
os.environ.setdefault("TASKFLOW_DB_URL", f"sqlite+aiosqlite:///{_TMP}/taskflow.db")
os.environ.setdefault("TASKFLOW_STORAGE_DIR", str(_TMP / "storage"))
os.environ.setdefault("TASKFLOW_STEP_CWD", str(_TMP / "storage/runtime"))

from app.config import settings  # noqa: E402
from app.models import Base  # noqa: E402


@pytest_asyncio.fixture()
async def session() -> AsyncSession:
    engine = create_async_engine(settings.db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


@pytest.fixture(autouse=True)
def reset_rate_bucket():
    from app.services.keys import _RATE_BUCKETS

    _RATE_BUCKETS.clear()
    yield
    _RATE_BUCKETS.clear()
