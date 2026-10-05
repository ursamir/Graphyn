"""REST surface of the run audit record: record / verify / replay / drift /
archive-vs-purge / short-id resolution / actor + trigger stamping."""
from __future__ import annotations

import json
from pathlib import Path

from unit_test.core.test_audit_record_core import (  # noqa: F401 — aud_env is a fixture
    _run,
    _save_pipeline,
    aud_env,
    two_branch_graph,
)


def _get(api_client, url, **kw):
    resp = api_client.get(url, **kw)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_get_run_by_prefix_returns_record(api_client, aud_env):
    rm = _run()
    body = _get(api_client, f"/api/v1/runs/{rm.run_id[:10]}")
    assert body["run_id"] == rm.run_id
    assert body["record_status"] == "sealed"
    assert body["record"]["record_hash"] and body["record"]["schema_version"] == "2.0"
    assert body["pipeline_drift"] is None  # ad-hoc graph
    assert "Path B" in body["meta"]["node_labels"]["trainer_b"]
    # other endpoints resolve prefixes too
    assert _get(api_client, f"/api/v1/runs/{rm.run_id[:8]}/status")["status"] == "succeeded"
    assert _get(api_client, f"/api/v1/runs/{rm.run_id[:8]}/models")["run_id"] == rm.run_id
    resp = api_client.get(f"/api/v1/runs/{rm.run_id[:8]}/outputs")
    assert resp.status_code == 200


def test_ambiguous_and_short_prefix(api_client, aud_env):
    runs = aud_env / "runs"
    for rid in ("deadbeef0001", "deadbeef0002"):
        (runs / rid).mkdir(parents=True)
        (runs / rid / "meta.json").write_text(json.dumps({"run_id": rid, "status": "succeeded"}))
    resp = api_client.get("/api/v1/runs/deadbeef")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "run_id_ambiguous"
    assert detail["matches"] == ["deadbeef0001", "deadbeef0002"]
    short = api_client.get("/api/v1/runs/deadbee")
    assert short.status_code == 404 and short.json()["detail"]["code"] == "run_not_found"
    assert _get(api_client, "/api/v1/runs/deadbeef0002")["run_id"] == "deadbeef0002"
    cmp = api_client.get("/api/v1/experiments/compare?run_ids=deadbeef")
    assert cmp.status_code == 409


def test_verify_endpoint(api_client, aud_env):
    rm = _run()
    body = _get(api_client, f"/api/v1/runs/{rm.run_id}/verify")
    assert body["status"] == "pass" and body["ok"] is True
    (aud_env / "datasets" / "output" / "proj" / "v1" / "train" / "1.wav").unlink()
    body = _get(api_client, f"/api/v1/runs/{rm.run_id}/verify")
    assert body["status"] == "changed"


