"""MCP proposal tool handlers."""
from __future__ import annotations

from app.mcp.handlers.proposals import (
    get_proposal_handler,
    list_proposals_handler,
    propose_graph_handler,
)

GRAPH = {
    "schema_version": "1.1",
    "metadata": {"name": "mcp-prop", "seed": 2},
    "nodes": [{"id": "a", "node_type": "python_code", "config": {}}],
    "edges": [],
}


def test_propose_list_get(tmp_workspace):
    bad = propose_graph_handler({"summary": "", "graph": GRAPH})
    assert bad.get("error") is True

    result = propose_graph_handler(
        {"summary": "MCP proposes a graph", "graph": GRAPH, "actor": "cursor"}
    )
    assert result.get("ok") is True
    pid = result["id"]

    listed = list_proposals_handler({"status": "pending"})
    assert listed["count"] >= 1
    assert any(p["id"] == pid for p in listed["proposals"])

    got = get_proposal_handler({"id": pid})
    assert got["id"] == pid
    assert got["proposed_graph"]["metadata"]["name"] == "mcp-prop"
