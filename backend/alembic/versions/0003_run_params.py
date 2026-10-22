"""trigger-time run parameters

Adds `jobs.params` (the declaration) and `runs.params` (the resolved values
pinned on each run). Existing rows get empty defaults: a Job with no declared
params behaves exactly as before.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as b:
        b.add_column(sa.Column("params", sa.JSON(), nullable=False, server_default="[]"))
    with op.batch_alter_table("runs") as b:
        b.add_column(sa.Column("params", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as b:
        b.drop_column("params")
    with op.batch_alter_table("runs") as b:
        b.drop_column("params")
