"""at most one RUNNING run per job; record which process runs it

Adds a partial unique index on `runs.job_id` where `status = 'RUNNING'`. The
backend and the MCP server each keep their own in-memory engine, so only the
database can stop both from starting the same job at once.

Any job already holding several RUNNING rows (left behind by a crash, or by the
race this index closes) would make the index creation fail. All but the newest
are marked FAILED first; the newest stays so a run that is genuinely still
executing is not misreported.

Adds `runs.runner` ("api" / "mcp") so each process can finalize its own
orphaned RUNNING runs at startup. Existing rows stay null: which process ran
them is unknown, so a leftover one is cancelled by hand.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RUNNING = sa.text("status = 'RUNNING'")


def upgrade() -> None:
    with op.batch_alter_table("runs") as b:
        b.add_column(sa.Column("runner", sa.String(20), nullable=True))
    stale = (
        "SELECT id FROM runs WHERE status = 'RUNNING' AND id NOT IN "
        "(SELECT MAX(id) FROM runs WHERE status = 'RUNNING' GROUP BY job_id)"
    )
    op.execute(
        f"UPDATE run_steps SET state = 'FAILED' WHERE state = 'RUNNING' AND run_id IN ({stale})"
    )
    op.execute(
        """
        UPDATE runs
        SET status = 'FAILED',
            err_message = COALESCE(err_message, '중복 RUNNING 정리 (migration 0005)'),
            finished_at = COALESCE(finished_at, started_at)
        WHERE status = 'RUNNING'
          AND id NOT IN (
            SELECT MAX(id) FROM runs WHERE status = 'RUNNING' GROUP BY job_id
          )
        """
    )
    op.create_index(
        "uq_runs_job_running",
        "runs",
        ["job_id"],
        unique=True,
        sqlite_where=_RUNNING,
        postgresql_where=_RUNNING,
    )


def downgrade() -> None:
    op.drop_index("uq_runs_job_running", table_name="runs")
    with op.batch_alter_table("runs") as b:
        b.drop_column("runner")
