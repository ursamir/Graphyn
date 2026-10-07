"""Mode B Swarm-style join: join tokens, control-assigned ids, worker
credentials, CA-signed certs, enrollment enforcement, rotation, revocation."""
from __future__ import annotations

import json
import subprocess

import pytest

from app.core.distributed.queue import _reset_job_queue
from app.core.distributed.registry import _reset_worker_registry, get_worker_registry
from app.core.trust.users import get_user_store, reset_user_store

OP = {"Authorization": "Bearer op-token"}


@pytest.fixture(autouse=True)
def patch_threads(real_threads):
    yield


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GRAPHYN_USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("GRAPHYN_API_TOKEN", "op-token")
    for k in (
        "GRAPHYN_API_TOKENS",
        "GRAPHYN_AUTH_REQUIRED",
        "GRAPHYN_LEGACY_TOKEN_DISABLED",
        "GRAPHYN_MTLS_ENABLED",
        "GRAPHYN_MTLS_CERT",
        "GRAPHYN_MTLS_KEY",
        "GRAPHYN_MTLS_CLIENT_CERT",
        "GRAPHYN_MTLS_CLIENT_KEY",
        "GRAPHYN_MTLS_TEST_HEADER",
        "GRAPHYN_WORKER_TRUST_REQUIRED",
    ):
        monkeypatch.delenv(k, raising=False)
    from app.core.distributed.mtls import generate_modeb_mtls_certs

    paths = generate_modeb_mtls_certs(tmp_path / "certs", worker_ids=["unused"])
    monkeypatch.setenv("GRAPHYN_MTLS_CA_CERT", str(paths["ca_cert"]))
    monkeypatch.setenv("GRAPHYN_MTLS_CA_KEY", str(paths["ca_key"]))
    reset_user_store()
    _reset_worker_registry()
    _reset_job_queue(use_memory=True, lease_ttl_s=60.0)
    yield paths
    reset_user_store()
    _reset_worker_registry()
    _reset_job_queue(use_memory=True)


