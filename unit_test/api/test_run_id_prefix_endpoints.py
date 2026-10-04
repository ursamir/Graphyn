"""Every REST endpoint that takes a run id resolves unique short prefixes
(>= 8 chars) to the FULL id: ambiguous → 409 ``run_id_ambiguous``, unknown →
404 ``run_not_found`` with a human message. Also: run rows carry best-path
metrics."""
from __future__ import annotations

import json

import pytest

from unit_test.core.test_audit_record_core import _run, aud_env  # noqa: F401 — aud_env is a fixture


def _ok(resp):
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def test_register_model_with_short_run_id_stores_full_id(api_client, aud_env):
    rm = _run()
    body = _ok(api_client.post(
        "/api/v1/models",
        json={"name": "audm", "run_id": rm.run_id[:8], "slug": "audtest", "allow_untrained": True},
    ))
    assert body["source_run_id"] == rm.run_id
    assert body["stages"]["staging"]["run_id"] == rm.run_id
    # request-prod body run_id prefix too
    rp = api_client.post("/api/v1/models/audm/request-prod", json={"run_id": rm.run_id[:9]})
    assert rp.status_code == 200, rp.text
    assert rp.json()["pending_prod"]["run_id"] == rm.run_id


def test_register_model_unknown_and_ambiguous(api_client, aud_env):
    runs = aud_env / "runs"
    for rid in ("cafebabe0001", "cafebabe0002"):
        (runs / rid).mkdir(parents=True)
        (runs / rid / "meta.json").write_text(json.dumps({"run_id": rid, "status": "succeeded"}))
    amb = api_client.post("/api/v1/models", json={"name": "m1", "run_id": "cafebabe", "slug": "x"})
    assert amb.status_code == 409
    d = amb.json()["detail"]
    assert d["code"] == "run_id_ambiguous" and len(d["matches"]) == 2 and "cafebabe" in d["message"]
    nf = api_client.post("/api/v1/models", json={"name": "m1", "run_id": "0badc0de99", "slug": "x"})
    assert nf.status_code == 404
    assert nf.json()["detail"]["code"] == "run_not_found"
    assert "0badc0de99" in nf.json()["detail"]["message"]


def test_trace_with_short_run_id(api_client, aud_env):
    rm = _run()
    body = _ok(api_client.get(f"/api/v1/trace?run_id={rm.run_id[:8]}"))
    assert body["run"]["run_id"] == rm.run_id
    assert not any(str(w).startswith("run_not_found") for w in body.get("warnings") or [])
    via_path = _ok(api_client.get(f"/api/v1/trace/run/{rm.run_id[:8]}"))
    assert via_path["run"]["run_id"] == rm.run_id


def test_trace_ambiguous_prefix_is_409(api_client, aud_env):
    runs = aud_env / "runs"
    for rid in ("abcdabcd0001", "abcdabcd0002"):
        (runs / rid).mkdir(parents=True)
        (runs / rid / "meta.json").write_text(json.dumps({"run_id": rid}))
    resp = api_client.get("/api/v1/trace?run_id=abcdabcd")
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "run_id_ambiguous"


def test_run_subresources_and_artifacts_filter_resolve_prefix(api_client, aud_env):
    rm = _run()
    short = rm.run_id[:8]
    for sub in ("", "/graph", "/status", "/checkpoints", "/artifacts", "/provenance", "/outputs",
                "/models", "/verify", "/debug-report"):
        resp = api_client.get(f"/api/v1/runs/{short}{sub}")
        assert resp.status_code == 200, (sub, resp.text)
    arts = api_client.get(f"/api/v1/artifacts?run_id={short}&envelope=0")
    assert arts.status_code == 200
    full = api_client.get(f"/api/v1/artifacts?run_id={rm.run_id}&envelope=0")
    assert arts.json() == full.json()
    # unknown run → human 404
    nf = api_client.get("/api/v1/runs/feedface1234/status")
    assert nf.status_code == 404 and "feedface1234" in nf.json()["detail"]["message"]


def test_cancel_finished_run_by_prefix_is_idempotent_with_full_id(api_client, aud_env):
    rm = _run()
    resp = api_client.post(f"/api/v1/runs/{rm.run_id[:8]}/cancel")
    # succeeded run: cancel is an invalid transition (409) reported for the FULL id
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["run_id"] == rm.run_id


def test_run_rows_carry_best_path_metrics(api_client, aud_env, monkeypatch):
    rm = _run()
    summary = {
        "primary_metric": {"name": "accuracy", "value": 0.9},
        "best_path_id": "B",
        "paths": [
            {"path_id": "A", "label": "Path A", "node_ids": [], "metrics": {"accuracy": 0.7}, "model_artifacts": []},
            {"path_id": "B", "label": "Path B", "node_ids": [], "metrics": {"accuracy": 0.9}, "model_artifacts": []},
        ],
        "dataset": None,
    }
    import app.core.runs.run_summary as rs

    monkeypatch.setattr(rs, "run_insights", lambda *a, **k: {"display_name": "x", "summary": summary,
                                                            "models": [], "status": "succeeded"})
    meta = json.loads((aud_env / "runs" / rm.run_id / "meta.json").read_text())
    meta["metrics"] = {"accuracy": 0.7}
    (aud_env / "runs" / rm.run_id / "meta.json").write_text(json.dumps(meta))
    body = _ok(api_client.get(f"/api/v1/runs/{rm.run_id}"))
    assert body["meta"]["metrics"] == {"accuracy": 0.9}
    assert body["meta"]["metrics_path"] == {"path_id": "B", "label": "Path B"}
    assert [p["path_id"] for p in body["meta"]["metrics_by_path"]] == ["A", "B"]
    rows = _ok(api_client.get("/api/v1/runs"))
    row = next(r for r in rows if r["run_id"] == rm.run_id)
    assert row["metrics"]["accuracy"] == 0.9


@pytest.mark.parametrize("raw", ["a", "zzzzzzzzzzzz"])
def test_resolve_helper_not_found(raw, aud_env):
    from fastapi import HTTPException

    from app.api.run_ids import resolve_run_id_http

    with pytest.raises(HTTPException) as exc:
        resolve_run_id_http(raw)
    assert exc.value.status_code == 404
    assert resolve_run_id_http(raw, allow_missing=True) == raw


def test_ship_package_run_records_trigger_and_lineage(api_client, aud_env):
    """Ship-wizard package run: top-level ``trigger: ship`` + ``lineage.model``."""
    from unit_test.core.test_audit_record_core import two_branch_graph

    src = _run()
    _ok(api_client.post("/api/v1/models",
                        json={"name": "audm", "run_id": src.run_id, "slug": "audtest", "allow_untrained": True}))
    from app.core.ir.loader import dump_ir

    payload = json.loads(json.dumps(dump_ir(two_branch_graph(name="audship")), default=str))
    payload.update({"trigger": "ship", "source_run_id": src.run_id[:8],
                    "lineage": {"model": {"name": "audm", "stage": "staging", "version": "1"}}})
    resp = api_client.post("/api/v1/pipelines/run", json=payload)
    assert resp.status_code == 200, resp.text
    run_id = resp.headers["X-Run-Id"]
    rec = json.loads((aud_env / "runs" / run_id / "prove.json").read_text())
    assert rec["trigger"] == "ship"
    lin = rec["lineage"]
    assert lin["source_run_id"] == src.run_id
    m = lin["models"][0]
    assert (m["name"], m["stage"], m["match"], m["run_id"]) == ("audm", "staging", "declared", src.run_id)
    assert rec["model_version"]["name"] == "audm"
