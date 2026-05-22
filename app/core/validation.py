# app/core/validation.py
"""Pipeline and node config validation using the Enhanced Node System.

All validation uses registry.get_class() + Config.model_validate() directly.
No dict-style registry access (registry[node_type]) anywhere in this module.
"""
from __future__ import annotations

import pydantic

from typing import Any


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
    # Build id → type mapping
    id_to_type: dict[str, str] = {}
    for node in nodes:
        if "id" in node:
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
    except Exception:
        pass


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
    if not (isinstance(seed, int) and not isinstance(seed, bool)):
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
            available = sorted(m.node_type for m in registry.list_nodes())
            raise ValueError(
                f"Unknown node type '{node_type}'. "
                f"Available types: {', '.join(available)}"
            )

        # Validate config using Pydantic
        try:
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
