from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Load dotenv from both `backend/.env` (when cwd=backend) and the repo
    # root `../.env` (which is what README instructs the user to create).
    # Later entries in the tuple win, so a repo-root override takes precedence.
    model_config = SettingsConfigDict(
        env_prefix="TASKFLOW_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_url: str = "sqlite+aiosqlite:///./taskflow.db"
    storage_dir: Path = Path("./storage")
    step_cwd: Path = Path("./storage/runtime")
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 7391
    mcp_max_sync_sec: int = 600
    allowlist_path: Path = Path("./app/dev/allowlist.yaml")

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


settings = Settings()
