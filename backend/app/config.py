from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Load dotenv from both `backend/.env` (when cwd=backend) and the repo
    # root `../.env` (which is what README instructs the user to create).
    # Later entries win, so a repo-root override takes precedence.
    model_config = SettingsConfigDict(
        env_prefix="TASKFLOW_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Runtime mode. `dev` keeps CORS permissive toward the Vite dev server and
    # does not serve the built frontend; `production` locks CORS to explicit
    # hosts and mounts `frontend_dist_dir` as a static SPA under `/`.
    env: Literal["dev", "production"] = "dev"

    db_url: str = "sqlite+aiosqlite:///./taskflow.db"
    storage_dir: Path = Path("./storage")
    step_cwd: Path = Path("./storage/runtime")

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 7391
    mcp_max_sync_sec: int = 600
    allowlist_path: Path = Path("./app/dev/allowlist.yaml")

    # Frontend dev server knobs — consumed by the Makefile + vite.config.ts
    # via explicit flags. These are declared here so a single .env controls
    # every process.
    frontend_host: str = "localhost"
    frontend_port: int = 5173

    # Optional path to a production `vite build` output. When set and the
    # mode is `production`, FastAPI mounts it as a static SPA under `/`.
    frontend_dist_dir: Path | None = None

    # CORS allow-list as a comma-separated string. Kept as `str` (not
    # `list[str]`) so pydantic-settings does not try to JSON-parse env values
    # and fail on plain comma lists. Use `effective_cors_origins` for the
    # parsed result.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def sync_db_url(self) -> str:
        """Alembic/sync SQLAlchemy URL (drops aiosqlite driver)."""
        return self.db_url.replace("sqlite+aiosqlite", "sqlite")

    @property
    def artifacts_dir(self) -> Path:
        return self.storage_dir / "artifacts"

    @property
    def logs_dir(self) -> Path:
        return self.storage_dir / "logs"

    @property
    def effective_cors_origins(self) -> list[str]:
        """Parse the comma-separated `cors_origins` env into a list, applying
        production safety.

        If any entry is "*", allow-all only in dev; in production we drop the
        wildcard and keep the explicit entries instead (so a stray env setting
        can't accidentally open the box)."""
        raw = (self.cors_origins or "").strip()
        if raw.startswith("["):
            import json as _json

            items = [str(x) for x in _json.loads(raw)]
        else:
            items = [s.strip() for s in raw.split(",") if s.strip()]
        if "*" in items:
            if self.env == "dev":
                return ["*"]
            return [o for o in items if o != "*"]
        return items


settings = Settings()
