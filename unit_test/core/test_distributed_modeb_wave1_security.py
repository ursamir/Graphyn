"""Mode B WAVE-1 enterprise security: worker token ACL, claim pins, signed blobs,
audit actions, remote secret strip, event redaction."""
from __future__ import annotations

import hashlib
import time

import pytest

from app.core.distributed.models import NodeJob, WorkerInfo
from app.core.distributed.queue import _reset_job_queue, get_job_queue, _plugins_allow
from app.core.distributed.registry import (
    _reset_worker_registry,
    get_worker_registry,
    known_remote_node_types,
)


@pytest.fixture(autouse=True)
def patch_threads(real_threads):
    yield


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "ws"))
    monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    monkeypatch.delenv("GRAPHYN_API_TOKENS", raising=False)
    monkeypatch.delenv("GRAPHYN_BLOB_SIGNING_KEY", raising=False)
    monkeypatch.delenv("GRAPHYN_WORKER_TRUST_REQUIRED", raising=False)
    monkeypatch.delenv("GRAPHYN_WORKER_REQUIRE_PLUGIN_ADVERTISE", raising=False)
    _reset_worker_registry()
    q = _reset_job_queue(use_memory=True, lease_ttl_s=60.0)
    yield q
    _reset_worker_registry()
    _reset_job_queue(use_memory=True)


# ── A. worker token route ACL ─────────────────────────────────────────────────


def test_parse_worker_scoped_tokens():
    from app.core.trust.identity import parse_token_entries, parse_token_map

    assert parse_token_map("alice:t1") == {"t1": "alice"}
    e = parse_token_entries("s99:tok:worker:s99-ml")
    assert e["tok"].kind == "worker" and e["tok"].worker_id == "s99-ml"
    e2 = parse_token_entries(
        '{"wt": {"name": "ml", "kind": "worker", "worker_id": "s99-ml"}}'
    )
    assert e2["wt"].is_worker and e2["wt"].name == "ml"


