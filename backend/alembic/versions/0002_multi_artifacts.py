"""multi-artifact consumption

Replaces the single `jobs.consumes_artifact` name with an aliased list, and
`runs.artifact_ref` with a pinned map keyed by the same aliases.

Existing single-artifact rows are carried over under the alias `artifact`, so
environments that already had a value keep working (their steps just read
`ARTIFACT_ARTIFACT_PATH` unless the alias is renamed). Names with no READY
artifact behind them are dropped rather than migrated — see `upgrade`.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-13

"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY_ALIAS = "artifact"


def _as_json(raw: object, default: object) -> object:
    """Read a JSON column that different drivers hand back differently.

    SQLite returns the stored text, while Postgres deserializes `JSON`/`JSONB`
    before it reaches `sa.text()` — `json.loads` on the latter raises TypeError.
    """
    if raw is None:
        return default
    return json.loads(raw) if isinstance(raw, str) else raw


def upgrade() -> None:
    conn = op.get_bind()

    with op.batch_alter_table("jobs") as b:
        b.add_column(
            sa.Column("consumes_artifacts", sa.JSON(), nullable=False, server_default="[]")
        )
    with op.batch_alter_table("runs") as b:
        b.add_column(
            sa.Column("artifact_refs", sa.JSON(), nullable=False, server_default="{}")
        )

    # Before this revision `consumes_artifact` was inert: nothing resolved it and
    # no run was gated on it. Now every declared entry is resolved at trigger
    # time, so carrying over a name that has no READY artifact would turn a
    # working Job into one that fails every single run. Migrate the resolvable
    # ones and drop the rest — the operator can re-declare them once the
    # artifact exists, which is far easier to notice than a run that 404s.
    ready = {
        row[0]
        for row in conn.execute(
            sa.text("SELECT DISTINCT name FROM artifacts WHERE status = 'READY'")
        ).fetchall()
    }
    dropped: list[str] = []
    for job_id, legacy in conn.execute(
        sa.text("SELECT id, consumes_artifact FROM jobs WHERE consumes_artifact IS NOT NULL")
    ).fetchall():
        name = (legacy or "").strip()
        if not name:
            continue
        if name not in ready:
            dropped.append(f"{job_id}→{name}")
            continue
        conn.execute(
            sa.text("UPDATE jobs SET consumes_artifacts = :v WHERE id = :id"),
            {"v": json.dumps([{"alias": _LEGACY_ALIAS, "name": name}]), "id": job_id},
        )
    if dropped:
        print(
            f"[0002] dropped {len(dropped)} unresolvable consumes_artifact "
            f"declaration(s); re-add them once the artifact is uploaded: "
            f"{', '.join(dropped)}"
        )

    for run_id, legacy in conn.execute(
        sa.text("SELECT id, artifact_ref FROM runs WHERE artifact_ref IS NOT NULL")
    ).fetchall():
        if not (legacy or "").strip():
            continue
        conn.execute(
            sa.text("UPDATE runs SET artifact_refs = :v WHERE id = :id"),
            {"v": json.dumps({_LEGACY_ALIAS: {"ref": legacy, "sha256": ""}}), "id": run_id},
        )

    with op.batch_alter_table("jobs") as b:
        b.drop_column("consumes_artifact")
    with op.batch_alter_table("runs") as b:
        b.drop_column("artifact_ref")


def downgrade() -> None:
    conn = op.get_bind()

    with op.batch_alter_table("jobs") as b:
        b.add_column(sa.Column("consumes_artifact", sa.String(100), nullable=True))
    with op.batch_alter_table("runs") as b:
        b.add_column(sa.Column("artifact_ref", sa.String(200), nullable=True))

    # Only the first entry survives the round-trip — the old schema cannot
    # express more than one artifact per job.
    for job_id, raw in conn.execute(
        sa.text("SELECT id, consumes_artifacts FROM jobs")
    ).fetchall():
        entries = _as_json(raw, [])
        if not entries:
            continue
        conn.execute(
            sa.text("UPDATE jobs SET consumes_artifact = :v WHERE id = :id"),
            {"v": entries[0].get("name"), "id": job_id},
        )

    for run_id, raw in conn.execute(sa.text("SELECT id, artifact_refs FROM runs")).fetchall():
        refs = _as_json(raw, {})
        if not refs:
            continue
        first = next(iter(refs.values()))
        conn.execute(
            sa.text("UPDATE runs SET artifact_ref = :v WHERE id = :id"),
            {"v": first.get("ref"), "id": run_id},
        )

    with op.batch_alter_table("jobs") as b:
        b.drop_column("consumes_artifacts")
    with op.batch_alter_table("runs") as b:
        b.drop_column("artifact_refs")
