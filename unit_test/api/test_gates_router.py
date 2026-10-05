"""Human approval gates: GET /runs/{id}/gates, POST /runs/{id}/gates/{node}/decision, MCP tools."""
from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

HITL_NODES = Path(__file__).resolve().parents[2] / "PluginPackage/Agents/hitl_approve/nodes.py"


@pytest.fixture
def gate_run(tmp_path, monkeypatch):
    """A running run whose graph has one hitl_approve node with a pending request."""
    from app.core.runs.run_journal import RunManager

    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(ws))
    # Must sit inside the project jail (decision_dir escapes are refused).
    decision_dir = ws / "artifacts" / "agents" / "hitl_approve" / "decisions"
    run = RunManager()
    run.mark_running()
    graph = {
        "schema_version": "1.3",
        "metadata": {"name": "g", "seed": 0},
        "nodes": [
            {"id": "approve_ship", "node_type": "hitl_approve", "label": "Ship to prod?",
             "config": {"gate_id": "approve_ship",
                        "decision_dir": "workspace/artifacts/agents/hitl_approve/decisions",
                        "timeout_s": 600, "reason_required": True}},
        ],
        "edges": [],
    }
    (Path(run.base_path) / "graph.json").write_text(json.dumps(graph))
    request = {
        "request_id": "req-123",
        "run_id": run.run_id,
        "gate_id": "approve_ship",
        "approver_roles": [],
        "reason_required": True,
        "timeout_s": 600,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }
    decision_dir.mkdir(parents=True)
    (decision_dir / f"{run.run_id}__approve_ship.request.json").write_text(json.dumps(request))
    return SimpleNamespace(ws=ws, run=run, decision_dir=decision_dir)


def test_list_gates_and_awaiting_status(api_client, gate_run):
    rid = gate_run.run.run_id
    r = api_client.get(f"/api/v1/runs/{rid}/gates")
    assert r.status_code == 200
    body = r.json()
    assert body["awaiting_approval"] is True
    gate = body["gates"][0]
    assert gate["node_id"] == "approve_ship"
    assert gate["status"] == "pending"
    assert gate["prompt"] == "Ship to prod?"
    assert gate["waiting_since"] and gate["expires_at"]
    st = api_client.get(f"/api/v1/runs/{rid}/status").json()
    assert st["status"] == "awaiting_approval"
    assert st["durable_status"] == "running"
    assert st["pending_gates"] == ["approve_ship"]


