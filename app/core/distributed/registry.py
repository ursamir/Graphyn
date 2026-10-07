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
Reason To Change: Persistence backend added (Redis/disk), TTL policy changes, or
                  cache read-through (state_version) / status validation rules.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, get_args

from app.core.distributed.models import WorkerInfo, WorkerResources, WorkerStatus

if TYPE_CHECKING:
    from app.core.distributed.store import DistributedStateStore

log = logging.getLogger(__name__)

# Default stale threshold (~3 missed 15s heartbeats).
DEFAULT_STALE_AFTER_S = 45.0
_VALID_STATUSES = frozenset(get_args(WorkerStatus))


def _validate_status(status: str | None) -> str | None:
    if status is None:
        return None
    if status not in _VALID_STATUSES:
        raise ValueError(
            f"invalid worker status {status!r}; expected one of {sorted(_VALID_STATUSES)}"
        )
    return status


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
        self._seen_version: Any = None
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

    def _reload_unlocked(self) -> None:
        assert self._store is not None
        try:
            token = self._store.state_version("workers")
        except Exception:
            token = None
        self._apply_workers_snapshot_unlocked(self._store.load_workers())
        self._seen_version = token

    def _refresh_if_stale_unlocked(self) -> None:
        """Read-through for get/list: reload when the store's version changed.

        Another API process (multi-uvicorn) may have registered/heartbeated a
        worker; serving only this process's cache would report it missing or
        stale. Redis (version ``None``) is always read-through.
        """
        if self._store is None:
            return
        try:
            token = self._store.state_version("workers")
        except Exception:
            token = None
        if token is not None and token == self._seen_version:
            return
        try:
            self._reload_unlocked()
        except Exception as exc:
            log.warning("WorkerRegistry: read-through refresh failed: %s", exc)

    def _durable_mutate_workers(self, mutator):
        """Apply ``mutator(workers) -> (new_workers, result)`` under store lock; refresh."""
        assert self._store is not None
        result = self._store.mutate_workers(mutator)
        try:
            self._reload_unlocked()
        except Exception as exc:
            log.warning("WorkerRegistry: durable refresh failed: %s", exc)
        return result

    def register(self, info: WorkerInfo) -> WorkerInfo:
        """Register or refresh a worker. Updates ``heartbeat_at`` to now.

        Control-side ACL fields (``allowed_plugins``, ``plugin_hashes``,
        ``trusted``) are preserved from an existing record when the incoming
        payload leaves them unset / default — so a worker re-register cannot
        clear an admin pin. Explicit non-default values in the payload win
        (admin register / PATCH path).
        """
        with self._lock:
            def _merge(existing: WorkerInfo | None, incoming: WorkerInfo) -> WorkerInfo:
                updates: dict[str, Any] = {"heartbeat_at": _utcnow()}
                if existing is not None:
                    # Preserve admin ACL when worker omits them (None / default trusted).
                    if incoming.allowed_plugins is None and existing.allowed_plugins is not None:
                        updates["allowed_plugins"] = existing.allowed_plugins
                    if incoming.plugin_hashes is None and existing.plugin_hashes is not None:
                        updates["plugin_hashes"] = existing.plugin_hashes
                    # trusted default True — only preserve False when incoming is still True
                    # and existing was explicitly False (worker cannot self-trust).
                    if incoming.trusted is True and existing.trusted is False:
                        updates["trusted"] = False
                    # Preserve admin quota + usage counters across worker re-register.
                    if incoming.max_claimed is None and existing.max_claimed is not None:
                        updates["max_claimed"] = existing.max_claimed
                    for usage_f in (
                        "usage_claims",
                        "usage_completes",
                        "usage_bytes_in",
                        "usage_bytes_out",
                    ):
                        inc_v = getattr(incoming, usage_f, 0) or 0
                        prev_v = getattr(existing, usage_f, 0) or 0
                        if inc_v == 0 and prev_v:
                            updates[usage_f] = prev_v
                return incoming.model_copy(update=updates)

            if self._store is not None:
                def mut(workers: dict[str, Any]):
                    workers = dict(workers or {})
                    prev = None
                    raw = workers.get(info.worker_id)
                    if raw is not None:
                        try:
                            prev = WorkerInfo.model_validate(raw)
                        except Exception:
                            prev = None
                    updated = _merge(prev, info)
                    workers[updated.worker_id] = updated.model_dump(mode="json")
                    return workers, updated

                return self._durable_mutate_workers(mut)

            prev = self._workers.get(info.worker_id)
            updated = _merge(prev, info)
            self._workers[updated.worker_id] = updated
            return updated

    def patch(self, worker_id: str, **fields: Any) -> WorkerInfo:
        """Update durable control fields on a registered worker.

        Allowed keys: ``allowed_plugins``, ``plugin_hashes``, ``trusted``,
        ``labels``, ``pools``, ``node_types``. Raises ``KeyError`` if missing,
        ``ValueError`` for unknown keys.
        """
        allowed = {
            "allowed_plugins",
            "plugin_hashes",
            "trusted",
            "labels",
            "pools",
            "node_types",
            "content_hashes",
            "max_claimed",
            "usage_claims",
            "usage_completes",
            "usage_bytes_in",
            "usage_bytes_out",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unsupported patch fields: {sorted(unknown)}")
        with self._lock:
            if self._store is not None:
                def mut(workers: dict[str, Any]):
                    workers = dict(workers or {})
                    payload = workers.get(worker_id)
                    if payload is None:
                        raise KeyError(worker_id)
                    existing = WorkerInfo.model_validate(payload)
                    updated = existing.model_copy(update=fields)
                    workers[worker_id] = updated.model_dump(mode="json")
                    return workers, updated

                return self._durable_mutate_workers(mut)

            existing = self._workers.get(worker_id)
            if existing is None:
                raise KeyError(worker_id)
            updated = existing.model_copy(update=fields)
            self._workers[worker_id] = updated
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
            ValueError: if ``status`` is not a valid ``WorkerStatus``.
        """
        status = _validate_status(status)
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
            self._refresh_if_stale_unlocked()
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
            self._refresh_if_stale_unlocked()
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



def known_remote_node_types(*, include_stale: bool = False) -> set[str]:
    """Union of worker-advertised plugin / node_type names (control catalog).

    Used by validation when ``GRAPHYN_BACKEND=distributed`` so remote-only
    types advertised by workers can pass VAL-UNK-TYPE without being installed
    on the control plane. Returns type *names only* — never code.
    """
    names: set[str] = set()
    try:
        reg = get_worker_registry()
        workers = reg.list(include_stale=include_stale)
    except Exception as exc:
        log.warning("known_remote_node_types: registry unavailable: %s", exc)
        return names
    for w in workers:
        for p in list(getattr(w, "plugins", None) or []):
            s = str(p or "").strip()
            if s:
                names.add(s)
        for p in list(getattr(w, "node_types", None) or []):
            s = str(p or "").strip()
            if s:
                names.add(s)
    return names



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

# Public names. A leading underscore stays private to this module.
reset_worker_registry = _reset_worker_registry
