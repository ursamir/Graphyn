# Design 02 — Node Discovery Tool

## Overview

This sub-document covers `app/mcp/handlers/discovery.py` — the implementation of the `list_nodes` MCP tool.

The tool exposes the full node catalogue from the `NodeRegistry` singleton, with optional filtering by category, capability metadata, node type, port type compatibility, and schema-only mode.

---

## 1. Tool Schema

```python
LIST_NODES_DESCRIPTION = (
    "Discover registered node types with their full schemas and capability metadata. "
    "Supports filtering by category, capability fields, node type, and port data type."
)

LIST_NODES_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "description": "Filter nodes by exact category match (e.g. 'audio', 'ml').",
        },
        "capability_filter": {
            "type": "object",
            "description": (
                "Filter nodes by capability metadata. Keys must be one of: "
                "requires_gpu, supports_cpu, supports_edge, deterministic, "
                "cacheable, streaming_support, realtime_support. Values are booleans."
            ),
            "additionalProperties": {"type": "boolean"},
        },
        "node_type": {
            "type": "string",
            "description": "Return the full schema for a single node type.",
        },
        "schema_only": {
            "type": "boolean",
            "description": (
                "When true and node_type is provided, return only the config "
                "JSON Schema for that node type."
            ),
            "default": False,
        },
        "list_types": {
            "type": "boolean",
            "description": "When true, return all registered port data type class names.",
            "default": False,
        },
        "output_type": {
            "type": "string",
            "description": "Port data type name to filter by (used with direction).",
        },
        "direction": {
            "type": "string",
            "enum": ["input", "output"],
            "description": (
                "Port direction for output_type filtering. "
                "'input' = nodes that consume the type; 'output' = nodes that produce it."
            ),
        },
        "_meta": {
            "type": "object",
            "description": "MCP metadata (auth_token, etc.).",
            "properties": {
                "auth_token": {"type": "string"}
            },
        },
    },
    "additionalProperties": False,
}
```

---

## 2. Capability Field Constants

```python
_CAPABILITY_FIELDS = frozenset({
    "requires_gpu",
    "supports_cpu",
    "supports_edge",
    "deterministic",
    "cacheable",
    "streaming_support",
    "realtime_support",
})
```

---

## 3. Capability Resolution

The two-step resolution rule from `_resolve_capability()` in `app/core/pipeline.py` is replicated here as a pure helper (Req 7.8):

```python
def _resolve_capability(ir_node_cap, node_meta) -> dict[str, bool]:
    """Resolve capability metadata for a node.

    Step 1: if IRNode.capability_metadata is non-null, use those values.
    Step 2: otherwise, use the NodeMetadata capability fields.

    For the discovery tool, we only have NodeMetadata (no IRNode instance),
    so we always use step 2. The full two-step rule is used in graph tools
    when an IRNode is available.

    Returns a dict with all seven capability fields.
    """
    return {
        "requires_gpu":      node_meta.requires_gpu,
        "supports_cpu":      node_meta.supports_cpu,
        "supports_edge":     node_meta.supports_edge,
        "deterministic":     node_meta.deterministic,
        "cacheable":         node_meta.cacheable,
        "streaming_support": node_meta.streaming_support,
        "realtime_support":  node_meta.realtime_support,
    }
```

---

## 4. Node Serialization Helper

```python
def _serialize_node_metadata(meta) -> dict:
    """Convert a NodeMetadata object to a JSON-serializable dict.

    Returns all fields required by Req 2.1:
    node_type, label, description, category, version, tags,
    input_ports, output_ports, config_schema, capability_metadata.
    """
    from app.core.registry_runtime import get_registry
    registry = get_registry()

    return {
        "node_type":          meta.node_type,
        "label":              meta.label,
        "description":        meta.description,
        "category":           meta.category,
        "version":            meta.version,
        "tags":               meta.tags,
        "input_ports":        meta.input_ports,
        "output_ports":       meta.output_ports,
        "config_schema":      registry.get_config_schema(meta.node_type),
        "capability_metadata": _resolve_capability(None, meta),
    }
```

---

## 5. Handler Implementation

