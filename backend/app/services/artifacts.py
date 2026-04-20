from __future__ import annotations

import hashlib
import re
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Artifact


# P1-2: artifact identifiers become filesystem path components. Restrict to a
# safe alphabet and reject any `..` traversal so a malicious caller cannot
# escape `storage/artifacts/` by supplying `name="../../etc/passwd"`.
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


class ArtifactValidationError(ValueError):
    pass


def _validate_component(value: str, field: str) -> None:
    if not value or ".." in value or "/" in value or "\\" in value:
        raise ArtifactValidationError(f"invalid {field}: {value!r}")
    if not _SAFE_COMPONENT.match(value):
        raise ArtifactValidationError(
            f"invalid {field}: {value!r} (allowed: letters, digits, dot, underscore, hyphen)"
        )


def _validate_upload_fields(name: str, version: str, ext: str) -> None:
    _validate_component(name, "name")
    _validate_component(version, "version")
    _validate_component(ext, "ext")


async def save_upload(
    *,
    session: AsyncSession,
    name: str,
    version: str,
    ext: str,
    uploader: str,
    file: UploadFile,
) -> Artifact:
    _validate_upload_fields(name, version, ext)
    hasher = hashlib.sha256()
    tmp_dir = settings.artifacts_dir / "_incoming"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{name}-{version}.{ext}.partial"
    size = 0
    with tmp_path.open("wb") as dst:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
            size += len(chunk)
            dst.write(chunk)
    return await _finalise(session, name, version, ext, uploader, hasher.hexdigest(), size, tmp_path)


async def save_upload_bytes(
    *,
    session: AsyncSession,
    name: str,
    version: str,
    ext: str,
    uploader: str,
    data: bytes,
) -> Artifact:
    _validate_upload_fields(name, version, ext)
    hasher = hashlib.sha256()
    hasher.update(data)
    tmp_dir = settings.artifacts_dir / "_incoming"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{name}-{version}.{ext}.partial"
    with tmp_path.open("wb") as dst:
        dst.write(data)
    return await _finalise(session, name, version, ext, uploader, hasher.hexdigest(), len(data), tmp_path)


async def _finalise(
    session: AsyncSession,
    name: str,
    version: str,
    ext: str,
    uploader: str,
    digest: str,
    size: int,
    tmp_path: Path,
) -> Artifact:
    prefix = digest[:2]
    final_dir = settings.artifacts_dir / prefix
    final_dir.mkdir(parents=True, exist_ok=True)
    final_path = final_dir / f"{name}-{version}.{ext}"
    tmp_path.replace(final_path)
    final_path.chmod(0o444)  # 읽기 전용

    prev = (
        await session.execute(select(Artifact).where(Artifact.name == name, Artifact.latest))
    ).scalars().all()
    for p in prev:
        p.latest = False

    art = Artifact(
        name=name,
        version=version,
        ext=ext,
        size_bytes=size,
        sha256=digest,
        uploader=uploader,
        latest=True,
        status="READY",  # MVP: ClamAV stub 즉시 통과
        blob_path=str(final_path),
        consumers=[],
    )
    session.add(art)
    await session.flush()
    return art


def resolve_reference(ref: str, session_artifacts: list[Artifact]) -> Artifact | None:
    if not ref.startswith("uploads://"):
        return None
    body = ref[len("uploads://") :]
    if "@" not in body:
        return None
    name, version = body.split("@", 1)
    if version == "latest":
        candidates = [a for a in session_artifacts if a.name == name and a.latest]
        return candidates[0] if candidates else None
    for a in session_artifacts:
        if a.name == name and a.version == version:
            return a
    return None


def ensure_storage_dirs() -> None:
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    Path(settings.step_cwd).mkdir(parents=True, exist_ok=True)
