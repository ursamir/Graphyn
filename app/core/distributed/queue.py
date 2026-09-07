# app/core/distributed/queue.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Thread-safe in-memory node-job queue with claim by
                  worker eligibility and completion reporting.
Owns:             JobQueue (enqueue, claim, complete, get, cancel, events).
Public Surface:   JobQueue, get_job_queue(), _reset_job_queue() (tests).
Must NOT:         Import from app.domain, app.api, or orchestrator.
Dependencies:     stdlib (threading, datetime, uuid), app.core.distributed.models,
                  app.core.distributed.placement (eligibility).
Reason To Change: Lease/TTL reclaim, Redis-backed queue, or cancel fan-out.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.distributed.models import JobResult, JobStatus, NodeJob, WorkerInfo
from app.core.distributed.placement import worker_eligible_for_job


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobQueue:
    """Process-local FIFO job queue with eligibility-aware claim (P0)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, NodeJob] = {}
        self._order: list[str] = []  # pending claim order
        self._results: dict[str, JobResult] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._waiters: dict[str, threading.Event] = {}

    def enqueue(self, job: NodeJob) -> NodeJob:
        """Add a pending job. Assigns ``job_id`` if empty."""
        with self._lock:
            job_id = job.job_id or str(uuid.uuid4())
            stored = job.model_copy(
                update={
                    "job_id": job_id,
                    "status": "pending",
                    "created_at": job.created_at or _utcnow(),
                }
            )
            self._jobs[job_id] = stored
            self._order.append(job_id)
            self._events.setdefault(job_id, [])
            self._waiters.setdefault(job_id, threading.Event())
            return stored

    def get(self, job_id: str) -> NodeJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_result(self, job_id: str) -> JobResult | None:
        with self._lock:
            return self._results.get(job_id)

    def claim(self, worker: WorkerInfo) -> NodeJob | None:
        """Claim the oldest pending job this worker is eligible for.

        Returns the claimed job, or ``None`` if none match.
        """
        with self._lock:
            for job_id in list(self._order):
                job = self._jobs.get(job_id)
                if job is None or job.status != "pending":
                    continue
                if not worker_eligible_for_job(worker, job):
                    continue
                claimed = job.model_copy(
                    update={
                        "status": "claimed",
                        "claimed_by": worker.worker_id,
                        "claimed_at": _utcnow(),
                    }
                )
                self._jobs[job_id] = claimed
                self._order.remove(job_id)
                return claimed
            return None

    def complete(self, result: JobResult) -> NodeJob:
        """Mark a job finished from a worker result.

        Raises:
            KeyError: unknown job_id.
            ValueError: job already terminal or result status invalid.
        """
        with self._lock:
            job = self._jobs.get(result.job_id)
            if job is None:
                raise KeyError(result.job_id)
            if job.status in ("succeeded", "failed", "cancelled"):
                raise ValueError(
                    f"Job {result.job_id} already terminal ({job.status})"
                )
            status: JobStatus = result.status  # type: ignore[assignment]
            updated = job.model_copy(update={"status": status})
            self._jobs[result.job_id] = updated
            self._results[result.job_id] = result
            if result.events:
                self._events.setdefault(result.job_id, []).extend(result.events)
            evt = self._waiters.get(result.job_id)
            if evt is not None:
                evt.set()
            return updated

    def cancel(self, job_id: str) -> NodeJob:
        """Cancel a pending/claimed job (control-plane signal)."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status in ("succeeded", "failed", "cancelled"):
                return job
            updated = job.model_copy(update={"status": "cancelled"})
            self._jobs[job_id] = updated
            if job_id in self._order:
                self._order.remove(job_id)
            self._results[job_id] = JobResult(
                job_id=job_id,
                status="cancelled",
                error="cancelled by control plane",
            )
            evt = self._waiters.get(job_id)
            if evt is not None:
                evt.set()
            return updated

    def append_events(self, job_id: str, events: list[dict[str, Any]]) -> int:
        """Append log/event payloads for a job. Returns new event count."""
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            bucket = self._events.setdefault(job_id, [])
            bucket.extend(events)
            return len(bucket)

    def wait_for_result(
        self,
        job_id: str,
        *,
        timeout_s: float | None = None,
    ) -> JobResult | None:
        """Block until the job has a result (or timeout)."""
        with self._lock:
            if job_id in self._results:
                return self._results[job_id]
            evt = self._waiters.setdefault(job_id, threading.Event())
        ok = evt.wait(timeout=timeout_s)
        if not ok:
            return None
        with self._lock:
            return self._results.get(job_id)

    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for jid in self._order if self._jobs.get(jid) is not None)

    def clear(self) -> None:
        with self._lock:
            for evt in self._waiters.values():
                evt.set()
            self._jobs.clear()
            self._order.clear()
            self._results.clear()
            self._events.clear()
            self._waiters.clear()


_QUEUE: JobQueue | None = None
_QUEUE_LOCK = threading.Lock()


def get_job_queue() -> JobQueue:
    global _QUEUE
    with _QUEUE_LOCK:
        if _QUEUE is None:
            _QUEUE = JobQueue()
        return _QUEUE


def _reset_job_queue() -> None:
    global _QUEUE
    with _QUEUE_LOCK:
        if _QUEUE is not None:
            _QUEUE.clear()
        _QUEUE = JobQueue()