def test_replay_endpoint_and_input_check(api_client, aud_env):
    rm = _run()
    resp = api_client.post(f"/api/v1/runs/{rm.run_id[:9]}/replay", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["replay_of"] == rm.run_id and body["status"] == "pending"
    meta = json.loads((aud_env / "runs" / body["run_id"] / "meta.json").read_text())
    assert meta["replay_of"] == rm.run_id and meta["trigger"] == "replay"
    (aud_env / "datasets" / "output" / "proj" / "v1" / "train" / "0.wav").write_bytes(b"x")
    resp = api_client.post(f"/api/v1/runs/{rm.run_id}/replay", json={"check_inputs": True})
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "inputs_changed" and detail["changes"][0]["status"] == "changed"
    resp = api_client.post(f"/api/v1/runs/{rm.run_id}/replay", json={"check_inputs": True, "force": True})
    assert resp.status_code == 200


def test_drift_in_run_detail(api_client, aud_env):
    graph = two_branch_graph(project="proj")
    saved = _save_pipeline(aud_env, graph)
    rm = _run(graph)
    body = _get(api_client, f"/api/v1/runs/{rm.run_id}")
    assert body["record"]["pipeline_source"] == "saved"
    assert body["pipeline_drift"]["drifted"] is False
    data = json.loads(saved.read_text())
    data["nodes"][2]["config"]["architecture"] = "crnn"
    saved.write_text(json.dumps(data))
    drift = _get(api_client, f"/api/v1/runs/{rm.run_id}")["pipeline_drift"]
    assert drift["drifted"] is True and drift["current_hash"] != drift["run_graph_hash"]


def test_archive_restore_purge(api_client, aud_env):
    rm = _run()
    rid = rm.run_id
    resp = api_client.delete(f"/api/v1/runs/{rid}", headers={"X-Actor": "alice"})
    assert resp.status_code == 200 and resp.json()["archived"] is True
    assert (aud_env / "runs" / rid).is_dir()
    ids = [r["run_id"] for r in _get(api_client, "/api/v1/runs")]
    assert rid not in ids
    rows = _get(api_client, "/api/v1/runs?include_archived=1")
    assert any(r["run_id"] == rid and r.get("archived") for r in rows)
    assert _get(api_client, f"/api/v1/runs/{rid}")["meta"]["archived"] is True
    assert api_client.post(f"/api/v1/runs/{rid}/restore").json()["archived"] is False
    assert rid in [r["run_id"] for r in _get(api_client, "/api/v1/runs")]
    # purge requires the confirm header
    resp = api_client.delete(f"/api/v1/runs/{rid}?purge=true")
    assert resp.status_code == 428 and resp.json()["detail"]["code"] == "confirm_required"
    record_hash = json.loads((aud_env / "runs" / rid / "prove.json").read_text())["record_hash"]
    resp = api_client.delete(f"/api/v1/runs/{rid}?purge=true", headers={"X-Confirm-Purge": rid, "X-Actor": "admin"})
    assert resp.status_code == 200 and resp.json()["purged"] is True
    assert resp.json()["record_hash"] == record_hash
    assert not (aud_env / "runs" / rid).exists()
    events = _get(api_client, "/api/v1/audit?limit=100")
    events = events["events"] if isinstance(events, dict) else events
    acts = {(e["action"], e["actor"]) for e in events if e.get("resource_id") == rid}
    assert ("run.archive", "alice") in acts and ("run.purge", "admin") in acts
    assert ("run.finish", "alice") in acts and ("run.restore", "unidentified") in acts


def test_run_async_stamps_actor_trigger_and_declared_pipeline(api_client, aud_env):
    from app.core.ir.loader import dump_ir

    payload = {"graph": dump_ir(two_branch_graph(project="proj")), "trigger": "ui",
               "pipeline": "audtest", "pipeline_env": "draft"}
    resp = api_client.post("/api/v1/pipelines/run-async", json=payload, headers={"X-Actor": "carol"})
    assert resp.status_code == 200, resp.text
    rid = resp.json()["run_id"]
    meta = json.loads((aud_env / "runs" / rid / "meta.json").read_text())
    assert meta["actor"] == "carol" and meta["trigger"] == "ui"
    assert meta["pipeline_name"] == "audtest" and meta["pipeline_env"] == "draft"


def test_audit_filters_paging_and_project(api_client, aud_env):
    from app.core.trust.audit import record_audit

    for i in range(5):
        record_audit(actor="x", action="noise.event", resource_type="other", resource_id=f"n{i}")
    rm = _run(two_branch_graph(project="proj"))
    body = _get(api_client, f"/api/v1/audit?run_id={rm.run_id[:8]}")
    acts = {e["action"] for e in body["events"]}
    assert "run.finish" in acts and all(e["resource_id"] == rm.run_id for e in body["events"])
    fin = next(e for e in body["events"] if e["action"] == "run.finish")
    assert fin["metadata"]["project"] == "proj"
    page = _get(api_client, "/api/v1/audit?action=noise.event&limit=2&offset=2")
    assert page["total"] == 5 and len(page["events"]) == 2 and page["has_more"] is True
    assert [e["resource_id"] for e in page["events"]] == ["n2", "n1"]
    hits = _get(api_client, "/api/v1/audit?q=N3")
    assert [e["resource_id"] for e in hits["events"]] == ["n3"]
