# app/core/validation.py
"""
Bounded Context:  Application Layer — Validation
Responsibility:   Validate pipeline config dicts (YAML-derived or API-supplied)
                  against the node registry. Used by the REST API and CLI.
Owns:             validate_pipeline(), _validate_dag_edges(),
                  _validate_connections().
Public Surface:   validate_pipeline(config, registry) -> list[dict],
                  validate_graph_ir(graph, registry) -> list[str],
                  validate_graph_ir_result(graph, registry) -> dict (SRS §14.3)
Must NOT:         Import from app.domain or app.api. Must not execute nodes.
Dependencies:     BC2 (nodes.compat, nodes.errors — lazy), BC3 (registry —
                  passed as argument), pydantic.
Reason To Change: Validation rules evolve (new edge constraints, new config
                  requirements), or the pipeline config schema changes.
"""
from __future__ import annotations

import copy
import logging
from collections import defaultdict, deque
from typing import Any

import pydantic

from app.core.nodes.config import sanitize_node_config_dict
from app.core.utils.hash import stable_hash

logger = logging.getLogger(__name__)


def _validate_dag_edges(nodes: list[dict], edges: list[dict], registry: Any) -> None:
    """Validate edges in a DAG-format pipeline config.

    Args:
        nodes: List of node dicts with 'id' and 'type' keys.
        edges: List of edge dicts with 'from_node', 'to_node', and optional
               'from_port' / 'to_port' keys.
        registry: NodeRegistry instance.

    Raises:
        ValueError: if any edge references an unknown node id or port name,
                    or if port types are incompatible.
    """
    # Pre-pass: every node in DAG format must have an "id" key.
    for idx, node in enumerate(nodes):
        if "id" not in node:
            raise ValueError(
                f"pipeline.nodes[{idx}] is missing required 'id' field "
                "(DAG-format pipelines require each node to have a unique 'id')."
            )

    # Build id → type mapping
    id_to_type: dict[str, str] = {}
    for node in nodes:
        id_to_type[node["id"]] = node["type"]

    try:
        from app.core.nodes.compat import CompatibilityChecker
        _checker_available = True
    except ImportError:
        _checker_available = False

    for edge_idx, edge in enumerate(edges):
        # P-10 fix: guard against "from"/"to" being a string instead of a list
        from_raw = edge.get("from")
        to_raw = edge.get("to")

        if isinstance(from_raw, list):
            from_id = from_raw[0] if len(from_raw) > 0 else None
            from_port = from_raw[1] if len(from_raw) > 1 else "output"
        else:
            from_id = edge.get("from_node") or from_raw
            from_port = edge.get("from_port", "output")

        if isinstance(to_raw, list):
            to_id = to_raw[0] if len(to_raw) > 0 else None
            to_port = to_raw[1] if len(to_raw) > 1 else "input"
        else:
            to_id = edge.get("to_node") or to_raw
            to_port = edge.get("to_port", "input")

        # G2-12 fix: guard against None node IDs (e.g. empty 'from'/'to' list)
        if from_id is None:
            raise ValueError(
                f"Edge at index {edge_idx} has a missing or empty 'from' field. "
                "Each edge must specify a source node ID."
            )
        if to_id is None:
            raise ValueError(
                f"Edge at index {edge_idx} has a missing or empty 'to' field. "
                "Each edge must specify a destination node ID."
            )

        if from_id not in id_to_type:
            raise ValueError(
                f"Edge references unknown source node id '{from_id}'. "
                f"Known ids: {sorted(id_to_type)}"
            )
        if to_id not in id_to_type:
            raise ValueError(
                f"Edge references unknown destination node id '{to_id}'. "
                f"Known ids: {sorted(id_to_type)}"
            )

        from_type = id_to_type[from_id]
        to_type = id_to_type[to_id]

        try:
            from_class = registry.get_class(from_type)
            to_class = registry.get_class(to_type)
        except Exception:
            continue  # unknown node type — caught by node-level validation

        if from_port not in from_class.output_ports:
            raise ValueError(
                f"Edge references unknown output port '{from_port}' on node '{from_id}' "
                f"(type '{from_type}'). Available output ports: {sorted(from_class.output_ports)}"
            )
        if to_port not in to_class.input_ports:
            raise ValueError(
                f"Edge references unknown input port '{to_port}' on node '{to_id}' "
                f"(type '{to_type}'). Available input ports: {sorted(to_class.input_ports)}"
            )

        if _checker_available:
            src_data_type = from_class.output_ports[from_port].data_type
            dst_data_type = to_class.input_ports[to_port].data_type
            if src_data_type is not None and dst_data_type is not None:
                from app.core.nodes.compat import CompatibilityChecker
                if not CompatibilityChecker.are_compatible(src_data_type, dst_data_type):
                    raise ValueError(
                        f"Incompatible port types: '{from_id}.{from_port}' produces "
                        f"{src_data_type} but '{to_id}.{to_port}' expects {dst_data_type}"
                    )


