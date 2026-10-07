"""Mode B WAVE-2: mTLS helpers, blob encrypt-at-rest, pool quotas, worker spool."""
from __future__ import annotations

import base64
import hashlib
import os
import ssl
import tempfile
from pathlib import Path

import pytest

from app.core.distributed.models import NodeJob, WorkerInfo
from app.core.distributed.queue import _reset_job_queue, get_job_queue
from app.core.distributed.registry import _reset_worker_registry, get_worker_registry


@pytest.fixture(autouse=True)
def patch_threads(real_threads):
    """Override global Thread.start no-op so mTLS handshake threads run."""
    yield


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    monkeypatch.delenv("GRAPHYN_API_TOKENS", raising=False)
    monkeypatch.delenv("GRAPHYN_BLOB_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("GRAPHYN_POOL_MAX_CLAIMED", raising=False)
    monkeypatch.delenv("GRAPHYN_MTLS_ENABLED", raising=False)
    monkeypatch.delenv("GRAPHYN_MTLS_CA_CERT", raising=False)
    monkeypatch.delenv("GRAPHYN_MTLS_CERT", raising=False)
    monkeypatch.delenv("GRAPHYN_MTLS_KEY", raising=False)
    monkeypatch.delenv("GRAPHYN_MTLS_CLIENT_CERT", raising=False)
    monkeypatch.delenv("GRAPHYN_MTLS_CLIENT_KEY", raising=False)
    monkeypatch.delenv("GRAPHYN_MTLS_TEST_HEADER", raising=False)
    monkeypatch.delenv("GRAPHYN_WORKER_SPOOL", raising=False)
    _reset_worker_registry()
    q = _reset_job_queue(use_memory=True, lease_ttl_s=60.0)
    yield q
    _reset_worker_registry()
    _reset_job_queue(use_memory=True)


# ── 1. mTLS cert generation + identity ───────────────────────────────────────


def test_generate_mtls_certs_and_parse_worker_id(tmp_path, env, monkeypatch):
    from app.core.distributed.mtls import (
        generate_modeb_mtls_certs,
        client_ssl_context,
        server_ssl_context,
        worker_id_from_pem,
        worker_id_from_peercert,
        mtls_enabled,
    )

    paths = generate_modeb_mtls_certs(tmp_path / "certs", worker_ids=["s99-ml", "w2"])
    assert paths["ca_cert"].is_file()
    assert paths["control_cert"].is_file()
    assert paths["worker:s99-ml:cert"].is_file()

    pem = paths["worker:s99-ml:cert"].read_bytes()
    assert worker_id_from_pem(pem) == "s99-ml"

    # peercert dict shape (as ssl module returns)
    peercert = {
        "subject": ((("commonName", "s99-ml"),),),
        "subjectAltName": (
            ("URI", "urn:graphyn:worker:s99-ml"),
            ("DNS", "s99-ml"),
        ),
    }
    assert worker_id_from_peercert(peercert) == "s99-ml"

    # SSL contexts load
    monkeypatch.setenv("GRAPHYN_MTLS_CA_CERT", str(paths["ca_cert"]))
    monkeypatch.setenv("GRAPHYN_MTLS_CERT", str(paths["control_cert"]))
    monkeypatch.setenv("GRAPHYN_MTLS_KEY", str(paths["control_key"]))
    monkeypatch.setenv("GRAPHYN_MTLS_CLIENT_CERT", str(paths["worker:s99-ml:cert"]))
    monkeypatch.setenv("GRAPHYN_MTLS_CLIENT_KEY", str(paths["worker:s99-ml:key"]))
    monkeypatch.setenv("GRAPHYN_MTLS_ENABLED", "1")
    assert mtls_enabled()
    sctx = server_ssl_context()
    assert sctx.verify_mode == ssl.CERT_REQUIRED
    cctx = client_ssl_context(check_hostname=False)
    assert cctx.verify_mode == ssl.CERT_REQUIRED


def test_mtls_handshake_roundtrip(tmp_path, monkeypatch):
    """Real TLS handshake: server requires client cert; worker context connects."""
    import socket
    import threading

    from app.core.distributed.mtls import (
        generate_modeb_mtls_certs,
        client_ssl_context,
        server_ssl_context,
    )

    monkeypatch.setenv("GRAPHYN_MTLS_ENABLED", "1")
    paths = generate_modeb_mtls_certs(tmp_path / "certs", worker_ids=["lab-w"])
    monkeypatch.setenv("GRAPHYN_MTLS_CA_CERT", str(paths["ca_cert"]))
    monkeypatch.setenv("GRAPHYN_MTLS_CERT", str(paths["control_cert"]))
    monkeypatch.setenv("GRAPHYN_MTLS_KEY", str(paths["control_key"]))
    monkeypatch.setenv("GRAPHYN_MTLS_CLIENT_CERT", str(paths["worker:lab-w:cert"]))
    monkeypatch.setenv("GRAPHYN_MTLS_CLIENT_KEY", str(paths["worker:lab-w:key"]))
    monkeypatch.setenv("GRAPHYN_MTLS_ENABLED", "1")

    sctx = server_ssl_context()
    cctx = client_ssl_context(check_hostname=False)

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen(1)
    srv.settimeout(10)
    got = {}

    def _accept():
        try:
            conn, _ = srv.accept()
            conn.settimeout(10)
            tls = sctx.wrap_socket(conn, server_side=True)
            got["peercert"] = tls.getpeercert()
            tls.sendall(b"OK")
            tls.close()
        except Exception as exc:
            got["error"] = exc

    t = threading.Thread(target=_accept, daemon=True)
    t.start()
    raw = socket.create_connection(("127.0.0.1", port), timeout=10)
    raw.settimeout(10)
    client = cctx.wrap_socket(raw, server_hostname="localhost")
    data = client.recv(16)
    client.close()
    t.join(timeout=10)
    srv.close()
    assert data == b"OK"
    assert "error" not in got
    from app.core.distributed.mtls import worker_id_from_peercert

    assert worker_id_from_peercert(got.get("peercert")) == "lab-w"


def test_mtls_identity_header_binds_worker(api_client, env, monkeypatch):
    monkeypatch.setenv("GRAPHYN_MTLS_ENABLED", "1")
    monkeypatch.setenv("GRAPHYN_MTLS_TEST_HEADER", "1")
    # Minimal cert paths so mtls_enabled stays true without real TLS in TestClient
    monkeypatch.setenv("GRAPHYN_MTLS_CA_CERT", "/tmp/fake-ca.pem")
    monkeypatch.setenv("GRAPHYN_MTLS_CERT", "/tmp/fake-cert.pem")
    monkeypatch.setenv("GRAPHYN_MTLS_KEY", "/tmp/fake-key.pem")
    get_worker_registry().register(
        WorkerInfo(worker_id="s99-ml", plugins=["python_code"])
    )
    get_worker_registry().register(
        WorkerInfo(worker_id="other", plugins=["python_code"])
    )
    env.enqueue(NodeJob(job_id="j1", run_id="r", node_id="n", node_type="python_code"))
    # Cert says s99-ml but claim as other → 403
    r = api_client.post(
        "/api/v1/jobs/claim",
        json={"worker_id": "other"},
        headers={"X-Graphyn-Mtls-Worker-Id": "s99-ml"},
    )
    assert r.status_code == 403, r.text
    r = api_client.post(
        "/api/v1/jobs/claim",
        json={"worker_id": "s99-ml"},
        headers={"X-Graphyn-Mtls-Worker-Id": "s99-ml"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["job"]["job_id"] == "j1"


# ── 2. Blob encrypt-at-rest ──────────────────────────────────────────────────


def test_blob_encrypt_roundtrip_and_wrong_key(tmp_path, env, monkeypatch):
    from app.core.distributed.blob_crypto import (
        BlobCryptoError,
        encrypt_blob_envelope,
        decrypt_blob_envelope,
        is_encrypted_envelope,
    )
    from app.core.distributed import transfer as tr

    key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setenv("GRAPHYN_BLOB_ENCRYPTION_KEY", key)
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "ws"))

    plain = b"hello-modeb-blob-" + os.urandom(32)
    uri, digest = tr.put_blob_with_digest(plain)
    assert digest == hashlib.sha256(plain).hexdigest()
    # On disk is encrypted
    path = tr._safe_path(tr.uri_to_key(uri))
    raw = path.read_bytes()
    assert is_encrypted_envelope(raw)
    assert raw != plain
    # get returns plaintext
    assert tr.get_blob(uri) == plain
    assert tr.get_blob(uri, expected_sha256=digest) == plain

    # Wrong key fails
    monkeypatch.setenv(
        "GRAPHYN_BLOB_ENCRYPTION_KEY",
        base64.urlsafe_b64encode(os.urandom(32)).decode("ascii"),
    )
    with pytest.raises(BlobCryptoError):
        tr.get_blob(uri)

    monkeypatch.setenv("GRAPHYN_BLOB_ENCRYPTION_KEY", key)
    assert decrypt_blob_envelope(encrypt_blob_envelope(b"xyz")) == b"xyz"


def test_blob_plaintext_when_key_unset(tmp_path, env, monkeypatch):
    from app.core.distributed import transfer as tr

    monkeypatch.delenv("GRAPHYN_BLOB_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "ws2"))
    plain = b"plaintext-blob"
    uri, digest = tr.put_blob_with_digest(plain)
    path = tr._safe_path(tr.uri_to_key(uri))
    assert path.read_bytes() == plain
    assert tr.get_blob(uri) == plain
    assert digest == hashlib.sha256(plain).hexdigest()


# ── 3. Pool / worker quotas + usage ──────────────────────────────────────────


def test_worker_max_claimed_quota(env, monkeypatch):
    from app.core.distributed.quotas import QuotaExceeded, assert_claim_quota

    q = env
    reg = get_worker_registry()
    w = reg.register(
        WorkerInfo(worker_id="w1", plugins=["python_code"], max_claimed=1)
    )
    q.enqueue(NodeJob(job_id="a", run_id="r", node_id="n", node_type="python_code"))
    q.enqueue(NodeJob(job_id="b", run_id="r", node_id="n", node_type="python_code"))
    j1 = q.claim(w)
    assert j1 is not None and j1.job_id == "a"
    # Second claim refused (skipped → None) because max_claimed=1
    j2 = q.claim(reg.get("w1"))
    assert j2 is None
    with pytest.raises(QuotaExceeded):
        assert_claim_quota(reg.get("w1"))


def test_pool_max_claimed_env(env, monkeypatch):
    monkeypatch.setenv("GRAPHYN_POOL_MAX_CLAIMED", "gpu-lab=1")
    q = env
    reg = get_worker_registry()
    w1 = reg.register(
        WorkerInfo(worker_id="w1", plugins=["python_code"], pools=["gpu-lab"])
    )
    w2 = reg.register(
        WorkerInfo(worker_id="w2", plugins=["python_code"], pools=["gpu-lab"])
    )
    q.enqueue(
        NodeJob(job_id="a", run_id="r", node_id="n", node_type="python_code", pool="gpu-lab")
    )
    q.enqueue(
        NodeJob(job_id="b", run_id="r", node_id="n", node_type="python_code", pool="gpu-lab")
    )
    assert q.claim(w1) is not None
    # Pool full — neither worker can claim the second
    assert q.claim(w2) is None
    assert q.claim(w1) is None


def test_usage_counters_on_claim_complete(api_client, env, monkeypatch):
    reg = get_worker_registry()
    reg.register(WorkerInfo(worker_id="w1", plugins=["python_code"]))
    env.enqueue(NodeJob(job_id="j1", run_id="r", node_id="n", node_type="python_code"))
    r = api_client.post("/api/v1/jobs/claim", json={"worker_id": "w1"})
    assert r.status_code == 200 and r.json()["job"]["job_id"] == "j1"
    rows = api_client.get("/api/v1/workers").json()
    w = next(x for x in rows if x["worker_id"] == "w1")
    assert w["usage"]["claims"] >= 1
    assert w.get("usage_claims", 0) >= 1
    # complete
    r = api_client.post(
        "/api/v1/jobs/j1/complete",
        json={
            "job_id": "j1",
            "status": "succeeded",
            "worker_id": "w1",
            "lease_generation": 0,
            "output_refs": {},
        },
    )
    assert r.status_code == 200, r.text
    rows = api_client.get("/api/v1/workers").json()
    w = next(x for x in rows if x["worker_id"] == "w1")
    assert w["usage"]["completes"] >= 1


def test_admin_patch_max_claimed(api_client, env):
    get_worker_registry().register(WorkerInfo(worker_id="w1", plugins=["python_code"]))
    r = api_client.patch("/api/v1/workers/w1", json={"max_claimed": 2})
    assert r.status_code == 200, r.text
    assert r.json()["max_claimed"] == 2


# ── 4. Worker offline spool ──────────────────────────────────────────────────


def test_worker_spool_store_and_flush(tmp_path, env, monkeypatch):
    from app.core.distributed.worker_spool import WorkerSpool, is_network_error

    monkeypatch.setenv("GRAPHYN_WORKER_SPOOL", "1")
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    spool = WorkerSpool(tmp_path / "spool")
    spool.enqueue_blob(key="jobs/j1/g0/out", data=b"blob-bytes", worker_id="w1", job_id="j1", lease_generation=0)
    spool.enqueue_complete(
        {
            "job_id": "j1",
            "status": "succeeded",
            "worker_id": "w1",
            "lease_generation": 0,
            "output_refs": {},
        }
    )
    assert len(spool.pending()) == 2

    flushed_blobs = []
    completed = []

    def put_blob(data, *, key=None, worker_id=None):
        flushed_blobs.append((key, data, worker_id))
        return "artifact://local/" + (key or "x")

    def complete(job_id, result):
        completed.append((job_id, result))

    stats = spool.flush(put_blob=put_blob, complete=complete)
    assert stats["flushed"] == 2
    assert stats["remaining"] == 0
    assert flushed_blobs[0][1] == b"blob-bytes"
    assert completed[0][0] == "j1"

    # Fenced complete is dropped
    spool.enqueue_complete(
        {"job_id": "j2", "status": "succeeded", "worker_id": "w1", "lease_generation": 1}
    )

    class Fence(Exception):
        code = 409

    def complete_fence(job_id, result):
        raise Fence("lease generation mismatch")

    stats = spool.flush(complete=complete_fence)
    assert stats["dropped"] == 1
    assert stats["remaining"] == 0
    assert (tmp_path / "spool" / "dropped.jsonl").is_file()

    assert is_network_error(ConnectionRefusedError())
    assert is_network_error(TimeoutError())
