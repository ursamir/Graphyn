# app/core/distributed/registry.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Thread-safe in-memory registry of distributed workers with
                  heartbeat tracking and stale detection.
Owns:             WorkerRegistry (register, heartbeat, list, get, remove,
                  mark_stale).
Public Surface:   WorkerRegistry, get_worker_registry(),
                  _reset_worker_registry() (tests).
Must NOT:         Import from app.domain, app.api, or orchestrator.
Dependencies:     stdlib (threading, datetime), app.core.distributed.models.
Reason To Change: Persistence backend added (Redis/disk), or TTL policy changes.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Iterable

from app.core.distributed.models import WorkerInfo, WorkerResources

# Default stale threshold (~3 missed 15s heartbeats).
DEFAULT_STALE_AFTER_S = 45.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkerRegistry:
    """Process-local worker registry (P0)."""

    def __init__(self, *, stale_after_s: float = DEFAULT_STALE_AFTER_S) -> None:
        self._stale_after_s = float(stale_after_s)
        self._lock = threading.RLock()
        self._workers: dict[str, WorkerInfo] = {}

    def register(self, info: WorkerInfo) -> WorkerInfo:
        """Register or refresh a worker. Updates ``heartbeat_at`` to now."""
        with self._lock:
            updated = info.model_copy(update={"heartbeat_at": _utcnow()})
            self._workers[updated.worker_id] = updated
            return updated

    def heartbeat(
        self,
        worker_id: str,
        *,
        resources: WorkerResources | dict | None = None,
        status: str | None = None,
        active_jobs: int | None = None,
    ) -> WorkerInfo:
        """Refresh heartbeat (+ optional resource / status snapshot).

        Raises:
            KeyError: if ``worker_id`` is not registered.
        """
        with self._lock:
            existing = self._workers.get(worker_id)
            if existing is None:
                raise KeyError(worker_id)
            updates: dict = {"heartbeat_at": _utcnow()}
            if resources is not None:
                if isinstance(resources, dict):
                    resources = WorkerResources.model_validate(resources)
                updates["resources"] = resources
            if status is not None:
                updates["status"] = status
            if active_jobs is not None:
                updates["active_jobs"] = active_jobs
            updated = existing.model_copy(update=updates)
            self._workers[worker_id] = updated
            return updated

    def get(self, worker_id: str) -> WorkerInfo | None:
        with self._lock:
            return self._workers.get(worker_id)

    def remove(self, worker_id: str) -> bool:
        """Deregister a worker. Returns True if it existed."""
        with self._lock:
            return self._workers.pop(worker_id, None) is not None

    def list(
        self,
        *,
        include_stale: bool = False,
        now: datetime | None = None,
    ) -> list[WorkerInfo]:
        """Return registered workers (optionally excluding stale ones)."""
        with self._lock:
            workers = list(self._workers.values())
        if include_stale:
            return workers
        return [w for w in workers if not self.is_stale(w, now=now)]

    def is_stale(
        self,
        worker: WorkerInfo | str,
        *,
        now: datetime | None = None,
    ) -> bool:
        """True if the worker's last heartbeat is older than the stale TTL."""
        if isinstance(worker, str):
            info = self.get(worker)
            if info is None:
                return True
            worker = info
        now = now or _utcnow()
        hb = worker.heartbeat_at
        if hb.tzinfo is None:
            hb = hb.replace(tzinfo=timezone.utc)
        age = (now - hb).total_seconds()
        return age > self._stale_after_s

    def alive_workers(self, *, now: datetime | None = None) -> list[WorkerInfo]:
        """Non-stale workers suitable for scheduling."""
        return self.list(include_stale=False, now=now)

    def clear(self) -> None:
        with self._lock:
            self._workers.clear()


_REGISTRY: WorkerRegistry | None = None
_REGISTRY_LOCK = threading.Lock()


def get_worker_registry() -> WorkerRegistry:
    """Return the process-wide singleton worker registry."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = WorkerRegistry()
        return _REGISTRY


def _reset_worker_registry() -> None:
    """Test helper — clear the singleton registry."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is not None:
            _REGISTRY.clear()
        _REGISTRY = WorkerRegistry()
