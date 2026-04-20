from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Artifact
from app.schemas import ArtifactOut
from app.services.artifacts import ArtifactValidationError, save_upload
from app.services.audit import append_event

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


@router.get("", response_model=list[ArtifactOut])
async def list_artifacts(session: AsyncSession = Depends(get_session)) -> list[Artifact]:
    rows = (
        await session.execute(select(Artifact).order_by(Artifact.uploaded_at.desc()))
    ).scalars().all()
    return list(rows)


@router.get("/{artifact_id}", response_model=ArtifactOut)
async def get_artifact(
    artifact_id: int, session: AsyncSession = Depends(get_session)
) -> Artifact:
    row = await session.get(Artifact, artifact_id)
    if not row:
        raise HTTPException(404, "artifact not found")
    return row


@router.post("", response_model=ArtifactOut, status_code=201)
async def upload_artifact(
    request: Request,
    name: str = Form(...),
    version: str = Form(...),
    ext: str = Form("tar.gz"),
    uploader: str = Form("admin"),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> Artifact:
    # reject duplicate (name, version)
    dup = (
        await session.execute(
            select(Artifact).where(Artifact.name == name, Artifact.version == version)
        )
    ).scalar_one_or_none()
    if dup:
        raise HTTPException(409, f"artifact {name}@{version} already exists")

    try:
        artifact = await save_upload(
            session=session,
            name=name,
            version=version,
            ext=ext,
            uploader=uploader,
            file=file,
        )
    except ArtifactValidationError as e:
        raise HTTPException(400, str(e))
    await append_event(
        session,
        who=uploader,
        kind="artifact.upload",
        target=f"{name}@{version}",
        src="web",
        ip=request.client.host if request.client else "",
        result="OK",
    )
    await session.refresh(artifact)
    return artifact
