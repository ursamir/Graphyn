# app/core/distributed/models.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Pydantic contracts for distributed workers, node jobs,
                  and job results (control ↔ worker protocol).
Owns:             WorkerResources, WorkerInfo, NodeJob, JobResult,
                  JobStatus, WorkerStatus.
Public Surface:   All model classes and type aliases above.
Must NOT:         Import from app.domain, app.api, orchestrator, or nodes.
Dependencies:     pydantic, stdlib (datetime, typing), app.core.ir.models
                  (IRPlacement only).
Reason To Change: Job protocol fields evolve, or worker capability schema grows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.ir.models import IRPlacement

JobStatus = Literal[
    "pending",
    "claimed",
    "running",
    "succeeded",
    "failed",
    "cancelled",
]
WorkerStatus = Literal["idle", "busy", "draining", "offline"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkerResources(BaseModel):
    """Resource snapshot advertised by a worker heartbeat."""

    model_config = ConfigDict(extra="allow")

    gpu: bool = False
    gpu_name: str | None = None
    vram_mib_total: int | None = None
    vram_mib_free: int | None = None
    cpus: int | None = None


class WorkerInfo(BaseModel):
    """Registered worker identity + capability advertisement."""

    model_config = ConfigDict(extra="forbid")

    worker_id: str
    labels: list[str] = Field(default_factory=list)
    pools: list[str] = Field(default_factory=list)
    resources: WorkerResources = Field(default_factory=WorkerResources)
    plugins: list[str] = Field(default_factory=list)
    graphyn_version: str | None = None
    heartbeat_at: datetime = Field(default_factory=_utcnow)
    status: WorkerStatus = "idle"
    active_jobs: int = 0

    @field_validator("worker_id")
    @classmethod
    def _id_non_empty(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("worker_id must be non-empty")
        return str(v).strip()


class NodeJob(BaseModel):
    """Unit of remote work — one node execution."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    run_id: str
    node_id: str
    node_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None
    input_refs: dict[str, str] = Field(default_factory=dict)
    placement: IRPlacement | None = None
    timeout_s: float | None = 3600.0
    created_at: datetime = Field(default_factory=_utcnow)
    status: JobStatus = "pending"
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    lease_expires_at: datetime | None = None
    require_gpu: bool = False
    min_vram_mib: int | None = None
    tags: list[str] = Field(default_factory=list)
    pool: str | None = None


class JobResult(BaseModel):
    """Result reported by a worker after completing (or failing) a job."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: Literal["succeeded", "failed", "cancelled"]
    output_refs: dict[str, str] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    worker_id: str | None = None
    duration_s: float | None = None
