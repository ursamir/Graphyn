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
Public Surface:   All classes/functions above; mutate_queue / mutate_workers for
                  atomic RMW; state_version(kind) change token for caches.
Must NOT:         Import from app.domain, app.api, or orchestrator.
Dependencies:     stdlib (json, os, threading, pathlib, typing),
                  app.core.persist.file_lock,
                  app.core.config (project_dir, redis_url) — lazy.
Reason To Change: New store backends, key layout, atomic claim / CAS policy,
                  or change-token (state_version) semantics for read-through.
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

    @abstractmethod
    def mutate_workers(
        self, mutator: Callable[[dict[str, Any]], tuple[dict[str, Any], T]]
    ) -> T:
        """Atomically load → mutate → save the workers snapshot.

        ``mutator(workers)`` returns ``(new_workers, result)``. Same locking
        contract as ``mutate_queue`` (disk flock / Redis lock-or-WATCH /
        memory RLock). Prefer this over ``load_workers`` + ``save_workers``
        for any production read-modify-write on shared worker state.
        """
        ...

    def state_version(self, kind: str) -> Any:
        """Cheap change token for ``kind`` (``"queue"`` / ``"workers"``).

        Read-only callers (registry/queue caches) reload only when the token
        changed. ``None`` means "unknown — always read through" (Redis).
        """
        return None

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
            "paused_runs": [],
        }
        # One lock per state kind (F19): a single shared lock deadlocked the API
        # live — JobQueue held it (queue mutate) while its mutator asked the
        # WorkerRegistry, and a heartbeat held the registry lock while waiting
        # for it (workers mutate). Queue and workers never share a lock now, so
        # the only nesting order left is queue → registry → workers.
        self._kind_locks = {"queue": threading.RLock(), "workers": threading.RLock()}
        self._versions = {"queue": 0, "workers": 0}

    def _bump(self, kind: str) -> None:
        self._versions[kind] = self._versions.get(kind, 0) + 1

    def state_version(self, kind: str) -> Any:
        with self._kind_locks.get(kind, self._kind_locks["queue"]):
            return self._versions.get(kind, 0)

    @property
    def backend_id(self) -> str:
        return "memory"

    def load_workers(self) -> dict[str, Any]:
        with self._kind_locks["workers"]:
            return {k: dict(v) if isinstance(v, dict) else v for k, v in self._workers.items()}

    def save_workers(self, workers: dict[str, Any]) -> None:
        with self._kind_locks["workers"]:
            self._workers = {
                k: dict(v) if isinstance(v, dict) else v for k, v in (workers or {}).items()
            }
            self._bump("workers")

    def load_queue(self) -> dict[str, Any]:
        with self._kind_locks["queue"]:
            paused = self._queue.get("paused_runs")
            return {
                "jobs": dict(self._queue.get("jobs") or {}),
                "order": list(self._queue.get("order") or []),
                "results": dict(self._queue.get("results") or {}),
                "events": {
                    k: list(v) if isinstance(v, list) else v
                    for k, v in (self._queue.get("events") or {}).items()
                },
                "paused_runs": list(paused) if isinstance(paused, list) else [],
            }

    def save_queue(self, snapshot: dict[str, Any]) -> None:
        with self._kind_locks["queue"]:
            paused = snapshot.get("paused_runs")
            self._queue = {
                "jobs": dict(snapshot.get("jobs") or {}),
                "order": list(snapshot.get("order") or []),
                "results": dict(snapshot.get("results") or {}),
                "events": {
                    k: list(v) if isinstance(v, list) else v
                    for k, v in (snapshot.get("events") or {}).items()
                },
                "paused_runs": list(paused) if isinstance(paused, list) else [],
            }
            self._bump("queue")

    def mutate_queue(
        self, mutator: Callable[[dict[str, Any]], tuple[dict[str, Any], T]]
    ) -> T:
        with self._kind_locks["queue"]:
            paused = self._queue.get("paused_runs")
            snap = {
                "jobs": dict(self._queue.get("jobs") or {}),
                "order": list(self._queue.get("order") or []),
                "results": dict(self._queue.get("results") or {}),
                "events": {
                    k: list(v) if isinstance(v, list) else v
                    for k, v in (self._queue.get("events") or {}).items()
                },
                "paused_runs": list(paused) if isinstance(paused, list) else [],
            }
            new_snap, result = mutator(snap)
            new_paused = new_snap.get("paused_runs")
            self._queue = {
                "jobs": dict(new_snap.get("jobs") or {}),
                "order": list(new_snap.get("order") or []),
                "results": dict(new_snap.get("results") or {}),
                "events": {
                    k: list(v) if isinstance(v, list) else v
                    for k, v in (new_snap.get("events") or {}).items()
                },
                "paused_runs": list(new_paused) if isinstance(new_paused, list) else [],
            }
            self._bump("queue")
            return result

    def mutate_workers(
        self, mutator: Callable[[dict[str, Any]], tuple[dict[str, Any], T]]
    ) -> T:
        with self._kind_locks["workers"]:
            snap = {
                k: dict(v) if isinstance(v, dict) else v for k, v in self._workers.items()
            }
            new_snap, result = mutator(snap)
            self._workers = {
                k: dict(v) if isinstance(v, dict) else v
                for k, v in (new_snap or {}).items()
            }
            self._bump("workers")
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
    ``mutate_workers`` likewise locks ``workers.lock`` for worker registry RMW.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else None
        # One lock per state kind (F19): a single shared lock deadlocked the API
        # live — JobQueue held it (queue mutate) while its mutator asked the
        # WorkerRegistry, and a heartbeat held the registry lock while waiting
        # for it (workers mutate). Queue and workers never share a lock now, so
        # the only nesting order left is queue → registry → workers.
        self._kind_locks = {"queue": threading.RLock(), "workers": threading.RLock()}

    @property
    def backend_id(self) -> str:
        return "disk"

    def state_version(self, kind: str) -> Any:
        """``(inode, mtime_ns, size)`` of the state file — changes on every replace."""
        workers_path, jobs_path, _, _ = self._paths()
        path = jobs_path if kind == "queue" else workers_path
        try:
            st = path.stat()
        except FileNotFoundError:
            return ("missing",)
        except OSError:
            return None
        return (st.st_ino, st.st_mtime_ns, st.st_size)

    def _paths(self) -> tuple[Path, Path, Path, Path]:
        base = _distributed_dir(self._root)
        return (
            base / "workers.json",
            base / "jobs.json",
            base / "jobs.lock",
            base / "workers.lock",
        )

    def _empty_queue(self) -> dict[str, Any]:
        return {"jobs": {}, "order": [], "results": {}, "events": {}, "paused_runs": []}

    def _normalize_queue(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            return self._empty_queue()
        paused = data.get("paused_runs")
        return {
            "jobs": data.get("jobs") if isinstance(data.get("jobs"), dict) else {},
            "order": data.get("order") if isinstance(data.get("order"), list) else [],
            "results": data.get("results") if isinstance(data.get("results"), dict) else {},
            "events": data.get("events") if isinstance(data.get("events"), dict) else {},
            "paused_runs": [str(x) for x in paused if str(x).strip()]
            if isinstance(paused, list)
            else [],
        }

    def _read_json(
        self, path: Path, default: Any, *, fail_closed: bool = False
    ) -> Any:
        from app.core.persist.file_lock import LockUnavailable, acquire, release

        if not path.is_file():
            if fail_closed:
                raise FileNotFoundError(f"DiskStateStore: missing state file {path}")
            return default
        try:
            with open(path, "rb") as f:
                acquire(f, exclusive=False)
                try:
                    raw = f.read()
                    data = json.loads(raw.decode("utf-8")) if raw else None
                finally:
                    release(f)
            return data if data is not None else default
        except LockUnavailable:
            raise
        except FileNotFoundError:
            if fail_closed:
                raise
            return default
        except Exception as exc:
            if fail_closed:
                raise OSError(
                    f"DiskStateStore: unreadable state file {path}: {exc}"
                ) from exc
            log.warning("DiskStateStore: failed to read %s: %s", path, exc)
            return default

    def _write_json(self, path: Path, data: Any) -> None:
        """Atomic replace write with a unique temp file (no shared ``*.tmp``).

        Caller must hold the matching exclusive lock (``jobs.lock`` /
        ``workers.lock``) for durable RMW. Unique temps prevent concurrent
        writers from colliding on a shared ``workers.json.tmp`` path.
        """
        self._write_payload(path, self._serialize(data))

    @staticmethod
    def _serialize(data: Any) -> str:
        return json.dumps(data, indent=2, default=str, sort_keys=True)

    def _write_payload(self, path: Path, payload: str) -> None:
        import uuid

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / (
            f".{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
        )
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _with_lock_file(
        self, lock_path: Path, exclusive: bool, fn: Callable[[], T], kind: str = "queue"
    ) -> T:
        """Run ``fn`` while holding an advisory lock file (cross-process).

        Fails closed when the platform has no lock primitive.
        """
        from app.core.persist.file_lock import acquire, release

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        # threading lock serializes in-process; file lock covers cross-process.
        with self._kind_locks[kind]:
            with open(lock_path, "a+b") as lf:
                acquire(lf, exclusive=exclusive)
                try:
                    return fn()
                finally:
                    release(lf)

    def _with_jobs_lock(self, exclusive: bool, fn: Callable[[], T]) -> T:
        """Run ``fn`` while holding the queue lock file (cross-process)."""
        _, _, jobs_lock, _ = self._paths()
        return self._with_lock_file(jobs_lock, exclusive, fn, "queue")

    def _with_workers_lock(self, exclusive: bool, fn: Callable[[], T]) -> T:
        """Run ``fn`` while holding the workers lock file (cross-process)."""
        _, _, _, workers_lock = self._paths()
        return self._with_lock_file(workers_lock, exclusive, fn, "workers")

    def load_workers(self) -> dict[str, Any]:
        def _load() -> dict[str, Any]:
            workers_path, _, _, _ = self._paths()
            data = self._read_json(workers_path, {})
            return data if isinstance(data, dict) else {}

        return self._with_workers_lock(False, _load)

    def save_workers(self, workers: dict[str, Any]) -> None:
        """Blind full replace — prefer ``mutate_workers`` for production RMW."""

        def _save() -> None:
            workers_path, _, _, _ = self._paths()
            self._write_json(workers_path, workers or {})

        self._with_workers_lock(True, _save)

    def load_queue(self) -> dict[str, Any]:
        def _load() -> dict[str, Any]:
            _, jobs_path, _, _ = self._paths()
            return self._normalize_queue(
                self._read_json(jobs_path, self._empty_queue())
            )

        return self._with_jobs_lock(False, _load)

    def save_queue(self, snapshot: dict[str, Any]) -> None:
        def _save() -> None:
            _, jobs_path, _, _ = self._paths()
            self._write_json(
                jobs_path,
                {
                    "jobs": snapshot.get("jobs") or {},
                    "order": snapshot.get("order") or [],
                    "results": snapshot.get("results") or {},
                    "events": snapshot.get("events") or {},
                    "paused_runs": list(snapshot.get("paused_runs") or []),
                },
            )

        self._with_jobs_lock(True, _save)

    def _read_raw(self, path: Path) -> bytes | None:
        """Raw bytes of a state file (caller holds the matching lock)."""
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None

    def mutate_queue(
        self, mutator: Callable[[dict[str, Any]], tuple[dict[str, Any], T]]
    ) -> T:
        """Locked RMW; skips the rewrite + fsync when the snapshot is unchanged."""

        def _mutate() -> T:
            _, jobs_path, _, _ = self._paths()
            # Missing jobs.json is empty queue (first write). fail_closed only
            # when the file exists but is unreadable/corrupt.
            raw = self._read_raw(jobs_path)
            if raw:
                try:
                    data = json.loads(raw.decode("utf-8"))
                except Exception as exc:
                    raise OSError(
                        f"DiskStateStore: unreadable state file {jobs_path}: {exc}"
                    ) from exc
            else:
                data = None
            snap = self._normalize_queue(data if data is not None else self._empty_queue())
            new_snap, result = mutator(snap)
            payload = self._serialize(
                {
                    "jobs": new_snap.get("jobs") or {},
                    "order": new_snap.get("order") or [],
                    "results": new_snap.get("results") or {},
                    "events": new_snap.get("events") or {},
                    "paused_runs": list(new_snap.get("paused_runs") or []),
                }
            )
            if raw is not None and raw.decode("utf-8", errors="replace") == payload:
                return result  # unchanged — no rewrite / fsync
            self._write_payload(jobs_path, payload)
            return result

        return self._with_jobs_lock(True, _mutate)

    def mutate_workers(
        self, mutator: Callable[[dict[str, Any]], tuple[dict[str, Any], T]]
    ) -> T:
        def _mutate() -> T:
            workers_path, _, _, _ = self._paths()
            raw = self._read_raw(workers_path)
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception as exc:
                log.warning("DiskStateStore: failed to read %s: %s", workers_path, exc)
                data = {}
            snap = data if isinstance(data, dict) else {}
            new_snap, result = mutator(dict(snap))
            payload = self._serialize(new_snap or {})
            if raw is not None and raw.decode("utf-8", errors="replace") == payload:
                return result
            self._write_payload(workers_path, payload)
            return result

        return self._with_workers_lock(True, _mutate)


class RedisStateStore(DistributedStateStore):
    """JSON blobs in Redis (reuse GRAPHYN_REDIS_URL / run_control client pattern)."""

    WORKERS_KEY = "graphyn:distributed:workers"
    QUEUE_KEY = "graphyn:distributed:jobs"
    TTL_S = 7 * 24 * 3600  # 7 days safety net

    def __init__(self, client: Any | None = None) -> None:
        self._client = client
        # One lock per state kind (F19): a single shared lock deadlocked the API
        # live — JobQueue held it (queue mutate) while its mutator asked the
        # WorkerRegistry, and a heartbeat held the registry lock while waiting
        # for it (workers mutate). Queue and workers never share a lock now, so
        # the only nesting order left is queue → registry → workers.
        self._kind_locks = {"queue": threading.RLock(), "workers": threading.RLock()}

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
        """Blind full replace — prefer ``mutate_workers`` for production RMW."""
        client = self._redis()
        if client is None:
            return
        try:
            with self._kind_locks["workers"]:
                client.set(
                    self.WORKERS_KEY,
                    json.dumps(workers or {}, default=str),
                    ex=self.TTL_S,
                )
        except Exception as exc:
            log.warning("RedisStateStore.save_workers failed: %s", exc)

    def load_queue(self) -> dict[str, Any]:
        client = self._redis()
        empty = {"jobs": {}, "order": [], "results": {}, "events": {}, "paused_runs": []}
        if client is None:
            return empty
        try:
            raw = client.get(self.QUEUE_KEY)
            if not raw:
                return empty
            data = json.loads(raw)
            if not isinstance(data, dict):
                return empty
            paused = data.get("paused_runs")
            return {
                "jobs": data.get("jobs") if isinstance(data.get("jobs"), dict) else {},
                "order": data.get("order") if isinstance(data.get("order"), list) else [],
                "results": data.get("results") if isinstance(data.get("results"), dict) else {},
                "events": data.get("events") if isinstance(data.get("events"), dict) else {},
                "paused_runs": [str(x) for x in paused if str(x).strip()]
                if isinstance(paused, list)
                else [],
            }
        except Exception as exc:
            log.warning("RedisStateStore.load_queue failed: %s", exc)
            return empty

    def save_queue(self, snapshot: dict[str, Any]) -> None:
        client = self._redis()
        if client is None:
            return
        try:
            with self._kind_locks["queue"]:
                client.set(
                    self.QUEUE_KEY,
                    json.dumps(
                        {
                            "jobs": snapshot.get("jobs") or {},
                            "order": snapshot.get("order") or [],
                            "results": snapshot.get("results") or {},
                            "events": snapshot.get("events") or {},
                            "paused_runs": list(snapshot.get("paused_runs") or []),
                        },
                        default=str,
                    ),
                    ex=self.TTL_S,
                )
        except Exception as exc:
            log.warning("RedisStateStore.save_queue failed: %s", exc)

    def _normalize_queue(self, data: Any) -> dict[str, Any]:
        empty = {"jobs": {}, "order": [], "results": {}, "events": {}, "paused_runs": []}
        if not isinstance(data, dict):
            return empty
        paused = data.get("paused_runs")
        return {
            "jobs": data.get("jobs") if isinstance(data.get("jobs"), dict) else {},
            "order": data.get("order") if isinstance(data.get("order"), list) else [],
            "results": data.get("results") if isinstance(data.get("results"), dict) else {},
            "events": data.get("events") if isinstance(data.get("events"), dict) else {},
            "paused_runs": [str(x) for x in paused if str(x).strip()]
            if isinstance(paused, list)
            else [],
        }

    # Lock is only a fairness hint; correctness comes from WATCH/MULTI CAS, so a
    # lock that expires mid-mutate can no longer cause a lost update.
    LOCK_TIMEOUT_S = 30
    LOCK_BLOCKING_TIMEOUT_S = 10
    WATCH_RETRIES = 32

    @staticmethod
    def _encode_queue(snap: dict[str, Any]) -> str:
        return json.dumps(
            {
                "jobs": snap.get("jobs") or {},
                "order": snap.get("order") or [],
                "results": snap.get("results") or {},
                "events": snap.get("events") or {},
                "paused_runs": list(snap.get("paused_runs") or []),
            },
            default=str,
        )

    def _decode_queue(self, raw: Any) -> dict[str, Any]:
        return self._normalize_queue(json.loads(raw) if raw else None)

    @staticmethod
    def _decode_workers(raw: Any) -> dict[str, Any]:
        snap = json.loads(raw) if raw else {}
        return dict(snap) if isinstance(snap, dict) else {}

    def _cas_mutate(
        self,
        key: str,
        mutator: Callable[[dict[str, Any]], tuple[dict[str, Any], T]],
        *,
        decode: Callable[[Any], dict[str, Any]],
        encode: Callable[[dict[str, Any]], str],
    ) -> T:
        """Lock (fairness) + WATCH/MULTI (correctness) read-modify-write."""
        client = self._redis()
        lock = None
        acquired = False
        try:
            lock = client.lock(
                key + ":lock",
                timeout=self.LOCK_TIMEOUT_S,
                blocking_timeout=self.LOCK_BLOCKING_TIMEOUT_S,
            )
            acquired = bool(lock.acquire(blocking=True))
        except Exception as exc:
            log.warning(
                "RedisStateStore: lock acquire failed for %s (WATCH-only CAS): %s",
                key,
                exc,
            )
            lock = None
        try:
            with self._kind_locks["queue" if key == self.QUEUE_KEY else "workers"]:
                for _ in range(self.WATCH_RETRIES):
                    pipe = client.pipeline()
                    try:
                        pipe.watch(key)
                        raw = pipe.get(key)
                        snap = decode(raw)
                        new_snap, result = mutator(snap)
                        pipe.multi()
                        pipe.set(key, encode(new_snap), ex=self.TTL_S)
                        pipe.execute()
                        return result
                    except Exception as exc:
                        # redis.WatchError → another writer won; retry on fresh data.
                        if "Watch" in type(exc).__name__:
                            continue
                        log.warning("RedisStateStore: mutate %s failed: %s", key, exc)
                        raise
                    finally:
                        reset = getattr(pipe, "reset", None)
                        if callable(reset):
                            try:
                                reset()
                            except Exception:
                                pass
                raise RuntimeError(f"RedisStateStore: exceeded WATCH retries for {key}")
        finally:
            if lock is not None and acquired:
                try:
                    lock.release()
                except Exception as exc:
                    # Typically LockNotOwnedError: the lock expired during a long
                    # mutate. The write itself was CAS-protected by WATCH.
                    log.warning(
                        "RedisStateStore: lock release for %s failed "
                        "(expired mid-mutate? write was WATCH-protected): %s",
                        key,
                        exc,
                    )

    def mutate_queue(
        self, mutator: Callable[[dict[str, Any]], tuple[dict[str, Any], T]]
    ) -> T:
        """WATCH/MULTI CAS (lock only for fairness); preserves ``paused_runs``."""
        client = self._redis()
        if client is None:
            # No Redis: mutate in-memory empty snapshot (non-durable).
            with self._kind_locks["queue"]:
                _new_snap, result = mutator(self._normalize_queue(None))
                return result
        return self._cas_mutate(
            self.QUEUE_KEY,
            mutator,
            decode=self._decode_queue,
            encode=self._encode_queue,
        )

    def mutate_workers(
        self, mutator: Callable[[dict[str, Any]], tuple[dict[str, Any], T]]
    ) -> T:
        """WATCH/MULTI CAS (lock only for fairness)."""
        client = self._redis()
        if client is None:
            with self._kind_locks["workers"]:
                _new_snap, result = mutator({})
                return result
        return self._cas_mutate(
            self.WORKERS_KEY,
            mutator,
            decode=self._decode_workers,
            encode=lambda snap: json.dumps(snap or {}, default=str),
        )


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

# Public names. A leading underscore stays private to this module.
reset_distributed_store = _reset_distributed_store
