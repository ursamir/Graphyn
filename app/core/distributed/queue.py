# app/core/distributed/queue.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Thread-safe node-job queue with claim by worker eligibility,
                  lease TTL + reclaim, cancel signaling, and durable store.
Owns:             JobQueue (enqueue, claim, complete, get, cancel, events,
                  reclaim_expired_leases, renew_lease).
Public Surface:   JobQueue, get_job_queue(), _reset_job_queue() (tests),
                  DEFAULT_LEASE_TTL_S.
Must NOT:         Import from app.domain, app.api, or orchestrator.
Dependencies:     stdlib (threading, datetime, uuid), app.core.distributed.models,
                  app.core.distributed.placement (eligibility),
                  app.core.distributed.store (lazy).
Reason To Change: Lease/TTL reclaim, Redis-backed queue, or cancel fan-out.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from app.core.distributed.models import JobResult, JobStatus, NodeJob, WorkerInfo
from app.core.distributed.placement import worker_eligible_for_job

if TYPE_CHECKING:
    from app.core.distributed.store import DistributedStateStore

log = logging.getLogger(__name__)

# Default job lease TTL (~4 missed 15s heartbeats). Override: GRAPHYN_JOB_LEASE_TTL_S.
DEFAULT_LEASE_TTL_S = float(os.environ.get("GRAPHYN_JOB_LEASE_TTL_S", "60") or "60")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class JobQueue:
    """FIFO job queue with eligibility-aware claim, lease reclaim, persist (P2)."""

    def __init__(
        self,
        *,
        lease_ttl_s: float | None = None,
        store: "DistributedStateStore | None" = None,
        load_persisted: bool = True,
    ) -> None:
        self._lease_ttl_s = float(
            lease_ttl_s if lease_ttl_s is not None else DEFAULT_LEASE_TTL_S
        )
        self._lock = threading.RLock()
        self._jobs: dict[str, NodeJob] = {}
        self._order: list[str] = []  # pending claim order
        self._results: dict[str, JobResult] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._waiters: dict[str, threading.Event] = {}
        self._store = store
        if load_persisted and store is not None:
            self._hydrate_from_store()

    def _hydrate_from_store(self) -> None:
        if self._store is None:
            return
        try:
            snap = self._store.load_queue()
        except Exception as exc:
            log.warning("JobQueue: failed to load queue: %s", exc)
            return
        jobs_raw = snap.get("jobs") or {}
        for jid, payload in jobs_raw.items():
            try:
                job = NodeJob.model_validate(payload)
                self._jobs[job.job_id] = job
            except Exception as exc:
                log.warning("JobQueue: skip corrupt job %r: %s", jid, exc)
        order = snap.get("order") or []
        self._order = [jid for jid in order if jid in self._jobs]
        # Any pending job missing from order gets appended (repair).
        for jid, job in self._jobs.items():
            if job.status == "pending" and jid not in self._order:
                self._order.append(jid)
        for jid, payload in (snap.get("results") or {}).items():
            try:
                self._results[jid] = JobResult.model_validate(payload)
            except Exception as exc:
                log.warning("JobQueue: skip corrupt result %r: %s", jid, exc)
        for jid, events in (snap.get("events") or {}).items():
            if isinstance(events, list):
                self._events[jid] = list(events)
        for jid in self._jobs:
            self._waiters.setdefault(jid, threading.Event())
            if jid in self._results:
                self._waiters[jid].set()
        log.debug(
            "JobQueue: hydrated %s job(s) from %s",
            len(self._jobs),
            self._store.backend_id,
        )

    def _persist_unlocked(self) -> None:
        if self._store is None:
            return
        try:
            snapshot = {
                "jobs": {jid: j.model_dump(mode="json") for jid, j in self._jobs.items()},
                "order": list(self._order),
                "results": {
                    jid: r.model_dump(mode="json") for jid, r in self._results.items()
                },
                "events": {jid: list(evs) for jid, evs in self._events.items()},
            }
            self._store.save_queue(snapshot)
        except Exception as exc:
            log.warning("JobQueue: persist failed: %s", exc)

    def enqueue(self, job: NodeJob) -> NodeJob:
        """Add a pending job. Assigns ``job_id`` if empty."""
        with self._lock:
            self._reclaim_expired_leases_unlocked(now=_utcnow())
            job_id = job.job_id or str(uuid.uuid4())
            stored = job.model_copy(
                update={
                    "job_id": job_id,
                    "status": "pending",
                    "created_at": job.created_at or _utcnow(),
                    "claimed_by": None,
                    "claimed_at": None,
                    "lease_expires_at": None,
                }
            )
            self._jobs[job_id] = stored
            self._order.append(job_id)
            self._events.setdefault(job_id, [])
            self._waiters.setdefault(job_id, threading.Event())
            self._persist_unlocked()
            return stored

    def get(self, job_id: str) -> NodeJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_result(self, job_id: str) -> JobResult | None:
        with self._lock:
            return self._results.get(job_id)

    def is_cancelled(self, job_id: str) -> bool:
        """True if the job is marked cancelled (control-plane signal)."""
        with self._lock:
            job = self._jobs.get(job_id)
            return job is not None and job.status == "cancelled"


    def _sync_from_store_unlocked(self, *, job_id: str | None = None) -> None:
        """Merge durable store snapshot into in-memory state (cross-process).

        Pulls results (and optionally a single job) written by another process
        sharing the same DiskStateStore / RedisStateStore. Local Event wakeups
        still work for in-process tests; this path covers CLI↔API splits.
        """
        if self._store is None:
            return
        try:
            snap = self._store.load_queue()
        except Exception as exc:
            log.warning("JobQueue: store sync failed: %s", exc)
            return

        results_raw = snap.get("results") or {}
        jobs_raw = snap.get("jobs") or {}
        order_raw = snap.get("order") or []
        events_raw = snap.get("events") or {}

        # Merge results — store wins for unknown / terminal updates.
        for jid, payload in results_raw.items():
            if job_id is not None and jid != job_id:
                continue
            if jid in self._results:
                continue
            try:
                self._results[jid] = JobResult.model_validate(payload)
                self._waiters.setdefault(jid, threading.Event()).set()
            except Exception as exc:
                log.warning("JobQueue: skip corrupt store result %r: %s", jid, exc)

        # Merge jobs we don't know about (pending enqueued by another process).
        for jid, payload in jobs_raw.items():
            if job_id is not None and jid != job_id:
                # Still allow updating the watched job's status from store.
                pass
            try:
                remote = NodeJob.model_validate(payload)
            except Exception as exc:
                log.warning("JobQueue: skip corrupt store job %r: %s", jid, exc)
                continue
            local = self._jobs.get(jid)
            if local is None:
                self._jobs[jid] = remote
                self._waiters.setdefault(jid, threading.Event())
                if remote.status == "pending" and jid not in self._order:
                    self._order.append(jid)
            else:
                # Prefer store when it is further along (terminal / claimed by other).
                terminal = ("succeeded", "failed", "cancelled")
                if local.status not in terminal and remote.status in terminal:
                    self._jobs[jid] = remote
                    if jid in self._order:
                        self._order.remove(jid)
                elif local.status == "pending" and remote.status in ("claimed", "running"):
                    self._jobs[jid] = remote
                    if jid in self._order:
                        self._order.remove(jid)
                elif (
                    local.status in ("claimed", "running")
                    and remote.status == "pending"
                    and remote.lease_generation > local.lease_generation
                ):
                    # Reclaimed elsewhere
                    self._jobs[jid] = remote
                    if jid not in self._order:
                        self._order.append(jid)

        # Repair order from store for pending jobs we now know.
        for jid in order_raw:
            job = self._jobs.get(jid)
            if job is not None and job.status == "pending" and jid not in self._order:
                self._order.append(jid)

        for jid, events in events_raw.items():
            if job_id is not None and jid != job_id:
                continue
            if isinstance(events, list) and jid not in self._events:
                self._events[jid] = list(events)

    def claim(self, worker: WorkerInfo) -> NodeJob | None:
        """Claim the oldest pending job this worker is eligible for.

        Hard-refuses jobs whose ``node_type`` is missing from the worker's
        advertised ``plugins`` list (when non-empty). Reclaims expired leases
        before scanning.

        Returns the claimed job, or ``None`` if none match.
        """
        with self._lock:
            self._sync_from_store_unlocked()
            self._reclaim_expired_leases_unlocked(now=_utcnow())
            for job_id in list(self._order):
                job = self._jobs.get(job_id)
                if job is None or job.status != "pending":
                    continue
                # Hard refuse: advertised plugins must include node_type.
                if not _plugins_allow(worker, job.node_type):
                    continue
                if not worker_eligible_for_job(worker, job):
                    continue
                now = _utcnow()
                claimed = job.model_copy(
                    update={
                        "status": "claimed",
                        "claimed_by": worker.worker_id,
                        "claimed_at": now,
                        "lease_expires_at": now
                        + timedelta(seconds=self._lease_ttl_s),
                    }
                )
                self._jobs[job_id] = claimed
                self._order.remove(job_id)
                self._persist_unlocked()
                return claimed
            return None

    def renew_lease(self, job_id: str, *, worker_id: str | None = None) -> NodeJob | None:
        """Extend lease for a claimed/running job (heartbeat renews lease)."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status not in ("claimed", "running"):
                return job
            if worker_id is not None and job.claimed_by and job.claimed_by != worker_id:
                return job
            updated = job.model_copy(
                update={
                    "lease_expires_at": _utcnow()
                    + timedelta(seconds=self._lease_ttl_s),
                }
            )
            self._jobs[job_id] = updated
            self._persist_unlocked()
            return updated

    def renew_leases_for_worker(self, worker_id: str) -> int:
        """Renew leases for all non-terminal jobs claimed by ``worker_id``."""
        with self._lock:
            count = 0
            now = _utcnow()
            expiry = now + timedelta(seconds=self._lease_ttl_s)
            for jid, job in list(self._jobs.items()):
                if job.claimed_by != worker_id:
                    continue
                if job.status not in ("claimed", "running"):
                    continue
                self._jobs[jid] = job.model_copy(update={"lease_expires_at": expiry})
                count += 1
            if count:
                self._persist_unlocked()
            return count

    def reclaim_expired_leases(self, *, now: datetime | None = None) -> list[str]:
        """Requeue claimed/running jobs whose lease has expired. Returns job ids.

        Safe to call with or without the queue lock held (RLock).
        """
        with self._lock:
            return self._reclaim_expired_leases_unlocked(now=now)

    def _reclaim_expired_leases_unlocked(
        self, *, now: datetime | None = None
    ) -> list[str]:
        now = _as_aware(now) or _utcnow()
        reclaimed: list[str] = []
        for jid, job in list(self._jobs.items()):
            if job.status not in ("claimed", "running"):
                continue
            expires = _as_aware(job.lease_expires_at)
            if expires is None:
                claimed_at = _as_aware(job.claimed_at)
                if claimed_at is None:
                    continue
                expires = claimed_at + timedelta(seconds=self._lease_ttl_s)
            if expires > now:
                continue
            updated = job.model_copy(
                update={
                    "status": "pending",
                    "claimed_by": None,
                    "claimed_at": None,
                    "lease_expires_at": None,
                    "lease_generation": int(job.lease_generation or 0) + 1,
                }
            )
            self._jobs[jid] = updated
            if jid not in self._order:
                self._order.append(jid)
            reclaimed.append(jid)
            log.info(
                "JobQueue: reclaimed expired lease for job %s (was claimed by %s)",
                jid,
                job.claimed_by,
            )
        if reclaimed:
            self._persist_unlocked()
        return reclaimed

    def mark_running(self, job_id: str) -> NodeJob | None:
        """Transition claimed → running (optional worker signal)."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in ("claimed", "running"):
                return job
            updated = job.model_copy(
                update={
                    "status": "running",
                    "lease_expires_at": _utcnow()
                    + timedelta(seconds=self._lease_ttl_s),
                }
            )
            self._jobs[job_id] = updated
            self._persist_unlocked()
            return updated

    def complete(self, result: JobResult) -> NodeJob:
        """Mark a job finished from a worker result.

        Authz / fencing (P1):
        * Job must be ``claimed`` or ``running``.
        * ``result.worker_id`` must equal ``job.claimed_by``.
        * ``result.lease_generation`` must equal ``job.lease_generation``.

        Raises:
            KeyError: unknown job_id.
            ValueError: authz/fencing failure or job already terminal (→ HTTP 409).
        """
        with self._lock:
            self._sync_from_store_unlocked(job_id=result.job_id)
            job = self._jobs.get(result.job_id)
            if job is None:
                raise KeyError(result.job_id)
            if job.status in ("succeeded", "failed", "cancelled"):
                raise ValueError(
                    f"Job {result.job_id} already terminal ({job.status})"
                )
            if job.status not in ("claimed", "running"):
                raise ValueError(
                    f"Job {result.job_id} is not claimable for complete "
                    f"(status={job.status})"
                )
            if not result.worker_id or result.worker_id != job.claimed_by:
                raise ValueError(
                    f"Job {result.job_id} complete worker mismatch: "
                    f"result.worker_id={result.worker_id!r} "
                    f"claimed_by={job.claimed_by!r}"
                )
            expected_gen = int(job.lease_generation or 0)
            if result.lease_generation is None or int(result.lease_generation) != expected_gen:
                raise ValueError(
                    f"Job {result.job_id} lease_generation mismatch: "
                    f"result={result.lease_generation!r} expected={expected_gen}"
                )
            status: JobStatus = result.status  # type: ignore[assignment]
            updated = job.model_copy(
                update={"status": status, "lease_expires_at": None}
            )
            self._jobs[result.job_id] = updated
            self._results[result.job_id] = result
            if result.events:
                self._events.setdefault(result.job_id, []).extend(result.events)
            evt = self._waiters.get(result.job_id)
            if evt is not None:
                evt.set()
            self._persist_unlocked()
            return updated

    def cancel(self, job_id: str) -> NodeJob:
        """Cancel a pending/claimed/running job (control-plane signal).

        Claiming workers should poll ``get`` / ``is_cancelled`` and stop.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status in ("succeeded", "failed", "cancelled"):
                return job
            updated = job.model_copy(
                update={"status": "cancelled", "lease_expires_at": None}
            )
            self._jobs[job_id] = updated
            if job_id in self._order:
                self._order.remove(job_id)
            self._results[job_id] = JobResult(
                job_id=job_id,
                status="cancelled",
                error="cancelled by control plane",
                worker_id=job.claimed_by,
            )
            evt = self._waiters.get(job_id)
            if evt is not None:
                evt.set()
            self._persist_unlocked()
            return updated

    def append_events(self, job_id: str, events: list[dict[str, Any]]) -> int:
        """Append log/event payloads for a job. Returns new event count."""
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            bucket = self._events.setdefault(job_id, [])
            bucket.extend(events)
            # Events from the claiming worker also renew the lease.
            job = self._jobs.get(job_id)
            if job is not None and job.status in ("claimed", "running"):
                self._jobs[job_id] = job.model_copy(
                    update={
                        "lease_expires_at": _utcnow()
                        + timedelta(seconds=self._lease_ttl_s),
                    }
                )
            self._persist_unlocked()
            return len(bucket)

    def wait_for_result(
        self,
        job_id: str,
        *,
        timeout_s: float | None = None,
        poll_interval_s: float | None = None,
    ) -> JobResult | None:
        """Block until the job has a result (or timeout).

        In-process callers still wake via ``threading.Event``. Cross-process
        (CLI enqueue vs API complete on a shared durable store) is covered by
        periodically reloading results from the store when the Event is unset.
        """
        poll = poll_interval_s
        if poll is None:
            poll = float(os.environ.get("GRAPHYN_JOB_WAIT_POLL_S", "0.25") or "0.25")
        poll = max(0.05, float(poll))

        deadline = None if timeout_s is None else (time.monotonic() + float(timeout_s))

        while True:
            with self._lock:
                if job_id in self._results:
                    return self._results[job_id]
                self._sync_from_store_unlocked(job_id=job_id)
                if job_id in self._results:
                    return self._results[job_id]
                evt = self._waiters.setdefault(job_id, threading.Event())

            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    with self._lock:
                        self._sync_from_store_unlocked(job_id=job_id)
                        return self._results.get(job_id)
                slice_s = min(poll, remaining)
            else:
                slice_s = poll

            evt.wait(timeout=slice_s)

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
            self._persist_unlocked()


def _plugins_allow(worker: WorkerInfo, node_type: str) -> bool:
    """Hard refuse when worker advertises plugins and node_type is missing."""
    plugins = list(worker.plugins or [])
    if not plugins:
        # Empty advertisement → unknown capability set (dev/tests); allow.
        return True
    if not node_type:
        return False
    return node_type in plugins


_QUEUE: JobQueue | None = None
_QUEUE_LOCK = threading.Lock()


def get_job_queue() -> JobQueue:
    global _QUEUE
    with _QUEUE_LOCK:
        if _QUEUE is None:
            from app.core.distributed.store import get_distributed_store

            _QUEUE = JobQueue(store=get_distributed_store())
        return _QUEUE


def _reset_job_queue(
    *,
    store: "DistributedStateStore | None" = None,
    use_memory: bool = True,
    lease_ttl_s: float | None = None,
) -> JobQueue:
    global _QUEUE
    with _QUEUE_LOCK:
        if use_memory and store is None:
            from app.core.distributed.store import MemoryStateStore

            store = MemoryStateStore()
        elif store is None:
            from app.core.distributed.store import get_distributed_store

            store = get_distributed_store()
        if _QUEUE is not None:
            try:
                _QUEUE.clear()
            except Exception:
                pass
        _QUEUE = JobQueue(
            store=store, load_persisted=False, lease_ttl_s=lease_ttl_s
        )
        return _QUEUE
