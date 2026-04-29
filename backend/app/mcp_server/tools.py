from __future__ import annotations

import asyncio
import base64
import binascii

from mcp.server.fastmcp import Context, FastMCP
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import SessionLocal
from app.engine.log_bus import log_bus
from app.engine.run_engine import get_engine
from app.mcp_server.auth import auth_from_context, ip_from_context
from app.models import Artifact, Job, Run, RunStep
from app.services.artifacts import ArtifactValidationError, save_upload_bytes
from app.services.audit import append_event
from app.services.keys import scope_allows


class DeniedError(Exception):
    pass


async def _require(ctx: Context, required: str, target: str = ""):
    """Check that the authenticated MCP key has the `required` scope.

    P2-10: on denial, record an `auth.fail` audit event (src=mcp) before
    raising — otherwise rejected tool calls silently disappear from the log,
    violating docs/02 §7.3."""
    auth = auth_from_context(ctx)
    if auth is None:
        raise RuntimeError("unauthenticated (middleware missing)")
    if not scope_allows(auth.scopes, required):
        async with SessionLocal() as s:
            await append_event(
                s,
                who=auth.label,
                kind="auth.fail",
                target=target or required,
                src="mcp",
                ip=ip_from_context(ctx),
                result="DENY",
            )
        raise RuntimeError(f"DENY: scope '{required}' not permitted")
    return auth


def _job_to_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "name": job.name,
        "description": job.description,
        "owner": job.owner,
        "tags": job.tags,
        "schedule": job.schedule,
        "timeout": job.timeout,
        "concurrency": job.concurrency,
        "on_failure": job.on_failure,
        "consumes_artifact": job.consumes_artifact,
        "steps": job.steps,
    }


