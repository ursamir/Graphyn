"""F19 (DIST-ORPHAN-1, worker side): a job whose worker lease is lost is
requeued only when that is safe — the node is idempotent and its retry policy
allows another attempt — otherwise it fails with a clear reason that the
waiting run surfaces."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.distributed.models import NodeJob
from app.core.distributed.queue import JobQueue, _lease_loss_failure
from app.core.distributed.store import MemoryStateStore


def _queue(durable: bool) -> JobQueue:
    return JobQueue(lease_ttl_s=30, store=MemoryStateStore() if durable else None, load_persisted=False)


def _lost(q: JobQueue, **job_kw) -> str:
    job = q.enqueue(NodeJob(job_id=job_kw.pop("job_id", "j1"), run_id="r1", node_id="n", node_type=job_kw.pop("node_type", "trainer"), **job_kw))
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    if q._store is not None:
        def mut(snap):
            jobs = dict(snap.get("jobs") or {})
            payload = dict(jobs[job.job_id])
            payload.update(status="running", claimed_by="w1", claimed_at=past.isoformat(), lease_expires_at=past.isoformat())
            jobs[job.job_id] = payload
            order = [j for j in (snap.get("order") or []) if j != job.job_id]
            return {**snap, "jobs": jobs, "order": order}, None
        q._durable_mutate(mut)
    else:
        q._jobs[job.job_id] = q._jobs[job.job_id].model_copy(update=dict(status="running", claimed_by="w1", claimed_at=past, lease_expires_at=past))
        q._order = [j for j in q._order if j != job.job_id]
    return job.job_id


@pytest.mark.parametrize("durable", [False, True])
def test_idempotent_job_is_requeued(durable):
    q = _queue(durable)
    jid = _lost(q)
    assert q.reclaim_expired_leases() == [jid]
    job = q.get(jid)
    assert job.status == "pending" and job.attempts == 1 and job.claimed_by is None
    assert job.lease_generation == 1


@pytest.mark.parametrize("durable", [False, True])
def test_non_idempotent_job_fails_instead_of_rerunning(durable):
    q = _queue(durable)
    jid = _lost(q, node_type="send_email", idempotent=False)
    assert q.reclaim_expired_leases() == []
    assert q.get(jid).status == "failed"
    res = q.get_result(jid)
    assert res is not None and res.status == "failed"
    assert "non-idempotent" in res.error and "send_email" in res.error


@pytest.mark.parametrize("durable", [False, True])
def test_retry_policy_max_attempts_one_is_not_retried(durable):
    q = _queue(durable)
    jid = _lost(q, max_attempts=0)  # IR retry.max_attempts=1 → 0 reclaims
    q.reclaim_expired_leases()
    assert q.get(jid).status == "failed"
    assert "exceeded max_attempts (0)" in q.get_result(jid).error


def test_worker_reregister_respects_idempotency():
    q = _queue(False)
    jid = _lost(q, node_type="http_request", idempotent=False)
    q.release_jobs_for_worker("w1")
    assert q.get(jid).status == "failed"
    assert "re-registered" in q.get_result(jid).error


def test_lease_loss_decision():
    base = dict(job_id="x", run_id="r", node_id="n", node_type="t")
    assert _lease_loss_failure(NodeJob(**base), 1) is None
    assert _lease_loss_failure(NodeJob(**base, max_attempts=2), 3).startswith("exceeded")
    assert "non-idempotent" in _lease_loss_failure(NodeJob(**base, idempotent=False), 1)


def test_job_retry_fields_from_node_and_ir(monkeypatch):
    from app.core.distributed import backend
    from app.core.nodes import idempotency

    class _Http:
        @classmethod
        def idempotent_for(cls, config):
            return str(config.get("method", "GET")).upper() in ("GET", "HEAD", "OPTIONS")

    class _Reg:
        def get_metadata(self, t):
            return SimpleNamespace(idempotent={"send_email": False}.get(t, True))

        def get_class(self, t):
            return _Http if t == "http_request" else object

    monkeypatch.setattr("app.core.host.registry_runtime.get_registry", lambda: _Reg())
    assert idempotency.node_is_idempotent("send_email") is False
    assert idempotency.node_is_idempotent("http_request", {"method": "POST"}) is False
    assert idempotency.node_is_idempotent("http_request", {"method": "get"}) is True
    assert idempotency.node_is_idempotent("trainer") is True
    f = backend._job_retry_fields(SimpleNamespace(node_type="send_email", retry={"max_attempts": 1}), {})
    assert f == {"idempotent": False, "max_attempts": 0}
    assert backend._job_retry_fields(SimpleNamespace(node_type="trainer", retry=None), {}) == {"idempotent": True}


def test_side_effect_plugins_declare_not_idempotent():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "PluginPackage" / "Common"
    for name in ("send_email", "http_webhook", "http_request"):
        assert "idempotent=False" in (root / name / "nodes.py").read_text(), name
