# app/mcp/handlers/graph.py
"""Graph generation, validation, and schema MCP tool handlers.

Implements five tools (Req 3.1–3.13, 7.5–7.9):
  - generate_graph              — construct a validated GraphIR from a node list
  - validate_graph              — validate a GraphIR document
  - get_graph_schema            — return the JSON Schema for GraphIR
  - get_graph_capability_summary — aggregate capability metadata for a graph
  - get_event_schema            — return the NDJSON event schema

All graph construction delegates to Pipeline / PipelineNode (Req 3.10, 6.2).
All validation delegates to load_ir() (Req 3.3, 3.11, 6.3).
All registry queries delegate to get_registry() (Req 6.4).
"""
from __future__ import annotations

from typing import Any

# ── Tool schema constants ─────────────────────────────────────────────────────

GENERATE_GRAPH_DESCRIPTION = (
    "Generate a validated GraphIR JSON document from a list of node specifications. "
    "Optionally provide explicit edges; otherwise nodes are auto-chained in order."
)

GENERATE_GRAPH_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "nodes": {
            "type": "array",
            "description": "List of node specifications.",
            "items": {
                "type": "object",
                "properties": {
                    "node_type": {"type": "string"},
                    "config": {"type": "object", "additionalProperties": True},
                },
                "required": ["node_type"],
            },
        },
        "edges": {
            "type": "array",
            "description": (
                "Optional explicit edges. If omitted, nodes are auto-chained "
                "(output → input)."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "src_id": {"type": "string"},
                    "src_port": {"type": "string"},
                    "dst_id": {"type": "string"},
                    "dst_port": {"type": "string"},
                },
                "required": ["src_id", "src_port", "dst_id", "dst_port"],
            },
        },
        "seed": {
            "type": "integer",
            "description": "Pipeline seed (default 42).",
            "default": 42,
        },
        "name": {
            "type": "string",
            "description": "Pipeline name (default 'pipeline').",
            "default": "pipeline",
        },
        "description": {
            "type": "string",
            "description": "Pipeline description (default '').",
            "default": "",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "required": ["nodes"],
    "additionalProperties": False,
}

VALIDATE_GRAPH_DESCRIPTION = (
    "Validate a GraphIR JSON document. Returns valid: true/false, node_count, and errors."
)

VALIDATE_GRAPH_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "graph": {
            "type": "object",
            "description": "A GraphIR JSON document to validate.",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "required": ["graph"],
    "additionalProperties": False,
}

GET_GRAPH_SCHEMA_DESCRIPTION = (
    "Return the JSON Schema for the GraphIR model, enabling agents to understand "
    "the graph format without invoking the generation tool."
)

GET_GRAPH_SCHEMA_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "additionalProperties": False,
}

GET_GRAPH_CAPABILITY_SUMMARY_DESCRIPTION = (
    "Aggregate capability metadata for a GraphIR document. Returns: "
    "any_requires_gpu, all_support_cpu, all_support_edge, all_deterministic, "
    "any_batch_support."
)

GET_GRAPH_CAPABILITY_SUMMARY_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "graph": {
            "type": "object",
            "description": "A GraphIR JSON document.",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "required": ["graph"],
    "additionalProperties": False,
}

GET_EVENT_SCHEMA_DESCRIPTION = (
    "Return a structured document describing the six NDJSON event types emitted "
    "during pipeline execution: pipeline_start, node_start, node_end, node_error, "
    "done, error."
)

GET_EVENT_SCHEMA_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "additionalProperties": False,
}


# ── Handlers ──────────────────────────────────────────────────────────────────


