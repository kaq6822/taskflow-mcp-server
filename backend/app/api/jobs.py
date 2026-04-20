from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.engine.dag import DagValidationError, validate_steps
from app.engine.policies import check_allowlist, AllowlistError
from app.models import Job
from app.schemas import JobCreate, JobOut, JobUpdate
from app.services.audit import append_event

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
async def list_jobs(session: AsyncSession = Depends(get_session)) -> list[Job]:
    rows = (await session.execute(select(Job).order_by(Job.updated_at.desc()))).scalars().all()
    return list(rows)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)) -> Job:
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@router.post("", response_model=JobOut, status_code=201)
async def create_job(
    body: JobCreate, request: Request, session: AsyncSession = Depends(get_session)
) -> Job:
    if await session.get(Job, body.id):
        raise HTTPException(409, "job already exists")
    steps_raw = [s.model_dump() for s in body.steps]
    try:
        validate_steps(steps_raw)
        for s in steps_raw:
            check_allowlist(s["cmd"])
    except (DagValidationError, AllowlistError) as e:
        await append_event(
            session,
            who=_actor(request),
            kind="policy.violation" if isinstance(e, AllowlistError) else "job.create",
            target=body.id,
            src="web",
            ip=_ip(request),
            result="DENY",
        )
        raise HTTPException(400, str(e))
    job = Job(
        id=body.id,
        name=body.name,
        description=body.description,
        owner=body.owner,
        tags=body.tags,
        schedule=body.schedule,
        timeout=body.timeout,
        concurrency=body.concurrency,
        on_failure=body.on_failure,
        consumes_artifact=body.consumes_artifact,
        steps=steps_raw,
    )
    session.add(job)
    await append_event(
        session,
        who=_actor(request),
        kind="job.create",
        target=body.id,
        src="web",
        ip=_ip(request),
        result="OK",
    )
    await session.refresh(job)
    return job


@router.patch("/{job_id}", response_model=JobOut)
async def update_job(
    job_id: str,
    body: JobUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Job:
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")

    data = body.model_dump(exclude_unset=True)
    if "steps" in data:
        steps_raw = [s.model_dump() if hasattr(s, "model_dump") else s for s in data["steps"]]
        try:
            validate_steps(steps_raw)
            for s in steps_raw:
                check_allowlist(s["cmd"])
        except (DagValidationError, AllowlistError) as e:
            await append_event(
                session,
                who=_actor(request),
                kind="policy.violation" if isinstance(e, AllowlistError) else "job.edit",
                target=job_id,
                src="web",
                ip=_ip(request),
                result="DENY",
            )
            raise HTTPException(400, str(e))
        data["steps"] = steps_raw

    for k, v in data.items():
        setattr(job, k, v)
    await append_event(
        session,
        who=_actor(request),
        kind="job.edit",
        target=job_id,
        src="web",
        ip=_ip(request),
        result="OK",
    )
    await session.refresh(job)
    return job


@router.delete("/{job_id}", status_code=204)
async def delete_job(
    job_id: str, request: Request, session: AsyncSession = Depends(get_session)
) -> None:
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    await session.delete(job)
    await append_event(
        session,
        who=_actor(request),
        kind="job.delete",
        target=job_id,
        src="web",
        ip=_ip(request),
        result="OK",
    )


def _actor(request: Request) -> str:
    return request.headers.get("X-Actor", "admin")


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""
