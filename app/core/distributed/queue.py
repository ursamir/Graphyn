# app/core/distributed/queue.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Thread-safe node-job queue with claim by worker eligibility,
                  lease TTL + reclaim, cancel signaling, and durable store.
Owns:             JobQueue (enqueue, claim, complete, get, cancel, events,
                  reclaim_expired_leases, renew_lease, renew_leases_for_worker,
                  release_jobs_for_worker, ack_result, active_blob_refs),
                  terminal-history trim (finished_at / unread-result TTL).
Public Surface:   JobQueue, get_job_queue(), _reset_job_queue() (tests),
                  DEFAULT_LEASE_TTL_S.
Must NOT:         Import from app.domain, app.api, or orchestrator.
Dependencies:     stdlib (threading, datetime, uuid), app.core.distributed.models,
                  app.core.distributed.placement (eligibility),
                  app.core.distributed.store (lazy; mutate_queue for CAS claim).
Reason To Change: Lease/TTL reclaim, atomic cross-process claim, cancel fan-out,
                  heartbeat renew scope, history retention, or cache read-through.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from types import MappingProxyType


def _plain_jsonable(value: Any) -> Any:
    """Normalize mappingproxy/tuples for durable JSON job snapshots."""
    if isinstance(value, MappingProxyType):
        return {k: _plain_jsonable(v) for k, v in value.items()}
    if isinstance(value, dict):
        return {k: _plain_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_plain_jsonable(v) for v in value]
    return value


from app.core.distributed.models import JobResult, JobStatus, NodeJob, WorkerInfo
from app.core.distributed.placement import (
    widen_placement_after_reclaim,
    worker_eligible_for_job,
)

if TYPE_CHECKING:
    from app.core.distributed.store import DistributedStateStore

log = logging.getLogger(__name__)

# Default job lease TTL (~4 missed 15s heartbeats). Override: GRAPHYN_JOB_LEASE_TTL_S.
DEFAULT_LEASE_TTL_S = float(os.environ.get("GRAPHYN_JOB_LEASE_TTL_S", "60") or "60")
_TERMINAL_JOB_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
_MAX_PERSISTED_TERMINAL_JOBS = int(os.environ.get("GRAPHYN_JOB_HISTORY_MAX", "500") or "500")


def _job_result_ttl_s() -> float:
    try:
        return float(os.environ.get("GRAPHYN_JOB_RESULT_TTL_S", "3600") or "3600")
    except ValueError:
        return 3600.0


def _max_events_per_job() -> int:
    try:
        return max(1, int(os.environ.get("GRAPHYN_JOB_EVENTS_MAX", "500") or "500"))
    except ValueError:
        return 500


