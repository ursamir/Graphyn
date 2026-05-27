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
             Must have a top-level 'pipeline' key with a dict value.

    Returns:
        A validated GraphIR object.

    Raises:
        ValueError: If 'pipeline' key is absent or not a dict, if a node is
                    missing the required 'type' field, if an edge list has the
                    wrong number of elements, or if auto-generated node IDs
                    collide with explicit IDs.

    Note:
        schema_version is always set to CURRENT_IR_VERSION (from
        app.core.ir.loader). Tests that assert on schema_version are
        implicitly coupled to that constant.

    Req 4.1
    """
    # Finding 2 fix: validate that 'pipeline' key exists and is a dict.
    if not isinstance(raw, dict) or "pipeline" not in raw or not isinstance(raw.get("pipeline"), dict):
        top_keys = list(raw.keys()) if isinstance(raw, dict) else type(raw).__name__
        raise ValueError(
            "YAML config must have a top-level 'pipeline' key with a dict value. "
            f"Got top-level keys: {top_keys}"
        )

    pipeline = raw["pipeline"]
    seed = pipeline.get("seed", 0)
    name = pipeline.get("name", "pipeline")  # Req 4.1.8
    raw_nodes = pipeline.get("nodes", [])

    # Build IRNode list
    ir_nodes: list[IRNode] = []
    explicit_ids: set[str] = set()
    for i, n in enumerate(raw_nodes):
        # Finding 1 fix: validate 'type' field exists before accessing it.
        node_type = n.get("type")
        if not node_type:
            raise ValueError(
                f"Node at index {i} is missing required 'type' field: {n!r}"
            )
        node_id = n.get("id") or f"{node_type}_{i}"  # Req 4.1.5
        if n.get("id"):
            explicit_ids.add(node_id)
        ir_nodes.append(IRNode(
            id=node_id,
            node_type=node_type,
            config=n.get("config", {}),
        ))

    # Finding 4 fix: check for collisions between auto-generated and explicit IDs.
    seen_ids: set[str] = set()
    for node in ir_nodes:
        if node.id in seen_ids:
            raise ValueError(
                f"Duplicate node id '{node.id}'. This may be caused by an "
                f"auto-generated id colliding with an explicit id in the same graph."
            )
        seen_ids.add(node.id)

    # Build IREdge list
    # Finding 5 fix: distinguish None (key absent → legacy) from [] (explicit empty → no edges).
    raw_edges = pipeline.get("edges")  # None if key absent
    if raw_edges is None:
        # Legacy linear format: auto-chain output → input (Req 4.1.3)
        ir_edges: list[IREdge] = [
            IREdge(
                src_id=ir_nodes[i].id,
                src_port="output",
                dst_id=ir_nodes[i + 1].id,
                dst_port="input",
            )
            for i in range(len(ir_nodes) - 1)
        ]
    elif raw_edges:
        # Explicit-edge format (Req 4.1.3, 4.1.6)
        ir_edges = []
        for e in raw_edges:
            if isinstance(e, dict) and "from" in e and "to" in e:
                # List format: {"from": [src_id, src_port], "to": [dst_id, dst_port]}
                # Finding 3 fix: validate list lengths before indexing.
                from_list = e["from"]
                to_list = e["to"]
                if len(from_list) != 2 or len(to_list) != 2:
                    raise ValueError(
                        f"Edge 'from'/'to' lists must each have exactly 2 elements "
                        f"[node_id, port_name], got from={from_list!r}, to={to_list!r}"
                    )
                src_id, src_port = from_list
                dst_id, dst_port = to_list
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
        # Explicit empty edges list — user intends no edges (e.g. single-node graph).
        ir_edges = []

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

    # Finding 6 fix: yaml.safe_load returns None for empty files; catch it here
    # with a clear message before yaml_config_to_ir receives a non-dict.
    if not isinstance(raw, dict):
        raise ValueError(
            f"YAML file '{path}' did not produce a dict. "
            f"Got: {type(raw).__name__}. Is the file empty or malformed?"
        )

    warnings.warn(
        f"YAML pipeline configs are deprecated. "
        f"Loading: {path}. "
        f"Run 'graphyn migrate --config {path}' to convert to IR JSON.",
        DeprecationWarning,
        stacklevel=2,  # Req 4.2.3 — points to the caller's code
    )

    return yaml_config_to_ir(raw)