```python
# app/mcp/handlers/discovery.py
"""list_nodes tool handler.

Req 2.1–2.11
"""
from __future__ import annotations

from typing import Any

from app.core.registry_runtime import get_registry

_CAPABILITY_FIELDS = frozenset({
    "requires_gpu", "supports_cpu", "supports_edge",
    "deterministic", "cacheable", "streaming_support", "realtime_support",
})


def list_nodes_handler(arguments: dict[str, Any]) -> Any:
    """Handle the list_nodes tool invocation.

    Dispatch table:
      list_types=true          → return port data type names
      node_type + schema_only  → return config JSON Schema only
      node_type (alone)        → return single node full schema
      output_type + direction  → return nodes compatible with port type
      category / capability_filter → return filtered node list
      (no args)                → return all nodes
    """
    registry = get_registry()

    # ── list_types ─────────────────────────────────────────────────────────────
    if arguments.get("list_types"):
        type_names = sorted(
            cls.__name__
            for cls in registry.type_catalogue.all_types()
        )
        return {"port_data_types": type_names}

    # ── single node_type lookup ────────────────────────────────────────────────
    node_type = arguments.get("node_type")
    if node_type:
        if node_type not in registry:
            return {
                "error": True,
                "error_type": "unknown_node_type",
                "message": f"Node type '{node_type}' is not registered.",
                "available_types": sorted(
                    m.node_type for m in registry.list_nodes()
                ),
            }
        meta = registry.get_metadata(node_type)

        if arguments.get("schema_only"):
            # Req 2.7: return config JSON Schema only
            return {"node_type": node_type, "config_schema": registry.get_config_schema(node_type)}

        # Req 2.5: return full schema for single node
        return _serialize_node_metadata(meta)

    # ── port type compatibility ────────────────────────────────────────────────
    output_type = arguments.get("output_type")
    direction = arguments.get("direction")
    if output_type is not None:
        if direction not in ("input", "output"):
            return {
                "error": True,
                "error_type": "invalid_direction",
                "message": (
                    f"direction must be 'input' or 'output', got '{direction}'."
                ),
            }
        # Resolve the type class from the catalogue
        type_cls = registry.type_catalogue.get_by_name(output_type)
        if type_cls is None:
            return {
                "error": True,
                "error_type": "unknown_port_type",
                "message": f"Port data type '{output_type}' is not registered.",
            }
        matching = registry.find_compatible_nodes(type_cls, direction)
        return {"nodes": [_serialize_node_metadata(m) for m in matching]}

    # ── capability_filter validation ───────────────────────────────────────────
    capability_filter: dict[str, bool] = arguments.get("capability_filter") or {}
    for key in capability_filter:
        if key not in _CAPABILITY_FIELDS:
            return {
                "error": True,
                "error_type": "invalid_filter_key",
                "message": (
                    f"'{key}' is not a valid capability filter key. "
                    f"Valid keys: {sorted(_CAPABILITY_FIELDS)}"
                ),
                "invalid_key": key,
            }

    # ── category filter ────────────────────────────────────────────────────────
    category = arguments.get("category")
    nodes = registry.list_nodes(category=category)

    # ── capability filter ──────────────────────────────────────────────────────
    if capability_filter:
        filtered = []
        for meta in nodes:
            cap = _resolve_capability(None, meta)
            if all(cap.get(k) == v for k, v in capability_filter.items()):
                filtered.append(meta)
        nodes = filtered

    return {"nodes": [_serialize_node_metadata(m) for m in nodes]}
```

---

## 6. Consistency Property (Req 2.11)

The `capability_metadata` returned by `list_nodes` must be field-for-field identical to the `capability_metadata` object returned by `GET /api/v1/nodes` for the same node type.

Both paths read from the same `NodeRegistry` singleton via `get_registry()`. The REST API router (`app/api/routers/nodes.py`) serializes `NodeMetadata` directly. The MCP handler calls `_resolve_capability(None, meta)` which reads the same seven fields from `NodeMetadata`. Since both paths read from the same source object, consistency is guaranteed structurally.

---

## 7. Registry-Driven Extensibility (Req 6.9)

The handler calls `get_registry()` on every invocation — it does not cache the registry reference at module import time. This means that if a new node type is registered in the same process (e.g., a plugin loaded at runtime), subsequent `list_nodes` calls will include it without any MCP layer changes.

---

## 8. Tool Invocation Examples

### List all nodes
```json
{"tool": "list_nodes", "arguments": {}}
```

### Filter by category
```json
{"tool": "list_nodes", "arguments": {"category": "audio"}}
```

### Filter by capability
```json
{"tool": "list_nodes", "arguments": {"capability_filter": {"supports_edge": true, "requires_gpu": false}}}
```

### Get single node schema
```json
{"tool": "list_nodes", "arguments": {"node_type": "clean"}}
```

### Get config schema only
```json
{"tool": "list_nodes", "arguments": {"node_type": "clean", "schema_only": true}}
```

### List port data types
```json
{"tool": "list_nodes", "arguments": {"list_types": true}}
```

### Find nodes that produce AudioSample
```json
{"tool": "list_nodes", "arguments": {"output_type": "AudioSample", "direction": "output"}}
```

---

## 9. Response Shape Examples

### Full node list entry
```json
{
  "node_type": "clean",
  "label": "Audio Cleaner",
  "description": "Removes noise and normalizes audio samples.",
  "category": "audio",
  "version": "1.0.0",
  "tags": ["audio", "preprocessing"],
  "input_ports": {
    "input": {"name": "input", "data_type": "app.models.audio_sample.AudioSample", "required": true, "cardinality": "single"}
  },
  "output_ports": {
    "output": {"name": "output", "data_type": "app.models.audio_sample.AudioSample", "required": true, "cardinality": "single"}
  },
  "config_schema": {
    "$defs": {},
    "properties": {
      "sample_rate": {"default": 16000, "title": "Sample Rate", "type": "integer"}
    },
    "title": "CleanConfig",
    "type": "object"
  },
  "capability_metadata": {
    "requires_gpu": false,
    "supports_cpu": true,
    "supports_edge": false,
    "deterministic": true,
    "cacheable": true,
    "streaming_support": false,
    "realtime_support": false
  }
}
```

### Error: unknown node type
```json
{
  "error": true,
  "error_type": "unknown_node_type",
  "message": "Node type 'foo' is not registered.",
  "available_types": ["clean", "export", "input", "split"]
}
```

### Error: invalid capability filter key
```json
{
  "error": true,
  "error_type": "invalid_filter_key",
  "message": "'uses_tpu' is not a valid capability filter key. Valid keys: ['cacheable', 'deterministic', 'realtime_support', 'requires_gpu', 'streaming_support', 'supports_cpu', 'supports_edge']",
  "invalid_key": "uses_tpu"
}
```
