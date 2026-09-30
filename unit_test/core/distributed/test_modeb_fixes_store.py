"""Mode B fixes — state stores: Redis paused_runs + CAS, disk no-op writes,
change tokens."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from app.core.distributed.models import NodeJob
from app.core.distributed.queue import JobQueue
from app.core.distributed.store import DiskStateStore, MemoryStateStore, RedisStateStore


class _WatchError(Exception):
    """Stand-in for redis.WatchError (type name contains 'Watch')."""


class _Pipe:
    def __init__(self, client: "_FakeRedis") -> None:
        self._c = client
        self._watched: Any = None
        self._key: str | None = None
        self._ops: list = []

    def watch(self, key: str) -> None:
        self._key = key
        self._watched = self._c.data.get(key)

    def get(self, key: str) -> Any:
        return self._c.data.get(key)

    def multi(self) -> None:
        self._ops = []

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._ops.append((key, value))

    def execute(self) -> list:
        if self._key is not None and self._c.data.get(self._key) != self._watched:
            raise _WatchError("changed")
        for key, value in self._ops:
            self._c.data[key] = value
        self._c.sets += len(self._ops)
        return [True] * len(self._ops)


class _Lock:
    def __init__(self, client: "_FakeRedis") -> None:
        self._c = client

    def acquire(self, blocking: bool = True) -> bool:
        return True

    def release(self) -> None:
        if self._c.fail_release:
            raise RuntimeError("LockNotOwnedError: lock expired")


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.sets = 0
        self.fail_release = False

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.data[key] = value
        return True

    def lock(self, name: str, timeout: int = 10, blocking_timeout: int = 10) -> _Lock:
        return _Lock(self)

    def pipeline(self) -> _Pipe:
        return _Pipe(self)


# ── 6. Redis keeps paused_runs → pause works on Redis ───────────────────────


def test_redis_mutate_queue_preserves_paused_runs():
    fake = _FakeRedis()
    store = RedisStateStore(client=fake)
    q = JobQueue(store=store, load_persisted=False)
    q.set_run_paused("run-p", True)
    assert json.loads(fake.data[RedisStateStore.QUEUE_KEY])["paused_runs"] == ["run-p"]
    assert q.is_run_paused("run-p") is True
    # Unrelated mutation must not drop the pause.
    q.enqueue(NodeJob(job_id="j", run_id="run-p", node_id="n", node_type="x"))
    assert q.is_run_paused("run-p") is True
    from app.core.distributed.models import WorkerInfo

    assert q.claim(WorkerInfo(worker_id="w")) is None  # held while paused
    q.set_run_paused("run-p", False)
    assert q.claim(WorkerInfo(worker_id="w")) is not None


# ── 7. lock expiry cannot lose updates (WATCH/MULTI always) ─────────────────


def test_redis_concurrent_writer_during_locked_mutate_is_not_lost(caplog):
    fake = _FakeRedis()
    store = RedisStateStore(client=fake)
    store.mutate_queue(lambda s: ({**s, "order": ["seed"]}, None))
    calls = {"n": 0}

    def slow_mutator(snap: dict[str, Any]):
        calls["n"] += 1
        if calls["n"] == 1:
            # Our lock "expired"; another process wrote meanwhile.
            other = dict(snap)
            other["order"] = list(snap["order"]) + ["intruder"]
            fake.data[RedisStateStore.QUEUE_KEY] = json.dumps(other)
        return {**snap, "order": list(snap["order"]) + ["mine"]}, "ok"

    fake.fail_release = True
    with caplog.at_level("WARNING"):
        assert store.mutate_queue(slow_mutator) == "ok"
    order = json.loads(fake.data[RedisStateStore.QUEUE_KEY])["order"]
    assert order == ["seed", "intruder", "mine"]
    assert calls["n"] == 2
    assert "lock release" in caplog.text  # release failure is logged, not swallowed


def test_redis_mutate_workers_cas_on_lock_path():
    fake = _FakeRedis()
    store = RedisStateStore(client=fake)
    store.mutate_workers(lambda w: ({**w, "a": {"worker_id": "a"}}, None))

    def mut(w):
        if "b" not in fake.data.get(RedisStateStore.WORKERS_KEY, ""):
            fake.data[RedisStateStore.WORKERS_KEY] = json.dumps({**w, "b": {"worker_id": "b"}})
        return {**w, "c": {"worker_id": "c"}}, None

    store.mutate_workers(mut)
    assert set(store.load_workers()) == {"a", "b", "c"}


# ── 8. Disk store skips rewrite/fsync when unchanged ────────────────────────


def test_disk_mutate_queue_skips_write_when_unchanged(tmp_path: Path, monkeypatch):
    store = DiskStateStore(tmp_path)
    store.mutate_queue(lambda s: ({**s, "order": ["a"]}, None))
    jobs_path = tmp_path / "jobs.json"
    before = store.state_version("queue")
    writes = {"n": 0}
    real = store._write_payload

    def counting(path, payload):
        writes["n"] += 1
        return real(path, payload)

    monkeypatch.setattr(store, "_write_payload", counting)
    time.sleep(0.01)
    assert store.mutate_queue(lambda s: (s, "same")) == "same"
    assert writes["n"] == 0
    assert store.state_version("queue") == before
    store.mutate_queue(lambda s: ({**s, "order": ["b"]}, None))
    assert writes["n"] == 1
    assert store.state_version("queue") != before
    assert json.loads(jobs_path.read_text())["order"] == ["b"]


def test_disk_mutate_workers_skips_write_when_unchanged(tmp_path: Path, monkeypatch):
    store = DiskStateStore(tmp_path)
    store.mutate_workers(lambda w: ({"w": {"worker_id": "w"}}, None))
    writes = {"n": 0}
    real = store._write_payload
    monkeypatch.setattr(
        store, "_write_payload", lambda p, d: (writes.__setitem__("n", writes["n"] + 1), real(p, d))
    )
    store.mutate_workers(lambda w: (w, None))
    assert writes["n"] == 0


def test_memory_store_version_bumps_on_mutation():
    store = MemoryStateStore()
    v0 = store.state_version("queue")
    store.mutate_queue(lambda s: (s, None))
    assert store.state_version("queue") != v0
    w0 = store.state_version("workers")
    store.mutate_workers(lambda w: (w, None))
    assert store.state_version("workers") != w0


def test_disk_corrupt_queue_still_fails_closed(tmp_path: Path):
    store = DiskStateStore(tmp_path)
    (tmp_path / "jobs.json").write_text("{not json")
    import pytest

    with pytest.raises(OSError):
        store.mutate_queue(lambda s: (s, None))
    assert os.path.exists(tmp_path / "jobs.json")
