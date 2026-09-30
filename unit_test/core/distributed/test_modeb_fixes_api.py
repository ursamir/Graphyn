"""Mode B fixes — worker/job/blob HTTP protocol (heartbeat active_job_ids,
register = new instance, read-only GET, blob key authz + integrity, typed status)."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.core.distributed.models import NodeJob, WorkerInfo
from app.core.distributed.queue import _reset_job_queue, get_job_queue
from app.core.distributed.registry import (
    WorkerRegistry,
    _reset_worker_registry,
    get_worker_registry,
)
from app.core.distributed.store import DiskStateStore


@pytest.fixture(autouse=True)
def patch_threads():
    """Override the global no-op Thread.start patch: TestClient needs threads."""
    yield


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "ws"))
    monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    _reset_worker_registry()
    q = _reset_job_queue(use_memory=True, lease_ttl_s=60.0)
    yield q
    _reset_worker_registry()
    _reset_job_queue(use_memory=True)


def _claim(q, wid: str, jid: str) -> NodeJob:
    reg = get_worker_registry()
    if reg.get(wid) is None:
        reg.register(WorkerInfo(worker_id=wid))
    q.enqueue(NodeJob(job_id=jid, run_id="r", node_id="n", node_type="x"))
    job = q.claim(reg.get(wid))
    assert job is not None and job.job_id == jid
    return job


# ── 2. heartbeat active_job_ids / register releases stale claims ────────────


def test_heartbeat_active_job_ids_renews_only_listed(api_client, env):
    q = env
    _claim(q, "hb", "keep")
    _claim(q, "hb", "dead")
    dead_before = q.get("dead").lease_expires_at
    resp = api_client.post(
        "/api/v1/workers/hb/heartbeat",
        json={"status": "busy", "active_job_ids": ["keep"]},
    )
    assert resp.status_code == 200, resp.text
    assert q.get("dead").lease_expires_at == dead_before
    assert q.get("keep").lease_expires_at >= dead_before


def test_register_releases_jobs_of_previous_instance(api_client, env):
    q = env
    _claim(q, "restarted", "orphan")
    _claim(q, "restarted", "resumed")
    resp = api_client.post(
        "/api/v1/workers/register",
        params={"active_job_ids": "resumed"},
        json={"worker_id": "restarted"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["released_job_ids"] == ["orphan"]
    orphan = q.get("orphan")
    assert orphan.status == "pending" and orphan.lease_generation == 1
    assert q.get("resumed").status == "claimed"


# ── 8. GET /jobs/{id} is read-only ──────────────────────────────────────────


def test_get_job_with_worker_id_does_not_renew_lease(api_client, env, monkeypatch):
    q = env
    _claim(q, "poller", "polled")
    calls = {"n": 0}
    real = type(q).renew_lease

    def spy(self, *a, **k):
        calls["n"] += 1
        return real(self, *a, **k)

    monkeypatch.setattr(type(q), "renew_lease", spy)
    before = q.get("polled").lease_expires_at
    for _ in range(3):
        r = api_client.get("/api/v1/jobs/polled", params={"worker_id": "poller"})
        assert r.status_code == 200
    assert calls["n"] == 0
    assert q.get("polled").lease_expires_at == before


# ── 10. typed heartbeat status ───────────────────────────────────────────────


def test_heartbeat_invalid_status_rejected(api_client, env):
    get_worker_registry().register(WorkerInfo(worker_id="typo"))
    r = api_client.post("/api/v1/workers/typo/heartbeat", json={"status": "bussy"})
    assert r.status_code == 422
    assert get_worker_registry().get("typo").status == "idle"
    ok = api_client.post("/api/v1/workers/typo/heartbeat", json={"status": "draining"})
    assert ok.status_code == 200
    assert get_worker_registry().get("typo").status == "draining"


def test_registry_heartbeat_rejects_invalid_status_directly():
    reg = WorkerRegistry()
    reg.register(WorkerInfo(worker_id="w"))
    with pytest.raises(ValueError):
        reg.heartbeat("w", status="exploded")


# ── 12. registry read-through across processes ──────────────────────────────


def test_registry_get_list_refresh_from_disk(tmp_path: Path):
    a = WorkerRegistry(store=DiskStateStore(tmp_path), load_persisted=False)
    b = WorkerRegistry(store=DiskStateStore(tmp_path), load_persisted=True)
    a.register(WorkerInfo(worker_id="late"))
    assert b.get("late") is not None
    assert [w.worker_id for w in b.list()] == ["late"]
    a.remove("late")
    assert b.get("late") is None


# ── 9. blob upload key rules + integrity ────────────────────────────────────


def test_blob_upload_rejects_explicit_sha256_key(api_client, env):
    body = b"payload"
    digest = hashlib.sha256(body).hexdigest()
    r = api_client.post(
        "/api/v1/artifacts/blob",
        params={"key": f"sha256/{digest[:2]}/{digest}"},
        content=body,
    )
    assert r.status_code == 400


def test_blob_upload_rejects_arbitrary_key(api_client, env):
    r = api_client.post("/api/v1/artifacts/blob", params={"key": "other/x"}, content=b"x")
    assert r.status_code == 400


def test_blob_upload_job_key_requires_current_claim(api_client, env):
    q = env
    job = _claim(q, "owner", "jb1")
    key = f"jobs/jb1/g{job.lease_generation}/out"
    # No worker id
    assert api_client.post("/api/v1/artifacts/blob", params={"key": key},
                           content=b"a").status_code == 403
    # Wrong worker
    get_worker_registry().register(WorkerInfo(worker_id="thief"))
    assert api_client.post("/api/v1/artifacts/blob",
                           params={"key": key, "worker_id": "thief"},
                           content=b"a").status_code == 403
    # Wrong generation
    assert api_client.post("/api/v1/artifacts/blob",
                           params={"key": "jobs/jb1/g7/out", "worker_id": "owner"},
                           content=b"a").status_code == 403
    ok = api_client.post("/api/v1/artifacts/blob",
                         params={"key": key, "worker_id": "owner"}, content=b"a")
    assert ok.status_code == 200, ok.text
    assert ok.json()["sha256"] == hashlib.sha256(b"a").hexdigest()
    # Idempotent same bytes; different bytes never overwrite.
    again = api_client.post("/api/v1/artifacts/blob",
                            params={"key": key, "worker_id": "owner"}, content=b"a")
    assert again.status_code == 200
    clobber = api_client.post("/api/v1/artifacts/blob",
                              params={"key": key, "worker_id": "owner"}, content=b"B")
    assert clobber.status_code == 409
    # Header form of worker id also accepted.
    hdr = api_client.post("/api/v1/artifacts/blob",
                          params={"key": f"jobs/jb1/g{job.lease_generation}/p2"},
                          headers={"X-Graphyn-Worker-Id": "owner"}, content=b"z")
    assert hdr.status_code == 200


def test_blob_upload_after_reclaim_is_rejected(api_client, env):
    q = env
    job = _claim(q, "slow", "jb2")
    q.release_jobs_for_worker("slow")  # reclaim → generation bumped
    r = api_client.post("/api/v1/artifacts/blob",
                        params={"key": f"jobs/jb2/g{job.lease_generation}/out",
                                "worker_id": "slow"},
                        content=b"late")
    assert r.status_code == 403


def test_blob_upload_runs_in_threadpool(api_client, env, monkeypatch):
    import app.api.routers.workers as workers_router

    seen: list[str] = []
    real = workers_router.run_in_threadpool

    async def spy(fn, *a, **k):
        seen.append(getattr(fn, "__name__", "?"))
        return await real(fn, *a, **k)

    monkeypatch.setattr(workers_router, "run_in_threadpool", spy)
    r = api_client.post("/api/v1/artifacts/blob", content=b"content-addressed")
    assert r.status_code == 200
    assert "_store" in seen


def test_blob_get_verifies_content_addressed_bytes(api_client, env):
    r = api_client.post("/api/v1/artifacts/blob", content=b"good-bytes")
    key = r.json()["key"]
    assert api_client.get(f"/api/v1/artifacts/blob/{key}").content == b"good-bytes"
    from app.core.distributed.transfer import blob_root

    (blob_root() / key).write_bytes(b"tampered")
    bad = api_client.get(f"/api/v1/artifacts/blob/{key}")
    assert bad.status_code == 409


def test_transfer_verifies_expected_sha256(env):
    from app.core.distributed.transfer import (
        BlobIntegrityError,
        get_blob,
        put_blob_with_digest,
        verify_blob_bytes,
    )

    uri, digest = put_blob_with_digest(b"out", key="jobs/j/g0/p")
    assert get_blob(uri, expected_sha256=digest) == b"out"
    with pytest.raises(BlobIntegrityError):
        get_blob(uri, expected_sha256="0" * 64)
    with pytest.raises(BlobIntegrityError):
        verify_blob_bytes(b"x", key="sha256/aa/" + "a" * 64)


def test_http_get_blob_verifies_downloaded_bytes(env, monkeypatch):
    import io

    from app.core.distributed import transfer

    body = b"network-bytes"
    digest = hashlib.sha256(body).hexdigest()

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(transfer.urllib.request, "urlopen",
                        lambda req, timeout=0: _Resp(b"corrupted!"))
    uri = f"artifact://local/sha256/{digest[:2]}/{digest}"
    with pytest.raises(transfer.BlobIntegrityError):
        transfer.http_get_blob("http://control", uri)
    monkeypatch.setattr(transfer.urllib.request, "urlopen",
                        lambda req, timeout=0: _Resp(body))
    assert transfer.http_get_blob("http://control", uri) == body
    with pytest.raises(transfer.BlobIntegrityError):
        transfer.http_get_blob("http://control", "artifact://local/jobs/j/g0/p",
                               expected_sha256="f" * 64)