def _csr(tmp_path, cn="evil-other-worker"):
    key = tmp_path / "w.key"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", str(key)],
        check=True,
        capture_output=True,
    )
    return subprocess.run(
        ["openssl", "req", "-new", "-key", str(key), "-subj", f"/CN={cn}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _mint(client, **body):
    r = client.post("/api/v1/workers/join-tokens", json={"pool": "conf-lab", "labels": ["gpu", "confidential"], **body}, headers=OP)
    assert r.status_code == 200, r.text
    return r.json()


def _join(client, token, tmp_path=None, name="edge"):
    body = {"token": token, "name": name, "hostname": "host-a"}
    if tmp_path is not None:
        body["csr_pem"] = _csr(tmp_path)
    return client.post("/api/v1/workers/join", json=body)


def test_join_assigns_identity_signs_cert_and_preregisters(api_client, env, tmp_path):
    minted = _mint(api_client, allowed_plugins=["set_map"], max_uses=1)
    assert minted["token"].startswith("gxj_") and minted["join_token"]["uses"] == 0
    r = _join(api_client, minted["token"], tmp_path)
    assert r.status_code == 200, r.text
    out = r.json()
    wid = out["worker_id"]
    assert wid.startswith("edge-") and out["token"].startswith("gxw_") and out["cert_status"] == "issued"
    # Cert carries the control-assigned id, not the CSR's subject.
    from app.core.distributed.mtls import worker_id_from_pem

    assert worker_id_from_pem(out["cert_pem"]) == wid
    subj = subprocess.run(["openssl", "x509", "-noout", "-subject"], input=out["cert_pem"], capture_output=True, text=True).stdout
    assert f"CN = {wid}" in subj and "evil" not in subj
    w = get_worker_registry().get(wid)
    assert w.pools == ["conf-lab"] and w.labels == ["gpu", "confidential"] and w.allowed_plugins == ["set_map"] and w.trusted
    # single use
    assert _join(api_client, minted["token"]).status_code == 401
    listed = api_client.get("/api/v1/workers/join-tokens", params={"include_inactive": True}, headers=OP).json()
    assert listed[0]["workers"] == [wid] and listed[0]["active"] is False
    enr = api_client.get("/api/v1/workers/enrollments", headers=OP).json()
    assert enr[0]["worker_id"] == wid and enr[0]["cert_fingerprint"] == out["cert_fingerprint"]
    events = api_client.get("/api/v1/audit", params={"limit": 50}, headers=OP).json()
    rows = events.get("events") if isinstance(events, dict) else events
    joined = [e for e in rows if e.get("action") == "worker.join"]
    assert joined and joined[0]["meta"]["credential_id"] == out["credential_id"]
    assert any(e.get("action") == "worker.join_denied" for e in rows)


def test_worker_credential_scope_and_enrollment_enforced(api_client, env):
    out = _join(api_client, _mint(api_client)["token"]).json()
    wid, h = out["worker_id"], {"Authorization": f"Bearer {out['token']}"}
    me_body = {"worker_id": wid, "labels": ["cpu"], "pools": ["public"], "plugins": ["set_map"]}
    r = api_client.post("/api/v1/workers/register", json=me_body, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["pools"] == ["conf-lab"] and r.json()["labels"] == ["gpu", "confidential"]
    assert api_client.post("/api/v1/workers/register", json={**me_body, "worker_id": "other"}, headers=h).status_code == 403
    assert api_client.get("/api/v1/runs", headers=h).status_code == 403
    assert api_client.post("/api/v1/workers/join-tokens", json={}, headers=h).status_code == 403
    assert api_client.post(f"/api/v1/workers/{wid}/heartbeat", json={}, headers=h).status_code == 200
    # Operator relabel survives the worker's next register.
    api_client.patch(f"/api/v1/workers/{wid}", json={"labels": ["gpu"]}, headers=OP)
    assert api_client.post("/api/v1/workers/register", json=me_body, headers=h).json()["labels"] == ["gpu"]


def test_rotate_then_revoke(api_client, env, tmp_path, monkeypatch):
    out = _join(api_client, _mint(api_client)["token"], tmp_path).json()
    wid, old = out["worker_id"], {"Authorization": f"Bearer {out['token']}"}
    r = api_client.post(f"/api/v1/workers/{wid}/credentials/rotate", json={"csr_pem": _csr(tmp_path)}, headers=old)
    assert r.status_code == 200, r.text
    new = {"Authorization": f"Bearer {r.json()['token']}"}
    assert r.json()["revoked_credentials"] == 1 and r.json()["cert_status"] == "issued"
    assert api_client.post(f"/api/v1/workers/{wid}/heartbeat", json={}, headers=old).status_code == 401
    assert api_client.post(f"/api/v1/workers/{wid}/heartbeat", json={}, headers=new).status_code in (200, 404)
    creds = api_client.get(f"/api/v1/workers/{wid}/credentials", params={"include_inactive": True}, headers=OP).json()
    assert len(creds["credentials"]) == 2
    rv = api_client.post(f"/api/v1/workers/{wid}/revoke", headers=OP)
    assert rv.status_code == 200 and rv.json()["revoked_credentials"] == 1
    assert get_worker_registry().get(wid) is None
    assert api_client.post(f"/api/v1/workers/{wid}/heartbeat", json={}, headers=new).status_code == 401
    # Cert identity of a revoked worker is refused too.
    monkeypatch.setenv("GRAPHYN_MTLS_ENABLED", "1")
    monkeypatch.setenv("GRAPHYN_MTLS_TEST_HEADER", "1")
    r = api_client.post(
        "/api/v1/workers/register",
        json={"worker_id": wid},
        headers={"x-graphyn-mtls-worker-id": wid},
    )
    assert r.status_code == 403 and "revoked" in r.text


def test_join_without_ca_key_gives_bearer_only(api_client, env, tmp_path, monkeypatch):
    monkeypatch.delenv("GRAPHYN_MTLS_CA_KEY", raising=False)
    out = _join(api_client, _mint(api_client)["token"], tmp_path).json()
    assert out["cert_status"] == "unavailable" and out["cert_pem"] is None and out["token"]


def test_rbac_user_needs_workers_admin(api_client, env):
    store = get_user_store()
    store.create_user("ops", "correct-horse-1", roles=["operator"])
    store.create_user("bld", "correct-horse-1", roles=["builder"])

    def login(u):
        t = api_client.post("/api/v1/auth/login", json={"username": u, "password": "correct-horse-1"}).json()["token"]
        return {"Authorization": f"Bearer {t}"}

    assert api_client.post("/api/v1/workers/join-tokens", json={}, headers=login("bld")).status_code == 403
    r = api_client.post("/api/v1/workers/join-tokens", json={"pool": "p"}, headers=login("ops"))
    assert r.status_code == 200 and r.json()["join_token"]["created_by"] == "ops"
    out = _join(api_client, r.json()["token"]).json()
    assert get_user_store().get_enrollment(out["worker_id"])["enrolled_by"] == "ops"


def test_cli_join_saves_enrollment_and_start_uses_it(api_client, env, tmp_path, monkeypatch):
    import argparse

    import app.cli.cmd_worker_join as cj

    monkeypatch.setenv("GRAPHYN_WORKER_ENROLLMENT_DIR", str(tmp_path / "enr"))

    def fake_post(url, payload, *, token=None, ctx=None):
        path = url.split("/api/v1", 1)[1]
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = api_client.post(f"/api/v1{path}", json=payload, headers=headers)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text}")
        return r.json()

    monkeypatch.setattr(cj, "_post", fake_post)
    tok = _mint(api_client)["token"]
    args = argparse.Namespace(
        control_url="http://ctl/api/v1", token=tok, name="lab", worker_control_url=None,
        ca_cert=None, no_cert=False, force=False,
    )
    cj.cmd_worker_join(args)
    state = cj.load_enrollment()
    assert state["worker_id"].startswith("lab-") and state["token"].startswith("gxw_")
    assert (tmp_path / "enr" / "cert.pem").is_file() and (tmp_path / "enr" / "key.pem").stat().st_mode & 0o077 == 0
    raw = json.loads((tmp_path / "enr" / "enrollment.json").read_text())
    assert "cert_pem" not in raw
    with pytest.raises(SystemExit):
        cj.cmd_worker_join(args)  # already enrolled
    rotated = cj.rotate_if_due(state, "http://ctl/api/v1", force=True)
    assert rotated["credential_id"] != state["credential_id"]
    # https control → enrollment cert becomes the mTLS client identity
    for k in ("GRAPHYN_MTLS_CLIENT_CERT", "GRAPHYN_MTLS_CLIENT_KEY", "GRAPHYN_MTLS_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("GRAPHYN_MTLS_CA_CERT", raising=False)
    cj.apply_enrollment_mtls_env(rotated, "https://ctl/api/v1")
    import os

    assert os.environ["GRAPHYN_MTLS_CLIENT_CERT"].endswith("cert.pem")
    assert os.environ["GRAPHYN_MTLS_CA_CERT"].endswith("ca.pem")


# ── lineage ───────────────────────────────────────────────────────────────────


def test_complete_records_control_observed_provenance(api_client, env):
    from app.core.distributed.models import NodeJob
    from app.core.distributed.queue import get_job_queue

    out = _join(api_client, _mint(api_client, allowed_plugins=["set_map"])["token"]).json()
    wid, h = out["worker_id"], {"Authorization": f"Bearer {out['token']}"}
    api_client.post("/api/v1/workers/register", json={"worker_id": wid, "plugins": ["set_map"]}, headers=h)
    get_job_queue().enqueue(NodeJob(job_id="j1", run_id="r1", node_id="n1", node_type="set_map", pool="conf-lab"))
    claimed = api_client.post("/api/v1/jobs/claim", json={"worker_id": wid}, headers=h).json()["job"]
    assert claimed and claimed["job_id"] == "j1"
    forged = {"type": "provenance", "worker_id": "someone-else", "principal": {"user_id": "u_fake"}}
    r = api_client.post(
        "/api/v1/jobs/j1/complete",
        json={"job_id": "j1", "status": "succeeded", "worker_id": wid,
              "lease_generation": claimed["lease_generation"], "events": [forged]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    from app.core.distributed.backend import _node_execution_lineage

    result = get_job_queue().get_result("j1")
    provs = [e for e in result.events if e.get("type") == "provenance"]
    assert len(provs) == 1 and provs[0]["worker_id"] == wid
    row = _node_execution_lineage(get_job_queue().get("j1"), result, "set_map")
    assert row["principal"]["credential_id"] == out["credential_id"]
    assert row["principal"]["auth_method"] == "worker_credential"
    assert row["enrollment"]["join_token_id"] == out["join_token_id"] and row["worker"]["pools"] == ["conf-lab"]


def test_run_record_accountability(tmp_path, env, monkeypatch):
    import app.core.runs.audit_record as ar

    pdir = tmp_path / "proj"
    vdir = pdir / "pipelines" / "versions" / "flow"
    monkeypatch.setattr(ar, "_project_pipelines_dir", lambda p: pdir)
    import app.core.pipelines.pipeline_environments as pe

    monkeypatch.setattr(pe, "versions_dir", lambda d, n: vdir)
    vdir.mkdir(parents=True)
    (vdir / "v3.graph.json").write_text(json.dumps({"_publish": {"actor": "bob", "published_at": "t"}}))
    meta = {
        "actor": "alice",
        "actor_verified": True,
        "principal": {"kind": "user", "user_id": "u_1", "credential_id": "c1", "auth_method": "session"},
        "pipeline_ref": {"project": "p", "name": "flow", "version": "v3", "env": "prod", "match": "content"},
        "distributed_node_workers": {"a": "local", "b": "edge-1"},
        "distributed_node_lineage": {"b": {"worker_id": "edge-1", "principal": {"credential_id": "cw"}}},
    }
    acc = ar._accountability(tmp_path, "r1", meta)
    assert acc["built_by"]["published_by"] == "bob" and acc["built_by"]["version"] == "v3"
    assert acc["run_by"]["principal"]["user_id"] == "u_1" and acc["run_by"]["actor_verified"]
    assert acc["executed_by"]["a"] == {"worker_id": "local"}
    assert acc["executed_by"]["b"]["principal"]["credential_id"] == "cw"