def _validate_connections(nodes: list[dict], registry: Any) -> None:
    """Validate port-to-port type compatibility for linear pipelines.

    Accesses ``input_ports`` and ``output_ports`` directly on the class
    (they are ClassVars) rather than instantiating via ``__new__``, which
    avoids triggering ``__init_subclass__`` side effects (P-08 fix).
    """
    try:
        from app.core.nodes.compat import CompatibilityChecker

        node_classes: dict[int, Any] = {}
        for i, node_cfg in enumerate(nodes):
            node_type = node_cfg["type"]
            try:
                node_class = registry.get_class(node_type)
                node_classes[i] = node_class
            except Exception:
                continue

        for i in range(1, len(nodes)):
            src_class = node_classes.get(i - 1)
            dst_class = node_classes.get(i)
            if src_class is None or dst_class is None:
                continue
            if (
                "output" in src_class.output_ports
                and "input" in dst_class.input_ports
            ):
                src_type = src_class.output_ports["output"].data_type
                dst_type = dst_class.input_ports["input"].data_type
                if src_type is not None and dst_type is not None:
                    if not CompatibilityChecker.are_compatible(src_type, dst_type):
                        raise ValueError(
                            f"Incompatible connection: node[{i-1}] '{src_class.__name__}.output' "
                            f"produces {src_type} but node[{i}] '{dst_class.__name__}.input' "
                            f"expects {dst_type}"
                        )
    except ValueError:
        raise
    except Exception as exc:
        logger.warning(
            "_validate_connections skipped due to unexpected error: %s", exc
        )


def validate_pipeline(config: Any, registry: Any) -> list[dict]:
    """Validate a pipeline config dict against the node registry.

    Uses registry.get_class(node_type).Config.model_validate(config) for
    per-node config validation. No dict-style registry access.

    Args:
        config: Raw pipeline config dict (from YAML).
        registry: NodeRegistry instance.

    Returns:
        List of validated node dicts with 'type' and 'config' keys.

    Raises:
        ValueError: if the config is structurally invalid, references unknown
                    node types, or contains invalid node configs.
    """
    if not isinstance(config, dict):
        raise ValueError("Pipeline config must be a mapping")

    if "pipeline" not in config:
        raise ValueError("Missing 'pipeline' section")

    pipeline = config["pipeline"]
    if not isinstance(pipeline, dict):
        raise ValueError("'pipeline' section must be a mapping")

    seed = pipeline.get("seed")
    if seed is not None and not (isinstance(seed, int) and not isinstance(seed, bool)):
        raise ValueError("pipeline.seed must be an integer")

    nodes = pipeline.get("nodes", [])

    if not isinstance(nodes, list):
        raise ValueError("pipeline.nodes must be an array")

    if not nodes:
        raise ValueError("Pipeline must contain nodes")

    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise ValueError(f"pipeline.nodes[{index}] must be an object")
        if "type" not in node:
            raise ValueError(f"pipeline.nodes[{index}] missing 'type'")
        if not isinstance(node["type"], str):
            raise ValueError(f"pipeline.nodes[{index}].type must be string")
        if "config" in node and not isinstance(node["config"], dict):
            raise ValueError(f"pipeline.nodes[{index}].config must be an object")

    validated_nodes = []

    for node in nodes:
        node_type = node["type"]
        config_in = node.get("config", {})

        # Validate node type exists
        try:
            node_class = registry.get_class(node_type)
        except Exception:
            try:
                available = sorted(m.node_type for m in registry.list_nodes())
            except Exception:
                available = ["<registry unavailable>"]
            raise ValueError(
                f"Unknown node type '{node_type}'. "
                f"Available types: {', '.join(available)}"
            )

        # Validate config using Pydantic (strip legacy UI stamp keys first)
        try:
            config_in = sanitize_node_config_dict(node_class.Config, config_in)
            node_class.Config.model_validate(config_in)
        except pydantic.ValidationError as exc:
            raise ValueError(
                f"Invalid config for node '{node_type}': {exc}"
            ) from exc

        validated_nodes.append({
            "type": node_type,
            "config": config_in,
        })

    # Validate edges (DAG format) or connections (linear format)
    edges = pipeline.get("edges")
    if edges:
        _validate_dag_edges(nodes, edges, registry)
    else:
        _validate_connections(validated_nodes, registry)

    return validated_nodes