def generate_graph_handler(arguments: dict[str, Any]) -> Any:
    """Generate a validated GraphIR from a node list (Req 3.1–3.5, 3.10, 3.12).

    Delegates to Pipeline / PipelineNode for graph construction (Req 3.10).
    Validates via load_ir() before returning (Req 3.3).

    Steps:
      1. Validate all node_type values against the registry (Req 3.4).
      2. Validate all node config dicts via node_class.Config.model_validate() (Req 3.5).
      3. Construct via Pipeline(nodes=[PipelineNode(...)], ...) and call pipeline.to_ir().
      4. If explicit edges provided, rebuild GraphIR with IREdge objects (Req 3.1).
      5. Validate final graph via load_ir(dump_ir(graph)) (Req 3.3).
      6. Return dump_ir(graph) on success (Req 3.12).
    """
    import pydantic

    from app.core.ir.loader import CURRENT_IR_VERSION, dump_ir, load_ir
    from app.core.ir.models import GraphIR, IREdge
    from app.core.registry_runtime import get_registry
    from app.core.sdk import Pipeline, PipelineNode

    registry = get_registry()
    node_specs = arguments.get("nodes", [])
    edges = arguments.get("edges")
    seed = arguments.get("seed", 42)
    name = arguments.get("name", "pipeline")
    description = arguments.get("description", "")

    # ── Step 1: Validate node types ───────────────────────────────────────────
    # Req 3.4: return error on first unknown node_type, before construction.
    for spec in node_specs:
        node_type = spec.get("node_type")
        if node_type not in registry:
            return {
                "error": True,
                "error_type": "unknown_node_type",
                "message": f"Node type '{node_type}' is not registered.",
                "node_type": node_type,
                "available_types": sorted(m.node_type for m in registry.list_nodes()),
            }

    # ── Step 2: Validate node configs ─────────────────────────────────────────
    # Req 3.5: validate each config dict via node_class.Config.model_validate().
    for spec in node_specs:
        node_type = spec.get("node_type")
        config = spec.get("config") or {}
        node_class = registry.get_class(node_type)
        try:
            node_class.Config.model_validate(config)
        except pydantic.ValidationError as exc:
            return {
                "error": True,
                "error_type": "invalid_node_config",
                "message": f"Invalid config for node '{node_type}': {exc}",
                "node_type": node_type,
                "validation_errors": exc.errors(),
            }

    # ── Step 3: Construct Pipeline ────────────────────────────────────────────
    # Req 3.10: delegate to Pipeline / PipelineNode — no IR construction here.
    # PipelineNode.__init__ also validates, but we've already validated above so
    # any error here would be unexpected; we let it propagate as an unhandled
    # exception (caught by the server's generic handler).
    pipeline_nodes = [
        PipelineNode(spec["node_type"], spec.get("config") or {})
        for spec in node_specs
    ]
    pipeline = Pipeline(
        nodes=pipeline_nodes,
        seed=seed,
        name=name,
        description=description,
    )

    # ── Step 4: Handle explicit edges ─────────────────────────────────────────
    # Req 3.1: if edges provided, replace auto-chained edges with explicit ones.
    # Req 3.2: if no edges, auto-chaining is already done by Pipeline._build_ir().
    if edges is not None:
        graph = pipeline.to_ir()
        ir_edges = [
            IREdge(
                src_id=e["src_id"],
                src_port=e["src_port"],
                dst_id=e["dst_id"],
                dst_port=e["dst_port"],
            )
            for e in edges
        ]
        # Rebuild GraphIR with explicit edges, preserving all other fields.
        # GraphIR's model_validator checks edge references; catch validation errors.
        try:
            graph = GraphIR(
                schema_version=CURRENT_IR_VERSION,
                metadata=graph.metadata,
                nodes=graph.nodes,
                edges=ir_edges,
                parameters=graph.parameters,
            )
        except Exception as exc:
            return {
                "error": True,
                "error_type": "ir_validation_error",
                "message": str(exc),
                "errors": [str(exc)],
            }
    else:
        # Req 3.2: auto-chained (output → input) by Pipeline._build_ir().
        graph = pipeline.to_ir()

    # ── Step 5: Validate via load_ir ──────────────────────────────────────────
    # Req 3.3: validate the final graph before returning.
    try:
        graph_dict = dump_ir(graph)
        load_ir(graph_dict)  # raises pydantic.ValidationError or IRVersionError
    except Exception as exc:
        return {
            "error": True,
            "error_type": "ir_validation_error",
            "message": str(exc),
            "errors": [str(exc)],
        }

    # ── Step 6: Return serialised graph ───────────────────────────────────────
    # Req 3.12: dump_ir(graph) is the canonical return value.
    return graph_dict


def validate_graph_handler(arguments: dict[str, Any]) -> Any:
    """Validate a GraphIR document (Req 3.6–3.9, 3.11).

    Delegates to load_ir() for validation (Req 3.11, 6.3).
    Returns: {valid, node_count, errors}.
    """
    import pydantic

    from app.core.ir.loader import IRVersionError, load_ir

    graph_dict = arguments.get("graph")
    if not graph_dict:
        return {
            "valid": False,
            "node_count": 0,
            "errors": ["Missing 'graph' argument."],
        }

    try:
        graph = load_ir(graph_dict)
        return {
            "valid": True,
            "node_count": len(graph.nodes),
            "errors": [],
        }
    except IRVersionError as exc:
        # Req 3.9: version mismatch → valid: false
        return {
            "valid": False,
            "node_count": 0,
            "errors": [f"Version error: {exc}"],
        }
    except pydantic.ValidationError as exc:
        errors = [f"{e['loc']}: {e['msg']}" for e in exc.errors()]
        return {
            "valid": False,
            "node_count": 0,
            "errors": errors,
        }
    except ValueError as exc:
        # Req 3.7, 3.8: duplicate node ID or invalid edge reference
        return {
            "valid": False,
            "node_count": 0,
            "errors": [str(exc)],
        }
    except Exception as exc:
        return {
            "valid": False,
            "node_count": 0,
            "errors": [f"Unexpected error: {exc}"],
        }


