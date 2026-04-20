from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.engine.run_engine import get_engine
from app.models import Job, Run
from app.schemas import RunCreate, RunOut
from app.services.audit import append_event

router = APIRouter(prefix="/api", tags=["runs"])


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
            await session.execute(select(Run).where(Run.idempotency_key == body.idempotency_key))
        ).scalar_one_or_none()
        if existing:
            return existing

    engine = get_engine()
    live = engine.live_run_for(job_id)
    if live:
        raise HTTPException(409, detail={"error": "CONFLICT", "current_run_id": live})

    actor = body.actor or request.headers.get("X-Actor", "admin")
    run = await engine.start(
        session,
        job=job,
        trigger=body.trigger,
        actor=actor,
        artifact_ref=body.artifact_ref,
        idempotency_key=body.idempotency_key,
    )
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