def _finding(
    code: str,
    severity: str,
    message: str,
    *,
    node_ids: list[str] | None = None,
    edge_index: int | None = None,
    field: str | None = None,
) -> dict:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "node_ids": list(node_ids or []),
        "edge_index": edge_index,
        "field": field,
    }


def validate_graph_ir_result(graph: Any, registry: Any) -> dict:
    """Deep GraphIR validation returning SRS §14.3 result schema.

    ``valid`` is true iff ``errors`` is empty (VAL-002). Warnings do not
    invalidate. Execute paths must refuse when errors is non-empty (VAL-003).
    """
    from app.core.ir.models import _deep_unfreeze
    from app.core.nodes.compat import CompatibilityChecker
    from app.core.nodes.errors import NodeTypeError

    errors: list[dict] = []
    warnings: list[dict] = []
    node_classes: dict[str, type] = {}

    # VAL-DUP-ID
    seen_ids: set[str] = set()
    for node in graph.nodes:
        if node.id in seen_ids:
            errors.append(
                _finding(
                    "VAL-DUP-ID",
                    "error",
                    f"Duplicate node id '{node.id}'",
                    node_ids=[node.id],
                )
            )
        seen_ids.add(node.id)

    # VAL-EMPTY
    if len(graph.nodes) == 0:
        warnings.append(
            _finding("VAL-EMPTY", "warning", "Graph has zero nodes")
        )

    node_id_set = {n.id for n in graph.nodes}

    for node in graph.nodes:
        try:
            node_class = registry.get_class(node.node_type)
            node_classes[node.id] = node_class
        except Exception:
            try:
                available = sorted(m.node_type for m in registry.list_nodes())
            except Exception:
                available = ["<registry unavailable>"]
            errors.append(
                _finding(
                    "VAL-UNK-TYPE",
                    "error",
                    f"[{node.id}] Unknown node type '{node.node_type}'. "
                    f"Available: {', '.join(available)}",
                    node_ids=[node.id],
                    field="node_type",
                )
            )
            continue

        try:
            cfg = sanitize_node_config_dict(
                node_class.Config, dict(_deep_unfreeze(node.config or {}))
            )
            node_class.Config.model_validate(cfg)
        except pydantic.ValidationError as exc:
            for e in exc.errors():
                loc = ".".join(str(part) for part in e["loc"])
                errors.append(
                    _finding(
                        "VAL-CONFIG",
                        "error",
                        f"[{node.id}] Config error at '{loc}': {e['msg']}",
                        node_ids=[node.id],
                        field=loc or None,
                    )
                )

    node_instances: dict[str, object] = {}
    seed_base = getattr(getattr(graph, "metadata", None), "seed", 0) or 0
    for node in graph.nodes:
        if node.id not in node_classes:
            continue
        try:
            node_class = node_classes[node.id]
            node_seed = stable_hash(seed_base, node.node_type, 0) % (2 ** 32)
            instance = node_class(
                config=copy.deepcopy(dict(_deep_unfreeze(node.config or {}))),
                seed=node_seed,
            )
            node_instances[node.id] = instance
        except Exception as exc:
            errors.append(
                _finding(
                    "VAL-CONFIG",
                    "error",
                    f"[{node.id}] Failed to instantiate node: {exc}",
                    node_ids=[node.id],
                )
            )

    for edge_index, edge in enumerate(graph.edges):
        if edge.src_id not in node_id_set or edge.dst_id not in node_id_set:
            missing = []
            if edge.src_id not in node_id_set:
                missing.append(edge.src_id)
            if edge.dst_id not in node_id_set:
                missing.append(edge.dst_id)
            errors.append(
                _finding(
                    "VAL-MISS-NODE",
                    "error",
                    f"Edge references unknown node(s): {missing}",
                    node_ids=missing,
                    edge_index=edge_index,
                )
            )
            continue

        src_inst = node_instances.get(edge.src_id)
        dst_inst = node_instances.get(edge.dst_id)
        if src_inst is None or dst_inst is None:
            errors.append(
                _finding(
                    "VAL-MISS-NODE",
                    "error",
                    f"Edge {edge.src_id}.{edge.src_port} → {edge.dst_id}.{edge.dst_port}: "
                    f"skipped (node instantiation failed)",
                    node_ids=[edge.src_id, edge.dst_id],
                    edge_index=edge_index,
                )
            )
            continue

        if edge.src_port not in src_inst.__class__.output_ports:
            available = sorted(src_inst.__class__.output_ports)
            errors.append(
                _finding(
                    "VAL-MISS-PORT",
                    "error",
                    f"Edge {edge.src_id}.{edge.src_port} → {edge.dst_id}.{edge.dst_port}: "
                    f"'{edge.src_id}' has no output port '{edge.src_port}'. "
                    f"Available: {available}",
                    node_ids=[edge.src_id],
                    edge_index=edge_index,
                    field=edge.src_port,
                )
            )
            continue

        if edge.dst_port not in dst_inst.__class__.input_ports:
            available = sorted(dst_inst.__class__.input_ports)
            errors.append(
                _finding(
                    "VAL-MISS-PORT",
                    "error",
                    f"Edge {edge.src_id}.{edge.src_port} → {edge.dst_id}.{edge.dst_port}: "
                    f"'{edge.dst_id}' has no input port '{edge.dst_port}'. "
                    f"Available: {available}",
                    node_ids=[edge.dst_id],
                    edge_index=edge_index,
                    field=edge.dst_port,
                )
            )
            continue

        try:
            CompatibilityChecker.check_connection(
                src_inst, edge.src_port, dst_inst, edge.dst_port
            )
        except NodeTypeError as exc:
            errors.append(
                _finding(
                    "VAL-TYPE",
                    "error",
                    f"Edge {edge.src_id}.{edge.src_port} → {edge.dst_id}.{edge.dst_port}: "
                    f"Type mismatch — {exc}",
                    node_ids=[edge.src_id, edge.dst_id],
                    edge_index=edge_index,
                )
            )

    in_degree: dict[str, int] = {n.id: 0 for n in graph.nodes}
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        if edge.src_id in in_degree and edge.dst_id in in_degree:
            adjacency[edge.src_id].append(edge.dst_id)
            in_degree[edge.dst_id] += 1
    queue: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
    visited = 0
    reachable: set[str] = set()
    while queue:
        nid = queue.popleft()
        visited += 1
        reachable.add(nid)
        for succ in adjacency[nid]:
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)
    if graph.nodes and visited != len(graph.nodes):
        cycle_nodes = [n.id for n in graph.nodes if in_degree[n.id] > 0]
        errors.append(
            _finding(
                "VAL-CYCLE",
                "error",
                f"Cycle detected — nodes involved: {cycle_nodes}",
                node_ids=cycle_nodes,
            )
        )

    # VAL-UNREACH: nodes never reached from zero-indegree sources (warning)
    if graph.nodes:
        adj2: dict[str, list[str]] = defaultdict(list)
        indeg2: dict[str, int] = {n.id: 0 for n in graph.nodes}
        for edge in graph.edges:
            if edge.src_id in indeg2 and edge.dst_id in indeg2:
                adj2[edge.src_id].append(edge.dst_id)
                indeg2[edge.dst_id] += 1
        sources = [nid for nid, deg in indeg2.items() if deg == 0]
        cycle_ids: set[str] = set()
        for e in errors:
            if e.get("code") == "VAL-CYCLE":
                cycle_ids.update(e.get("node_ids") or [])
        reach: set[str] = set()
        q2: deque[str] = deque(sources)
        while q2:
            nid = q2.popleft()
            if nid in reach:
                continue
            reach.add(nid)
            for succ in adj2[nid]:
                q2.append(succ)
        for n in graph.nodes:
            if n.id not in reach and n.id not in cycle_ids:
                warnings.append(
                    _finding(
                        "VAL-UNREACH",
                        "warning",
                        f"Node {n.id} is unreachable from sources",
                        node_ids=[n.id],
                    )
                )

    schema_version = None
    try:
        schema_version = getattr(graph, "schema_version", None) or getattr(
            getattr(graph, "metadata", None), "schema_version", None
        )
    except Exception:
        schema_version = None
    if schema_version is None:
        try:
            schema_version = str(getattr(graph, "schema_version", "1.2"))
        except Exception:
            schema_version = "1.2"

    return {
        "valid": len(errors) == 0,
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "schema_version": str(schema_version),
        "errors": errors,
        "warnings": warnings,
    }


def validate_graph_ir(graph: Any, registry: Any) -> list[str]:
    """Deep GraphIR validation (CLI validate steps 3–7).

    Returns a list of human-readable error strings; empty means the graph can execute.
    Prefer ``validate_graph_ir_result`` for the normative SRS §14.3 schema.
    """
    result = validate_graph_ir_result(graph, registry)
    return [e["message"] for e in result["errors"]]


def validate_node_config(node_type: str, config: dict, schema: dict) -> dict:
    """Deprecated — raises NotImplementedError.

    This function previously returned an empty dict (no errors) regardless of
    input, silently passing all validation. It has been replaced by:

        registry.get_class(node_type).Config.model_validate(config)

    Raises:
        NotImplementedError: always — migrate callers to the Pydantic-based API.
    """
    raise NotImplementedError(
        "validate_node_config() is removed. "
        "Use registry.get_class(node_type).Config.model_validate(config) instead."
    )
