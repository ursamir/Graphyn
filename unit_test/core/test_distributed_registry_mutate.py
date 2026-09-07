"""DIST-003: WorkerRegistry durable mutate_workers — no lost updates."""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import time
from pathlib import Path
from typing import Any

import pytest

from app.core.distributed.models import WorkerInfo, WorkerResources
from app.core.distributed.registry import WorkerRegistry
from app.core.distributed.store import (
    DiskStateStore,
    MemoryStateStore,
    RedisStateStore,
)


def _worker(wid: str, **kwargs) -> WorkerInfo:
    return WorkerInfo(
        worker_id=wid,
        labels=kwargs.pop("labels", [wid]),
        resources=kwargs.pop("resources", WorkerResources()),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Multiprocess helpers (must be top-level for spawn/fork pickling)
# ---------------------------------------------------------------------------


def _mp_register(root: str, wid: str, out_path: str, delay: float = 0.0) -> None:
    if delay:
        time.sleep(delay)
    store = DiskStateStore(root=Path(root))
    reg = WorkerRegistry(store=store, load_persisted=True)
    reg.register(_worker(wid))
    Path(out_path).write_text("ok", encoding="utf-8")


def _mp_heartbeat(root: str, wid: str, rounds: int, out_path: str) -> None:
    store = DiskStateStore(root=Path(root))
    reg = WorkerRegistry(store=store, load_persisted=True)
    for i in range(rounds):
        reg.heartbeat(wid, status="busy", active_jobs=i + 1)
    Path(out_path).write_text("ok", encoding="utf-8")


def _mp_remove(root: str, wid: str, out_path: str) -> None:
    store = DiskStateStore(root=Path(root))
    reg = WorkerRegistry(store=store, load_persisted=True)
    existed = reg.remove(wid)
    Path(out_path).write_text("1" if existed else "0", encoding="utf-8")


def _mp_register_loop(root: str, wid: str, rounds: int, out_path: str) -> None:
    store = DiskStateStore(root=Path(root))
    reg = WorkerRegistry(store=store, load_persisted=True)
    for _ in range(rounds):
        reg.register(_worker(wid))
    Path(out_path).write_text("ok", encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Two independent registries register different workers concurrently
# ---------------------------------------------------------------------------


def test_concurrent_register_two_registries_no_loss(tmp_path: Path):
    """DIST-003: two processes register distinct workers — both survive."""
    losses = 0
    trials = 24
    for i in range(trials):
        root = tmp_path / f"t{i}"
        root.mkdir()
        outs = [root / "a.txt", root / "b.txt"]
        procs = [
            mp.Process(target=_mp_register, args=(str(root), "w-a", str(outs[0]))),
            mp.Process(target=_mp_register, args=(str(root), "w-b", str(outs[1]))),
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=20)
            assert p.exitcode == 0, f"exit {p.exitcode}"
        workers = DiskStateStore(root=root).load_workers()
        if set(workers.keys()) != {"w-a", "w-b"}:
            losses += 1
    assert losses == 0, f"lost updates in {losses}/{trials} trials"


def test_concurrent_register_many_workers_no_loss(tmp_path: Path):
    n = 8
    outs = [tmp_path / f"out{i}.txt" for i in range(n)]
    procs = [
        mp.Process(
            target=_mp_register,
            args=(str(tmp_path), f"w{i}", str(outs[i])),
        )
        for i in range(n)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0
    workers = DiskStateStore(root=tmp_path).load_workers()
    assert set(workers.keys()) == {f"w{i}" for i in range(n)}


# ---------------------------------------------------------------------------
# 2. Concurrent heartbeats don’t erase other workers
# ---------------------------------------------------------------------------


def test_concurrent_heartbeats_preserve_other_workers(tmp_path: Path):
    store = DiskStateStore(root=tmp_path)
    seed = WorkerRegistry(store=store, load_persisted=False)
    seed.register(_worker("w-a"))
    seed.register(_worker("w-b"))

    outs = [tmp_path / "ha.txt", tmp_path / "hb.txt"]
    procs = [
        mp.Process(target=_mp_heartbeat, args=(str(tmp_path), "w-a", 20, str(outs[0]))),
        mp.Process(target=_mp_heartbeat, args=(str(tmp_path), "w-b", 20, str(outs[1]))),
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0

    workers = DiskStateStore(root=tmp_path).load_workers()
    assert set(workers.keys()) == {"w-a", "w-b"}
    assert workers["w-a"]["active_jobs"] == 20
    assert workers["w-b"]["active_jobs"] == 20
    assert workers["w-a"]["status"] == "busy"
    assert workers["w-b"]["status"] == "busy"


# ---------------------------------------------------------------------------
# 3. Concurrent remove/register preserves valid updates
# ---------------------------------------------------------------------------


def test_concurrent_remove_and_register_preserves_valid(tmp_path: Path):
    store = DiskStateStore(root=tmp_path)
    seed = WorkerRegistry(store=store, load_persisted=False)
    seed.register(_worker("doomed"))
    seed.register(_worker("keeper"))

    out_rm = tmp_path / "rm.txt"
    out_reg = tmp_path / "reg.txt"
    p_rm = mp.Process(target=_mp_remove, args=(str(tmp_path), "doomed", str(out_rm)))
    p_reg = mp.Process(
        target=_mp_register_loop, args=(str(tmp_path), "newbie", 15, str(out_reg))
    )
    p_rm.start()
    p_reg.start()
    p_rm.join(timeout=20)
    p_reg.join(timeout=20)
    assert p_rm.exitcode == 0 and p_reg.exitcode == 0
    assert out_rm.read_text(encoding="utf-8").strip() == "1"

    workers = DiskStateStore(root=tmp_path).load_workers()
    assert "doomed" not in workers
    assert "keeper" in workers
    assert "newbie" in workers


# ---------------------------------------------------------------------------
# 4. Disk writes cannot collide on shared temp filename
# ---------------------------------------------------------------------------


def test_disk_write_uses_unique_temp_filenames(tmp_path: Path, monkeypatch):
    """Concurrent writers must not share workers.json.tmp."""
    store = DiskStateStore(root=tmp_path)
    seen_tmps: list[Path] = []
    real_replace = os.replace

    def tracking_replace(src, dst, *args, **kwargs):
        src_p = Path(src)
        seen_tmps.append(src_p)
        assert src_p.name != "workers.json.tmp", "shared temp filename used"
        assert ".tmp." in src_p.name, f"expected unique temp, got {src_p.name}"
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", tracking_replace)

    # Verify single-process unique temps across sequential writes
    for i in range(3):
        store.mutate_workers(
            lambda w, i=i: (
                {**dict(w), f"s{i}": _worker(f"s{i}").model_dump(mode="json")},
                None,
            )
        )
    assert len(seen_tmps) == 3
    assert len({p.name for p in seen_tmps}) == 3

    # Multiprocess register should not raise "No such file" on shared tmp
    outs = [tmp_path / f"u{i}.txt" for i in range(6)]
    procs = [
        mp.Process(target=_mp_register, args=(str(tmp_path), f"u{i}", str(outs[i])))
        for i in range(6)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0
    workers = DiskStateStore(root=tmp_path).load_workers()
    for i in range(6):
        assert f"u{i}" in workers


def test_disk_mutate_workers_returns_mutator_result(tmp_path: Path):
    store = DiskStateStore(root=tmp_path)

    def mut(workers: dict[str, Any]):
        workers = dict(workers)
        workers["x"] = _worker("x").model_dump(mode="json")
        return workers, "ok"

    assert store.mutate_workers(mut) == "ok"
    assert "x" in store.load_workers()


# ---------------------------------------------------------------------------
# 5. Redis: fake/contract test for mutation algorithm
# ---------------------------------------------------------------------------


class _FakeWatchError(Exception):
    """Stand-in for redis.WatchError."""


class _FakePipeline:
    def __init__(self, client: "_FakeRedis"):
        self._client = client
        self._watching: str | None = None
        self._queued: list[tuple] = []
        self._watched_value: Any = None

    def watch(self, key: str) -> None:
        self._watching = key
        self._watched_value = self._client._data.get(key)

    def get(self, key: str) -> Any:
        return self._client._data.get(key)

    def multi(self) -> None:
        self._queued = []

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._queued.append(("set", key, value, ex))

    def execute(self) -> list:
        if self._watching is not None:
            current = self._client._data.get(self._watching)
            if current != self._watched_value:
                raise _FakeWatchError("watched key changed")
        results = []
        for op in self._queued:
            if op[0] == "set":
                _, key, value, ex = op
                self._client.set(key, value, ex=ex)
                results.append(True)
        self._watching = None
        self._queued = []
        return results


class _FakeLock:
    def __init__(self, client: "_FakeRedis", name: str):
        self._client = client
        self._name = name
        self._held = False

    def acquire(self, blocking: bool = True) -> bool:
        # Non-reentrant simple lock for contract tests.
        while True:
            if self._name not in self._client._locks:
                self._client._locks.add(self._name)
                self._held = True
                return True
            if not blocking:
                return False
            time.sleep(0.001)

    def release(self) -> None:
        if self._held:
            self._client._locks.discard(self._name)
            self._held = False


class _FakeRedis:
    """Minimal redis-like client for RedisStateStore.mutate_workers contract."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._locks: set[str] = set()

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._data[key] = value
        return True

    def lock(self, name: str, timeout: int = 10, blocking_timeout: int = 10) -> _FakeLock:
        return _FakeLock(self, name)

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)


def test_redis_mutate_workers_lock_path_merges():
    """Contract: mutate_workers under fake Redis lock merges workers (no loss)."""
    fake = _FakeRedis()
    store = RedisStateStore(client=fake)

    def add(wid: str):
        def mut(workers: dict[str, Any]):
            workers = dict(workers)
            workers[wid] = _worker(wid).model_dump(mode="json")
            return workers, wid

        return store.mutate_workers(mut)

    assert add("r1") == "r1"
    assert add("r2") == "r2"
    loaded = store.load_workers()
    assert set(loaded.keys()) == {"r1", "r2"}


def test_redis_mutate_workers_watch_fallback_on_lock_failure(monkeypatch):
    """Contract: when lock acquire fails, WATCH/MULTI path still merges."""
    fake = _FakeRedis()

    def boom_lock(name, timeout=10, blocking_timeout=10):
        raise RuntimeError("lock unavailable")

    fake.lock = boom_lock  # type: ignore[method-assign]
    store = RedisStateStore(client=fake)

    # Patch WatchError detection: our fake raises _FakeWatchError with "Watch" in name
    def mut_a(workers: dict[str, Any]):
        workers = dict(workers)
        workers["a"] = _worker("a").model_dump(mode="json")
        return workers, "a"

    assert store.mutate_workers(mut_a) == "a"
    assert "a" in store.load_workers()

    def mut_b(workers: dict[str, Any]):
        workers = dict(workers)
        workers["b"] = _worker("b").model_dump(mode="json")
        return workers, "b"

    assert store.mutate_workers(mut_b) == "b"
    assert set(store.load_workers().keys()) == {"a", "b"}


def test_redis_mutate_workers_watch_retries_on_conflict():
    """Contract: WATCH conflict retries until mutation commits."""
    fake = _FakeRedis()
    store = RedisStateStore(client=fake)

    # Seed via lock path first
    store.mutate_workers(
        lambda w: ({**dict(w), "seed": _worker("seed").model_dump(mode="json")}, None)
    )

    # Force lock failure → WATCH path
    def boom_lock(name, timeout=10, blocking_timeout=10):
        raise RuntimeError("lock unavailable")

    fake.lock = boom_lock  # type: ignore[method-assign]

    calls = {"n": 0}
    orig_pipeline = fake.pipeline

    def flaky_pipeline():
        pipe = orig_pipeline()
        orig_execute = pipe.execute

        def execute_flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                # Simulate concurrent writer changing the key mid-watch
                fake._data[RedisStateStore.WORKERS_KEY] = json.dumps(
                    {"seed": _worker("seed").model_dump(mode="json"), "intruder": True}
                )
                raise _FakeWatchError("watched key changed")
            return orig_execute()

        pipe.execute = execute_flaky  # type: ignore[method-assign]
        return pipe

    fake.pipeline = flaky_pipeline  # type: ignore[method-assign]

    def mut(workers: dict[str, Any]):
        workers = dict(workers)
        workers["final"] = _worker("final").model_dump(mode="json")
        return workers, "done"

    assert store.mutate_workers(mut) == "done"
    assert calls["n"] >= 2
    loaded = store.load_workers()
    assert "final" in loaded
    # After retry, mutation applied on top of whatever was watched on success path
    assert "seed" in loaded


def test_memory_mutate_workers_two_registries():
    store = MemoryStateStore()
    a = WorkerRegistry(store=store, load_persisted=False)
    b = WorkerRegistry(store=store, load_persisted=True)
    a.register(_worker("ma"))
    b.register(_worker("mb"))
    # Shared memory store — both workers present after RMW merges
    assert set(store.load_workers().keys()) == {"ma", "mb"}


# Live Redis integration is pending (no Redis in CI). Contract coverage above
# exercises lock + WATCH/MULTI algorithms via _FakeRedis.