def test_worker_token_claim_acl(api_client, env, monkeypatch):
    monkeypatch.setenv("GRAPHYN_API_TOKENS", "op:op-tok,s99:w-tok:worker:s99-ml")
    get_worker_registry().register(
        WorkerInfo(worker_id="s99-ml", plugins=["python_code"])
    )
    get_worker_registry().register(WorkerInfo(worker_id="other", plugins=["python_code"]))
    q = env
    q.enqueue(NodeJob(job_id="j1", run_id="r", node_id="n", node_type="python_code"))

    # Wrong worker id with worker-scoped token → 403
    r = api_client.post(
        "/api/v1/jobs/claim",
        json={"worker_id": "other"},
        headers={"Authorization": "Bearer w-tok"},
    )
    assert r.status_code == 403, r.text

    # Matching worker id → ok
    r = api_client.post(
        "/api/v1/jobs/claim",
        json={"worker_id": "s99-ml"},
        headers={"Authorization": "Bearer w-tok", "X-Graphyn-Worker-Id": "s99-ml"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["job"]["job_id"] == "j1"

    # Operator can claim as any worker
    q.enqueue(NodeJob(job_id="j2", run_id="r", node_id="n", node_type="python_code"))
    r = api_client.post(
        "/api/v1/jobs/claim",
        json={"worker_id": "other"},
        headers={"Authorization": "Bearer op-tok"},
    )
    assert r.status_code == 200, r.text


# ── B. claim allowlist + hash pin ─────────────────────────────────────────────


def test_claim_allowed_plugins_and_hash_pin(env, monkeypatch):
    q = env
    reg = get_worker_registry()
    w = reg.register(
        WorkerInfo(
            worker_id="w1",
            plugins=["trainer", "evaluator"],
            allowed_plugins=["trainer"],
            plugin_hashes={"trainer": "abc123"},
            content_hashes={"trainer": "abc123"},
        )
    )
    q.enqueue(NodeJob(job_id="ok", run_id="r", node_id="n", node_type="trainer"))
    q.enqueue(NodeJob(job_id="deny", run_id="r", node_id="n", node_type="evaluator"))
    claimed = q.claim(reg.get("w1"))
    assert claimed is not None and claimed.job_id == "ok"
    # evaluator not in allowed_plugins
    assert q.claim(reg.get("w1")) is None

    # hash mismatch refuses
    reg.patch("w1", content_hashes={"trainer": "deadbeef"})
    q.enqueue(NodeJob(job_id="pin", run_id="r", node_id="n", node_type="trainer"))
    assert q.claim(reg.get("w1")) is None

    monkeypatch.setenv("GRAPHYN_WORKER_REQUIRE_PLUGIN_ADVERTISE", "1")
    empty = WorkerInfo(worker_id="empty", plugins=[])
    assert _plugins_allow(empty, "trainer") is False


def test_untrusted_cannot_claim_when_required(env, monkeypatch):
    monkeypatch.setenv("GRAPHYN_AUTH_REQUIRED", "1")
    monkeypatch.setenv("GRAPHYN_WORKER_TRUST_REQUIRED", "1")
    q = env
    reg = get_worker_registry()
    reg.register(WorkerInfo(worker_id="bad", plugins=["x"], trusted=False))
    q.enqueue(NodeJob(job_id="j", run_id="r", node_id="n", node_type="x"))
    assert q.claim(reg.get("bad")) is None


def test_known_remote_node_types(env):
    get_worker_registry().register(
        WorkerInfo(worker_id="w", plugins=["trainer"], node_types=["edge_pack"])
    )
    names = known_remote_node_types()
    assert "trainer" in names and "edge_pack" in names


def test_patch_worker_acl(api_client, env, monkeypatch):
    monkeypatch.setenv("GRAPHYN_API_TOKENS", "op:op-tok,s99:w-tok:worker:s99-ml")
    get_worker_registry().register(WorkerInfo(worker_id="s99-ml", plugins=["a"]))
    # Worker token cannot PATCH
    r = api_client.patch(
        "/api/v1/workers/s99-ml",
        json={"trusted": False},
        headers={"Authorization": "Bearer w-tok"},
    )
    assert r.status_code == 403
    r = api_client.patch(
        "/api/v1/workers/s99-ml",
        json={"trusted": False, "allowed_plugins": ["a"]},
        headers={"Authorization": "Bearer op-tok"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["trusted"] is False
    assert r.json()["allowed_plugins"] == ["a"]


# ── C. signed blob URL + GET deny ─────────────────────────────────────────────


def test_signed_blob_url_mint_verify_and_get_deny(api_client, env, monkeypatch):
    from app.core.distributed.transfer import (
        mint_signed_blob_url,
        put_blob_with_digest,
        verify_signed_blob_url,
    )

    monkeypatch.setenv("GRAPHYN_BLOB_SIGNING_KEY", "sign-secret")
    monkeypatch.setenv("GRAPHYN_API_TOKENS", "op:op-tok,s99:w-tok:worker:s99-ml")
    uri, digest = put_blob_with_digest(b"hello-blob")
    from app.core.artifacts.artifact_uri import parse_artifact_uri

    key = parse_artifact_uri(uri).key
    signed = mint_signed_blob_url(key, method="GET")
    assert "exp=" in signed and "sig=" in signed
    from urllib.parse import parse_qs

    qs = parse_qs(signed.split("?", 1)[1])
    assert verify_signed_blob_url(key, exp=qs["exp"][0], sig=qs["sig"][0])

    # Worker token without signed URL and without claim → 403
    bad = api_client.get(
        f"/api/v1/artifacts/blob/{key}",
        headers={"Authorization": "Bearer w-tok", "X-Graphyn-Worker-Id": "s99-ml"},
    )
    assert bad.status_code == 403, bad.text

    # Signed URL works (even without bearer, but auth middleware may require bearer)
    # Present operator bearer + signed query still fine; worker + signed OK.
    ok = api_client.get(
        f"/api/v1/artifacts/blob/{key}?exp={qs['exp'][0]}&sig={qs['sig'][0]}",
        headers={"Authorization": "Bearer w-tok"},
    )
    assert ok.status_code == 200
    assert ok.content == b"hello-blob"

    # Operator GET allowed
    op = api_client.get(
        f"/api/v1/artifacts/blob/{key}",
        headers={"Authorization": "Bearer op-tok"},
    )
    assert op.status_code == 200


# ── E. audit actions ──────────────────────────────────────────────────────────


def test_audit_actions_present(api_client, env, monkeypatch):
    from app.core.trust.audit import audit_label, list_audit

    monkeypatch.setenv("GRAPHYN_API_TOKENS", "op:op-tok")
    h = {"Authorization": "Bearer op-tok"}
    assert api_client.post(
        "/api/v1/workers/register", json={"worker_id": "aud-w"}, headers=h
    ).status_code == 200
    assert api_client.delete("/api/v1/workers/aud-w", headers=h).status_code == 200
    assert audit_label("worker.register") == "Worker registered"
    assert audit_label("worker.deregister") == "Worker deregistered"
    assert audit_label("job.claim") == "Job claimed"
    assert audit_label("blob.put") == "Artifact blob uploaded"
    events = list_audit(limit=50)
    actions = {e.get("action") for e in events}
    assert "worker.register" in actions
    assert "worker.deregister" in actions


# ── D. secret strip on remote enqueue ─────────────────────────────────────────


def test_secret_strip_on_remote_config():
    from app.core.distributed.security import assert_remote_config_safe
    from app.core.ir.secret_policy import InlineSecretError

    safe = assert_remote_config_safe(
        {"auth_env": "MY_KEY", "connection_id": "c1", "temperature": 0.2}
    )
    assert safe["auth_env"] == "MY_KEY"
    with pytest.raises(InlineSecretError):
        assert_remote_config_safe({"api_key": "sk-ant-abcdefghijklmnopqrstuvwxyz"})


# ── G. event redaction ────────────────────────────────────────────────────────


def test_event_redaction():
    from app.core.distributed.security import redact_job_events, redact_job_result_payload
    from app.core.distributed.models import JobResult

    ev = redact_job_events(
        [
            {
                "msg": "Authorization: Bearer abcdefghijklmnop",
                "url": "https://user:pass@hooks.example.com/h?token=1",
                "api_key": "secret-value",
            }
        ]
    )
    assert "***" in ev[0]["msg"]
    assert "pass" not in ev[0]["url"]
    assert ev[0]["api_key"] == "***"
    jr = JobResult(
        job_id="j",
        status="failed",
        error="Bearer abcdefghijklmnop failed",
        events=[{"token": "ghp_abcdefghijklmnopqrstuvwxyz"}],
    )
    red = redact_job_result_payload(jr)
    assert "***" in (red.error or "")
    assert red.events[0]["token"] == "***"


def test_complete_redacts_events(api_client, env, monkeypatch):
    monkeypatch.setenv("GRAPHYN_API_TOKENS", "op:op-tok")
    h = {"Authorization": "Bearer op-tok"}
    q = env
    reg = get_worker_registry()
    reg.register(WorkerInfo(worker_id="w", plugins=["x"]))
    q.enqueue(NodeJob(job_id="c1", run_id="r", node_id="n", node_type="x"))
    job = q.claim(reg.get("w"))
    assert job is not None
    r = api_client.post(
        "/api/v1/jobs/c1/complete",
        json={
            "job_id": "c1",
            "status": "succeeded",
            "worker_id": "w",
            "lease_generation": job.lease_generation,
            "events": [{"api_key": "should-not-persist", "msg": "ok"}],
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    stored = q.get_result("c1")
    assert stored is not None
    # events merged into result
    assert any(
        (e.get("api_key") == "***") for e in (stored.events or []) if isinstance(e, dict)
    ) or all(
        e.get("api_key") != "should-not-persist"
        for e in (stored.events or [])
        if isinstance(e, dict)
    )