def test_decision_written_where_hitl_reads_it(api_client, gate_run, monkeypatch):
    monkeypatch.setenv("GRAPHYN_API_TOKENS", "alice:tok-alice")
    rid = gate_run.run.run_id
    r = api_client.post(
        f"/api/v1/runs/{rid}/gates/approve_ship/decision",
        json={"decision": "approve", "comment": "LGTM"},
        headers={"Authorization": "Bearer tok-alice"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["gate"]["decision"]["approver"] == "alice"
    dec_path = gate_run.decision_dir / f"{rid}__approve_ship.decision.json"
    decision = json.loads(dec_path.read_text())
    assert decision["request_id"] == "req-123"
    assert decision["approved"] is True
    assert decision["approver"] == "alice"
    assert decision["actor_verified"] is True
    assert decision["reason"] == "LGTM"

    # The real plugin accepts the decision file we wrote.
    if HITL_NODES.is_file():
        monkeypatch.syspath_prepend(str(HITL_NODES.parents[1]))
        import sys

        try:
            mod = importlib.import_module("hitl_approve.nodes")
        finally:
            for key in [k for k in sys.modules if k == "hitl_approve" or k.startswith("hitl_approve.")]:
                sys.modules.pop(key, None)
        cfg = SimpleNamespace(approver_roles=[], reason_required=True)
        assert mod._evaluate_decision(decision, "req-123", cfg) == (True, "LGTM")
        req_p, dec_p = mod.decision_paths(str(gate_run.decision_dir), rid, "approve_ship")
        assert dec_p == dec_path

    again = api_client.post(
        f"/api/v1/runs/{rid}/gates/approve_ship/decision",
        json={"decision": "reject", "comment": "changed my mind"},
        headers={"Authorization": "Bearer tok-alice"},
    )
    assert again.status_code == 409

    events = [json.loads(line) for line in (gate_run.ws / "audit" / "events.jsonl").read_text().splitlines()]
    ev = [e for e in events if e.get("action") == "gate.decision"][-1]
    assert ev["actor"] == "alice"
    assert ev["meta"]["decision"] == "approve"
    assert len(ev["meta"]["comment_sha256"]) == 64
    assert "LGTM" not in json.dumps(ev)


def test_decision_requires_comment_and_known_gate(api_client, gate_run):
    rid = gate_run.run.run_id
    r = api_client.post(f"/api/v1/runs/{rid}/gates/approve_ship/decision", json={"decision": "approve"})
    assert r.status_code == 422
    r = api_client.post(f"/api/v1/runs/{rid}/gates/nope/decision", json={"decision": "approve", "comment": "x"})
    assert r.status_code == 404
    r = api_client.post(f"/api/v1/runs/{rid}/gates/approve_ship/decision", json={"decision": "maybe"})
    assert r.status_code == 422


def test_not_reached_gate_is_not_pending(api_client, gate_run):
    rid = gate_run.run.run_id
    (gate_run.decision_dir / f"{rid}__approve_ship.request.json").unlink()
    gates = api_client.get(f"/api/v1/runs/{rid}/gates").json()["gates"]
    assert gates[0]["status"] == "not_reached"
    r = api_client.post(f"/api/v1/runs/{rid}/gates/approve_ship/decision",
                        json={"decision": "approve", "comment": "x"})
    assert r.status_code == 409
    assert api_client.get(f"/api/v1/runs/{rid}/status").json()["status"] == "running"


def test_mcp_gate_tools(gate_run, monkeypatch):
    from app.mcp.handlers.gates import decide_gate_handler, list_pending_gates_handler
    from app.mcp.tool_registry import register_all_tools

    names: list[str] = []
    register_all_tools(lambda name, desc, schema, handler: names.append(name))
    assert {"list_pending_gates", "decide_gate"} <= set(names)

    rid = gate_run.run.run_id
    listed = list_pending_gates_handler({})
    assert any(g["run_id"] == rid and g["node_id"] == "approve_ship" for g in listed["gates"])
    monkeypatch.delenv("GRAPHYN_MCP_HUMAN_APPROVAL", raising=False)
    denied = decide_gate_handler({"run_id": rid, "node_id": "approve_ship", "decision": "approve", "comment": "ok"})
    assert denied.get("error") and denied["error_type"] == "capability_denied"
    rejected = decide_gate_handler({"run_id": rid, "node_id": "approve_ship", "decision": "reject",
                                    "comment": "not today", "actor": "bot"})
    assert rejected["ok"] is True
    decision = json.loads((gate_run.decision_dir / f"{rid}__approve_ship.decision.json").read_text())
    assert decision["approved"] is False
    assert decision["approver"] == "mcp:bot"
    assert decision["actor_verified"] is False
    assert decision["source"] == "mcp"


def test_decision_dir_outside_project_refused(api_client, gate_run, tmp_path, monkeypatch):
    """Approve must not write a decision file outside the project jail."""
    outside = tmp_path / "outside_decisions"
    outside.mkdir()
    rid = gate_run.run.run_id
    graph_path = Path(gate_run.run.base_path) / "graph.json"
    graph = json.loads(graph_path.read_text())
    graph["nodes"][0]["config"]["decision_dir"] = str(outside)
    graph_path.write_text(json.dumps(graph))
    # Pending request still exists under the jailed dir from the fixture — rewrite
    # status lookup will miss it (escaped dir), so plant a request under outside
    # and ensure decide still refuses to write there.
    (outside / f"{rid}__approve_ship.request.json").write_text(
        (gate_run.decision_dir / f"{rid}__approve_ship.request.json").read_text()
    )
    r = api_client.post(
        f"/api/v1/runs/{rid}/gates/approve_ship/decision",
        json={"decision": "approve", "comment": "nope"},
    )
    assert r.status_code == 400
    detail = r.json().get("detail") or {}
    assert (detail.get("code") if isinstance(detail, dict) else "") == "invalid_decision_dir" or "decision_dir" in str(detail).lower()
    assert not (outside / f"{rid}__approve_ship.decision.json").exists()
