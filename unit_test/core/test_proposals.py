"""Unit tests for Agentic Builder proposal store + GraphIR diff."""
from __future__ import annotations

import json
from pathlib import Path

from app.core.agentic.proposals import (
    accept_proposal,
    create_proposal,
    diff_graphs,
    get_proposal,
    list_proposals,
    reject_proposal,
)
from app.core.audit import list_audit


def _graph(nodes, edges=None, name="demo"):
    return {
        "schema_version": "1.1",
        "metadata": {"name": name, "seed": 42},
        "nodes": nodes,
        "edges": edges or [],
    }


def test_diff_graphs_nodes_and_edges():
    base = _graph(
        [
            {"id": "a", "node_type": "python_code", "config": {"code": "x=1"}},
            {"id": "b", "node_type": "python_code", "config": {"code": "y=2"}},
        ],
        [
            {
                "src_id": "a",
                "src_port": "output",
                "dst_id": "b",
                "dst_port": "input",
            }
        ],
    )
    proposed = _graph(
        [
            {"id": "a", "node_type": "python_code", "config": {"code": "x=99"}},
            {"id": "c", "node_type": "trainer", "config": {"epochs": 3}},
        ],
        [
            {
                "src_id": "a",
                "src_port": "output",
                "dst_id": "c",
                "dst_port": "input",
            }
        ],
    )
    diff = diff_graphs(base, proposed)
    assert diff["nodes_added"] == ["c"]
    assert diff["nodes_removed"] == ["b"]
    assert len(diff["nodes_changed"]) == 1
    assert diff["nodes_changed"][0]["id"] == "a"
    assert "a:output->c:input" in diff["edges_changed"]["added"]
    assert "a:output->b:input" in diff["edges_changed"]["removed"]
    assert diff["counts"]["nodes_added"] == 1
    assert diff["counts"]["nodes_removed"] == 1
    assert diff["counts"]["nodes_changed"] == 1


def test_diff_against_empty_base():
    proposed = _graph([{"id": "n1", "node_type": "python_code", "config": {}}])
    diff = diff_graphs(None, proposed)
    assert diff["nodes_added"] == ["n1"]
    assert diff["nodes_removed"] == []
    assert diff["nodes_changed"] == []


def test_create_list_accept_reject(tmp_workspace: Path):
    graph = _graph(
        [
            {"id": "n1", "node_type": "python_code", "config": {"code": "print(1)"}},
        ]
    )
    created = create_proposal(graph, "Add python node", actor="mcp-agent")
    assert created["status"] == "pending"
    assert created["id"]
    assert (tmp_workspace / "proposals" / f"{created['id']}.json").is_file()

    listed = list_proposals(status="pending")
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]
    assert "proposed_graph" not in listed[0]
    assert listed[0]["diff_summary"]["nodes_added"] == 1

    fetched = get_proposal(created["id"])
    assert fetched is not None
    assert fetched["proposed_graph"]["nodes"][0]["id"] == "n1"

    accepted = accept_proposal(created["id"], actor="reviewer")
    assert accepted["status"] == "accepted"
    assert accepted["resolved_by"] == "reviewer"

    # second accept should fail
    try:
        accept_proposal(created["id"])
        assert False, "expected ValueError"
    except ValueError:
        pass

    other = create_proposal(graph, "Second", actor="agent")
    rejected = reject_proposal(other["id"], actor="reviewer", reason="not now")
    assert rejected["status"] == "rejected"
    assert rejected["reject_reason"] == "not now"

    audits = list_audit(limit=20)
    actions = {e["action"] for e in audits}
    assert "proposal.create" in actions
    assert "proposal.accept" in actions
    assert "proposal.reject" in actions


def test_list_status_filter(tmp_workspace: Path):
    g = _graph([{"id": "x", "node_type": "python_code", "config": {}}])
    a = create_proposal(g, "one", actor="a")
    b = create_proposal(g, "two", actor="b")
    accept_proposal(a["id"])
    assert len(list_proposals(status="pending")) == 1
    assert list_proposals(status="pending")[0]["id"] == b["id"]
    assert len(list_proposals(status="accepted")) == 1
