# Design 03 — Graph Generation, Validation, and Schema Tools

## Overview

This sub-document covers `app/mcp/handlers/graph.py` — the implementation of five MCP tools:
- `generate_graph` — construct a validated GraphIR from a node list
- `validate_graph` — validate a GraphIR document
- `get_graph_schema` — return the JSON Schema for GraphIR
- `get_graph_capability_summary` — aggregate capability metadata for a graph
- `get_event_schema` — return the NDJSON event schema

---

## 1. Tool: `generate_graph`

### Schema

```python
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
```

### Handler

```python
def generate_graph_handler(arguments: dict[str, Any]) -> Any:
    """Generate a validated GraphIR from a node list (Req 3.1–3.5, 3.10, 3.12).

    Delegates to Pipeline / PipelineNode for graph construction (Req 3.10).
    Validates via load_ir() before returning (Req 3.3).
    """
    from app.core.sdk import Pipeline, PipelineNode
    from app.core.ir.loader import load_ir, dump_ir
    from app.core.registry_runtime import get_registry
    import pydantic

    registry = get_registry()
    node_specs = arguments.get("nodes", [])
    edges = arguments.get("edges")
    seed = arguments.get("seed", 42)
    name = arguments.get("name", "pipeline")
    description = arguments.get("description", "")

    # ── Validate node types ────────────────────────────────────────────────────
    for spec in node_specs:
        node_type = spec.get("node_type")
        if node_type not in registry:
            return {
                "error": True,
                "error_type": "unknown_node_type",
                "message": f"Node type '{node_type}' is not registered.",
                "available_types": sorted(m.node_type for m in registry.list_nodes()),
            }

    # ── Validate node configs ──────────────────────────────────────────────────
    for spec in node_specs:
        node_type = spec.get("node_type")
        config = spec.get("config", {})
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

    # ── Construct Pipeline ─────────────────────────────────────────────────────
    pipeline_nodes = [
        PipelineNode(spec["node_type"], spec.get("config"))
        for spec in node_specs
    ]
    pipeline = Pipeline(
        nodes=pipeline_nodes,
        seed=seed,
        name=name,
        description=description,
    )

    # ── Handle explicit edges ──────────────────────────────────────────────────
    if edges is not None:
        # Rebuild the GraphIR with explicit edges
        from app.core.ir.models import GraphIR, IREdge, IRMetadata
        from app.core.ir.loader import CURRENT_IR_VERSION

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
        graph = GraphIR(
            schema_version=CURRENT_IR_VERSION,
            metadata=graph.metadata,
            nodes=graph.nodes,
            edges=ir_edges,
            parameters=graph.parameters,
        )
    else:
        # Auto-chained (Req 3.2)
        graph = pipeline.to_ir()

    # ── Validate via load_ir ───────────────────────────────────────────────────
    try:
        graph_dict = dump_ir(graph)
        load_ir(graph_dict)  # raises ValidationError or IRVersionError
    except Exception as exc:
        return {
            "error": True,
            "error_type": "ir_validation_error",
            "message": str(exc),
            "errors": [str(exc)],
        }

    return graph_dict
```

---

## 2. Tool: `validate_graph`

### Schema

```python
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
```

### Handler

```python
def validate_graph_handler(arguments: dict[str, Any]) -> Any:
    """Validate a GraphIR document (Req 3.6–3.9, 3.11).

    Delegates to load_ir() for validation (Req 3.11).
    """
    from app.core.ir.loader import load_ir, IRVersionError
    import pydantic

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
        # Catches duplicate node ID, invalid edge references (Req 3.7, 3.8)
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
```

---

## 3. Tool: `get_graph_schema`

### Schema

```python
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
```

### Handler

```python
def get_graph_schema_handler(arguments: dict[str, Any]) -> Any:
    """Return the JSON Schema for GraphIR (Req 3.13, 7.5)."""
    from app.core.ir.models import GraphIR
    return GraphIR.model_json_schema()
```

---

## 4. Tool: `get_graph_capability_summary`

### Schema

```python
GET_GRAPH_CAPABILITY_SUMMARY_DESCRIPTION = (
    "Aggregate capability metadata for a GraphIR document. Returns: "
    "any_requires_gpu, all_support_cpu, all_support_edge, all_deterministic."
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
```

### Handler

```python
def get_graph_capability_summary_handler(arguments: dict[str, Any]) -> Any:
    """Aggregate capability metadata for a graph (Req 7.7–7.9).

    Uses the two-step resolution rule from _resolve_capability() in pipeline.py.
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
    capabilities = []

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
                )
            except Exception:
                return {
                    "error": True,
                    "error_type": "unknown_node_type",
                    "message": f"Node type '{ir_node.node_type}' is not registered.",
                }
        capabilities.append(cap)

    return {
        "any_requires_gpu": any(c.requires_gpu for c in capabilities),
        "all_support_cpu": all(c.supports_cpu for c in capabilities),
        "all_support_edge": all(c.supports_edge for c in capabilities),
        "all_deterministic": all(c.deterministic for c in capabilities),
    }
```

---

## 5. Tool: `get_event_schema`

### Schema

```python
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
```

### Handler

```python
def get_event_schema_handler(arguments: dict[str, Any]) -> Any:
    """Return the NDJSON event schema (Req 7.6)."""
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
```

---

## 6. Round-Trip Property (Req 3.12)

For all valid GraphIR documents produced by `generate_graph`, the following property must hold:

```python
graph_dict = generate_graph_handler({"nodes": [...]})
graph = load_ir(graph_dict)
round_trip_dict = dump_ir(graph)
assert graph_dict == round_trip_dict
```

This is validated by a property-based test in `design-05-correctness-properties.md`.

---

## 7. Consistency Property (Req 7.9)

The `any_requires_gpu`, `all_support_cpu`, `all_support_edge`, and `all_deterministic` values returned by `get_graph_capability_summary` must be derivable by applying the two-step resolution rule to each node's capability metadata as returned by `list_nodes` for the same node types.

Both tools use the same `_resolve_capability()` logic and read from the same `NodeRegistry` singleton, so consistency is guaranteed structurally.
