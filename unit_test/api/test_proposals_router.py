"""API tests for /api/v1/proposals."""
from __future__ import annotations

SAMPLE_GRAPH = {
    "schema_version": "1.1",
    "metadata": {"name": "api-proposal", "seed": 1},
    "nodes": [
        {"id": "n1", "node_type": "python_code", "config": {"code": "1"}},
    ],
    "edges": [],
}


def test_proposals_lifecycle(api_client, tmp_workspace):
    create = api_client.post(
        "/api/v1/proposals",
        json={"summary": "Add node", "graph": SAMPLE_GRAPH, "actor": "tester"},
    )
    assert create.status_code == 200, create.text
    body = create.json()
    pid = body["id"]
    assert body["status"] == "pending"

    listed = api_client.get("/api/v1/proposals?status=pending")
    assert listed.status_code == 200
    assert any(p["id"] == pid for p in listed.json()["proposals"])

    got = api_client.get(f"/api/v1/proposals/{pid}")
    assert got.status_code == 200
    assert got.json()["proposed_graph"]["metadata"]["name"] == "api-proposal"

    accepted = api_client.post(f"/api/v1/proposals/{pid}/accept", json={"actor": "ui"})
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert "proposed_graph" in accepted.json()

    # reject another
    create2 = api_client.post(
        "/api/v1/proposals",
        json={"summary": "Nope", "graph": SAMPLE_GRAPH},
    )
    pid2 = create2.json()["id"]
    rejected = api_client.post(
        f"/api/v1/proposals/{pid2}/reject",
        json={"actor": "ui", "reason": "duplicate"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


def test_proposal_not_found(api_client, tmp_workspace):
    resp = api_client.get("/api/v1/proposals/doesnotexist1")
    assert resp.status_code == 404


def test_accept_non_pending_conflict(api_client, tmp_workspace):
    create = api_client.post(
        "/api/v1/proposals",
        json={"summary": "x", "graph": SAMPLE_GRAPH},
    )
    pid = create.json()["id"]
    assert api_client.post(f"/api/v1/proposals/{pid}/accept").status_code == 200
    again = api_client.post(f"/api/v1/proposals/{pid}/accept")
    assert again.status_code == 409
