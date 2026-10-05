"""Trustworthy audit trail: token-bound identity, GET /me, persisted verify,
model lineage (made from / used in), run compare diff, audit labels/categories."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from unit_test.core.test_audit_record_core import (  # noqa: F401 — aud_env is a fixture
    DATA,
    _run,
    aud_env,
    two_branch_graph,
)


def _get(api_client, url, **kw):
    resp = api_client.get(url, **kw)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _events(api_client, headers=None, **params):
    qs = "".join(f"&{k}={v}" for k, v in params.items())
    return _get(api_client, f"/api/v1/audit?limit=200{qs}", headers=headers or {})["events"]


# ── token map parsing ─────────────────────────────────────────────────────────


def test_parse_token_map_formats(tmp_path, monkeypatch):
    from app.core.trust.identity import load_token_map, lookup_token, parse_token_map

    assert parse_token_map('{"t1": "alice", "t2": " bob ", "": "x"}') == {"t1": "alice", "t2": "bob"}
    assert parse_token_map("alice:t1, bob:t2\n# c\ncarol:") == {"t1": "alice", "t2": "bob"}
    assert parse_token_map("{bad json") == {}
    f = tmp_path / "tokens.txt"
    f.write_text("dave:t4\n")
    monkeypatch.setenv("GRAPHYN_API_TOKENS_FILE", str(f))
    monkeypatch.setenv("GRAPHYN_API_TOKENS", "alice:t1")
    assert load_token_map() == {"t4": "dave", "t1": "alice"}
    assert lookup_token("t4") == "dave" and lookup_token("nope") is None


# ── GET /me + auth with mapped tokens ─────────────────────────────────────────


def test_me_unmapped_and_mapped(api_client, aud_env, monkeypatch):
    me = _get(api_client, "/api/v1/me")
    assert me == {"actor": "unidentified", "actor_verified": False, "token_mapped": False,
                  "claimed_actor": None, "auth_configured": False, "token_map_configured": False}
    assert _get(api_client, "/api/v1/me", headers={"X-Actor": "eve"})["actor"] == "eve"

    monkeypatch.setenv("GRAPHYN_API_TOKEN", "single")
    monkeypatch.setenv("GRAPHYN_API_TOKENS", '{"tok-alice": "alice"}')
    assert api_client.get("/api/v1/me").status_code == 401
    assert api_client.get("/api/v1/me", headers={"Authorization": "Bearer wrong"}).status_code == 401
    me = _get(api_client, "/api/v1/me", headers={"Authorization": "Bearer tok-alice", "X-Actor": "bob"})
    assert me["actor"] == "alice" and me["actor_verified"] is True and me["token_mapped"] is True
    assert me["claimed_actor"] == "bob"
    me = _get(api_client, "/api/v1/me", headers={"Authorization": "Bearer single", "X-Actor": "bob"})
    assert me["actor"] == "bob" and me["actor_verified"] is False and me["claimed_actor"] is None
    status = _get(api_client, "/api/v1/system/auth-status")
    assert status["token_configured"] is True and status["token_map_configured"] is True


def test_map_only_requires_token(api_client, aud_env, monkeypatch):
    monkeypatch.setenv("GRAPHYN_API_TOKENS", "alice:tok-a")
    assert api_client.get("/api/v1/runs").status_code == 401
    assert api_client.get("/api/v1/runs", headers={"Authorization": "Bearer tok-a"}).status_code == 200


def test_mutations_record_token_identity(api_client, aud_env, monkeypatch):
    rm = _run()
    monkeypatch.setenv("GRAPHYN_API_TOKENS", '{"tok-alice": "alice"}')
    h = {"Authorization": "Bearer tok-alice", "X-Actor": "mallory"}
    assert api_client.delete(f"/api/v1/runs/{rm.run_id}", headers=h).status_code == 200
    assert api_client.post("/api/v1/system/cleanup", json={"older_than_days": 3650}, headers=h).status_code == 200
    assert api_client.post("/api/v1/system/notifications/mark-read", json={"all": True}, headers=h).status_code == 200
    evs = _events(api_client, headers=h)
    archive = next(e for e in evs if e["action"] == "run.archive")
    assert archive["actor"] == "alice" and archive["actor_verified"] is True
    assert archive["claimed_actor"] == "mallory" and archive["origin"] == "http"
    cleanup = next(e for e in evs if e["action"] == "system.cleanup")
    assert cleanup["actor"] == "alice" and cleanup["actor_verified"] is True
    # unmapped token: header actor recorded but unverified; never "system"/"api"
    monkeypatch.setenv("GRAPHYN_API_TOKEN", "single")
    resp = api_client.post(f"/api/v1/runs/{rm.run_id}/restore", headers={"Authorization": "Bearer single"})
    assert resp.status_code == 200
    restore = next(e for e in _events(api_client, headers=h, action="run.restore") if e["resource_id"] == rm.run_id)
    assert restore["actor"] == "unidentified" and restore["actor_verified"] is False


def test_run_meta_and_record_carry_actor_verified(api_client, aud_env, monkeypatch):
    from app.core.ir.loader import dump_ir
    from app.core.runs.audit_record import build_record

    monkeypatch.setenv("GRAPHYN_API_TOKENS", "carol:tok-c")
    payload = {"graph": dump_ir(two_branch_graph()), "trigger": "ui"}
    resp = api_client.post("/api/v1/pipelines/run-async", json=payload,
                           headers={"Authorization": "Bearer tok-c", "X-Actor": "zed"})
    assert resp.status_code == 200, resp.text
    run_dir = aud_env / "runs" / resp.json()["run_id"]
    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["actor"] == "carol" and meta["actor_verified"] is True and meta["claimed_actor"] == "zed"
    rec = build_record(run_dir, run_id=run_dir.name, status="succeeded", meta=meta, graph={}, include_outputs=False)
    assert rec["actor"] == "carol" and rec["actor_verified"] is True and rec["claimed_actor"] == "zed"


def test_background_audit_is_system_unverified(aud_env):
    from app.core.trust.audit import record_audit

    ev = record_audit(actor="", action="ops.shutdown_drain", resource_type="host", resource_id="h")
    assert ev["actor"] == "system" and ev["actor_verified"] is False and ev["origin"] == "internal"


# ── verify persistence ────────────────────────────────────────────────────────


def test_verify_is_recorded_without_touching_record(api_client, aud_env, monkeypatch):
    rm = _run()
    run_dir = Path(rm.base_path)
    prove_before = (run_dir / "prove.json").read_bytes()
    assert _get(api_client, f"/api/v1/runs/{rm.run_id}")["last_verify"] is None
    monkeypatch.setenv("GRAPHYN_API_TOKENS", "vera:tok-v")
    body = _get(api_client, f"/api/v1/runs/{rm.run_id[:8]}/verify", headers={"Authorization": "Bearer tok-v"})
    assert body["status"] == "pass" and body["ok"] is True and body["checks"]
    assert body["actor"] == "vera" and body["actor_verified"] is True
    assert body["summary"]["passed"] == body["summary"]["total"] > 0
    resp = api_client.post(f"/api/v1/runs/{rm.run_id}/verify", headers={"Authorization": "Bearer tok-v"})
    assert resp.status_code == 200 and resp.json()["history_count"] == 2
    hist = json.loads((run_dir / "verify.json").read_text())["history"]
    assert len(hist) == 2 and all(h["actor"] == "vera" and h["checks"] for h in hist)
    assert (run_dir / "prove.json").read_bytes() == prove_before
    detail = _get(api_client, f"/api/v1/runs/{rm.run_id}", headers={"Authorization": "Bearer tok-v"})
    lv = detail["last_verify"]
    assert lv["actor"] == "vera" and lv["ok"] is True and lv["passed"] == lv["total"] > 0 and lv["checked_at"]
    rows = _get(api_client, "/api/v1/runs", headers={"Authorization": "Bearer tok-v"})
    assert next(r for r in rows if r["run_id"] == rm.run_id)["last_verify"]["actor"] == "vera"
    evs = _events(api_client, headers={"Authorization": "Bearer tok-v"}, action="run.verified")
    assert len(evs) == 2 and evs[0]["label"] == "Run verified" and evs[0]["category"] == "run"
    assert evs[0]["metadata"]["ok"] is True
    # a second verify still passes: verify.json is not part of any hashed output
    assert _get(api_client, f"/api/v1/runs/{rm.run_id}/verify", headers={"Authorization": "Bearer tok-v"})["ok"]
    hist = _get(api_client, f"/api/v1/runs/{rm.run_id}/verify/history", headers={"Authorization": "Bearer tok-v"})
    assert hist["total"] == 3 and len(hist["history"]) == 3


# ── compare diff ──────────────────────────────────────────────────────────────


def test_compare_diff(api_client, aud_env):
    a = _run()
    from app.core.ir.loader import dump_ir, load_ir

    data = dump_ir(two_branch_graph())
    data = json.loads(data) if isinstance(data, str) else data
    data["nodes"][2]["config"]["architecture"] = "crnn"
    data["nodes"][1]["config"]["epochs"] = 3
    b = _run(load_ir(data))
    body = _get(api_client, f"/api/v1/runs/compare/diff?ids={a.run_id[:8]},{b.run_id}")
    assert [r["run_id"] for r in body["runs"]] == [a.run_id, b.run_id]
    assert body["runs"][0]["short"] == a.run_id[:8] and body["runs"][0]["seed"] == 7
    keys = {(s["node_id"], s["key"]): s for s in body["settings"]}
    assert keys[("trainer_b", "architecture")]["values"] == ["mobilenet", "crnn"]
    ep = keys[("trainer_a", "epochs")]
    assert ep["values"] == [1, 3] and ep["default"] == 1
    assert all(s["differs"] for s in body["settings"])
    assert ("reader", "path") not in keys  # equal rows hidden by default
    summ = body["summary"]
    assert summ["settings_changed"] == len(body["settings"]) == 2
    assert summ["data_same"] is True and summ["code_same"] is True and summ["environment_same"] is True
    assert summ["graph_same"] is False
    assert body["data"] == [] and body["code"] == [] and body["environment"] == []
    full = _get(api_client, f"/api/v1/runs/compare/diff?ids={a.run_id},{b.run_id}&all=1")
    assert any(s["node_id"] == "reader" and s["key"] == "path" for s in full["settings"])
    assert full["data"] and full["data"][0]["content_hashes"][0] == full["data"][0]["content_hashes"][1]
    assert api_client.get(f"/api/v1/runs/compare/diff?ids={a.run_id}").status_code == 422
    assert api_client.get("/api/v1/runs/compare/diff?ids=zzzzzzzz9,zzzzzzzz8").status_code == 404


# ── model lineage ─────────────────────────────────────────────────────────────


def test_model_lineage_made_from_and_used_in(api_client, aud_env):
    from app.core.ir.models import GraphIR, IRMetadata, IRNode
    from app.core.mlops.model_lineage import clear_lineage_cache
    from app.core.mlops.model_registry import _register

    clear_lineage_cache()
    src = _run()
    rec = json.loads((Path(src.base_path) / "prove.json").read_text())
    out = next(o for o in rec["outputs"] if o["node_id"] == "trainer_a")
    _register("kws", run_id=src.run_id, slug="audtest", stage="staging", description=None, actor="t",
              base_dir=None, artifact={"artifact_path": out["path"], "node_id": "trainer_a", "path_id": "path-a"})
    consumer = _run(GraphIR(schema_version="1.2", metadata=IRMetadata(name="ship-kws", seed=1),
                            nodes=[IRNode(id="reader", node_type="aud_reader", config={"path": out["path"]})],
                            edges=[]))
    body = _get(api_client, "/api/v1/models/kws/lineage")
    st = body["stages"]["staging"]
    assert st["run_id"] == src.run_id and st["node_id"] == "trainer_a" and st["path_id"] == "path-a"
    assert st["model_hash"].startswith("sha256:")
    mf = st["made_from"]
    assert mf["graph_hash"] == rec["graph_hash"] and mf["seed"] == 7
    assert mf["step_config"]["architecture"] == "ds_cnn"
    assert mf["node"]["node_type"] == "aud_trainer" and mf["node"]["plugin_version"]
    ds = next(d for d in mf["datasets"] if d["path"] == DATA)
    assert ds["content_hash"] and ds["file_count"] == 3
    used = body["used_in"]
    assert [u["run_id"] for u in used] == [consumer.run_id]
    assert used[0]["stage"] == "staging" and used[0]["actor"] == "alice" and used[0]["trigger"] == "ui"
    assert used[0]["short"] == consumer.run_id[:8]
    # cached second call returns the same
    assert _get(api_client, "/api/v1/models/kws/lineage")["used_in"] == used
    assert api_client.get("/api/v1/models/nope/lineage").status_code == 404


# ── audit labels / categories ─────────────────────────────────────────────────


def test_audit_labels_and_category_filters(api_client, aud_env):
    from app.core.trust.audit import audit_category, audit_label, record_audit

    record_audit(actor="u", action="model.register", resource_type="model", resource_id="m@staging")
    record_audit(actor="u", action="notifications.mark_read", resource_type="notification", resource_id="all")
    record_audit(actor="u", action="schedule.tick", resource_type="schedule", resource_id="x")
    record_audit(actor="u", action="run.archive", resource_type="run", resource_id="r1")
    evs = _events(api_client)
    by = {e["action"]: e for e in evs}
    assert by["model.register"]["label"] == "Model registered" and by["model.register"]["category"] == "model"
    assert by["notifications.mark_read"]["label"] == "Notifications marked read"
    assert by["notifications.mark_read"]["category"] == "ui"
    assert by["schedule.tick"]["category"] == "system" and by["run.archive"]["category"] == "run"
    kept = {e["action"] for e in _events(api_client, exclude_category="ui,system")}
    assert kept == {"model.register", "run.archive"}
    assert {e["action"] for e in _events(api_client, category="run")} == {"run.archive"}
    assert audit_label("ship.validate") == "Ship package validate"
    assert audit_label("foo.bar_baz") == "Foo bar baz" and audit_category("foo.x") == "system"
    assert audit_category("credential.create") == "admin"


@pytest.mark.parametrize("trainer_lr,expected", [(0.01, "lr 0.01"), (None, "lr 0.002")])
def test_path_label_learning_rate_trainer_wins(trainer_lr, expected):
    from app.core.runs.run_summary import compute_paths, path_labels

    def branch(i, lr_t):
        return [
            {"id": f"b{i}", "node_type": "model_builder", "config": {"architecture": "ds_cnn", "learning_rate": 0.002}},
            {"id": f"t{i}", "node_type": "trainer", "config": {"epochs": 5, "learning_rate": lr_t}},
        ]

    graph = {
        "nodes": [{"id": "src", "node_type": "reader", "config": {}}] + branch(1, trainer_lr) + branch(2, 0.5),
        "edges": [
            {"src_id": "src", "dst_id": "b1"}, {"src_id": "b1", "dst_id": "t1"},
            {"src_id": "src", "dst_id": "b2"}, {"src_id": "b2", "dst_id": "t2"},
        ],
    }
    labels = path_labels(graph, compute_paths(graph))
    assert labels["path-a"] == expected and labels["path-b"] == "lr 0.5"
