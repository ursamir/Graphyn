"""F18: pipeline queue + worker slot booking + org fair-share."""
from __future__ import annotations

import pytest

from app.core.distributed.models import JobResult, NodeJob, WorkerInfo
from app.core.distributed.queue import _reset_job_queue
from app.core.distributed.registry import _reset_worker_registry, get_worker_registry
from app.core.distributed.slots import slot_snapshot, slots_bookable, worker_used_slots
from app.core.ir.models import IRPlacement
from app.core.trust.metering import get_meter_store, reset_meter_store
from app.core.trust.orgs import reset_org_store
from app.core.trust.users import get_user_store, reset_user_store


TOKENS = "op:op-tok"


@pytest.fixture(autouse=True)
def patch_threads(real_threads):
    yield


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GRAPHYN_USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("GRAPHYN_API_TOKENS", TOKENS)
    for k in (
        "GRAPHYN_AUTH_REQUIRED",
        "GRAPHYN_API_TOKEN",
        "GRAPHYN_POOL_MAX_CLAIMED",
        "GRAPHYN_WORKER_TRUST_REQUIRED",
    ):
        monkeypatch.delenv(k, raising=False)
    _reset_worker_registry()
    reset_user_store()
    reset_org_store()
    reset_meter_store()
    get_user_store()  # ensure users table exists for org usage()
    q = _reset_job_queue(use_memory=True, lease_ttl_s=60.0)
    yield q
    _reset_worker_registry()
    _reset_job_queue(use_memory=True)
    reset_meter_store()
    reset_org_store()
    reset_user_store()


def _job(jid: str, *, org: str | None = None, placement=None) -> NodeJob:
    return NodeJob(
        job_id=jid,
        run_id="r1",
        node_id="n1",
        node_type="python_code",
        org_id=org,
        placement=placement,
    )


def test_book_when_free_and_queue_when_full(env):
    q = env
    reg = get_worker_registry()
    w = reg.register(WorkerInfo(worker_id="w1", plugins=["python_code"], max_claimed=1))
    assert slots_bookable(w)
    q.enqueue(_job("a", org="org_a"))
    q.enqueue(_job("b", org="org_a"))
    j1 = q.claim(w)
    assert j1 is not None and j1.job_id == "a"
    assert worker_used_slots("w1") == 1
    snap = slot_snapshot(reg.get("w1"))
    assert snap["max_slots"] == 1 and snap["used_slots"] == 1 and snap["free_slots"] == 0
    assert q.claim(reg.get("w1")) is None
    pending = q.list_queue()
    assert len(pending) == 1 and pending[0]["job_id"] == "b"
    assert pending[0]["queue_position"] == 1
    assert pending[0]["queue_reason"] in ("no_capacity", "waiting_worker", "org_quota")


def test_release_on_finish_then_pull(env):
    q = env
    reg = get_worker_registry()
    w = reg.register(WorkerInfo(worker_id="w1", plugins=["python_code"], max_claimed=1))
    q.enqueue(_job("a", org="org_a"))
    q.enqueue(_job("b", org="org_a"))
    j1 = q.claim(w)
    assert j1 is not None
    q.complete(
        JobResult(
            job_id=j1.job_id,
            status="succeeded",
            worker_id="w1",
            lease_generation=j1.lease_generation,
        )
    )
    assert worker_used_slots("w1") == 0
    j2 = q.claim(reg.get("w1"))
    assert j2 is not None and j2.job_id == "b"


def test_fair_share_across_two_orgs(env):
    q = env
    store = get_meter_store()
    store.set_quota("org_a", max_concurrent_jobs=2, max_queued_jobs=50)
    store.set_quota("org_b", max_concurrent_jobs=2, max_queued_jobs=50)
    reg = get_worker_registry()
    w = reg.register(WorkerInfo(worker_id="w1", plugins=["python_code"], max_claimed=2))
    q.enqueue(_job("a1", org="org_a"))
    assert q.claim(w).job_id == "a1"
    q.enqueue(_job("b1", org="org_b"))
    q.enqueue(_job("a2", org="org_a"))
    j = q.claim(reg.get("w1"))
    assert j is not None
    assert j.job_id == "b1", f"expected fair-share pick b1, got {j.job_id}"


