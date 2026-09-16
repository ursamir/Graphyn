"""Deep GraphIR validation shared by CLI/API/MCP."""
from __future__ import annotations

from app.core.ir.loader import load_ir
from app.core.registry_runtime import get_registry
from app.core.validation import validate_graph_ir


def test_validate_graph_ir_unknown_node():
    graph = load_ir(
        {
            "schema_version": "1.0",
            "metadata": {"name": "t", "seed": 1},
            "nodes": [
                {
                    "id": "n1",
                    "node_type": "definitely_not_a_real_node_type_xyz",
                    "config": {},
                }
            ],
            "edges": [],
        }
    )
    errors = validate_graph_ir(graph, get_registry())
    assert errors and "Unknown node type" in errors[0]
