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


def test_accept_reject_actor_from_header(api_client, tmp_workspace):
    """X-Actor header is honored when the body carries no actor; default is unidentified."""
    pid = api_client.post(
        "/api/v1/proposals", json={"summary": "h", "graph": SAMPLE_GRAPH}
    ).json()["id"]
    accepted = api_client.post(
        f"/api/v1/proposals/{pid}/accept", headers={"X-Actor": "alice"}
    )
    assert accepted.status_code == 200
    assert accepted.json()["resolved_by"] == "alice"

    pid2 = api_client.post(
        "/api/v1/proposals", json={"summary": "h2", "graph": SAMPLE_GRAPH}
    ).json()["id"]
    rejected = api_client.post(f"/api/v1/proposals/{pid2}/reject", json={"reason": "no"})
    assert rejected.status_code == 200
    assert rejected.json()["resolved_by"] == "unidentified"
