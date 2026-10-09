# app/core/distributed/models.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Pydantic contracts for distributed workers, node jobs,
                  and job results (control ↔ worker protocol).
Owns:             WorkerResources, WorkerInfo, NodeJob, JobResult,
                  JobStatus, QueueReason, WorkerStatus.
Public Surface:   All model classes and type aliases above.
Must NOT:         Import from app.domain, app.api, orchestrator, or nodes.
Dependencies:     pydantic, stdlib (datetime, typing), app.core.ir.models
                  (IRPlacement only).
Reason To Change: Job protocol fields evolve, or worker capability schema grows
                  (e.g. finished_at / result_consumed_at history markers,
                  JobResult.output_sha256 integrity map,
                  Mode B plugin ACL / trust / remote node_types).
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
# Why a pending job has not been claimed yet (F18 queue visibility).
QueueReason = Literal["no_capacity", "org_quota", "waiting_worker"]
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
    """Advertised executable node_type ids this worker can run."""
    node_types: list[str] = Field(default_factory=list)
    """Optional remote-only type names (no code) for control catalog awareness."""
    allowed_plugins: list[str] | None = None
    """Control-side allowlist; when set, claim intersects advertised ∩ allowed."""
    plugin_hashes: dict[str, str] | None = None
    """Control-side node_type → sha256 pins (admin PATCH / register)."""
    content_hashes: dict[str, str] | None = None
    """Worker-advertised node_type → sha256 (from register/heartbeat body)."""
    trusted: bool = True
    """Lab default True. When auth_required and GRAPHYN_WORKER_TRUST_REQUIRED=1,
    untrusted workers cannot claim."""
    max_claimed: int | None = None
    """Optional per-worker concurrent claimed/running cap (admin PATCH).
    F18 alias: max_slots — used_slots = count of claimed/running jobs."""
    usage_claims: int = 0
    """Durable claim counter (incremented on successful claim)."""
    usage_completes: int = 0
    """Durable complete counter."""
    usage_bytes_in: int = 0
    """Bytes downloaded from control (blob GET) attributed to this worker."""
    usage_bytes_out: int = 0
    """Bytes uploaded to control (blob PUT) attributed to this worker."""
    graphyn_version: str | None = None
    heartbeat_at: datetime = Field(default_factory=_utcnow)
    status: WorkerStatus = "idle"
    active_jobs: int = 0
    org_id: str | None = None
    """Owning organization for tenancy isolation (Wave 2)."""

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
    blob_grants: list[str] = Field(default_factory=list)
    """Companion blob keys referenced inside ``input_refs`` payloads; the claim
    holder may GET these (plus the input_ref keys) without a signed URL."""
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
    claim_pools: list[str] = Field(default_factory=list)
    """Pools this claim counts against for ``GRAPHYN_POOL_MAX_CLAIMED`` (set at claim)."""
    lease_generation: int = 0
    """Incremented on lease reclaim; complete must present the same value."""
    attempts: int = 0
    """Times this job was reclaimed after lease expiry (P1-12)."""
    max_attempts: int = 5
    """Stop requeueing after this many reclaim cycles (P1-12). Set from the
    node's IR ``retry.max_attempts`` (executions) as ``max_attempts - 1``."""
    idempotent: bool = True
    """False → a lost lease fails the job instead of requeueing it (F19)."""
    org_id: str | None = None
    """Owning organization for fair-share + org concurrent quotas (F18)."""
    queue_reason: QueueReason | None = None
    """Set while status=pending: no_capacity | org_quota | waiting_worker."""
    finished_at: datetime | None = None
    """Set when the job reaches a terminal status (history trim ordering)."""
    result_consumed_at: datetime | None = None
    """Set when the control plane has read the result (safe to trim)."""


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
    lease_generation: int | None = None
    """Must match NodeJob.lease_generation when completing a claimed job."""
    output_sha256: dict[str, str] = Field(default_factory=dict)
    """Optional ``{port: sha256 hex}`` of each uploaded output blob; the
    control plane verifies downloaded bytes against it."""