def _cap_events(bucket: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the newest ``GRAPHYN_JOB_EVENTS_MAX`` events for a job."""
    cap = _max_events_per_job()
    if len(bucket) > cap:
        return bucket[-cap:]
    return bucket


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_aware(value)
    try:
        return _as_aware(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _trim_terminal_jobs_snapshot(
    snap: dict[str, Any],
    *,
    keep: frozenset[str] | set[str] = frozenset(),
    now: datetime | None = None,
) -> dict[str, Any]:
    """Drop the oldest terminal jobs when history exceeds GRAPHYN_JOB_HISTORY_MAX.

    Ordering is by ``finished_at`` (fallback ``created_at``), never by job id.
    Never trimmed:

    * ids in ``keep`` (e.g. the job being completed right now);
    * jobs whose result has not been consumed by the control plane yet
      (``result_consumed_at`` unset) and finished less than
      ``GRAPHYN_JOB_RESULT_TTL_S`` (default 3600s) ago.

    History can therefore temporarily exceed the cap while unread results wait.
    """
    jobs = dict(snap.get("jobs") or {})
    if not jobs:
        return snap
    results_in = snap.get("results") or {}
    terminal = [
        (jid, payload)
        for jid, payload in jobs.items()
        if isinstance(payload, dict) and payload.get("status") in _TERMINAL_JOB_STATUSES
    ]
    excess = len(terminal) - _MAX_PERSISTED_TERMINAL_JOBS
    if excess <= 0:
        return snap
    now = _as_aware(now) or _utcnow()
    ttl = _job_result_ttl_s()
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    candidates: list[tuple[datetime, str]] = []
    for jid, payload in terminal:
        if jid in keep:
            continue
        finished = (
            _parse_dt(payload.get("finished_at"))
            or _parse_dt(payload.get("created_at"))
            or epoch
        )
        consumed = payload.get("result_consumed_at") is not None
        if (
            jid in results_in
            and not consumed
            and (now - finished).total_seconds() < ttl
        ):
            continue  # unread result — keep until acked or TTL
        candidates.append((finished, jid))
    candidates.sort()
    drop = {jid for _finished, jid in candidates[:excess]}
    if not drop:
        return snap
    for jid in drop:
        jobs.pop(jid, None)
    results = dict(results_in)
    events = dict(snap.get("events") or {})
    for jid in drop:
        results.pop(jid, None)
        events.pop(jid, None)
    order = [j for j in (snap.get("order") or []) if j not in drop]
    return _keep_pause(snap, jobs=jobs, results=results, events=events, order=order)


def _keep_pause(snap: dict[str, Any], **updates: Any) -> dict[str, Any]:
    """Rebuild a queue snapshot without dropping ``paused_runs``."""
    paused = snap.get("paused_runs")
    out: dict[str, Any] = {
        "jobs": snap.get("jobs") or {},
        "order": list(snap.get("order") or []),
        "results": snap.get("results") or {},
        "events": snap.get("events") or {},
        "paused_runs": list(paused) if isinstance(paused, list) else [],
    }
    out.update(updates)
    return out


def _paused_run_ids(snap_or_ids: Any) -> set[str]:
    if isinstance(snap_or_ids, dict):
        raw = snap_or_ids.get("paused_runs") or []
    else:
        raw = snap_or_ids or []
    return {str(x) for x in raw if str(x).strip()}


def _tombstone_rejected_outputs(result: JobResult, *, reason: str) -> None:
    refs = [str(u) for u in (result.output_refs or {}).values() if u]
    if not refs:
        return
    try:
        from app.core.distributed.transfer import tombstone_blobs

        tombstone_blobs(refs, reason=reason)
    except Exception as exc:
        log.warning("JobQueue: failed to tombstone rejected blobs: %s", exc)


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
        self._paused_runs: set[str] = set()
        self._store = store
        # Last store version token applied to the local cache (None = unknown).
        self._seen_version: Any = None
        self._warned_legacy_heartbeat: set[str] = set()
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
        """Persist local snapshot under the store's exclusive lock.

        Prefer ``_durable_mutate`` for cross-process safety (DIST-002): blind
        full-snapshot replace from a stale local cache can still lose concurrent
        record updates. This path remains for in-memory-only / legacy callers.
        """
        if self._store is None:
            return
        try:
            snapshot = self._queue_snapshot_unlocked()
            # mutate_queue holds the cross-process lock for the write.
            self._store.mutate_queue(lambda _snap: (snapshot, None))
        except Exception as exc:
            log.warning("JobQueue: persist failed: %s", exc)

    def _reload_unlocked(self) -> None:
        """Reload the local cache from the durable store (records version)."""
        assert self._store is not None
        try:
            token = self._store.state_version("queue")
        except Exception:
            token = None
        self._apply_queue_snapshot_unlocked(self._store.load_queue())
        self._seen_version = token

    def _refresh_if_stale_unlocked(self) -> None:
        """Read-through for read-only accessors (multi-process control planes).

        Disk/memory stores expose a cheap version token; the cache is reloaded
        only when it changed. Redis (token ``None``) is always read-through.
        """
        if self._store is None:
            return
        try:
            token = self._store.state_version("queue")
        except Exception:
            token = None
        if token is not None and token == self._seen_version:
            return
        try:
            self._reload_unlocked()
        except Exception as exc:
            log.warning("JobQueue: read-through refresh failed: %s", exc)

    def _durable_mutate(self, mutator):
        """Apply ``mutator(snap) -> (new_snap, result)`` under store lock; refresh."""
        assert self._store is not None
        result = self._store.mutate_queue(mutator)
        try:
            self._reload_unlocked()
        except Exception as exc:
            log.warning("JobQueue: durable refresh failed: %s", exc)
        return result

    def enqueue(self, job: NodeJob) -> NodeJob:
        """Add a pending job. Assigns ``job_id`` if empty."""
        with self._lock:
            if self._store is not None:
                job_id = job.job_id or str(uuid.uuid4())
                created = job.created_at or _utcnow()

                def mut(snap: dict[str, Any]):
                    snap = self._reclaim_in_snapshot(
                        snap,
                        lease_ttl_s=self._lease_ttl_s,
                        now=_utcnow(),
                        stale_workers=self._stale_worker_ids(),
                    )
                    stored = job.model_copy(
                        update={
                            "job_id": job_id,
                            "status": "pending",
                            "created_at": created,
                            "claimed_by": None,
                            "claimed_at": None,
                            "lease_expires_at": None,
                        }
                    )
                    jobs = dict(snap.get("jobs") or {})
                    order = list(snap.get("order") or [])
                    events = dict(snap.get("events") or {})
                    jobs[job_id] = _plain_jsonable(stored.model_dump(mode="python"))
                    if job_id not in order:
                        order.append(job_id)
                    events.setdefault(job_id, [])
                    new_snap = _keep_pause(
                        snap,
                        jobs=jobs,
                        order=order,
                        results=dict(snap.get("results") or {}),
                        events=events,
                    )
                    return new_snap, stored

                stored = self._durable_mutate(mut)
                self._waiters.setdefault(stored.job_id, threading.Event())
                return stored

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
            self._refresh_if_stale_unlocked()
            return self._jobs.get(job_id)

    def get_result(self, job_id: str) -> JobResult | None:
        with self._lock:
            self._refresh_if_stale_unlocked()
            return self._results.get(job_id)

    def ack_result(self, job_id: str) -> bool:
        """Mark a job's result as consumed by the control plane.

        Unconsumed results are protected from history trimming (until
        ``GRAPHYN_JOB_RESULT_TTL_S``). Returns True when a marker was set.
        """
        with self._lock:
            if self._store is not None:
                def mut(snap: dict[str, Any]):
                    jobs = dict(snap.get("jobs") or {})
                    payload = jobs.get(job_id)
                    if not isinstance(payload, dict):
                        return snap, False
                    if payload.get("result_consumed_at") is not None:
                        return snap, False
                    if job_id not in (snap.get("results") or {}):
                        return snap, False
                    jobs[job_id] = {
                        **payload,
                        "result_consumed_at": _plain_jsonable(_utcnow()),
                    }
                    return _keep_pause(snap, jobs=jobs), True

                return bool(self._durable_mutate(mut))
            job = self._jobs.get(job_id)
            if job is None or job.result_consumed_at is not None:
                return False
            self._jobs[job_id] = job.model_copy(
                update={"result_consumed_at": _utcnow()}
            )
            return True

    def is_cancelled(self, job_id: str) -> bool:
        """True if the job is marked cancelled (control-plane signal)."""
        with self._lock:
            self._refresh_if_stale_unlocked()
            job = self._jobs.get(job_id)
            return job is not None and job.status == "cancelled"

    def set_run_paused(self, run_id: str, paused: bool) -> None:
        """Hold or release claims for every job belonging to ``run_id``.

        Already-running ``process()`` calls are not interrupted; workers must
        poll :meth:`is_run_paused` before starting the next node and renew the
        lease while they wait. Cancel remains the hard stop.
        """
        rid = str(run_id or "").strip()
        if not rid:
            return
        with self._lock:
            if self._store is not None:
                def mut(snap: dict[str, Any]):
                    held = _paused_run_ids(snap)
                    if paused:
                        held.add(rid)
                    else:
                        held.discard(rid)
                    new_snap = _keep_pause(snap, paused_runs=sorted(held))
                    return new_snap, None

                self._durable_mutate(mut)
                return
            if paused:
                self._paused_runs.add(rid)
            else:
                self._paused_runs.discard(rid)

    def is_run_paused(self, run_id: str) -> bool:
        rid = str(run_id or "").strip()
        if not rid:
            return False
        with self._lock:
            if self._store is not None:
                try:
                    snap = self._store.load_queue()
                except Exception:
                    snap = {}
                return rid in _paused_run_ids(snap)
            return rid in self._paused_runs

    def has_active_jobs_for_run(self, run_id: str) -> bool:
        """True if any pending/claimed/running job belongs to ``run_id``."""
        rid = str(run_id or "").strip()
        if not rid:
            return False
        with self._lock:
            self._refresh_if_stale_unlocked()
            for job in self._jobs.values():
                if str(job.run_id or "") == rid and job.status in (
                    "pending",
                    "claimed",
                    "running",
                ):
                    return True
        return False


    def active_blob_refs(
        self, *, exclude_run_id: str | None = None
    ) -> tuple[set[str], set[str]]:
        """``(input_ref_uris, job_ids)`` of non-terminal jobs (blob GC guard).

        Jobs of ``exclude_run_id`` are ignored (the run being cleaned up).
        """
        uris: set[str] = set()
        job_ids: set[str] = set()
        with self._lock:
            self._refresh_if_stale_unlocked()
            for jid, job in self._jobs.items():
                if job.status in _TERMINAL_JOB_STATUSES:
                    continue
                if exclude_run_id is not None and str(job.run_id or "") == exclude_run_id:
                    continue
                job_ids.add(jid)
                for ref in (job.input_refs or {}).values():
                    if isinstance(ref, str):
                        uris.add(ref)
        return uris, job_ids

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

    def _queue_snapshot_unlocked(self) -> dict[str, Any]:
        return {
            "jobs": {jid: _plain_jsonable(j.model_dump(mode="python")) for jid, j in self._jobs.items()},
            "order": list(self._order),
            "results": {
                jid: _plain_jsonable(r.model_dump(mode="python")) for jid, r in self._results.items()
            },
            "events": {jid: list(evs) for jid, evs in self._events.items()},
            "paused_runs": sorted(self._paused_runs),
        }

    def _apply_queue_snapshot_unlocked(self, snap: dict[str, Any]) -> None:
        """Replace in-memory queue maps from a durable snapshot (keep waiters)."""
        jobs_raw = snap.get("jobs") or {}
        new_jobs: dict[str, NodeJob] = {}
        for jid, payload in jobs_raw.items():
            try:
                new_jobs[jid] = NodeJob.model_validate(payload)
            except Exception as exc:
                log.warning("JobQueue: skip corrupt job %r in apply: %s", jid, exc)
        order = [jid for jid in (snap.get("order") or []) if jid in new_jobs]
        for jid, job in new_jobs.items():
            if job.status == "pending" and jid not in order:
                order.append(jid)
        new_results: dict[str, JobResult] = {}
        for jid, payload in (snap.get("results") or {}).items():
            try:
                new_results[jid] = JobResult.model_validate(payload)
            except Exception as exc:
                log.warning("JobQueue: skip corrupt result %r in apply: %s", jid, exc)
        new_events: dict[str, list[dict[str, Any]]] = {}
        for jid, events in (snap.get("events") or {}).items():
            if isinstance(events, list):
                new_events[jid] = list(events)
        self._jobs = new_jobs
        self._order = order
        self._results = new_results
        self._events = new_events
        self._paused_runs = _paused_run_ids(snap)
        for jid in self._jobs:
            self._waiters.setdefault(jid, threading.Event())
            if jid in self._results:
                self._waiters[jid].set()

    def _stale_worker_ids(self) -> frozenset[str]:
        """Worker ids whose heartbeat is past the stale TTL (unreachable pins)."""
        try:
            from app.core.distributed.registry import get_worker_registry

            reg = get_worker_registry()
            return frozenset(
                w.worker_id
                for w in reg.list(include_stale=True)
                if reg.is_stale(w)
            )
        except Exception:
            return frozenset()

    @staticmethod
    def _reclaim_in_snapshot(
        snap: dict[str, Any],
        *,
        lease_ttl_s: float,
        now: datetime | None = None,
        stale_workers: frozenset[str] | None = None,
    ) -> dict[str, Any]:
        """Return a new snapshot with expired leases requeued (pure)."""
        now = _as_aware(now) or _utcnow()
        jobs_raw = dict(snap.get("jobs") or {})
        order = list(snap.get("order") or [])
        results_raw = dict(snap.get("results") or {})
        changed = False
        stale_workers = stale_workers or frozenset()
        for jid, payload in list(jobs_raw.items()):
            try:
                job = NodeJob.model_validate(payload)
            except Exception as exc:
                log.warning(
                    "JobQueue: skip corrupt job %r during reclaim: %s", jid, exc
                )
                continue
            if job.status not in ("claimed", "running"):
                continue
            expires = _as_aware(job.lease_expires_at)
            if expires is None:
                claimed_at = _as_aware(job.claimed_at)
                if claimed_at is None:
                    continue
                expires = claimed_at + timedelta(seconds=lease_ttl_s)
            if expires > now:
                continue
            next_attempts = int(job.attempts or 0) + 1
            max_attempts = int(job.max_attempts or 5)
            if next_attempts > max_attempts:
                failed = job.model_copy(
                    update={
                        "status": "failed",
                        "claimed_by": None,
                        "claimed_at": None,
                        "lease_expires_at": None,
                        "attempts": next_attempts,
                        "finished_at": now,
                    }
                )
                jobs_raw[jid] = _plain_jsonable(failed.model_dump(mode="python"))
                if jid in order:
                    order = [j for j in order if j != jid]
                results_raw[jid] = _plain_jsonable(JobResult(
                    job_id=jid,
                    status="failed",
                    error=(
                        f"exceeded max_attempts ({max_attempts}) after lease reclaim"
                    ),
                    worker_id=job.claimed_by,
                ).model_dump(mode="python"))
                changed = True
                log.warning(
                    "JobQueue: job %s failed — max_attempts %s exceeded",
                    jid,
                    max_attempts,
                )
                continue
            update: dict[str, Any] = {
                "status": "pending",
                "claimed_by": None,
                "claimed_at": None,
                "lease_expires_at": None,
                "lease_generation": int(job.lease_generation or 0) + 1,
                "attempts": next_attempts,
            }
            widened = widen_placement_after_reclaim(
                job.placement,
                tags=list(job.tags or []),
                require_gpu=bool(job.require_gpu),
                min_vram_mib=job.min_vram_mib,
                pool=job.pool,
            )
            if widened is not job.placement:
                update["placement"] = widened
            updated = job.model_copy(update=update)
            jobs_raw[jid] = _plain_jsonable(updated.model_dump(mode="python"))
            if jid not in order:
                order.append(jid)
            changed = True
            log.info(
                "JobQueue: reclaimed expired lease for job %s (was claimed by %s)",
                jid,
                job.claimed_by,
            )
        for jid, payload in list(jobs_raw.items()):
            try:
                job = NodeJob.model_validate(payload)
            except Exception as exc:
                log.warning(
                    "JobQueue: skip corrupt job %r during pending pin release: %s",
                    jid,
                    exc,
                )
                continue
            if job.status != "pending":
                continue
            placement = job.placement
            pinned = (
                placement is not None
                and getattr(placement, "mode", None) == "worker"
                and getattr(placement, "worker", None)
            )
            if not pinned or placement.worker not in stale_workers:
                continue
            widened = widen_placement_after_reclaim(
                job.placement,
                tags=list(job.tags or []),
                require_gpu=bool(job.require_gpu),
                min_vram_mib=job.min_vram_mib,
                pool=job.pool,
            )
            if widened is job.placement:
                continue
            jobs_raw[jid] = _plain_jsonable(
                job.model_copy(update={"placement": widened}).model_dump(mode="python")
            )
            changed = True
            log.info(
                "JobQueue: released stale worker pin on pending job %s (was %s)",
                jid,
                placement.worker,
            )
        if not changed:
            return snap
        return _keep_pause(
            snap,
            jobs=jobs_raw,
            order=order,
            results=results_raw,
            events=dict(snap.get("events") or {}),
        )

    def _claim_in_snapshot(
        self, snap: dict[str, Any], worker: WorkerInfo
    ) -> tuple[dict[str, Any], NodeJob | None]:
        """CAS claim against a queue snapshot. At most one pending→claimed."""
        snap = self._reclaim_in_snapshot(
            snap,
            lease_ttl_s=self._lease_ttl_s,
            now=_utcnow(),
            stale_workers=self._stale_worker_ids(),
        )
        jobs_raw = dict(snap.get("jobs") or {})
        order = list(snap.get("order") or [])
        for job_id in list(order):
            payload = jobs_raw.get(job_id)
            if payload is None:
                continue
            try:
                job = NodeJob.model_validate(payload)
            except Exception as exc:
                log.warning(
                    "JobQueue: skip corrupt job %r during claim: %s", job_id, exc
                )
                continue
            if job.status != "pending":
                continue
            if str(job.run_id or "") in _paused_run_ids(snap):
                continue
            if not _worker_trust_ok(worker):
                continue
            if not _plugins_allow(worker, job.node_type):
                continue
            if not worker_eligible_for_job(worker, job):
                continue
            if _quota_blocks_claim(worker, job, jobs_raw):
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
            jobs_raw[job_id] = _plain_jsonable(claimed.model_dump(mode="python"))
            order = [jid for jid in order if jid != job_id]
            new_snap = _keep_pause(
                snap,
                jobs=jobs_raw,
                order=order,
                results=dict(snap.get("results") or {}),
                events=dict(snap.get("events") or {}),
            )
            return new_snap, claimed
        return snap, None

    def claim(self, worker: WorkerInfo) -> NodeJob | None:
        """Claim the oldest pending job this worker is eligible for.

        Hard-refuses jobs whose ``node_type`` is missing from the worker's
        advertised ``plugins`` list (when non-empty). Reclaims expired leases
        before scanning.

        When a durable store is configured, the pending→claimed transition runs
        inside ``store.mutate_queue`` (file lock / Redis lock) so at most one
        worker across processes wins. Threading locks alone are not sufficient.

        Returns the claimed job, or ``None`` if none match.
        """
        with self._lock:
            if self._store is not None:
                claimed = self._store.mutate_queue(
                    lambda snap: self._claim_in_snapshot(snap, worker)
                )
                # Refresh local cache from durable truth after CAS.
                try:
                    self._reload_unlocked()
                except Exception as exc:
                    log.warning("JobQueue: post-claim refresh failed: %s", exc)
                    if claimed is not None:
                        self._jobs[claimed.job_id] = claimed
                        if claimed.job_id in self._order:
                            self._order.remove(claimed.job_id)
                return claimed

            self._reclaim_expired_leases_unlocked(now=_utcnow())
            for job_id in list(self._order):
                job = self._jobs.get(job_id)
                if job is None or job.status != "pending":
                    continue
                if str(job.run_id or "") in self._paused_runs:
                    continue
                # Hard refuse: advertised plugins must include node_type.
                if not _worker_trust_ok(worker):
                    continue
                if not _plugins_allow(worker, job.node_type):
                    continue
                if not worker_eligible_for_job(worker, job):
                    continue
                jobs_raw = {
                    jid: j.model_dump(mode="python") for jid, j in self._jobs.items()
                }
                if _quota_blocks_claim(worker, job, jobs_raw):
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
            if self._store is not None:
                def mut(snap: dict[str, Any]):
                    payload = (snap.get("jobs") or {}).get(job_id)
                    if payload is None:
                        return snap, None
                    try:
                        job = NodeJob.model_validate(payload)
                    except Exception as exc:
                        log.warning(
                            "JobQueue: renew_lease skip corrupt job %r: %s",
                            job_id,
                            exc,
                        )
                        return snap, None
                    if job.status not in ("claimed", "running"):
                        return snap, job
                    if worker_id is not None and job.claimed_by and job.claimed_by != worker_id:
                        return snap, job
                    updated = job.model_copy(
                        update={
                            "lease_expires_at": _utcnow()
                            + timedelta(seconds=self._lease_ttl_s),
                        }
                    )
                    jobs = dict(snap.get("jobs") or {})
                    jobs[job_id] = _plain_jsonable(updated.model_dump(mode="python"))
                    return {**snap, "jobs": jobs}, updated

                return self._durable_mutate(mut)

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

    def renew_leases_for_worker(
        self,
        worker_id: str,
        active_job_ids: "list[str] | tuple[str, ...] | set[str] | None" = None,
    ) -> int:
        """Renew leases for jobs claimed by ``worker_id``.

        When ``active_job_ids`` is given (heartbeat protocol v2), only those
        jobs are renewed — a job the worker no longer reports (e.g. it
        restarted and lost it) is left to expire and be reclaimed. ``None``
        keeps the legacy "renew every claimed job" behaviour (deprecated).
        """
        wanted: set[str] | None = (
            None if active_job_ids is None else {str(j) for j in active_job_ids}
        )
        if wanted is None and worker_id not in self._warned_legacy_heartbeat:
            self._warned_legacy_heartbeat.add(worker_id)
            log.warning(
                "JobQueue: heartbeat from worker %s without active_job_ids — "
                "renewing every job it claimed (deprecated; upgrade the worker)",
                worker_id,
            )

        def _wanted(jid: str) -> bool:
            return wanted is None or jid in wanted

        with self._lock:
            if self._store is not None:
                def mut(snap: dict[str, Any]):
                    jobs = dict(snap.get("jobs") or {})
                    count = 0
                    expiry = _utcnow() + timedelta(seconds=self._lease_ttl_s)
                    for jid, payload in list(jobs.items()):
                        if not _wanted(jid):
                            continue
                        try:
                            job = NodeJob.model_validate(payload)
                        except Exception as exc:
                            log.warning(
                                "JobQueue: renew_leases_for_worker skip corrupt "
                                "job %r: %s",
                                jid,
                                exc,
                            )
                            continue
                        if job.claimed_by != worker_id:
                            continue
                        if job.status not in ("claimed", "running"):
                            continue
                        jobs[jid] = _plain_jsonable(job.model_copy(
                            update={"lease_expires_at": expiry}
                        ).model_dump(mode="python"))
                        count += 1
                    if not count:
                        return snap, 0
                    return {**snap, "jobs": jobs}, count

                return self._durable_mutate(mut)

            count = 0
            now = _utcnow()
            expiry = now + timedelta(seconds=self._lease_ttl_s)
            for jid, job in list(self._jobs.items()):
                if not _wanted(jid):
                    continue
                if job.claimed_by != worker_id:
                    continue
                if job.status not in ("claimed", "running"):
                    continue
                self._jobs[jid] = job.model_copy(update={"lease_expires_at": expiry})
                count += 1
            if count:
                self._persist_unlocked()
            return count

    @staticmethod
    def _release_worker_in_snapshot(
        snap: dict[str, Any],
        worker_id: str,
        keep: set[str],
    ) -> tuple[dict[str, Any], list[str]]:
        """Requeue (bump generation) jobs claimed by ``worker_id`` not in ``keep``."""
        jobs_raw = dict(snap.get("jobs") or {})
        order = list(snap.get("order") or [])
        results_raw = dict(snap.get("results") or {})
        released: list[str] = []
        now = _utcnow()
        for jid, payload in list(jobs_raw.items()):
            if jid in keep:
                continue
            try:
                job = NodeJob.model_validate(payload)
            except Exception:
                continue
            if job.claimed_by != worker_id or job.status not in ("claimed", "running"):
                continue
            next_attempts = int(job.attempts or 0) + 1
            max_attempts = int(job.max_attempts or 5)
            if next_attempts > max_attempts:
                failed = job.model_copy(
                    update={
                        "status": "failed",
                        "claimed_by": None,
                        "claimed_at": None,
                        "lease_expires_at": None,
                        "attempts": next_attempts,
                        "lease_generation": int(job.lease_generation or 0) + 1,
                        "finished_at": now,
                    }
                )
                jobs_raw[jid] = _plain_jsonable(failed.model_dump(mode="python"))
                order = [j for j in order if j != jid]
                results_raw[jid] = _plain_jsonable(JobResult(
                    job_id=jid,
                    status="failed",
                    error=(
                        f"exceeded max_attempts ({max_attempts}) after worker "
                        f"{worker_id} re-registered"
                    ),
                    worker_id=worker_id,
                ).model_dump(mode="python"))
                released.append(jid)
                continue
            update: dict[str, Any] = {
                "status": "pending",
                "claimed_by": None,
                "claimed_at": None,
                "lease_expires_at": None,
                "lease_generation": int(job.lease_generation or 0) + 1,
                "attempts": next_attempts,
            }
            widened = widen_placement_after_reclaim(
                job.placement,
                tags=list(job.tags or []),
                require_gpu=bool(job.require_gpu),
                min_vram_mib=job.min_vram_mib,
                pool=job.pool,
            )
            if widened is not job.placement:
                update["placement"] = widened
            jobs_raw[jid] = _plain_jsonable(
                job.model_copy(update=update).model_dump(mode="python")
            )
            if jid not in order:
                order.append(jid)
            released.append(jid)
        if not released:
            return snap, []
        return (
            _keep_pause(snap, jobs=jobs_raw, order=order, results=results_raw),
            released,
        )

    def release_jobs_for_worker(
        self,
        worker_id: str,
        *,
        keep_job_ids: "list[str] | tuple[str, ...] | set[str] | None" = None,
    ) -> list[str]:
        """Requeue every job claimed by ``worker_id`` (new worker instance).

        Called when a worker (re-)registers: a restarted process with the same
        id cannot still be running the old claims, so they are requeued with
        a bumped ``lease_generation`` (fencing any late complete from the dead
        instance). ``keep_job_ids`` lists jobs the registering instance is
        still actively running (re-register after a control-plane 404).
        Returns released job ids.
        """
        keep = {str(j) for j in (keep_job_ids or [])}
        with self._lock:
            if self._store is not None:
                released = self._durable_mutate(
                    lambda snap: self._release_worker_in_snapshot(snap, worker_id, keep)
                )
            else:
                snap = self._queue_snapshot_unlocked()
                new_snap, released = self._release_worker_in_snapshot(
                    snap, worker_id, keep
                )
                if released:
                    self._apply_queue_snapshot_unlocked(new_snap)
            for jid in released:
                job = self._jobs.get(jid)
                if job is not None and job.status == "failed":
                    self._waiters.setdefault(jid, threading.Event()).set()
            if released:
                log.info(
                    "JobQueue: worker %s re-registered — released %s stale claim(s): %s",
                    worker_id,
                    len(released),
                    released,
                )
            return list(released or [])

    def reclaim_expired_leases(self, *, now: datetime | None = None) -> list[str]:
        """Requeue claimed/running jobs whose lease has expired. Returns job ids.

        When a durable store is configured, reclaim runs inside ``mutate_queue``
        via ``_reclaim_in_snapshot`` (same CAS path as claim/enqueue). The
        in-memory unlocked helper remains for store-less callers.

        Safe to call with or without the queue lock held (RLock).
        """
        with self._lock:
            if self._store is not None:
                now_fixed = _as_aware(now) or _utcnow()

                def mut(snap: dict[str, Any]):
                    before = dict(snap.get("jobs") or {})
                    new_snap = self._reclaim_in_snapshot(
                        snap,
                        lease_ttl_s=self._lease_ttl_s,
                        now=now_fixed,
                        stale_workers=self._stale_worker_ids(),
                    )
                    reclaimed: list[str] = []
                    for jid, new_payload in (new_snap.get("jobs") or {}).items():
                        old_payload = before.get(jid)
                        if not isinstance(old_payload, dict) or not isinstance(
                            new_payload, dict
                        ):
                            continue
                        if old_payload.get("status") in ("claimed", "running") and (
                            new_payload.get("status") == "pending"
                        ):
                            reclaimed.append(jid)
                    return new_snap, reclaimed

                return self._durable_mutate(mut)

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
            update: dict[str, Any] = {
                "status": "pending",
                "claimed_by": None,
                "claimed_at": None,
                "lease_expires_at": None,
                "lease_generation": int(job.lease_generation or 0) + 1,
            }
            # Preferred-worker pin (placement.mode=worker) would trap the job on
            # the unreachable worker; widen to auto + original GPU/tag constraints.
            widened = widen_placement_after_reclaim(
                job.placement,
                tags=list(job.tags or []),
                require_gpu=bool(job.require_gpu),
                min_vram_mib=job.min_vram_mib,
                pool=job.pool,
            )
            if widened is not job.placement:
                update["placement"] = widened
                log.info(
                    "JobQueue: widened placement for reclaimed job %s "
                    "(cleared preferred worker pin → mode=auto)",
                    jid,
                )
            updated = job.model_copy(update=update)
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
            if self._store is not None:
                def mut(snap: dict[str, Any]):
                    jobs = dict(snap.get("jobs") or {})
                    payload = jobs.get(job_id)
                    if payload is None:
                        return snap, None
                    try:
                        job = NodeJob.model_validate(payload)
                    except Exception as exc:
                        log.warning(
                            "JobQueue: mark_running skip corrupt job %r: %s",
                            job_id,
                            exc,
                        )
                        return snap, None
                    if job.status not in ("claimed", "running"):
                        return snap, job
                    updated = job.model_copy(
                        update={
                            "status": "running",
                            "lease_expires_at": _utcnow()
                            + timedelta(seconds=self._lease_ttl_s),
                        }
                    )
                    jobs[job_id] = _plain_jsonable(updated.model_dump(mode="python"))
                    return {**snap, "jobs": jobs}, updated

                return self._durable_mutate(mut)

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
            if self._store is not None:
                def mut(snap: dict[str, Any]):
                    jobs = dict(snap.get("jobs") or {})
                    payload = jobs.get(result.job_id)
                    if payload is None:
                        raise KeyError(result.job_id)
                    job = NodeJob.model_validate(payload)
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
                    if (
                        result.lease_generation is None
                        or int(result.lease_generation) != expected_gen
                    ):
                        _tombstone_rejected_outputs(
                            result,
                            reason=(
                                f"lease_generation mismatch job={result.job_id} "
                                f"result={result.lease_generation!r} expected={expected_gen}"
                            ),
                        )
                        raise ValueError(
                            f"Job {result.job_id} lease_generation mismatch: "
                            f"result={result.lease_generation!r} expected={expected_gen}"
                        )
                    status: JobStatus = result.status  # type: ignore[assignment]
                    updated = job.model_copy(
                        update={
                            "status": status,
                            "lease_expires_at": None,
                            "finished_at": _utcnow(),
                        }
                    )
                    jobs[result.job_id] = _plain_jsonable(updated.model_dump(mode="python"))
                    results = dict(snap.get("results") or {})
                    results[result.job_id] = _plain_jsonable(result.model_dump(mode="python"))
                    evmap = {
                        k: list(v) if isinstance(v, list) else []
                        for k, v in (snap.get("events") or {}).items()
                    }
                    if result.events:
                        bucket = list(evmap.get(result.job_id) or [])
                        bucket.extend(result.events)
                        evmap[result.job_id] = _cap_events(bucket)
                    order = [j for j in (snap.get("order") or []) if j != result.job_id]
                    new_snap = _keep_pause(
                        snap,
                        jobs=jobs,
                        order=order,
                        results=results,
                        events=evmap,
                    )
                    return (
                        _trim_terminal_jobs_snapshot(
                            new_snap, keep=frozenset({result.job_id})
                        ),
                        updated,
                    )

                updated = self._durable_mutate(mut)
                evt = self._waiters.get(result.job_id)
                if evt is not None:
                    evt.set()
                return updated

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
                _tombstone_rejected_outputs(
                    result,
                    reason=(
                        f"lease_generation mismatch job={result.job_id} "
                        f"result={result.lease_generation!r} expected={expected_gen}"
                    ),
                )
                raise ValueError(
                    f"Job {result.job_id} lease_generation mismatch: "
                    f"result={result.lease_generation!r} expected={expected_gen}"
                )
            status: JobStatus = result.status  # type: ignore[assignment]
            updated = job.model_copy(
                update={
                    "status": status,
                    "lease_expires_at": None,
                    "finished_at": _utcnow(),
                }
            )
            self._jobs[result.job_id] = updated
            self._results[result.job_id] = result
            if result.events:
                bucket = self._events.setdefault(result.job_id, [])
                bucket.extend(result.events)
                self._events[result.job_id] = _cap_events(bucket)
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
            if self._store is not None:
                def mut(snap: dict[str, Any]):
                    jobs = dict(snap.get("jobs") or {})
                    payload = jobs.get(job_id)
                    if payload is None:
                        raise KeyError(job_id)
                    job = NodeJob.model_validate(payload)
                    if job.status in ("succeeded", "failed", "cancelled"):
                        return snap, job
                    updated = job.model_copy(
                        update={
                            "status": "cancelled",
                            "lease_expires_at": None,
                            "finished_at": _utcnow(),
                        }
                    )
                    jobs[job_id] = _plain_jsonable(updated.model_dump(mode="python"))
                    order = [j for j in (snap.get("order") or []) if j != job_id]
                    results = dict(snap.get("results") or {})
                    results[job_id] = _plain_jsonable(JobResult(
                        job_id=job_id,
                        status="cancelled",
                        error="cancelled by control plane",
                        worker_id=job.claimed_by,
                    ).model_dump(mode="python"))
                    new_snap = _keep_pause(
                        snap,
                        jobs=jobs,
                        order=order,
                        results=results,
                        events=dict(snap.get("events") or {}),
                    )
                    return (
                        _trim_terminal_jobs_snapshot(new_snap, keep=frozenset({job_id})),
                        updated,
                    )

                updated = self._durable_mutate(mut)
                self._waiters.setdefault(job_id, threading.Event()).set()
                return updated

            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status in ("succeeded", "failed", "cancelled"):
                return job
            updated = job.model_copy(
                update={
                    "status": "cancelled",
                    "lease_expires_at": None,
                    "finished_at": _utcnow(),
                }
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

    def list_events(self, job_id: str) -> list[dict[str, Any]]:
        """Return a copy of events appended for ``job_id`` (empty if none)."""
        with self._lock:
            if self._store is not None:
                self._sync_from_store_unlocked(job_id=job_id)
            return list(self._events.get(job_id) or [])

    def append_events(self, job_id: str, events: list[dict[str, Any]]) -> int:
        """Append log/event payloads for a job. Returns new event count."""
        with self._lock:
            if self._store is not None:
                def mut(snap: dict[str, Any]):
                    jobs = dict(snap.get("jobs") or {})
                    if job_id not in jobs:
                        raise KeyError(job_id)
                    evmap = {
                        k: list(v) if isinstance(v, list) else []
                        for k, v in (snap.get("events") or {}).items()
                    }
                    bucket = list(evmap.get(job_id) or [])
                    bucket.extend(events)
                    bucket = _cap_events(bucket)
                    evmap[job_id] = bucket
                    try:
                        job = NodeJob.model_validate(jobs[job_id])
                    except Exception as exc:
                        log.warning(
                            "JobQueue: append_events skip corrupt job %r: %s",
                            job_id,
                            exc,
                        )
                        job = None
                    if job is not None and job.status in ("claimed", "running"):
                        jobs[job_id] = _plain_jsonable(job.model_copy(
                            update={
                                "lease_expires_at": _utcnow()
                                + timedelta(seconds=self._lease_ttl_s),
                            }
                        ).model_dump(mode="python"))
                    new_snap = _keep_pause(
                        snap,
                        jobs=jobs,
                        order=list(snap.get("order") or []),
                        results=dict(snap.get("results") or {}),
                        events=evmap,
                    )
                    return new_snap, len(bucket)

                return self._durable_mutate(mut)

            if job_id not in self._jobs:
                raise KeyError(job_id)
            bucket = self._events.setdefault(job_id, [])
            bucket.extend(events)
            bucket = _cap_events(bucket)
            self._events[job_id] = bucket
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
            poll = float(os.environ.get("GRAPHYN_JOB_WAIT_POLL_S", "4.0") or "4.0")
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
            self._refresh_if_stale_unlocked()
            return sum(1 for jid in self._order if self._jobs.get(jid) is not None)

    def clear(self) -> None:
        with self._lock:
            if self._store is not None:
                def mut(_snap: dict[str, Any]):
                    return {
                        "jobs": {},
                        "order": [],
                        "results": {},
                        "events": {},
                        "paused_runs": [],
                    }, None

                self._durable_mutate(mut)
                for evt in list(self._waiters.values()):
                    evt.set()
                self._waiters.clear()
                return

            for evt in self._waiters.values():
                evt.set()
            self._jobs.clear()
            self._order.clear()
            self._results.clear()
            self._events.clear()
            self._waiters.clear()
            self._paused_runs.clear()
            self._persist_unlocked()



def _count_active_in_jobs(
    jobs: dict[str, Any] | list[Any],
    *,
    worker_id: str | None = None,
    pool: str | None = None,
) -> int:
    """Count claimed/running jobs in a snapshot dict or job list."""
    n = 0
    iterable = jobs.values() if isinstance(jobs, dict) else jobs
    for payload in iterable:
        try:
            if isinstance(payload, NodeJob):
                job = payload
            else:
                job = NodeJob.model_validate(payload)
        except Exception:
            continue
        if job.status not in ("claimed", "running"):
            continue
        if worker_id is not None and job.claimed_by != worker_id:
            continue
        if pool is not None and str(job.pool or "") != str(pool):
            continue
        n += 1
    return n


def _quota_blocks_claim(worker: WorkerInfo, job: NodeJob, jobs_raw: dict[str, Any]) -> bool:
    """True when claiming ``job`` would exceed worker or pool concurrent quotas."""
    from app.core.distributed.quotas import parse_pool_max_claimed, worker_max_claimed

    limit = worker_max_claimed(worker)
    if limit is not None:
        if _count_active_in_jobs(jobs_raw, worker_id=worker.worker_id) >= limit:
            return True
    limits = parse_pool_max_claimed()
    if limits:
        pools: list[str] = []
        if job.pool:
            pools.append(str(job.pool))
        for p in list(worker.pools or []):
            s = str(p or "").strip()
            if s and s not in pools:
                pools.append(s)
        for pool_name in pools:
            if pool_name in limits and _count_active_in_jobs(jobs_raw, pool=pool_name) >= limits[pool_name]:
                return True
    return False


def _worker_trust_ok(worker: WorkerInfo) -> bool:
    """Fail closed for untrusted workers when trust is required."""
    if bool(getattr(worker, "trusted", True)):
        return True
    import os

    flag = (os.environ.get("GRAPHYN_WORKER_TRUST_REQUIRED") or "").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return True
    try:
        from app.core.config import auth_required

        if not auth_required():
            return True
    except Exception:
        return True
    return False


def _plugins_allow(worker: WorkerInfo, node_type: str) -> bool:
    """Hard refuse when advertised / allowlisted plugins omit ``node_type``.

    Rules (fail closed when flags require it):
    * empty advertised ``plugins`` → allow in lab; deny when
      ``GRAPHYN_WORKER_REQUIRE_PLUGIN_ADVERTISE=1``.
    * intersect advertised ∩ ``allowed_plugins`` when the latter is set.
    * when ``plugin_hashes`` pins a type, ``content_hashes[type]`` must match.
    """
    import os

    plugins = list(worker.plugins or [])
    require_adv = (os.environ.get("GRAPHYN_WORKER_REQUIRE_PLUGIN_ADVERTISE") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    if not plugins:
        return not require_adv
    if not node_type:
        return False
    allowed = getattr(worker, "allowed_plugins", None)
    if allowed is not None:
        allow_set = {str(x) for x in allowed}
        plugins = [p for p in plugins if p in allow_set]
    if node_type not in plugins:
        return False
    pins = getattr(worker, "plugin_hashes", None) or None
    if isinstance(pins, dict) and node_type in pins:
        expected = str(pins.get(node_type) or "").strip().lower()
        if not expected:
            return False
        advert = getattr(worker, "content_hashes", None) or {}
        if not isinstance(advert, dict):
            return False
        got = str(advert.get(node_type) or "").strip().lower()
        if got != expected:
            return False
    return True


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
            except Exception as exc:
                log.warning("JobQueue reset: clear previous queue failed: %s", exc)
        _QUEUE = JobQueue(
            store=store, load_persisted=False, lease_ttl_s=lease_ttl_s
        )
        return _QUEUE

# Public names. A leading underscore stays private to this module.
reset_job_queue = _reset_job_queue
