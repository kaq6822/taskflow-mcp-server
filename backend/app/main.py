from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import artifacts as artifacts_api
from app.api import audit as audit_api
from app.api import jobs as jobs_api
from app.api import keys as keys_api
from app.api import runs as runs_api
from app.api import stream as stream_api
from app.bootstrap import ensure_admin_session
from app.db import SessionLocal, engine
from app.models import Base
from app.services.artifacts import ensure_storage_dirs


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables if not present (first-boot friendliness; alembic still preferred)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ensure_storage_dirs()
    async with SessionLocal() as session:  # type: AsyncSession
        token = await ensure_admin_session(session)
        if token:
            print("=" * 60)
            print("TaskFlow first boot — admin session token:")
            print(f"  {token}")
            print("store this safely; it will not be shown again.")
            print("=" * 60)
    yield


app = FastAPI(title="TaskFlow API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_api.router)
app.include_router(runs_api.router)
app.include_router(stream_api.router)
app.include_router(artifacts_api.router)
app.include_router(audit_api.router)
app.include_router(keys_api.router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