def get_graph_schema_handler(arguments: dict[str, Any]) -> Any:
    """Return the JSON Schema for GraphIR (Req 3.13, 7.5).

    Delegates to GraphIR.model_json_schema() — no custom schema logic.
    """
    from app.core.ir.models import GraphIR

    return GraphIR.model_json_schema()


def get_graph_capability_summary_handler(arguments: dict[str, Any]) -> Any:
    """Aggregate capability metadata for a graph (Req 7.7–7.9).

    Uses the two-step resolution rule from _resolve_capability() in pipeline.py:
      Step 1: if IRNode.capability_metadata is non-null, use those values.
      Step 2: otherwise, use the corresponding fields from NodeMetadata.

    Returns: {any_requires_gpu, all_support_cpu, all_support_edge, all_deterministic}.
    """
    from app.core.ir.loader import load_ir
    from app.core.ir.models import IRCapabilityMetadata
    from app.core.registry_runtime import get_registry

    graph_dict = arguments.get("graph")
    if not graph_dict:
        return {
            "error": True,
            "error_type": "missing_graph",
            "message": "Missing 'graph' argument.",
        }

    try:
        graph = load_ir(graph_dict)
    except Exception as exc:
        return {
            "error": True,
            "error_type": "ir_validation_error",
            "message": str(exc),
        }

    registry = get_registry()
    capabilities: list[IRCapabilityMetadata] = []

    for ir_node in graph.nodes:
        # Two-step resolution (Req 7.8)
        if ir_node.capability_metadata is not None:
            cap = ir_node.capability_metadata
        else:
            try:
                meta = registry.get_metadata(ir_node.node_type)
                cap = IRCapabilityMetadata(
                    requires_gpu=meta.requires_gpu,
                    supports_cpu=meta.supports_cpu,
                    supports_edge=meta.supports_edge,
                    deterministic=meta.deterministic,
                    cacheable=meta.cacheable,
                    streaming_support=meta.streaming_support,
                    realtime_support=meta.realtime_support,
                    memory_requirements=meta.memory_requirements,
                    dependency_requirements=meta.dependency_requirements,
                    batch_support=meta.batch_support,
                )
            except Exception:
                return {
                    "error": True,
                    "error_type": "unknown_node_type",
                    "message": (
                        f"Node type '{ir_node.node_type}' is not registered."
                    ),
                    "node_type": ir_node.node_type,
                }
        capabilities.append(cap)

    # Handle empty graph edge case gracefully
    if not capabilities:
        return {
            "any_requires_gpu": False,
            "all_support_cpu": True,
            "all_support_edge": True,
            "all_deterministic": True,
            "any_batch_support": False,
        }

    return {
        "any_requires_gpu": any(c.requires_gpu for c in capabilities),
        "all_support_cpu": all(c.supports_cpu for c in capabilities),
        "all_support_edge": all(c.supports_edge for c in capabilities),
        "all_deterministic": all(c.deterministic for c in capabilities),
        "any_batch_support": any(c.batch_support for c in capabilities),
    }


def get_event_schema_handler(arguments: dict[str, Any]) -> Any:
    """Return the NDJSON event schema (Req 7.6).

    Describes the six event types emitted during pipeline execution.
    """
    return {
        "event_types": [
            {
                "type": "pipeline_start",
                "fields": {
                    "type": {"type": "string", "const": "pipeline_start"},
                    "total_nodes": {"type": "integer"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
            {
                "type": "node_start",
                "fields": {
                    "type": {"type": "string", "const": "node_start"},
                    "node_type": {"type": "string"},
                    "node_index": {"type": "integer"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
            {
                "type": "node_end",
                "fields": {
                    "type": {"type": "string", "const": "node_end"},
                    "node_type": {"type": "string"},
                    "node_index": {"type": "integer"},
                    "duration_s": {"type": "number"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
            {
                "type": "node_error",
                "fields": {
                    "type": {"type": "string", "const": "node_error"},
                    "node_type": {"type": "string"},
                    "node_index": {"type": "integer"},
                    "error_message": {"type": "string"},
                    "error_type": {"type": "string"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
            {
                "type": "done",
                "fields": {
                    "type": {"type": "string", "const": "done"},
                    "run_id": {"type": "string"},
                    "duration_s": {"type": "number"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
            {
                "type": "error",
                "fields": {
                    "type": {"type": "string", "const": "error"},
                    "message": {"type": "string"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
        ],
    }
