# app/core/distributed/store.py
"""
Bounded Context:  BC5 — Execution Runtime
Responsibility:   Persistence backends for worker registry + job queue so the
                  control plane survives API process restart / multi-uvicorn
                  better than pure in-memory. In-memory remains the fast path;
                  disk is the default durable store; Redis is used when
                  GRAPHYN_REDIS_URL (or GRAPHYN_DISTRIBUTED_STORE=redis) is set.
Owns:             DistributedStateStore protocol, MemoryStateStore,
                  DiskStateStore, RedisStateStore, get_distributed_store(),
                  _reset_distributed_store() (tests).
Public Surface:   All classes/functions above; mutate_queue for atomic RMW.
Must NOT:         Import from app.domain, app.api, or orchestrator.
Dependencies:     stdlib (json, os, threading, pathlib, fcntl, typing),
                  app.core.config (project_dir, redis_url) — lazy.
Reason To Change: New store backends, key layout, atomic claim / CAS policy.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

# Optional override: memory | disk | redis (empty → auto: redis if URL else disk).
_STORE_ENV = "GRAPHYN_DISTRIBUTED_STORE"


class DistributedStateStore(ABC):
    """Minimal snapshot store for workers + job queue."""

    @abstractmethod
    def load_workers(self) -> dict[str, Any]:
        """Return ``{worker_id: worker_dict, ...}``."""

    @abstractmethod
    def save_workers(self, workers: dict[str, Any]) -> None:
        ...

    @abstractmethod
    def load_queue(self) -> dict[str, Any]:
        """Return ``{jobs, order, results, events}`` dicts/lists."""

    @abstractmethod
    def save_queue(self, snapshot: dict[str, Any]) -> None:
        ...

    @abstractmethod
    def mutate_queue(
        self, mutator: Callable[[dict[str, Any]], tuple[dict[str, Any], T]]
    ) -> T:
        """Atomically load → mutate → save the queue snapshot.

        ``mutator(snapshot)`` returns ``(new_snapshot, result)``. The new
        snapshot is persisted under an exclusive cross-process lock (disk /
        Redis WATCH) or an in-process lock (memory). Returns ``result``.

        Used by ``JobQueue.claim`` so pending→claimed is CAS-safe across
        processes sharing the same durable store.
        """
        ...

    @property
    def backend_id(self) -> str:
        return type(self).__name__


class MemoryStateStore(DistributedStateStore):
    """Process-local only — no durability (tests / GRAPHYN_DISTRIBUTED_STORE=memory)."""

    def __init__(self) -> None:
        self._workers: dict[str, Any] = {}
        self._queue: dict[str, Any] = {
            "jobs": {},
            "order": [],
            "results": {},
            "events": {},
        }
        self._lock = threading.RLock()

    @property
    def backend_id(self) -> str:
        return "memory"

    def load_workers(self) -> dict[str, Any]:
        with self._lock:
            return {k: dict(v) if isinstance(v, dict) else v for k, v in self._workers.items()}

    def save_workers(self, workers: dict[str, Any]) -> None:
        with self._lock:
            self._workers = {
                k: dict(v) if isinstance(v, dict) else v for k, v in (workers or {}).items()
            }

    def load_queue(self) -> dict[str, Any]:
        with self._lock:
            return {
                "jobs": dict(self._queue.get("jobs") or {}),
                "order": list(self._queue.get("order") or []),
                "results": dict(self._queue.get("results") or {}),
                "events": {
                    k: list(v) if isinstance(v, list) else v
                    for k, v in (self._queue.get("events") or {}).items()
                },
            }

    def save_queue(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            self._queue = {
                "jobs": dict(snapshot.get("jobs") or {}),
                "order": list(snapshot.get("order") or []),
                "results": dict(snapshot.get("results") or {}),
                "events": {
                    k: list(v) if isinstance(v, list) else v
                    for k, v in (snapshot.get("events") or {}).items()
                },
            }

    def mutate_queue(
        self, mutator: Callable[[dict[str, Any]], tuple[dict[str, Any], T]]
    ) -> T:
        with self._lock:
            snap = {
                "jobs": dict(self._queue.get("jobs") or {}),
                "order": list(self._queue.get("order") or []),
                "results": dict(self._queue.get("results") or {}),
                "events": {
                    k: list(v) if isinstance(v, list) else v
                    for k, v in (self._queue.get("events") or {}).items()
                },
            }
            new_snap, result = mutator(snap)
            self._queue = {
                "jobs": dict(new_snap.get("jobs") or {}),
                "order": list(new_snap.get("order") or []),
                "results": dict(new_snap.get("results") or {}),
                "events": {
                    k: list(v) if isinstance(v, list) else v
                    for k, v in (new_snap.get("events") or {}).items()
                },
            }
            return result


def _distributed_dir(root: Path | None = None) -> Path:
    if root is not None:
        path = Path(root)
    else:
        from app.core.config import project_dir

        path = project_dir() / "distributed"
    path.mkdir(parents=True, exist_ok=True)
    return path


class DiskStateStore(DistributedStateStore):
    """JSON files under ``{project_dir}/distributed/`` with advisory file locks.

    ``mutate_queue`` holds an exclusive flock on ``jobs.lock`` for the full
    read-modify-write so pending→claimed is atomic across processes.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else None
        self._lock = threading.RLock()

    @property
    def backend_id(self) -> str:
        return "disk"

    def _paths(self) -> tuple[Path, Path, Path]:
        base = _distributed_dir(self._root)
        return base / "workers.json", base / "jobs.json", base / "jobs.lock"

    def _empty_queue(self) -> dict[str, Any]:
        return {"jobs": {}, "order": [], "results": {}, "events": {}}

    def _normalize_queue(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            return self._empty_queue()
        return {
            "jobs": data.get("jobs") if isinstance(data.get("jobs"), dict) else {},
            "order": data.get("order") if isinstance(data.get("order"), list) else [],
            "results": data.get("results") if isinstance(data.get("results"), dict) else {},
            "events": data.get("events") if isinstance(data.get("events"), dict) else {},
        }

    def _read_json(self, path: Path, default: Any) -> Any:
        try:
            import fcntl
        except ImportError:  # pragma: no cover — non-POSIX
            fcntl = None  # type: ignore[assignment]

        if not path.is_file():
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                if fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    data = json.load(f)
                finally:
                    if fcntl is not None:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            return data if data is not None else default
        except Exception as exc:
            log.warning("DiskStateStore: failed to read %s: %s", path, exc)
            return default

    def _write_json(self, path: Path, data: Any) -> None:
        """Atomic replace write. Caller must hold jobs.lock for queue files."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        payload = json.dumps(data, indent=2, default=str, sort_keys=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _with_jobs_lock(self, exclusive: bool, fn: Callable[[], T]) -> T:
        """Run ``fn`` while holding the queue lock file (cross-process)."""
        try:
            import fcntl
        except ImportError:  # pragma: no cover
            fcntl = None  # type: ignore[assignment]

        _, _, lock_path = self._paths()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        # threading lock serializes in-process; flock covers cross-process.
        with self._lock:
            with open(lock_path, "a+", encoding="utf-8") as lf:
                if fcntl is not None:
                    fcntl.flock(
                        lf.fileno(),
                        fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH,
                    )
                try:
                    return fn()
                finally:
                    if fcntl is not None:
                        fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    def load_workers(self) -> dict[str, Any]:
        workers_path, _, _ = self._paths()
        data = self._read_json(workers_path, {})
        return data if isinstance(data, dict) else {}

    def save_workers(self, workers: dict[str, Any]) -> None:
        workers_path, _, _ = self._paths()
        with self._lock:
            self._write_json(workers_path, workers or {})

    def load_queue(self) -> dict[str, Any]:
        def _load() -> dict[str, Any]:
            _, jobs_path, _ = self._paths()
            return self._normalize_queue(
                self._read_json(jobs_path, self._empty_queue())
            )

        return self._with_jobs_lock(False, _load)

    def save_queue(self, snapshot: dict[str, Any]) -> None:
        def _save() -> None:
            _, jobs_path, _ = self._paths()
            self._write_json(
                jobs_path,
                {
                    "jobs": snapshot.get("jobs") or {},
                    "order": snapshot.get("order") or [],
                    "results": snapshot.get("results") or {},
                    "events": snapshot.get("events") or {},
                },
            )

        self._with_jobs_lock(True, _save)

    def mutate_queue(
        self, mutator: Callable[[dict[str, Any]], tuple[dict[str, Any], T]]
    ) -> T:
        def _mutate() -> T:
            _, jobs_path, _ = self._paths()
            snap = self._normalize_queue(
                self._read_json(jobs_path, self._empty_queue())
            )
            new_snap, result = mutator(snap)
            self._write_json(
                jobs_path,
                {
                    "jobs": new_snap.get("jobs") or {},
                    "order": new_snap.get("order") or [],
                    "results": new_snap.get("results") or {},
                    "events": new_snap.get("events") or {},
                },
            )
            return result

        return self._with_jobs_lock(True, _mutate)


class RedisStateStore(DistributedStateStore):
    """JSON blobs in Redis (reuse GRAPHYN_REDIS_URL / run_control client pattern)."""

    WORKERS_KEY = "graphyn:distributed:workers"
    QUEUE_KEY = "graphyn:distributed:jobs"
    TTL_S = 7 * 24 * 3600  # 7 days safety net

    def __init__(self, client: Any | None = None) -> None:
        self._client = client
        self._lock = threading.RLock()

    @property
    def backend_id(self) -> str:
        return "redis"

    def _redis(self) -> Any | None:
        if self._client is not None:
            return self._client
        # Mirror run_control: optional redis-py + GRAPHYN_REDIS_URL.
        from app.core.config import redis_url as _redis_url

        url = _redis_url()
        if not url:
            return None
        try:
            import redis  # type: ignore[import]

            self._client = redis.Redis.from_url(
                url, decode_responses=True, socket_timeout=2.0
            )
            return self._client
        except Exception as exc:
            log.warning("RedisStateStore: cannot connect (%s); treat as empty", exc)
            return None

    def load_workers(self) -> dict[str, Any]:
        client = self._redis()
        if client is None:
            return {}
        try:
            raw = client.get(self.WORKERS_KEY)
            if not raw:
                return {}
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            log.warning("RedisStateStore.load_workers failed: %s", exc)
            return {}

    def save_workers(self, workers: dict[str, Any]) -> None:
        client = self._redis()
        if client is None:
            return
        try:
            with self._lock:
                client.set(
                    self.WORKERS_KEY,
                    json.dumps(workers or {}, default=str),
                    ex=self.TTL_S,
                )
        except Exception as exc:
            log.warning("RedisStateStore.save_workers failed: %s", exc)

    def load_queue(self) -> dict[str, Any]:
        client = self._redis()
        empty = {"jobs": {}, "order": [], "results": {}, "events": {}}
        if client is None:
            return empty
        try:
            raw = client.get(self.QUEUE_KEY)
            if not raw:
                return empty
            data = json.loads(raw)
            if not isinstance(data, dict):
                return empty
            return {
                "jobs": data.get("jobs") if isinstance(data.get("jobs"), dict) else {},
                "order": data.get("order") if isinstance(data.get("order"), list) else [],
                "results": data.get("results") if isinstance(data.get("results"), dict) else {},
                "events": data.get("events") if isinstance(data.get("events"), dict) else {},
            }
        except Exception as exc:
            log.warning("RedisStateStore.load_queue failed: %s", exc)
            return empty

    def save_queue(self, snapshot: dict[str, Any]) -> None:
        client = self._redis()
        if client is None:
            return
        try:
            with self._lock:
                client.set(
                    self.QUEUE_KEY,
                    json.dumps(
                        {
                            "jobs": snapshot.get("jobs") or {},
                            "order": snapshot.get("order") or [],
                            "results": snapshot.get("results") or {},
                            "events": snapshot.get("events") or {},
                        },
                        default=str,
                    ),
                    ex=self.TTL_S,
                )
        except Exception as exc:
            log.warning("RedisStateStore.save_queue failed: %s", exc)

    def _normalize_queue(self, data: Any) -> dict[str, Any]:
        empty = {"jobs": {}, "order": [], "results": {}, "events": {}}
        if not isinstance(data, dict):
            return empty
        return {
            "jobs": data.get("jobs") if isinstance(data.get("jobs"), dict) else {},
            "order": data.get("order") if isinstance(data.get("order"), list) else [],
            "results": data.get("results") if isinstance(data.get("results"), dict) else {},
            "events": data.get("events") if isinstance(data.get("events"), dict) else {},
        }

    def mutate_queue(
        self, mutator: Callable[[dict[str, Any]], tuple[dict[str, Any], T]]
    ) -> T:
        """Optimistic CAS via Redis WATCH/MULTI; falls back to process lock."""
        client = self._redis()
        empty = {"jobs": {}, "order": [], "results": {}, "events": {}}
        if client is None:
            # No Redis: mutate in-memory empty snapshot (non-durable).
            with self._lock:
                new_snap, result = mutator(dict(empty))
                return result

        # Prefer Redis lock for fairness across processes; WATCH as CAS backup.
        lock = None
        try:
            try:
                lock = client.lock(
                    self.QUEUE_KEY + ":lock",
                    timeout=10,
                    blocking_timeout=10,
                )
                acquired = lock.acquire(blocking=True)
            except Exception as exc:
                log.warning(
                    "RedisStateStore.mutate_queue: lock acquire failed "
                    "(falling back to WATCH): %s",
                    exc,
                )
                acquired = False
                lock = None

            with self._lock:
                if acquired:
                    try:
                        raw = client.get(self.QUEUE_KEY)
                        snap = self._normalize_queue(
                            json.loads(raw) if raw else empty
                        )
                        new_snap, result = mutator(snap)
                        client.set(
                            self.QUEUE_KEY,
                            json.dumps(
                                {
                                    "jobs": new_snap.get("jobs") or {},
                                    "order": new_snap.get("order") or [],
                                    "results": new_snap.get("results") or {},
                                    "events": new_snap.get("events") or {},
                                },
                                default=str,
                            ),
                            ex=self.TTL_S,
                        )
                        return result
                    finally:
                        try:
                            lock.release()
                        except Exception:
                            pass

                # WATCH/MULTI optimistic retry loop
                for _ in range(32):
                    try:
                        pipe = client.pipeline()
                        pipe.watch(self.QUEUE_KEY)
                        raw = pipe.get(self.QUEUE_KEY)
                        snap = self._normalize_queue(
                            json.loads(raw) if raw else empty
                        )
                        new_snap, result = mutator(snap)
                        pipe.multi()
                        pipe.set(
                            self.QUEUE_KEY,
                            json.dumps(
                                {
                                    "jobs": new_snap.get("jobs") or {},
                                    "order": new_snap.get("order") or [],
                                    "results": new_snap.get("results") or {},
                                    "events": new_snap.get("events") or {},
                                },
                                default=str,
                            ),
                            ex=self.TTL_S,
                        )
                        pipe.execute()
                        return result
                    except Exception as exc:
                        # redis.WatchError → retry; other errors abort.
                        if "Watch" in type(exc).__name__:
                            continue
                        log.warning("RedisStateStore.mutate_queue failed: %s", exc)
                        raise
                raise RuntimeError(
                    "RedisStateStore.mutate_queue: exceeded WATCH retries"
                )
        except Exception:
            if lock is not None:
                try:
                    lock.release()
                except Exception:
                    pass
            raise


_STORE: DistributedStateStore | None = None
_STORE_LOCK = threading.Lock()


def resolve_store_backend_id() -> str:
    """Return the store backend id that would be selected (without constructing)."""
    mode = (os.environ.get(_STORE_ENV) or "").strip().lower()
    if mode in ("memory", "mem", "inmemory"):
        return "memory"
    if mode == "disk":
        return "disk"
    if mode == "redis":
        return "redis"
    try:
        from app.core.config import redis_url as _redis_url

        if _redis_url():
            return "redis"
    except Exception:
        pass
    return "disk"


def get_distributed_store() -> DistributedStateStore:
    """Return the process-wide distributed state store (disk default, Redis if URL)."""
    global _STORE
    with _STORE_LOCK:
        if _STORE is not None:
            return _STORE
        backend = resolve_store_backend_id()
        if backend == "memory":
            _STORE = MemoryStateStore()
        elif backend == "redis":
            store = RedisStateStore()
            # Probe: if Redis is unusable, fall back to disk for durability.
            if store._redis() is None:
                log.warning(
                    "GRAPHYN_REDIS_URL set but Redis unavailable — "
                    "falling back to disk store for distributed state"
                )
                _STORE = DiskStateStore()
            else:
                _STORE = store
        else:
            _STORE = DiskStateStore()
        return _STORE


def _reset_distributed_store(
    store: DistributedStateStore | None = None,
) -> DistributedStateStore:
    """Test helper — replace the singleton store (default: fresh MemoryStateStore)."""
    global _STORE
    with _STORE_LOCK:
        _STORE = store if store is not None else MemoryStateStore()
        return _STORE
