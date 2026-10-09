# app/api/queue_schemas.py
"""
Bounded Context:  REST API Layer
Responsibility:   OpenAPI response models for the F18 queue / slot / quota
                  endpoints (F19: they were published with empty ``{}`` schemas).
Owns:             WorkerRow, JobQueueView, ClaimResponse, JobStatusView,
                  JobCompleteResponse, OrgQuotaView, OrgUsageView.
Must NOT:         Change what the handlers return — these document the shapes;
                  ``unit_test/f19/test_f19_openapi_cancel.py`` checks live
                  responses against them so the docs cannot drift.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.distributed.models import JobResult, NodeJob, WorkerInfo


class SlotSnapshot(BaseModel):
    """Per-worker slot booking (``max_slots`` null = unlimited)."""

    max_slots: Optional[int] = Field(None, description="Concurrent job cap (null = unlimited)")
    used_slots: int = Field(0, description="Claimed + running jobs")
    free_slots: Optional[int] = Field(None, description="max_slots - used_slots (null = unlimited)")


class WorkerUsage(BaseModel):
    claims: int = 0
    completes: int = 0
    bytes_in: int = 0
    bytes_out: int = 0


class WorkerRow(WorkerInfo):
    """``GET /workers`` row: registration + live slot / usage view."""

    model_config = ConfigDict(extra="allow")

    usage: Optional[WorkerUsage] = None
    max_slots: Optional[int] = None
    used_slots: int = 0
    free_slots: Optional[int] = None
    pool_max_claimed: Optional[dict[str, int]] = Field(
        None, description="Pool caps that apply to this worker (GRAPHYN_POOL_MAX_CLAIMED)"
    )


class QueueRow(BaseModel):
    job_id: str
    run_id: str
    node_id: str
    node_type: str
    org_id: Optional[str] = None
    status: Literal["queued"] = "queued"
    queue_position: int = Field(..., description="1-based FIFO position")
    queue_reason: Optional[str] = Field(
        None, description="no_capacity | org_quota | waiting_worker"
    )
    pool: Optional[str] = None
    require_gpu: Optional[bool] = None
    created_at: Optional[str] = None
    placement: Optional[dict[str, Any]] = None


class WorkerSlotRow(SlotSnapshot):
    worker_id: str
    status: Optional[str] = None


class JobQueueView(BaseModel):
    queue: list[QueueRow]
    pending_count: int
    worker_slots: list[WorkerSlotRow]


class ClaimedJob(NodeJob):
    """Exactly a ``NodeJob`` — workers validate it strictly."""


class ClaimResponse(BaseModel):
    job: Optional[ClaimedJob] = Field(None, description="null when nothing is claimable")
    worker_slots: Optional[SlotSnapshot] = Field(
        None, description="Claiming worker's slot booking after this claim (absent when nothing was claimed)"
    )


class JobStatusView(BaseModel):
    job: NodeJob
    result: Optional[JobResult] = None
    run_paused: bool = Field(False, description="True while the owning run is paused (worker should hold)")


class JobCompleteResponse(BaseModel):
    job: NodeJob
    result: JobResult


class OrgQuotaView(BaseModel):
    org_id: str
    max_seats: Optional[int] = None
    max_projects: Optional[int] = None
    max_runs_per_day: Optional[int] = None
    max_credentials: Optional[int] = None
    max_concurrent_jobs: Optional[int] = None
    max_queued_jobs: Optional[int] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


class OrgUsage(BaseModel):
    org_id: str
    seats: int
    projects: int
    runs_today: int
    credentials: int
    meter_events: int
    concurrent_jobs: int = 0
    queued_jobs: int = 0


class OrgUsageView(BaseModel):
    usage: OrgUsage
    quota: OrgQuotaView


def doc(model: Any, description: str = "OK") -> dict[int, dict[str, Any]]:
    """``responses=`` helper: document *model* for 200 without filtering output."""
    return {200: {"model": model, "description": description}}
