"""API tests for /api/v1/trace and /api/v1/audit."""
from __future__ import annotations

from unittest.mock import patch


def test_trace_requires_query(api_client):
    resp = api_client.get("/api/v1/trace")
    assert resp.status_code == 400


def test_trace_returns_assembled_payload(api_client):
    fake = {
        "subject": {"kind": "run", "id": "r1"},
        "run": {"run_id": "r1", "status": "completed", "graph_name": "g", "created_at": None, "distributed_node_workers": {}},
        "graph": None,
        "node": None,
        "artifact": None,
        "provenance": None,
        "lineage": {"inputs": [], "downstream_hint": "..."},
        "chain": [{"step": "run", "label": "g", "id": "r1"}],
        "warnings": [],
    }
    with patch("app.core.trace.assemble_trace", return_value=fake) as mock_asm:
        resp = api_client.get("/api/v1/trace?run_id=r1")
    assert resp.status_code == 200
    assert resp.json()["subject"]["id"] == "r1"
    mock_asm.assert_called_once()


def test_trace_path_artifact(api_client):
    fake = {
        "subject": {"kind": "artifact", "id": "a1"},
        "run": None,
        "graph": None,
        "node": None,
        "artifact": None,
        "provenance": None,
        "lineage": {"inputs": [], "downstream_hint": "..."},
        "chain": [],
        "warnings": ["artifact_not_found:a1"],
    }
    with patch("app.core.trace.assemble_trace", return_value=fake):
        resp = api_client.get("/api/v1/trace/artifact/a1")
    assert resp.status_code == 200
    assert resp.json()["subject"]["kind"] == "artifact"


def test_audit_list_empty(api_client, tmp_workspace):
    resp = api_client.get("/api/v1/audit?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert "events" in body
    assert isinstance(body["events"], list)
