# unit_test/f19/test_f19_store_lock_order.py
"""F19 (found live, Mode B): the API deadlocked while a remote job was queued.

``JobQueue`` mutators run under the state store's lock and consult the
``WorkerRegistry`` (stale workers / queue reasons); a worker heartbeat holds the
registry lock while it waits for the store's lock to write workers. With ONE store
lock for both kinds that is a lock-order inversion: every sync endpoint and the
worker's claim/heartbeat calls hung (75 threads in futex wait). Queue and workers
now use separate store locks.
"""
from __future__ import annotations

import threading

import pytest

from app.core.distributed.store import DiskStateStore, MemoryStateStore, RedisStateStore


def _stores(tmp_path):
    redis = RedisStateStore.__new__(RedisStateStore)
    RedisStateStore.__init__(redis, client=None)
    redis._redis = lambda: None  # no server: exercises the in-process fallback paths
    return [MemoryStateStore(), DiskStateStore(tmp_path / "state"), redis]


@pytest.mark.parametrize("idx", [0, 1, 2], ids=["memory", "disk", "redis-fallback"])
def test_queue_mutator_consulting_registry_vs_heartbeat_does_not_deadlock(tmp_path, idx, real_threads):
    store = _stores(tmp_path)[idx]
    registry_lock = threading.RLock()  # stands in for WorkerRegistry._lock
    in_queue_mutate = threading.Event()
    registry_held = threading.Event()

    def queue_mutation():  # JobQueue.enqueue / refresh_queue_reasons
        def mut(snap):
            in_queue_mutate.set()
            registry_held.wait(2)
            with registry_lock:  # mutator asks the registry (stale workers)
                return snap, "queued"
        return store.mutate_queue(mut)

    def heartbeat():  # WorkerRegistry.heartbeat
        in_queue_mutate.wait(2)
        with registry_lock:
            registry_held.set()
            return store.mutate_workers(lambda w: ({**w, "w1": {"worker_id": "w1"}}, True))

    results = {}
    ta = threading.Thread(target=lambda: results.setdefault("q", queue_mutation()), daemon=True)
    tb = threading.Thread(target=lambda: results.setdefault("h", heartbeat()), daemon=True)
    ta.start(); tb.start()
    ta.join(10); tb.join(10)
    assert not ta.is_alive() and not tb.is_alive(), "lock-order deadlock between queue and workers"
    assert results == {"q": "queued", "h": True}


def test_store_uses_separate_locks_per_kind(tmp_path):
    for store in _stores(tmp_path):
        locks = store._kind_locks
        assert locks["queue"] is not locks["workers"]
