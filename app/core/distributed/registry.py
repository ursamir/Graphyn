# app/core/distributed/registry.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Thread-safe worker registry with heartbeat tracking, stale
                  detection, and optional durable store (disk/Redis).
Owns:             WorkerRegistry (register, heartbeat, list, get, remove,
                  mark_stale).
Public Surface:   WorkerRegistry, get_worker_registry(),
                  _reset_worker_registry() (tests).
Must NOT:         Import from app.domain, app.api, or orchestrator.
Dependencies:     stdlib (threading, datetime), app.core.distributed.models,
                  app.core.distributed.store (lazy via get_distributed_store;
                  mutate_workers for cross-process-safe RMW).
Reason To Change: Persistence backend added (Redis/disk), or TTL policy changes.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.core.distributed.models import WorkerInfo, WorkerResources

if TYPE_CHECKING:
    from app.core.distributed.store import DistributedStateStore

log = logging.getLogger(__name__)

# Default stale threshold (~3 missed 15s heartbeats).
DEFAULT_STALE_AFTER_S = 45.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkerRegistry:
    """Worker registry with in-memory fast path + optional durable store (P2)."""

    def __init__(
        self,
        *,
        stale_after_s: float = DEFAULT_STALE_AFTER_S,
        store: "DistributedStateStore | None" = None,
        load_persisted: bool = True,
    ) -> None:
        self._stale_after_s = float(stale_after_s)
        self._lock = threading.RLock()
        self._workers: dict[str, WorkerInfo] = {}
        self._store = store
        if load_persisted and store is not None:
            self._hydrate_from_store()

    def _hydrate_from_store(self) -> None:
        if self._store is None:
            return
        try:
            raw = self._store.load_workers()
        except Exception as exc:
            log.warning("WorkerRegistry: failed to load workers: %s", exc)
            return
        loaded = 0
        for wid, payload in (raw or {}).items():
            try:
                info = WorkerInfo.model_validate(payload)
                self._workers[info.worker_id] = info
                loaded += 1
            except Exception as exc:
                log.warning("WorkerRegistry: skip corrupt worker %r: %s", wid, exc)
        if loaded:
            log.debug("WorkerRegistry: hydrated %s worker(s) from %s", loaded, self._store.backend_id)

    def _apply_workers_snapshot_unlocked(self, raw: dict[str, Any] | None) -> None:
        """Replace local cache from a durable workers snapshot."""
        refreshed: dict[str, WorkerInfo] = {}
        for wid, payload in (raw or {}).items():
            try:
                info = WorkerInfo.model_validate(payload)
                refreshed[info.worker_id] = info
            except Exception as exc:
                log.warning("WorkerRegistry: skip corrupt worker %r: %s", wid, exc)
        self._workers = refreshed

    def _persist_unlocked(self) -> None:
        """Blind full-snapshot persist (in-memory / legacy only).

        Prefer ``_durable_mutate_workers`` for cross-process safety (DIST-003):
        blind replace from a stale local cache can lose concurrent updates.
        """
        if self._store is None:
            return
        try:
            snapshot = {
                wid: w.model_dump(mode="json") for wid, w in self._workers.items()
            }
            # Route through mutate so disk/Redis hold the exclusive lock for the write.
            self._store.mutate_workers(lambda _snap: (snapshot, None))
        except Exception as exc:
            log.warning("WorkerRegistry: persist failed: %s", exc)

    def _durable_mutate_workers(self, mutator):
        """Apply ``mutator(workers) -> (new_workers, result)`` under store lock; refresh."""
        assert self._store is not None
        result = self._store.mutate_workers(mutator)
        try:
            self._apply_workers_snapshot_unlocked(self._store.load_workers())
        except Exception as exc:
            log.warning("WorkerRegistry: durable refresh failed: %s", exc)
        return result

    def register(self, info: WorkerInfo) -> WorkerInfo:
        """Register or refresh a worker. Updates ``heartbeat_at`` to now."""
        with self._lock:
            if self._store is not None:
                updated = info.model_copy(update={"heartbeat_at": _utcnow()})

                def mut(workers: dict[str, Any]):
                    workers = dict(workers or {})
                    workers[updated.worker_id] = updated.model_dump(mode="json")
                    return workers, updated

                return self._durable_mutate_workers(mut)

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
            if self._store is not None:
                def mut(workers: dict[str, Any]):
                    workers = dict(workers or {})
                    payload = workers.get(worker_id)
                    if payload is None:
                        raise KeyError(worker_id)
                    existing = WorkerInfo.model_validate(payload)
                    updates: dict[str, Any] = {"heartbeat_at": _utcnow()}
                    res = resources
                    if res is not None:
                        if isinstance(res, dict):
                            res = WorkerResources.model_validate(res)
                        updates["resources"] = res
                    if status is not None:
                        updates["status"] = status
                    if active_jobs is not None:
                        updates["active_jobs"] = active_jobs
                    updated = existing.model_copy(update=updates)
                    workers[worker_id] = updated.model_dump(mode="json")
                    return workers, updated

                return self._durable_mutate_workers(mut)

            existing = self._workers.get(worker_id)
            if existing is None:
                raise KeyError(worker_id)
            updates: dict[str, Any] = {"heartbeat_at": _utcnow()}
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
            if self._store is not None:
                def mut(workers: dict[str, Any]):
                    workers = dict(workers or {})
                    existed = workers.pop(worker_id, None) is not None
                    return workers, existed

                return bool(self._durable_mutate_workers(mut))

            existed = self._workers.pop(worker_id, None) is not None
            return existed

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
            if self._store is not None:
                def mut(_workers: dict[str, Any]):
                    return {}, None

                self._durable_mutate_workers(mut)
                return
            self._workers.clear()


_REGISTRY: WorkerRegistry | None = None
_REGISTRY_LOCK = threading.Lock()


def get_worker_registry() -> WorkerRegistry:
    """Return the process-wide singleton worker registry (durable by default)."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            from app.core.distributed.store import get_distributed_store

            _REGISTRY = WorkerRegistry(store=get_distributed_store())
        return _REGISTRY


def _reset_worker_registry(
    *,
    store: "DistributedStateStore | None" = None,
    use_memory: bool = True,
) -> WorkerRegistry:
    """Test helper — clear the singleton registry (memory store by default)."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        if use_memory and store is None:
            from app.core.distributed.store import MemoryStateStore

            store = MemoryStateStore()
        elif store is None:
            from app.core.distributed.store import get_distributed_store

            store = get_distributed_store()
        if _REGISTRY is not None:
            try:
                _REGISTRY.clear()
            except Exception:
                pass
        _REGISTRY = WorkerRegistry(store=store, load_persisted=False)
        return _REGISTRY
