from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_session
from app.engine.run_engine import get_engine
from app.models import Job, Run
from app.schemas import RunCreate, RunOut
from app.services.artifacts import ArtifactResolutionError
from app.services.audit import append_event

router = APIRouter(prefix="/api", tags=["runs"])

def _replay_or_conflict(existing: Run, job_id: str, key: str | None) -> None:
    """Raise unless `existing` is this job's own run for `key`.

    `Run.idempotency_key` is unique table-wide, so a key can already belong to a
    different job. Returning that run would answer 201 for a deploy that never
    ran, and it cannot be inserted either. `current_run_id` is null rather than
    the other job's run id: the 409 contract (docs/03-system-spec.md §2.5) says
    the field is present, but the caller is only scoped to `job_id` and must not
    learn another job's ids from a probe.
    """
    if existing.job_id == job_id:
        return
    raise HTTPException(
        409,
        detail={
            "error": "CONFLICT",
            "current_run_id": None,
            "message": f"idempotency_key {key!r} is already used by another job",
        },
    )


# docs/03-system-spec.md §123 error vocabulary → HTTP status.
_ARTIFACT_ERROR_STATUS = {
    "NOT_FOUND": 404,
    "NOT_READY": 409,
    "INVALID_ARTIFACT": 400,
    "UNKNOWN_ALIAS": 400,
    "MISMATCH": 400,
}


@router.get("/runs", response_model=list[RunOut])
async def list_runs(
    job_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[Run]:
    # P1-3: eager-load steps so Pydantic serialization doesn't trigger async
    # lazy-load (which fails with MissingGreenlet and 500s the list endpoint).
    q = select(Run).options(selectinload(Run.steps)).order_by(Run.id.desc()).limit(limit)
    if job_id:
        q = q.where(Run.job_id == job_id)
    if status:
        q = q.where(Run.status == status)
    return list((await session.execute(q)).scalars().all())


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: int, session: AsyncSession = Depends(get_session)) -> Run:
    run = (
        await session.execute(
            select(Run).options(selectinload(Run.steps)).where(Run.id == run_id)
        )
    ).scalar_one_or_none()
    if not run:
        raise HTTPException(404, "run not found")
    return run


@router.get("/runs/{run_id}/logs/{step_id}", response_class=PlainTextResponse)
async def get_run_logs(
    run_id: int,
    step_id: str,
    tail: int = Query(200, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
) -> PlainTextResponse:
    run = (
        await session.execute(
            select(Run).options(selectinload(Run.steps)).where(Run.id == run_id)
        )
    ).scalar_one_or_none()
    if not run:
        raise HTTPException(404, "run not found")

    step = next((s for s in run.steps if s.step_id == step_id), None)
    if not step:
        raise HTTPException(404, "step not found")

    log_path = (
        Path(step.logs_path)
        if step.logs_path
        else settings.logs_dir / str(run_id) / f"{step_id}.log"
    )
    try:
        resolved = log_path.resolve()
        resolved.relative_to(settings.logs_dir.resolve())
    except ValueError:
        raise HTTPException(400, "invalid log path")

    if not resolved.exists():
        raise HTTPException(404, "log not found")

    with resolved.open("r", errors="replace") as f:
        lines = f.readlines()
    return PlainTextResponse("".join(lines[-tail:]), media_type="text/plain; charset=utf-8")


@router.post("/jobs/{job_id}/runs", response_model=RunOut, status_code=201)
async def start_run(
    job_id: str,
    body: RunCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Run:
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")

    # idempotency
    if body.idempotency_key:
        existing = (
            await session.execute(
                select(Run)
                .options(selectinload(Run.steps))  # P1-3: see list_runs
                .where(Run.idempotency_key == body.idempotency_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            _replay_or_conflict(existing, job_id, body.idempotency_key)
            return existing

    engine = get_engine()
    live = engine.live_run_for(job_id)
    if live:
        raise HTTPException(409, detail={"error": "CONFLICT", "current_run_id": live})

    actor = body.actor or request.headers.get("X-Actor", "admin")
    try:
        run = await engine.start(
            session,
            job=job,
            trigger=body.trigger,
            actor=actor,
            artifact_refs=body.artifact_refs,
            idempotency_key=body.idempotency_key,
        )
    except ArtifactResolutionError as e:
        await append_event(
            session,
            who=actor,
            kind="job.run",
            target=job_id,
            src="mcp" if body.trigger == "mcp" else "web",
            ip=request.client.host if request.client else "",
            result="DENY",
        )
        raise HTTPException(
            _ARTIFACT_ERROR_STATUS.get(e.code, 400),
            detail={"error": e.code, "message": e.message},
        )
    except IntegrityError:
        # The lookup above and this insert are not atomic, and the key is unique
        # table-wide: a concurrent trigger for another job can claim it in
        # between. Re-read and answer as the lookup would have.
        await session.rollback()
        winner = (
            await session.execute(
                select(Run)
                .options(selectinload(Run.steps))
                .where(Run.idempotency_key == body.idempotency_key)
            )
        ).scalar_one_or_none()
        if winner is None:
            raise
        _replay_or_conflict(winner, job_id, body.idempotency_key)
        return winner
    await append_event(
        session,
        who=actor,
        kind="job.run" if body.trigger != "mcp" else "mcp.run",
        target=f"{job_id} #{run.id}",
        src="mcp" if body.trigger == "mcp" else "web",
        ip=request.client.host if request.client else "",
        result="OK",
    )
    engine.launch(run.id)
    await session.refresh(run, ["steps"])
    return run


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
async def cancel_run(
    run_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> Run:
    engine = get_engine()
    run = await engine.cancel(session, run_id)
    if not run:
        raise HTTPException(404, "run not found or already finished")
    await append_event(
        session,
        who=request.headers.get("X-Actor", "admin"),
        kind="job.run.cancel",
        target=f"{run.job_id} #{run.id}",
        src="web",
        ip=request.client.host if request.client else "",
        result="OK",
    )
    await session.refresh(run, ["steps"])
    return run


@router.post("/jobs/{job_id}/runs/cancel", response_model=RunOut)
async def cancel_job_run(
    job_id: str, request: Request, session: AsyncSession = Depends(get_session)
) -> Run:
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")

    engine = get_engine()
    run_id = engine.live_run_for(job_id)
    if run_id is None:
        row = (
            await session.execute(
                select(Run)
                .where(Run.job_id == job_id, Run.status == "RUNNING")
                .order_by(Run.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        run_id = row.id if row else None
    if run_id is None:
        raise HTTPException(404, "no running run for job")

    run = await engine.cancel(session, run_id)
    if not run:
        raise HTTPException(404, "run not found or already finished")
    await append_event(
        session,
        who=request.headers.get("X-Actor", "admin"),
        kind="job.run.cancel",
        target=f"{run.job_id} #{run.id}",
        src="web",
        ip=request.client.host if request.client else "",
        result="OK",
    )
    await session.refresh(run, ["steps"])
    return run
