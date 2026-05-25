# app/core/ir/yaml_shim.py
"""
Bounded Context:  BC1 — Graph Language
Responsibility:   Convert legacy YAML pipeline configs to GraphIR. Pure
                  conversion — no I/O, no warnings emitted here.
Owns:             yaml_config_to_ir(), load_yaml_with_deprecation().
Public Surface:   yaml_config_to_ir(raw_dict) → GraphIR,
                  load_yaml_with_deprecation(path) → GraphIR
Must NOT:         Import from app.domain, app.api, or app.models.
                  Must not execute pipelines or touch the registry.
Dependencies:     app.core.ir.{loader, models}, stdlib (warnings), yaml.
Reason To Change: YAML schema changes, or new edge format variants are added.

No DeprecationWarning is emitted from yaml_config_to_ir() — it is a pure
conversion function. The warning is emitted only by load_yaml_with_deprecation()
and by run_pipeline() (the legacy executor shim).

Req 4.1 – 4.2
"""
from __future__ import annotations

import warnings
from typing import Any

from app.core.ir.loader import CURRENT_IR_VERSION
from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode


def yaml_config_to_ir(raw: dict[str, Any]) -> GraphIR:
    """Convert a raw YAML config dict to a GraphIR object.

    Supports both the legacy linear format (no 'edges' key, auto-chained)
    and the explicit-edge format.

    Args:
        raw: A dict as produced by yaml.safe_load() of a pipeline YAML file.

    Returns:
        A validated GraphIR object.

    Req 4.1
    """
    pipeline = raw.get("pipeline", {})
    seed = pipeline.get("seed", 0)
    name = pipeline.get("name", "pipeline")  # Req 4.1.8
    raw_nodes = pipeline.get("nodes", [])

    # Build IRNode list
    ir_nodes: list[IRNode] = []
    for i, n in enumerate(raw_nodes):
        node_type = n["type"]
        node_id = n.get("id") or f"{node_type}_{i}"  # Req 4.1.5
        ir_nodes.append(IRNode(
            id=node_id,
            node_type=node_type,
            config=n.get("config", {}),
        ))

    # Build IREdge list
    raw_edges = pipeline.get("edges")
    if raw_edges:
        # Explicit-edge format (Req 4.1.3, 4.1.6)
        ir_edges: list[IREdge] = []
        for e in raw_edges:
            if isinstance(e, dict) and "from" in e and "to" in e:
                # List format: {"from": [src_id, src_port], "to": [dst_id, dst_port]}
                src_id, src_port = e["from"][0], e["from"][1]
                dst_id, dst_port = e["to"][0], e["to"][1]
            elif isinstance(e, dict) and "src_id" in e:
                # Dict format: {"src_id": ..., "src_port": ..., "dst_id": ..., "dst_port": ...}
                src_id = e["src_id"]
                src_port = e["src_port"]
                dst_id = e["dst_id"]
                dst_port = e["dst_port"]
            else:
                raise ValueError(f"Unrecognized edge format: {e!r}")
            ir_edges.append(IREdge(
                src_id=src_id,
                src_port=src_port,
                dst_id=dst_id,
                dst_port=dst_port,
            ))
    else:
        # Legacy linear format: auto-chain output → input (Req 4.1.3)
        ir_edges = [
            IREdge(
                src_id=ir_nodes[i].id,
                src_port="output",
                dst_id=ir_nodes[i + 1].id,
                dst_port="input",
            )
            for i in range(len(ir_nodes) - 1)
        ]

    return GraphIR(
        schema_version=CURRENT_IR_VERSION,  # Req 4.1.7
        metadata=IRMetadata(
            name=name,
            seed=seed,
        ),
        nodes=ir_nodes,
        edges=ir_edges,
    )


def load_yaml_with_deprecation(path: str) -> GraphIR:
    """Read a YAML file, convert to GraphIR, and emit a DeprecationWarning.

    Args:
        path: Path to the YAML pipeline config file.

    Returns:
        A validated GraphIR object.

    Req 4.2
    """
    import yaml

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    warnings.warn(
        f"YAML pipeline configs are deprecated. "
        f"Loading: {path}. "
        f"Run 'graphyn migrate --config {path}' to convert to IR JSON.",
        DeprecationWarning,
        stacklevel=2,  # Req 4.2.3 — points to the caller's code
    )

    return yaml_config_to_ir(raw)