def _run_to_dict(run: Run, steps: list[RunStep]) -> dict:
    return {
        "run_id": run.id,
        "job_id": run.job_id,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_sec": run.duration_sec,
        "artifact_ref": run.artifact_ref,
        "steps": [
            {"id": s.step_id, "state": s.state, "elapsed_sec": s.elapsed_sec}
            for s in steps
        ],
        "failed_step": run.failed_step,
        "err_message": run.err_message,
        "logs_uri": f"taskflow://runs/{run.id}/logs",
    }


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def list_jobs(ctx: Context) -> list[dict]:
        """List all defined jobs. scope: read:jobs"""
        await _require(ctx, "read:jobs")
        async with SessionLocal() as s:
            rows = (await s.execute(select(Job).order_by(Job.updated_at.desc()))).scalars().all()
            return [_job_to_dict(j) for j in rows]

    @mcp.tool()
    async def get_job(job_id: str, ctx: Context) -> dict:
        """Get a single job by id. scope: read:jobs"""
        await _require(ctx, "read:jobs", target=job_id)
        async with SessionLocal() as s:
            j = await s.get(Job, job_id)
            if not j:
                raise RuntimeError(f"NOT_FOUND: job {job_id}")
            return _job_to_dict(j)

    @mcp.tool()
    async def list_runs(
        ctx: Context, job_id: str | None = None, status: str | None = None, limit: int = 20
    ) -> list[dict]:
        """List runs, optionally filtered. scope: read:runs"""
        await _require(ctx, "read:runs")
        async with SessionLocal() as s:
            q = (
                select(Run)
                .options(selectinload(Run.steps))
                .order_by(Run.id.desc())
                .limit(min(limit, 200))
            )
            if job_id:
                q = q.where(Run.job_id == job_id)
            if status:
                q = q.where(Run.status == status)
            rows = (await s.execute(q)).scalars().all()
            return [_run_to_dict(r, r.steps) for r in rows]

    @mcp.tool()
    async def get_run(run_id: int, ctx: Context) -> dict:
        """Fetch a run's status + structured result (Agent schema). scope: read:runs"""
        await _require(ctx, "read:runs", target=f"run #{run_id}")
        async with SessionLocal() as s:
            r = (
                await s.execute(
                    select(Run).options(selectinload(Run.steps)).where(Run.id == run_id)
                )
            ).scalar_one_or_none()
            if not r:
                raise RuntimeError(f"NOT_FOUND: run {run_id}")
            return _run_to_dict(r, r.steps)

    @mcp.tool()
    async def get_run_logs(
        run_id: int, step_id: str, ctx: Context, tail: int = 200
    ) -> str:
        """Fetch step stdout+stderr as plain text. scope: read:runs"""
        await _require(ctx, "read:runs", target=f"run #{run_id}/{step_id}")
        path = settings.logs_dir / str(run_id) / f"{step_id}.log"
        if not path.exists():
            raise RuntimeError(f"NOT_FOUND: logs for run {run_id} step {step_id}")
        with path.open("r", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-tail:])

    @mcp.tool()
    async def upload_artifact(
        name: str,
        version: str,
        content_base64: str,
        ctx: Context,
        ext: str = "tar.gz",
    ) -> dict:
        """Upload a build artifact. `content_base64` is the file bytes, base64-encoded.
        scope: write:uploads"""
        auth = await _require(ctx, "write:uploads", target=f"{name}@{version}")
        try:
            raw = base64.b64decode(content_base64, validate=True)
        except binascii.Error as e:
            raise RuntimeError(f"INVALID_ARTIFACT: base64 decode failed: {e}") from e
        async with SessionLocal() as s:
            dup = (
                await s.execute(
                    select(Artifact).where(Artifact.name == name, Artifact.version == version)
                )
            ).scalar_one_or_none()
            if dup:
                raise RuntimeError(f"CONFLICT: artifact {name}@{version} already exists")
            try:
                art = await save_upload_bytes(
                    session=s,
                    name=name,
                    version=version,
                    ext=ext,
                    uploader=auth.label,
                    data=raw,
                )
            except ArtifactValidationError as e:
                raise RuntimeError(f"INVALID_ARTIFACT: {e}") from e
            await append_event(
                s,
                who=auth.label,
                kind="artifact.upload",
                target=f"{name}@{version}",
                src="mcp",
                ip=ip_from_context(ctx),
                result="OK",
            )
            await s.refresh(art)
            return {
                "artifact_id": art.id,
                "name": art.name,
                "version": art.version,
                "sha256": art.sha256,
                "status": art.status,
                "size_bytes": art.size_bytes,
            }

    @mcp.tool()
    async def get_artifact(name: str, version: str, ctx: Context) -> dict:
        """Check an artifact's READY/SCANNING status. scope: read:jobs"""
        await _require(ctx, "read:jobs", target=f"{name}@{version}")
        async with SessionLocal() as s:
            if version == "latest":
                row = (
                    await s.execute(
                        select(Artifact)
                        .where(Artifact.name == name, Artifact.latest)
                        .limit(1)
                    )
                ).scalar_one_or_none()
            else:
                row = (
                    await s.execute(
                        select(Artifact).where(
                            Artifact.name == name, Artifact.version == version
                        )
                    )
                ).scalar_one_or_none()
            if not row:
                raise RuntimeError(f"NOT_FOUND: artifact {name}@{version}")
            return {
                "artifact_id": row.id,
                "name": row.name,
                "version": row.version,
                "sha256": row.sha256,
                "status": row.status,
                "size_bytes": row.size_bytes,
            }

    @mcp.tool()
    async def run_job(
        job_id: str,
        ctx: Context,
        mode: str = "sync",
        artifact_ref: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        """Trigger a run of `job_id`. modes: sync | async.
        scope: run:<job_id> (or run:*)"""
        auth = await _require(ctx, f"run:{job_id}", target=job_id)
        engine = get_engine()
        async with SessionLocal() as s:
            job = await s.get(Job, job_id)
            if not job:
                raise RuntimeError(f"NOT_FOUND: job {job_id}")
            if idempotency_key:
                existing = (
                    await s.execute(
                        select(Run)
                        .options(selectinload(Run.steps))
                        .where(Run.idempotency_key == idempotency_key)
                    )
                ).scalar_one_or_none()
                if existing:
                    return _run_to_dict(existing, existing.steps)
            if engine.live_run_for(job_id):
                raise RuntimeError(
                    f"CONFLICT: job {job_id} already running as #{engine.live_run_for(job_id)}"
                )
            run = await engine.start(
                s,
                job=job,
                trigger="mcp",
                actor=auth.label,
                artifact_ref=artifact_ref,
                idempotency_key=idempotency_key,
            )
            await append_event(
                s,
                who=auth.label,
                kind="mcp.run",
                target=f"{job_id} #{run.id}",
                src="mcp",
                ip=ip_from_context(ctx),
                result="OK",
            )
            engine.launch(run.id)
            run_id = run.id

        if mode == "async":
            return {"run_id": run_id, "status": "RUNNING", "poll_url": f"taskflow://runs/{run_id}"}

        deadline = asyncio.get_event_loop().time() + settings.mcp_max_sync_sec
        while asyncio.get_event_loop().time() < deadline:
            async with SessionLocal() as s2:
                r = (
                    await s2.execute(
                        select(Run).options(selectinload(Run.steps)).where(Run.id == run_id)
                    )
                ).scalar_one_or_none()
                if r and r.status != "RUNNING":
                    return _run_to_dict(r, r.steps)
            await asyncio.sleep(0.3)
        return {"run_id": run_id, "status": "RUNNING", "degraded_to": "async"}

    @mcp.tool()
    async def cancel_run(run_id: int, ctx: Context) -> dict:
        """Cancel a running run. scope: run:<job_id> of the run"""
        async with SessionLocal() as s:
            r = await s.get(Run, run_id)
            if not r:
                raise RuntimeError(f"NOT_FOUND: run {run_id}")
            auth = await _require(ctx, f"run:{r.job_id}", target=f"{r.job_id} #{run_id}")
            engine = get_engine()
            cancelled = await engine.cancel(s, run_id)
            if not cancelled:
                raise RuntimeError(f"NOT_RUNNING: run {run_id} is not running")
            await append_event(
                s,
                who=auth.label,
                kind="job.run.cancel",
                target=f"{r.job_id} #{r.id}",
                src="mcp",
                ip=ip_from_context(ctx),
                result="OK",
            )
            # re-read with steps after cancel finalization
            r = (
                await s.execute(
                    select(Run).options(selectinload(Run.steps)).where(Run.id == run_id)
                )
            ).scalar_one()
            return _run_to_dict(r, r.steps)

    @mcp.tool()
    async def subscribe_run(run_id: int, ctx: Context, tail: int = 200) -> list[dict]:
        """Return the latest event snapshot for a running run (log_bus tail).
        For true streaming, clients should use the HTTP SSE endpoint.
        scope: read:runs"""
        await _require(ctx, "read:runs", target=f"run #{run_id}")
        snap = log_bus.snapshot(run_id)
        return snap[-tail:]
