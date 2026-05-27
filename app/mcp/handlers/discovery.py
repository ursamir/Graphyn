# app/mcp/handlers/discovery.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   list_nodes tool handler. Exposes node discovery, capability
                  filtering, port-type compatibility, and schema queries.
Owns:             list_nodes_handler(), LIST_NODES_SCHEMA/DESCRIPTION,
                  _serialize_node_metadata(), _resolve_capability() (local helper),
                  _CAPABILITY_FIELDS constant.
Public Surface:   list_nodes_handler(arguments) -> dict
Must NOT:         Contain registry mutation logic. Must not import from app.domain.
Dependencies:     BC3 (registry_runtime — module-level import), stdlib (typing).
Reason To Change: list_nodes tool schema changes, new capability fields are
                  added, or new dispatch modes are needed.
"""
from __future__ import annotations

from typing import Any

from app.core.registry_runtime import get_registry

# ── Tool schema constants ─────────────────────────────────────────────────────

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
                "Filter nodes by capability metadata. Boolean fields: "
                "requires_gpu, supports_cpu, supports_edge, deterministic, "
                "cacheable, streaming_support, realtime_support, batch_support. "
                "String field: memory_requirements. "
                "Array field: dependency_requirements."
            ),
            "additionalProperties": True,
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

# ── Capability field constants ────────────────────────────────────────────────

_CAPABILITY_FIELDS = frozenset({
    "requires_gpu",
    "supports_cpu",
    "supports_edge",
    "deterministic",
    "cacheable",
    "streaming_support",
    "realtime_support",
    "memory_requirements",
    "dependency_requirements",
    "batch_support",
})

# ── Helpers ───────────────────────────────────────────────────────────────────


def _resolve_capability(ir_node_cap, node_meta) -> dict[str, bool]:
    """Resolve capability metadata for a node using the two-step rule (Req 7.8).

    Step 1: if IRNode.capability_metadata is non-null, use those values.
    Step 2: otherwise, use the corresponding fields from NodeMetadata.

    For the discovery tool we only have NodeMetadata (no IRNode instance),
    so ir_node_cap is always None here and we always fall through to step 2.
    The full two-step rule is exercised by the graph tools when an IRNode
    is available.

    Returns a dict with all seven capability fields.
    """
    if ir_node_cap is not None:
        return {
            "requires_gpu":            ir_node_cap.requires_gpu,
            "supports_cpu":            ir_node_cap.supports_cpu,
            "supports_edge":           ir_node_cap.supports_edge,
            "deterministic":           ir_node_cap.deterministic,
            "cacheable":               ir_node_cap.cacheable,
            "streaming_support":       ir_node_cap.streaming_support,
            "realtime_support":        ir_node_cap.realtime_support,
            "memory_requirements":     ir_node_cap.memory_requirements,
            "dependency_requirements": ir_node_cap.dependency_requirements,
            "batch_support":           ir_node_cap.batch_support,
        }
    # Step 2: fall back to NodeMetadata fields
    return {
        "requires_gpu":            node_meta.requires_gpu,
        "supports_cpu":            node_meta.supports_cpu,
        "supports_edge":           node_meta.supports_edge,
        "deterministic":           node_meta.deterministic,
        "cacheable":               node_meta.cacheable,
        "streaming_support":       node_meta.streaming_support,
        "realtime_support":        node_meta.realtime_support,
        "memory_requirements":     node_meta.memory_requirements,
        "dependency_requirements": node_meta.dependency_requirements,
        "batch_support":           node_meta.batch_support,
    }


def _serialize_node_metadata(meta, registry=None) -> dict[str, Any]:
    """Convert a NodeMetadata object to a JSON-serialisable dict.

    Returns all 10 fields required by Req 2.1:
    node_type, label, description, category, version, tags,
    input_ports, output_ports, config_schema, capability_metadata.

    ``registry`` should be passed by the caller (already fetched) to avoid
    a redundant get_registry() call per node when serialising a list.
    Falls back to get_registry() when called in isolation (e.g. single-node
    lookup paths).
    """
    if registry is None:
        registry = get_registry()
    return {
        "node_type":           meta.node_type,
        "label":               meta.label,
        "description":         meta.description,
        "category":            meta.category,
        "version":             meta.version,
        "tags":                meta.tags,
        "input_ports":         meta.input_ports,
        "output_ports":        meta.output_ports,
        "config_schema":       registry.get_config_schema(meta.node_type),
        "capability_metadata": _resolve_capability(None, meta),
    }


# ── Handler ───────────────────────────────────────────────────────────────────


def list_nodes_handler(arguments: dict[str, Any]) -> Any:
    """Handle the list_nodes MCP tool invocation.

    Dispatch table (evaluated in priority order):
      list_types=true          → return port data type FQNs          (Req 2.8)
      node_type + schema_only  → return config JSON Schema only       (Req 2.7)
      node_type (alone)        → return full single-node schema       (Req 2.5, 2.6)
      output_type + direction  → return compatible nodes              (Req 2.9)
      capability_filter keys   → validate; error on unknown key       (Req 2.4)
      category / capability_filter → return filtered node list        (Req 2.3, 2.4)
      (no args)                → return all nodes                     (Req 2.1, 2.2)

    All registry queries delegate to get_registry() (Req 2.10, 6.4).
    """
    registry = get_registry()

    # ── list_types ────────────────────────────────────────────────────────────
    # Req 2.8: return all registered port data type class names (FQNs).
    if arguments.get("list_types"):
        type_names = registry.type_catalogue.list_types()
        return {"port_data_types": type_names}

    # ── single node_type lookup ───────────────────────────────────────────────
    node_type = arguments.get("node_type")
    if node_type:
        if node_type not in registry:
            # Req 2.6: structured error for unknown node type
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
            return {
                "node_type": node_type,
                "config_schema": registry.get_config_schema(node_type),
            }

        # Req 2.5: return full schema for single node
        return _serialize_node_metadata(meta, registry)

    # ── port type compatibility ───────────────────────────────────────────────
    # Req 2.9: filter by output_type + direction
    output_type = arguments.get("output_type")
    direction = arguments.get("direction")
    if output_type:  # truthy check: empty string falls through to category path
        if direction not in ("input", "output"):
            return {
                "error": True,
                "error_type": "invalid_direction",
                "message": (
                    f"direction must be 'input' or 'output', got {direction!r}."
                ),
            }
        # Resolve the type class from the catalogue by FQN
        try:
            type_cls = registry.type_catalogue.resolve(output_type)
        except Exception:
            return {
                "error": True,
                "error_type": "unknown_port_type",
                "message": f"Port data type '{output_type}' is not registered.",
                "available_types": registry.type_catalogue.list_types(),
            }
        matching = registry.find_compatible_nodes(type_cls, direction)
        return {"nodes": [_serialize_node_metadata(m, registry) for m in matching]}

    # ── capability_filter key validation ─────────────────────────────────────
    # Req 2.4: validate keys before filtering; return error on unknown key
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

    # ── category filter ───────────────────────────────────────────────────────
    # Req 2.3: exact category match; empty list (not error) when no match
    category = arguments.get("category")
    try:
        nodes = registry.list_nodes(category=category)
    except Exception as exc:
        return {
            "error": True,
            "error_type": "registry_error",
            "message": str(exc),
        }

    # ── capability filter ─────────────────────────────────────────────────────
    # Req 2.4: filter by resolved capability values
    if capability_filter:
        filtered = []
        for meta in nodes:
            cap = _resolve_capability(None, meta)
            if all(cap.get(k) == v for k, v in capability_filter.items()):
                filtered.append(meta)
        nodes = filtered

    # Req 2.1, 2.2: return all (or filtered) nodes with full metadata
    return {"nodes": [_serialize_node_metadata(m, registry) for m in nodes]}
