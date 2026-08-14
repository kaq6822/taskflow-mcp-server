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

# Aliases become environment-variable name fragments (`ARTIFACT_<ALIAS>_PATH`),
# so they are restricted far more tightly than artifact names: the artifact
# name alphabet allows `.` and `-`, which would have to be folded to `_` and
# would make `my-app` and `my.app` collide on the same env key. Requiring an
# explicit alias sidesteps that entirely.
_ALIAS = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

_REF_SCHEME = "uploads://"


class ArtifactValidationError(ValueError):
    pass


class ArtifactResolutionError(Exception):
    """A `uploads://` reference could not be turned into a usable artifact.

    `code` mirrors the error vocabulary in docs/03-system-spec.md §123 so the
    REST and MCP layers can map to consistent statuses without re-parsing the
    message.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


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


def validate_alias(alias: str) -> None:
    if not _ALIAS.match(alias or ""):
        raise ArtifactValidationError(
            f"invalid alias: {alias!r} (must start with a letter; letters, digits, underscore only)"
        )


def validate_consumes(entries: list[dict]) -> None:
    """Validate a Job's `consumes_artifacts` list.

    Each entry is `{"alias": ..., "name": ...}`. Aliases must be unique because
    they map onto distinct environment-variable prefixes.
    """
    seen: set[str] = set()
    for entry in entries:
        alias = entry.get("alias", "")
        name = entry.get("name", "")
        validate_alias(alias)
        _validate_component(name, "artifact name")
        key = alias.upper()
        if key in seen:
            raise ArtifactValidationError(f"duplicate alias: {alias!r}")
        seen.add(key)


def parse_reference(ref: str) -> tuple[str, str]:
    """Split `uploads://<name>@<version|latest>` into (name, version)."""
    if not ref.startswith(_REF_SCHEME):
        raise ArtifactResolutionError(
            "INVALID_ARTIFACT", f"reference must start with {_REF_SCHEME!r}: {ref!r}"
        )
    body = ref[len(_REF_SCHEME) :]
    if "@" not in body:
        raise ArtifactResolutionError(
            "INVALID_ARTIFACT", f"reference must be <name>@<version|latest>: {ref!r}"
        )
    name, version = body.split("@", 1)
    if not name or not version:
        raise ArtifactResolutionError("INVALID_ARTIFACT", f"incomplete reference: {ref!r}")
    return name, version


def make_reference(name: str, version: str) -> str:
    return f"{_REF_SCHEME}{name}@{version}"


def latest_stmt(name: str):
    """Query for `name`'s `latest` row, with a deterministic tie-break.

    `latest` is a flag maintained by `_finalise`, not a unique constraint (only
    `(name, version)` is unique), so concurrent uploads can leave two rows
    flagged. Every reader must break the tie identically — otherwise a status
    check and the version a run actually pins can disagree.
    """
    return (
        select(Artifact)
        .where(Artifact.name == name, Artifact.latest)
        .order_by(Artifact.uploaded_at.desc(), Artifact.id.desc())
    )


async def resolve_reference(session: AsyncSession, ref: str) -> Artifact:
    """Resolve a `uploads://` reference to a READY artifact row.

    `@latest` follows the mutable pointer maintained by `_finalise`. Callers
    are expected to pin the concrete version afterwards (see
    `make_reference`) so the run record stays reproducible.
    """
    name, version = parse_reference(ref)
    if version == "latest":
        q = latest_stmt(name)
    else:
        q = select(Artifact).where(Artifact.name == name, Artifact.version == version)
    row = (await session.execute(q.limit(1))).scalar_one_or_none()
    if row is None:
        raise ArtifactResolutionError("NOT_FOUND", f"artifact {name}@{version} not found")
    if row.status != "READY":
        raise ArtifactResolutionError(
            "NOT_READY", f"artifact {name}@{row.version} is {row.status}"
        )
    return row


def artifact_env(alias: str, art: Artifact) -> dict[str, str]:
    """Environment variables handed to every step of a run consuming `art`."""
    p = f"ARTIFACT_{alias.upper()}"
    return {
        f"{p}_PATH": art.blob_path,
        f"{p}_NAME": art.name,
        f"{p}_VERSION": art.version,
        f"{p}_SHA256": art.sha256,
        f"{p}_REF": make_reference(art.name, art.version),
    }


def ensure_storage_dirs() -> None:
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    Path(settings.step_cwd).mkdir(parents=True, exist_ok=True)
