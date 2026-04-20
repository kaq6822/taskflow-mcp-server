"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("owner", sa.String(100), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("schedule", sa.String(100), nullable=False, server_default="manual"),
        sa.Column("timeout", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("concurrency", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("on_failure", sa.String(20), nullable=False, server_default="STOP"),
        sa.Column("consumes_artifact", sa.String(100), nullable=True),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="RUNNING"),
        sa.Column("trigger", sa.String(20), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_sec", sa.Float(), nullable=False, server_default="0"),
        sa.Column("order", sa.JSON(), nullable=False),
        sa.Column("artifact_ref", sa.String(200), nullable=True),
        sa.Column("failed_step", sa.String(100), nullable=True),
        sa.Column("err_message", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=True, unique=True),
    )
    op.create_table(
        "run_steps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("step_id", sa.String(100), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("elapsed_sec", sa.Float(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("logs_path", sa.String(400), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
    )
    op.create_table(
        "artifacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("version", sa.String(100), nullable=False),
        sa.Column("ext", sa.String(20), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(100), nullable=False),
        sa.Column("uploader", sa.String(100), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latest", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(20), nullable=False, server_default="SCANNING"),
        sa.Column("blob_path", sa.String(400), nullable=False),
        sa.Column("consumers", sa.JSON(), nullable=False),
        sa.UniqueConstraint("name", "version", name="uq_artifact_name_version"),
    )
    op.create_table(
        "audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("who", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("target", sa.String(400), nullable=False, server_default=""),
        sa.Column("src", sa.String(20), nullable=False),
        sa.Column("ip", sa.String(64), nullable=False, server_default=""),
        sa.Column("result", sa.String(10), nullable=False),
        sa.Column("prev_hash", sa.String(100), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(100), nullable=False, server_default=""),
    )
    op.create_table(
        "keys",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("key_hash", sa.String(200), nullable=False),
        sa.Column("key_prefix", sa.String(50), nullable=False),
        sa.Column("key_suffix", sa.String(20), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rate_limit", sa.String(20), nullable=False, server_default="30/min"),
        sa.Column("state", sa.String(20), nullable=False, server_default="ACTIVE"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("token_hash", sa.String(200), nullable=False),
        sa.Column("label", sa.String(100), nullable=False, server_default="admin"),
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sessions")
    op.drop_table("keys")
    op.drop_table("audit")
    op.drop_table("artifacts")
    op.drop_table("run_steps")
    op.drop_table("runs")
    op.drop_table("jobs")
