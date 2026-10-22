"""run outputs published by steps

Adds `runs.outputs`: the `::output key=value` lines steps printed, so a later
caller can read e.g. which commit the last successful deploy shipped.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as b:
        b.add_column(sa.Column("outputs", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("runs") as b:
        b.drop_column("outputs")
