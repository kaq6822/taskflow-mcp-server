"""drop runs.runner

The REST API and the MCP endpoint now run in one process with one engine
(`python -m app`), so there is no other process whose runs need telling apart.
Startup finalizes every leftover RUNNING run instead.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as b:
        b.drop_column("runner")


def downgrade() -> None:
    with op.batch_alter_table("runs") as b:
        b.add_column(sa.Column("runner", sa.String(20), nullable=True))
