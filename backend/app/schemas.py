from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StepSpec(BaseModel):
    id: str
    cmd: list[str]
    timeout: int = 60
    on_failure: Literal["STOP", "CONTINUE", "RETRY", "ROLLBACK"] = "STOP"
    deps: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None


class JobCreate(BaseModel):
    id: str
    name: str
    description: str = ""
    owner: str
    tags: list[str] = Field(default_factory=list)
    schedule: str = "manual"
    timeout: int = 600
    concurrency: int = 1
    on_failure: Literal["STOP", "CONTINUE", "RETRY", "ROLLBACK"] = "STOP"
    consumes_artifact: str | None = None
    steps: list[StepSpec]


class JobUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    owner: str | None = None
    tags: list[str] | None = None
    schedule: str | None = None
    timeout: int | None = None
    concurrency: int | None = None
    on_failure: Literal["STOP", "CONTINUE", "RETRY", "ROLLBACK"] | None = None
    consumes_artifact: str | None = None
    steps: list[StepSpec] | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    owner: str
    tags: list[str]
    schedule: str
    timeout: int
    concurrency: int
    on_failure: str
    consumes_artifact: str | None
    steps: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class RunStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step_id: str
    state: str
    elapsed_sec: float
    started_at: datetime | None
    finished_at: datetime | None
    exit_code: int | None


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: str
    status: str
    trigger: str
    actor: str
    started_at: datetime
    finished_at: datetime | None
    duration_sec: float
    order: list[str]
    artifact_ref: str | None
    failed_step: str | None
    err_message: str | None
    steps: list[RunStepOut] = Field(default_factory=list)


class RunCreate(BaseModel):
    trigger: Literal["manual", "schedule", "mcp"] = "manual"
    actor: str = "web"
    artifact_ref: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class AgentRunResult(BaseModel):
    """MCP Agent 응답 스키마 — docs/02 §10.4"""

    run_id: int
    job_id: str
    status: Literal["SUCCESS", "FAILED", "TIMEOUT", "RUNNING"]
    started_at: datetime
    finished_at: datetime | None
    duration_sec: float
    artifact_ref: str | None
    steps: list[dict[str, Any]]
    failed_step: str | None
    err_message: str | None
    logs_uri: str
    audit_event_ids: list[int] = Field(default_factory=list)
    degraded_to: str | None = None


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    version: str
    ext: str
    size_bytes: int
    sha256: str
    uploader: str
    uploaded_at: datetime
    latest: bool
    status: str
    consumers: list[str]


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    who: str
    kind: str
    target: str
    src: str
    ip: str
    result: str


class KeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    label: str
    key_prefix: str
    key_suffix: str
    scopes: list[str]
    created: datetime
    expires: datetime | None
    last_used: datetime | None
    rate_limit: str
    state: str


class KeyCreate(BaseModel):
    label: str
    scopes: list[str]
    expires_days: int = 90
    rate_limit: Literal["10/min", "30/min", "60/min"] = "30/min"


class KeyIssued(KeyOut):
    plaintext: str