def test_org_concurrent_quota_blocks_claim(env):
    q = env
    get_meter_store().set_quota("org_a", max_concurrent_jobs=1, max_queued_jobs=20)
    reg = get_worker_registry()
    w = reg.register(WorkerInfo(worker_id="w1", plugins=["python_code"], max_claimed=4))
    q.enqueue(_job("a1", org="org_a"))
    q.enqueue(_job("a2", org="org_a"))
    assert q.claim(w).job_id == "a1"
    assert q.claim(reg.get("w1")) is None
    rows = q.list_queue()
    assert len(rows) == 1
    assert rows[0]["queue_reason"] == "org_quota"


def test_pinned_worker_no_capacity_reason(env):
    q = env
    reg = get_worker_registry()
    w = reg.register(WorkerInfo(worker_id="w1", plugins=["python_code"], max_claimed=1))
    pin = IRPlacement(mode="worker", worker="w1")
    q.enqueue(_job("a", org="org_a", placement=pin))
    q.claim(w)
    q.enqueue(_job("b", org="org_a", placement=pin))
    q.refresh_queue_reasons()
    rows = q.list_queue()
    assert rows[0]["job_id"] == "b"
    assert rows[0]["queue_reason"] == "no_capacity"


def test_queue_api_and_worker_slots(api_client, env):
    headers = {"Authorization": "Bearer op-tok"}
    get_worker_registry().register(
        WorkerInfo(worker_id="w1", plugins=["python_code"], max_claimed=1)
    )
    env.enqueue(_job("j1", org="org_a"))
    r = api_client.get("/api/v1/jobs/queue", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pending_count"] >= 1
    assert body["queue"][0]["job_id"] == "j1"
    assert "queue_position" in body["queue"][0]
    wr = api_client.get("/api/v1/workers", headers=headers)
    assert wr.status_code == 200
    w = next(x for x in wr.json() if x["worker_id"] == "w1")
    assert w["max_slots"] == 1 and w["used_slots"] == 0 and w["free_slots"] == 1


def test_org_quota_fields_public(env):
    store = get_meter_store()
    q = store.set_quota("org_demo", max_concurrent_jobs=3, max_queued_jobs=9)
    pub = q.public()
    assert pub["max_concurrent_jobs"] == 3
    assert pub["max_queued_jobs"] == 9
    usage = store.usage("org_demo").public()
    assert "concurrent_jobs" in usage and "queued_jobs" in usage


def test_enqueue_over_queue_depth_raises(env):
    from app.core.distributed.quotas import QuotaExceeded

    get_meter_store().set_quota("org_a", max_concurrent_jobs=8, max_queued_jobs=1)
    q = env
    q.enqueue(_job("a", org="org_a"))
    with pytest.raises(QuotaExceeded) as ei:
        q.enqueue(_job("b", org="org_a"))
    assert ei.value.kind == "org"


def test_complete_stamps_event_seq(env, monkeypatch):
    monkeypatch.setenv("GRAPHYN_JOB_EVENTS_MAX", "10")
    q = env
    reg = get_worker_registry()
    w = reg.register(WorkerInfo(worker_id="w1", plugins=["python_code"], max_claimed=1))
    q.enqueue(_job("a", org="org_a"))
    j = q.claim(w)
    assert j is not None
    q.complete(
        JobResult(
            job_id=j.job_id,
            status="succeeded",
            worker_id="w1",
            lease_generation=j.lease_generation,
            events=[{"message": "done"}, {"message": "bye"}],
        )
    )
    ev = q.list_events(j.job_id)
    assert ev and all(isinstance(e.get("_seq"), int) for e in ev if isinstance(e, dict))
    seqs = [e["_seq"] for e in ev if isinstance(e, dict) and "_seq" in e]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)

