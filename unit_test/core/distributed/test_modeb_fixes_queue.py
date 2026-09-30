"""Mode B fixes — JobQueue: history trim, heartbeat scope, re-register release,
claimed-generation fencing, events cap, cross-process read-through."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.distributed import queue as queue_mod
from app.core.distributed.models import JobResult, NodeJob, WorkerInfo
from app.core.distributed.queue import JobQueue, _trim_terminal_jobs_snapshot
from app.core.distributed.store import DiskStateStore, MemoryStateStore


def _job(jid: str, run: str = "r") -> NodeJob:
    return NodeJob(job_id=jid, run_id=run, node_id="n", node_type="x")


def _complete(q: JobQueue, jid: str, wid: str = "w1", gen: int | None = None) -> None:
    job = q.get(jid)
    q.complete(
        JobResult(
            job_id=jid,
            status="succeeded",
            worker_id=wid,
            lease_generation=job.lease_generation if gen is None else gen,
        )
    )


# ── 1. terminal history trim ─────────────────────────────────────────────────


def test_trim_orders_by_finished_at_and_keeps_current_and_unread(monkeypatch):
    monkeypatch.setattr(queue_mod, "_MAX_PERSISTED_TERMINAL_JOBS", 2)
    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=5)).isoformat()
    mid = (now - timedelta(hours=3)).isoformat()
    recent = (now - timedelta(seconds=5)).isoformat()
    snap = {
        # ids chosen so lexical sort would drop "a…" first (the old bug)
        "jobs": {
            "a-newest": {"status": "succeeded", "finished_at": recent},
            "z-oldest": {"status": "succeeded", "finished_at": old,
                         "result_consumed_at": old},
            "m-mid": {"status": "failed", "finished_at": mid, "result_consumed_at": mid},
            "b-unread": {"status": "succeeded", "finished_at": recent},
        },
        "results": {"a-newest": {}, "z-oldest": {}, "m-mid": {}, "b-unread": {}},
        "events": {},
        "order": [],
        "paused_runs": ["keep-me"],
    }
    out = _trim_terminal_jobs_snapshot(snap, keep=frozenset({"a-newest"}))
    assert set(out["jobs"]) == {"a-newest", "b-unread"}
    assert "z-oldest" not in out["results"] and "m-mid" not in out["results"]
    assert out["paused_runs"] == ["keep-me"]


def test_trim_drops_unread_results_after_ttl(monkeypatch):
    monkeypatch.setattr(queue_mod, "_MAX_PERSISTED_TERMINAL_JOBS", 1)
    monkeypatch.setenv("GRAPHYN_JOB_RESULT_TTL_S", "60")
    now = datetime.now(timezone.utc)
    snap = {
        "jobs": {
            "stale-unread": {"status": "succeeded",
                             "finished_at": (now - timedelta(hours=2)).isoformat()},
            "fresh-unread": {"status": "succeeded", "finished_at": now.isoformat()},
        },
        "results": {"stale-unread": {}, "fresh-unread": {}},
    }
    out = _trim_terminal_jobs_snapshot(snap)
    assert set(out["jobs"]) == {"fresh-unread"}


def test_complete_never_trims_just_completed_job(monkeypatch):
    monkeypatch.setattr(queue_mod, "_MAX_PERSISTED_TERMINAL_JOBS", 1)
    q = JobQueue(store=MemoryStateStore(), load_persisted=False)
    w = WorkerInfo(worker_id="w1")
    for jid in ("j-1", "j-2", "j-3"):
        q.enqueue(_job(jid))
        assert q.claim(w).job_id == jid
        _complete(q, jid)
        # Result is unread, but the job being completed must always survive.
        assert q.wait_for_result(jid, timeout_s=0) is not None
        assert q.get(jid).finished_at is not None


def test_ack_result_marks_consumed_and_allows_trim(monkeypatch):
    monkeypatch.setattr(queue_mod, "_MAX_PERSISTED_TERMINAL_JOBS", 1)
    q = JobQueue(store=MemoryStateStore(), load_persisted=False)
    w = WorkerInfo(worker_id="w1")
    q.enqueue(_job("first"))
    q.claim(w)
    _complete(q, "first")
    assert q.ack_result("first") is True
    assert q.get("first").result_consumed_at is not None
    assert q.ack_result("first") is False  # idempotent
    q.enqueue(_job("second"))
    q.claim(w)
    _complete(q, "second")
    assert q.get("first") is None  # consumed → trimmed
    assert q.get("second") is not None


# ── 2. heartbeat scope + re-register release ─────────────────────────────────


def test_renew_leases_only_active_job_ids():
    q = JobQueue(store=MemoryStateStore(), load_persisted=False, lease_ttl_s=60)
    w = WorkerInfo(worker_id="w1")
    q.enqueue(_job("live"))
    q.enqueue(_job("dead"))
    q.claim(w)
    q.claim(w)
    before_dead = q.get("dead").lease_expires_at
    assert q.renew_leases_for_worker("w1", active_job_ids=["live"]) == 1
    assert q.get("dead").lease_expires_at == before_dead
    assert q.get("live").lease_expires_at >= before_dead


def test_renew_leases_legacy_without_ids_renews_all(caplog):
    q = JobQueue(store=MemoryStateStore(), load_persisted=False)
    w = WorkerInfo(worker_id="legacy")
    q.enqueue(_job("a"))
    q.enqueue(_job("b"))
    q.claim(w)
    q.claim(w)
    with caplog.at_level("WARNING"):
        assert q.renew_leases_for_worker("legacy") == 2
    assert "deprecated" in caplog.text


def test_release_jobs_for_worker_requeues_with_bumped_generation():
    q = JobQueue(store=MemoryStateStore(), load_persisted=False)
    w = WorkerInfo(worker_id="w1")
    q.enqueue(_job("old-claim"))
    q.enqueue(_job("still-running"))
    q.claim(w)
    q.claim(w)
    released = q.release_jobs_for_worker("w1", keep_job_ids=["still-running"])
    assert released == ["old-claim"]
    job = q.get("old-claim")
    assert job.status == "pending" and job.claimed_by is None
    assert job.lease_generation == 1
    assert q.get("still-running").status == "claimed"
    # A late complete from the dead instance (generation 0) is fenced.
    other = WorkerInfo(worker_id="w2")
    assert q.claim(other).job_id == "old-claim"
    with pytest.raises(ValueError, match="lease_generation mismatch"):
        q.complete(JobResult(job_id="old-claim", status="succeeded",
                             worker_id="w2", lease_generation=0))


def test_release_fails_job_after_max_attempts():
    q = JobQueue(store=MemoryStateStore(), load_persisted=False)
    q.enqueue(NodeJob(job_id="poison", run_id="r", node_id="n", node_type="x",
                      max_attempts=1, attempts=1))
    q.claim(WorkerInfo(worker_id="w1"))
    q.release_jobs_for_worker("w1")
    assert q.get("poison").status == "failed"
    assert q.get_result("poison").status == "failed"


# ── 3. loopback completes with the claimed generation ───────────────────────


def test_loopback_reports_claimed_generation_not_current(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "ws"))
    from app.core.distributed.backend import run_loopback_worker_once
    from app.core.distributed.queue import _reset_job_queue, get_job_queue
    from app.core.distributed.registry import _reset_worker_registry, get_worker_registry

    _reset_worker_registry()
    _reset_job_queue()
    try:
        get_worker_registry().register(WorkerInfo(worker_id="lb"))
        get_job_queue().enqueue(_job("fenced"))

        def execute(job, inputs):
            # Simulate a reclaim + re-claim by another instance mid-execution.
            q = get_job_queue()
            q.release_jobs_for_worker("lb")
            assert q.claim(WorkerInfo(worker_id="lb")) is not None  # gen 1
            return {"out": 1}

        assert run_loopback_worker_once("lb", execute_fn=execute) is True
        job = get_job_queue().get("fenced")
        # Old code read the queue's *current* generation (1) and succeeded;
        # the stale gen-0 execution must be rejected instead.
        assert job.status == "claimed"
        assert job.lease_generation == 1
        assert get_job_queue().get_result("fenced") is None
    finally:
        _reset_worker_registry()
        _reset_job_queue()


# ── 8. events cap ────────────────────────────────────────────────────────────


def test_events_capped_per_job(monkeypatch):
    monkeypatch.setenv("GRAPHYN_JOB_EVENTS_MAX", "5")
    q = JobQueue(store=MemoryStateStore(), load_persisted=False)
    q.enqueue(_job("chatty"))
    for i in range(12):
        n = q.append_events("chatty", [{"i": i}])
    assert n == 5
    snap = q._store.load_queue()
    assert [e["i"] for e in snap["events"]["chatty"]] == [7, 8, 9, 10, 11]


# ── 12. read-through across processes (two queues, one disk store) ─────────


def test_queue_get_refreshes_from_disk_store(tmp_path: Path):
    a = JobQueue(store=DiskStateStore(tmp_path), load_persisted=False)
    b = JobQueue(store=DiskStateStore(tmp_path), load_persisted=True)
    a.enqueue(_job("xproc"))
    assert b.get("xproc") is not None  # b never mutated — must read through
    a.cancel("xproc")
    assert b.is_cancelled("xproc") is True
    assert b.has_active_jobs_for_run("r") is False


def test_queue_get_uses_cache_when_version_unchanged(tmp_path: Path, monkeypatch):
    store = DiskStateStore(tmp_path)
    q = JobQueue(store=store, load_persisted=False)
    q.enqueue(_job("cached"))
    calls = {"n": 0}
    real = store.load_queue

    def counting():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(store, "load_queue", counting)
    for _ in range(5):
        assert q.get("cached") is not None
    assert calls["n"] == 0
