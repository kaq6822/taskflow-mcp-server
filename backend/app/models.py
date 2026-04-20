from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Naive UTC. SQLite's DateTime adapter can lose tzinfo on round-trip, which
    breaks the audit hash-chain reproducibility. We normalise to tz-naive UTC
    everywhere so write/read produce identical isoformat()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(String(100))
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    schedule: Mapped[str] = mapped_column(String(100), default="manual")
    timeout: Mapped[int] = mapped_column(Integer, default=600)
    concurrency: Mapped[int] = mapped_column(Integer, default=1)
    on_failure: Mapped[str] = mapped_column(String(20), default="STOP")
    consumes_artifact: Mapped[str | None] = mapped_column(String(100), nullable=True)
    steps: Mapped[list[dict]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    runs: Mapped[list[Run]] = relationship(back_populates="job", cascade="all,delete-orphan")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    actor: Mapped[str] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_sec: Mapped[float] = mapped_column(default=0.0)
    order: Mapped[list[str]] = mapped_column(JSON, default=list)
    artifact_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    failed_step: Mapped[str | None] = mapped_column(String(100), nullable=True)
    err_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)

    job: Mapped[Job] = relationship(back_populates="runs")
    steps: Mapped[list[RunStep]] = relationship(
        back_populates="run", cascade="all,delete-orphan", order_by="RunStep.id"
    )


class RunStep(Base):
    __tablename__ = "run_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    step_id: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(20), default="PENDING")
    elapsed_sec: Mapped[float] = mapped_column(default=0.0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    logs_path: Mapped[str | None] = mapped_column(String(400), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    run: Mapped[Run] = relationship(back_populates="steps")


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_artifact_name_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(100))
    ext: Mapped[str] = mapped_column(String(20))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(100))
    uploader: Mapped[str] = mapped_column(String(100))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    latest: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="SCANNING")
    blob_path: Mapped[str] = mapped_column(String(400))
    consumers: Mapped[list[str]] = mapped_column(JSON, default=list)


class AuditEvent(Base):
    __tablename__ = "audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    who: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(50))
    target: Mapped[str] = mapped_column(String(400), default="")
    src: Mapped[str] = mapped_column(String(20))  # web | mcp | api | sched
    ip: Mapped[str] = mapped_column(String(64), default="")
    result: Mapped[str] = mapped_column(String(10))  # OK | DENY | FAIL
    prev_hash: Mapped[str] = mapped_column(String(100), default="")
    content_hash: Mapped[str] = mapped_column(String(100), default="")


class Key(Base):
    __tablename__ = "keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200))
    key_hash: Mapped[str] = mapped_column(String(200))
    key_prefix: Mapped[str] = mapped_column(String(50))
    key_suffix: Mapped[str] = mapped_column(String(20))
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rate_limit: Mapped[str] = mapped_column(String(20), default="30/min")
    state: Mapped[str] = mapped_column(String(20), default="ACTIVE")


class Session(Base):
    """Local admin session token for UI. Issued once by bootstrap.py."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(200))
    label: Mapped[str] = mapped_column(String(100), default="admin")
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
