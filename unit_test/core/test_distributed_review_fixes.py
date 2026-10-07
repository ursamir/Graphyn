"""Regression tests for the post-F10 review fixes (Mode B security + ArtifactRef)."""
from __future__ import annotations

import hashlib
import tarfile
import io
from pathlib import Path

import pytest

from app.core.distributed.models import NodeJob, WorkerInfo
from app.core.distributed.queue import _reset_job_queue
from app.core.distributed.registry import _reset_worker_registry, get_worker_registry

TOKENS = "op:op-tok,s99:w-tok:worker:s99-ml"
OP = {"Authorization": "Bearer op-tok"}
W = {"Authorization": "Bearer w-tok", "X-Graphyn-Worker-Id": "s99-ml"}


@pytest.fixture(autouse=True)
def patch_threads(real_threads):
    """Real threads: TestClient's portal and the record_usage race test need them."""
    yield


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "ws"))
    for k in (
        "GRAPHYN_AUTH_REQUIRED",
        "GRAPHYN_API_TOKEN",
        "GRAPHYN_BLOB_SIGNING_KEY",
        "GRAPHYN_WORKER_TRUST_REQUIRED",
        "GRAPHYN_MTLS_ENABLED",
        "GRAPHYN_MTLS_TEST_HEADER",
        "GRAPHYN_POOL_MAX_CLAIMED",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GRAPHYN_API_TOKENS", TOKENS)
    _reset_worker_registry()
    q = _reset_job_queue(use_memory=True, lease_ttl_s=60.0)
    yield q
    _reset_worker_registry()
    _reset_job_queue(use_memory=True)


# ── Worker token scope ────────────────────────────────────────────────────────


def test_worker_token_cannot_call_operator_routes(api_client, env):
    for method, path in (
        ("GET", "/api/v1/runs"),
        ("GET", "/api/v1/workers"),
        ("POST", "/api/v1/pipelines/run"),
        ("GET", "/api/v1/credentials"),
    ):
        r = api_client.request(method, path, headers=W)
        assert r.status_code == 403, (method, path, r.status_code, r.text)
    assert api_client.get("/api/v1/workers", headers=OP).status_code == 200


def test_worker_scope_allowlist():
    from app.core.trust.identity import worker_scope_allows

    assert worker_scope_allows("POST", "/api/v1/jobs/claim")
    assert worker_scope_allows("POST", "/api/v1/jobs/j-1/complete")
    assert worker_scope_allows("HEAD", "/api/v1/artifacts/blob/sha256/ab")
    assert not worker_scope_allows("POST", "/api/v1/jobs/j-1/cancel")
    assert not worker_scope_allows("PATCH", "/api/v1/workers/s99-ml")
    assert not worker_scope_allows("POST", "/api/v1/artifacts/blob/sign")


def test_unbound_worker_token_fails_closed(monkeypatch):
    from app.core.trust import identity as idm

    monkeypatch.setenv("GRAPHYN_API_TOKENS", "w:unbound:worker")
    monkeypatch.delenv("GRAPHYN_WORKER_UNBOUND_TOKENS", raising=False)
    tok = idm.set_request_identity(idm.identity_from_credentials("unbound"))
    try:
        assert idm.worker_route_allowed("anyone") is False
        monkeypatch.setenv("GRAPHYN_WORKER_UNBOUND_TOKENS", "1")
        assert idm.worker_route_allowed("anyone") is True
    finally:
        idm.reset_request_identity(tok)


def test_mcp_rejects_worker_token(monkeypatch):
    from app.mcp.auth import check_auth

    monkeypatch.setenv("GRAPHYN_API_TOKENS", TOKENS)
    denied = check_auth({"_meta": {"auth_token": "w-tok"}})
    assert denied and denied["error_type"] == "forbidden"
    assert check_auth({"_meta": {"auth_token": "op-tok"}}) is None


# ── Register cannot widen admin fields ────────────────────────────────────────


def test_register_cannot_override_admin_fields(api_client, env):
    reg = get_worker_registry()
    reg.register(WorkerInfo(worker_id="s99-ml", plugins=["python_code"]))
    reg.patch("s99-ml", allowed_plugins=["python_code"], trusted=False, max_claimed=1, usage_claims=7)
    body = WorkerInfo(
        worker_id="s99-ml",
        plugins=["python_code", "trainer"],
        allowed_plugins=["python_code", "trainer"],
        plugin_hashes={"trainer": "x"},
        trusted=True,
        max_claimed=99,
        usage_claims=0,
    ).model_dump(mode="json")
    r = api_client.post("/api/v1/workers/register", json=body, headers=W)
    assert r.status_code == 200, r.text
    w = reg.get("s99-ml")
    assert w.allowed_plugins == ["python_code"]
    assert w.trusted is False
    assert w.max_claimed == 1
    assert w.usage_claims == 7
    assert w.plugin_hashes is None


def test_new_worker_untrusted_when_trust_required(api_client, env, monkeypatch):
    monkeypatch.setenv("GRAPHYN_WORKER_TRUST_REQUIRED", "1")
    monkeypatch.setenv("GRAPHYN_AUTH_REQUIRED", "1")
    monkeypatch.setenv("GRAPHYN_API_TOKEN", "op-tok")
    body = WorkerInfo(worker_id="s99-ml", trusted=True).model_dump(mode="json")
    r = api_client.post("/api/v1/workers/register", json=body, headers=W)
    assert r.status_code == 200, r.text
    assert get_worker_registry().get("s99-ml").trusted is False


# ── Job events / GET ACL; events dedup ────────────────────────────────────────


def _claimed(q, job_id="j1", worker="s99-ml", **kw):
    get_worker_registry().register(WorkerInfo(worker_id=worker, plugins=["python_code"]))
    q.enqueue(NodeJob(job_id=job_id, run_id="r", node_id="n", node_type="python_code", **kw))
    return q.claim(get_worker_registry().get(worker))


def test_job_events_and_get_acl(api_client, env):
    q = env
    get_worker_registry().register(WorkerInfo(worker_id="other", plugins=["python_code"]))
    q.enqueue(NodeJob(job_id="j1", run_id="r", node_id="n", node_type="python_code"))
    # Pending (unclaimed) job: worker may not append events or read it.
    r = api_client.post("/api/v1/jobs/j1/events", json={"events": [{"message": "x"}]}, headers=W)
    assert r.status_code == 409, r.text
    assert api_client.get("/api/v1/jobs/j1", headers=W).status_code == 403
    assert q.claim(get_worker_registry().get("other")) is not None
    r = api_client.post("/api/v1/jobs/j1/events", json={"events": [{"message": "x"}]}, headers=W)
    assert r.status_code == 403, r.text
    assert api_client.get("/api/v1/jobs/j1", headers=W).status_code == 403
    assert api_client.get("/api/v1/jobs/j1", headers=OP).status_code == 200


def test_event_seq_survives_cap(env, monkeypatch):
    from app.core.distributed.backend import _forward_job_events

    monkeypatch.setenv("GRAPHYN_JOB_EVENTS_MAX", "3")
    q = env
    _claimed(q)
    seen: set[int] = set()
    msgs: list[str] = []

    class _L:
        def info(self, m):
            msgs.append(m)

    q.append_events("j1", [{"message": f"e{i}"} for i in range(3)])
    _forward_job_events(q, "j1", logger=_L(), run=None, node_id="n", seen=seen)
    q.append_events("j1", [{"message": "e3"}, {"message": "e4"}])
    _forward_job_events(q, "j1", logger=_L(), run=None, node_id="n", seen=seen)
    assert [m.rsplit(" ", 1)[-1] for m in msgs] == ["e0", "e1", "e2", "e3", "e4"]


# ── Blob authorization ────────────────────────────────────────────────────────


def test_blob_get_scoped_to_claimed_inputs(api_client, env):
    from app.core.distributed.transfer import put_blob_with_digest

    q = env
    uri_in, _ = put_blob_with_digest(b"input-bytes")
    uri_comp, _ = put_blob_with_digest(b"companion-bytes")
    uri_other, _ = put_blob_with_digest(b"someone-elses")
    key = lambda u: u.split("artifact://local/", 1)[1]  # noqa: E731
    _claimed(q, input_refs={"x": uri_in}, blob_grants=[key(uri_comp)])
    for u in (uri_in, uri_comp):
        r = api_client.get(f"/api/v1/artifacts/blob/{key(u)}", headers=W)
        assert r.status_code == 200, (u, r.text)
    r = api_client.get(f"/api/v1/artifacts/blob/{key(uri_other)}", headers=W)
    assert r.status_code == 403
    assert api_client.get(f"/api/v1/artifacts/blob/{key(uri_other)}", headers=OP).status_code == 200


def test_signing_secret_never_falls_back_to_api_token(monkeypatch):
    from app.core.distributed.transfer import blob_signing_secret, mint_signed_blob_url

    monkeypatch.delenv("GRAPHYN_BLOB_SIGNING_KEY", raising=False)
    monkeypatch.setenv("GRAPHYN_API_TOKEN", "op-tok")
    assert blob_signing_secret() == ""
    with pytest.raises(ValueError):
        mint_signed_blob_url("sha256/" + "a" * 64)


def test_signed_url_ttl_capped(monkeypatch):
    import time
    from urllib.parse import parse_qs, urlparse

    from app.core.distributed.transfer import BLOB_URL_MAX_TTL_S, mint_signed_blob_url

    url = mint_signed_blob_url("sha256/" + "a" * 64, ttl_s=10**9, secret="s")
    exp = int(parse_qs(urlparse("http://x/" + url).query)["exp"][0])
    assert exp <= time.time() + BLOB_URL_MAX_TTL_S + 2


def test_http_get_blob_refuses_foreign_origin():
    from app.core.distributed.transfer import http_get_blob

    with pytest.raises(ValueError, match="outside control origin"):
        http_get_blob(
            "http://graphyn-api:8001/api/v1",
            "http://evil.example/api/v1/artifacts/blob/sha256/aa?sig=x&exp=1",
            token="secret",
        )


def test_enqueue_records_blob_grants(env):
    from app.core.distributed.transfer import blob_keys_referenced

    payload = b"\x8c\x1aartifact://local/sha256/abc\x94\x8c\x1fartifact://local/jobs/j/g1/out\x00"
    assert blob_keys_referenced(payload) == ["jobs/j/g1/out", "sha256/abc"]


# ── mTLS identity ─────────────────────────────────────────────────────────────


def test_mtls_without_cert_fails_closed_on_worker_routes(api_client, env, monkeypatch):
    monkeypatch.setenv("GRAPHYN_MTLS_ENABLED", "1")
    r = api_client.post("/api/v1/jobs/claim", json={"worker_id": "s99-ml"}, headers=OP)
    assert r.status_code == 403
    assert "client certificate" in r.text


def test_mtls_test_header_refused_in_production(monkeypatch):
    from app.api.main import _mtls_test_header_enabled

    monkeypatch.setenv("GRAPHYN_MTLS_TEST_HEADER", "1")
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    assert _mtls_test_header_enabled()
    monkeypatch.setenv("GRAPHYN_ENV", "production")
    assert not _mtls_test_header_enabled()


def test_san_uri_must_match_whole_value():
    from app.core.distributed.mtls import worker_id_from_peercert

    good = {"subjectAltName": (("URI", "urn:graphyn:worker:s99-ml"),)}
    bad = {"subjectAltName": (("URI", "https://x/?u=urn:graphyn:worker:evil"),)}
    assert worker_id_from_peercert(good) == "s99-ml"
    assert worker_id_from_peercert(bad) is None


# ── Quotas ────────────────────────────────────────────────────────────────────


def test_pool_quota_counts_unpinned_claims(env, monkeypatch):
    monkeypatch.setenv("GRAPHYN_POOL_MAX_CLAIMED", "gpu-lab=1")
    q = env
    reg = get_worker_registry()
    reg.register(WorkerInfo(worker_id="a", plugins=["python_code"], pools=["gpu-lab"]))
    reg.register(WorkerInfo(worker_id="b", plugins=["python_code"], pools=["gpu-lab"]))
    q.enqueue(NodeJob(job_id="j1", run_id="r", node_id="n", node_type="python_code"))
    q.enqueue(NodeJob(job_id="j2", run_id="r", node_id="n", node_type="python_code"))
    first = q.claim(reg.get("a"))
    assert first is not None and first.claim_pools == ["gpu-lab"]
    assert q.claim(reg.get("b")) is None


def test_record_usage_is_atomic_increment(env):
    import threading

    from app.core.distributed.quotas import record_usage

    get_worker_registry().register(WorkerInfo(worker_id="a"))
    threads = [threading.Thread(target=record_usage, args=("a",), kwargs={"claims": 1}) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert get_worker_registry().get("a").usage_claims == 20


# ── VAL-PLACE for remote-only types ───────────────────────────────────────────


def test_val_place_runs_for_remote_only_types(env, monkeypatch):
    from app.core.execution.validation import validate_graph_ir_result
    from app.core.host.registry_runtime import get_registry
    from app.core.ir.models import GraphIR, IRMetadata, IRNode, IRPlacement

    monkeypatch.setenv("GRAPHYN_BACKEND", "distributed")
    get_worker_registry().register(WorkerInfo(worker_id="w", plugins=["remote_only_type"]))
    g = GraphIR(
        schema_version="1.2",
        metadata=IRMetadata(name="remote-place", seed=42),
        nodes=[IRNode(id="n1", node_type="remote_only_type", placement=IRPlacement(mode="pool"))],
        edges=[],
    )
    res = validate_graph_ir_result(g, get_registry())
    codes = [f.get("code") for f in res.get("errors", [])]
    assert "VAL-PLACE" in codes and "VAL-UNK-TYPE" not in codes


# ── Spool ─────────────────────────────────────────────────────────────────────


def test_spool_per_worker_dirs_and_job_ids(tmp_path, monkeypatch):
    from app.core.distributed.worker_spool import WorkerSpool

    monkeypatch.setenv("GRAPHYN_WORKER_SPOOL_DIR", str(tmp_path / "sp"))
    a = WorkerSpool(worker_id="a")
    b = WorkerSpool(worker_id="b")
    assert a.root != b.root
    a.enqueue_complete({"job_id": "j9", "lease_generation": 0})
    assert a.spooled_job_ids() == ["j9"]
    assert b.spooled_job_ids() == []
    assert not list((a.root / "items").glob("*.tmp"))


# ── ArtifactRef packing / hashing / hydrate ───────────────────────────────────


def _tree(root: Path) -> Path:
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("alpha")
    (root / "sub" / "b.bin").write_bytes(b"\x00\x01")
    (root / "empty.txt").write_bytes(b"")
    return root


def test_dir_pack_is_deterministic_and_streamed_hash_matches(tmp_path):
    import os
    import time

    from app.core.artifacts.artifact_pack import hash_path, pack_path_bytes

    d = _tree(tmp_path / "m")
    b1, kind = pack_path_bytes(d)
    os.utime(d / "a.txt", (time.time() + 100, time.time() + 100))
    b2, _ = pack_path_bytes(d)
    assert kind == "dir" and b1 == b2
    assert hash_path(d)[0] == hashlib.sha256(b1).hexdigest()


def test_hardlinks_dereferenced_and_empty_files_allowed(tmp_path):
    import os

    from app.core.artifacts.artifact_pack import pack_path_bytes, unpack_directory

    d = _tree(tmp_path / "m")
    os.link(d / "a.txt", d / "a_link.txt")
    data, _ = pack_path_bytes(d)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        assert not any(m.islnk() for m in tar.getmembers())
    out = tmp_path / "out"
    unpack_directory(data, out)
    assert (out / "a_link.txt").read_text() == "alpha"
    assert (out / "empty.txt").read_bytes() == b""
    assert pack_path_bytes(d / "empty.txt") == (b"", "file")


def test_unpack_allows_dotdot_prefixed_names(tmp_path):
    from app.core.artifacts.artifact_pack import pack_path_bytes, unpack_directory

    d = tmp_path / "m"
    d.mkdir()
    (d / "..data").write_text("ok")
    out = tmp_path / "o"
    unpack_directory(pack_path_bytes(d)[0], out)
    assert (out / "..data").read_text() == "ok"


def test_hydrate_reextracts_when_digest_changes(tmp_path):
    from app.core.artifacts.artifact_pack import hydrate_ref_bytes, pack_path_bytes
    from app.models.artifact_ref import ArtifactRef

    v1 = tmp_path / "v1"
    v1.mkdir()
    (v1 / "w.txt").write_text("one")
    v2 = tmp_path / "v2"
    v2.mkdir()
    (v2 / "w.txt").write_text("two")
    root = tmp_path / "hyd"
    for src, want in ((v1, "one"), (v2, "two")):
        data, _ = pack_path_bytes(src)
        ref = ArtifactRef(role="saved_model", kind="dir", relative_path="saved_model",
                          sha256=hashlib.sha256(data).hexdigest())
        out = hydrate_ref_bytes(ref, data, dest_root=root)
        assert (out / "w.txt").read_text() == want
    f = root / "model.keras"
    f.write_bytes(b"AAAA")
    ref = ArtifactRef(role="keras_model", relative_path="model.keras", sha256=hashlib.sha256(b"BBBB").hexdigest())
    hydrate_ref_bytes(ref, b"BBBB", dest_root=root)
    assert f.read_bytes() == b"BBBB"


def test_passthrough_ref_must_be_artifact_uri():
    from app.core.artifacts.artifact_pack import UnreclaimedHostPathError, apply_packed_refs
    from app.models.artifact_ref import ArtifactRef
    from app.models.model_artifact import ModelArtifact

    art = ModelArtifact(model_path="", labels=[], metrics={})
    bad = ArtifactRef(role="other", uri="http://evil/x", sha256="ab")
    with pytest.raises(UnreclaimedHostPathError):
        apply_packed_refs(art, [bad], put_companion=lambda b: ("artifact://local/x", "y"))


def test_existing_path_metrics_travel_as_roles(tmp_path):
    from app.core.artifacts.artifact_pack import collect_path_bearing_roles, materialize_refs_onto, apply_packed_refs
    from app.models.model_artifact import ModelArtifact

    ck = tmp_path / "ckpt.bin"
    ck.write_bytes(b"ck")
    art = ModelArtifact(model_path="", labels=[], metrics={"checkpoint_path": str(ck), "acc": 0.9})
    store: dict[str, bytes] = {}

    def put(b):
        d = hashlib.sha256(b).hexdigest()
        store[d] = b
        return f"artifact://local/sha256/{d}", d

    wire = apply_packed_refs(art, collect_path_bearing_roles(art), put_companion=put)
    assert wire.metrics["checkpoint_path"] == ""
    assert any(r.role == "metrics.checkpoint_path" for r in wire.refs)
    back = materialize_refs_onto(
        wire, dest_root=tmp_path / "h", get_companion=lambda uri, expected_sha256=None: store[expected_sha256]
    )
    assert Path(back.metrics["checkpoint_path"]).read_bytes() == b"ck"
    assert back.metrics["acc"] == 0.9


def test_model_serializer_round_trip_and_real_content_hash(tmp_path):
    from app.models.model_artifact import ModelArtifact
    from app.models.model_artifact_serializer import ModelArtifactHandler

    h = ModelArtifactHandler()
    m1 = tmp_path / "m1.pt"
    m1.write_bytes(b"weights-1")
    m2 = tmp_path / "m2.pt"
    m2.write_bytes(b"weights-2")
    a1 = ModelArtifact(model_path=str(m1), labels=["a"], metrics={"acc": 1})
    a2 = ModelArtifact(model_path=str(m2), labels=["a"], metrics={"acc": 1})
    assert h.compute_content_hash_input(a1) != h.compute_content_hash_input(a2)

    h.serialize(a1, tmp_path / "out")
    back = h.deserialize(tmp_path / "out")
    assert Path(back.model_path).read_bytes() == b"weights-1"
    assert str(tmp_path / "out") in back.model_path

    missing = ModelArtifact(model_path="/nope/saved_model", labels=[], metrics={"keras_model_path": "/nope/m.keras"})
    h.serialize(missing, tmp_path / "out2")
    back2 = h.deserialize(tmp_path / "out2")
    assert back2.model_path == "/nope/saved_model"
    assert back2.metrics["keras_model_path"] == "/nope/m.keras"


def test_role_manifest_files_listed(tmp_path):
    from app.core.artifacts.artifact_pack import role_manifest_file_paths
    from app.models.model_artifact import ModelArtifact
    from app.models.model_artifact_serializer import ModelArtifactHandler

    m = tmp_path / "model.keras"
    m.write_bytes(b"k")
    ModelArtifactHandler().serialize(
        ModelArtifact(model_path=str(m), labels=[], metrics={}), tmp_path / "data"
    )
    files = role_manifest_file_paths(tmp_path / "data")
    assert files and all(Path(f).is_file() for f in files)
    assert role_manifest_file_paths(tmp_path) is None
