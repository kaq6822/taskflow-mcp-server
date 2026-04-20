from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.api import artifacts as artifacts_api
from app.api import audit as audit_api
from app.api import jobs as jobs_api
from app.api import keys as keys_api
from app.api import runs as runs_api
from app.api import stream as stream_api
from app.bootstrap import ensure_admin_session
from app.config import settings
from app.db import SessionLocal, engine
from app.models import Base
from app.services.artifacts import ensure_storage_dirs


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    allow_origins=settings.effective_cors_origins,
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
    return {"status": "ok", "env": settings.env}


# ---- Production static SPA ------------------------------------------------
# In production we serve the Vite `dist/` output from the same origin as the
# API so there is no cross-origin concern and no second process to deploy.
# `index.html` handles client routing; unknown non-API paths fall back to it.
def _mount_frontend() -> None:
    if settings.env != "production":
        return
    if settings.frontend_dist_dir is None:
        raise RuntimeError(
            "TASKFLOW_ENV=production requires TASKFLOW_FRONTEND_DIST_DIR to be set "
            "(e.g. ../frontend/dist). Use `make start` or set the variable manually."
        )
    dist = Path(settings.frontend_dist_dir)
    if not dist.exists() or not (dist / "index.html").exists():
        raise RuntimeError(
            f"TASKFLOW_FRONTEND_DIST_DIR={dist} does not contain index.html. "
            "Run `make build` first (or `cd frontend && npm run build`)."
        )

    assets_dir = dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(request: Request, full_path: str) -> FileResponse:
        # Let API and docs routes keep their 404s.
        if full_path.startswith(("api/", "api")) or full_path in {"openapi.json", "docs", "redoc"}:
            from fastapi import HTTPException

            raise HTTPException(status_code=404)
        candidate = dist / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


_mount_frontend()
