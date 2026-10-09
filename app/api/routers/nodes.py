# app/api/routers/nodes.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for node catalogue discovery — list, get,
                  config schema, port schema, config validation, type listing,
                  and compatibility queries.
Owns:             Route definitions for GET /nodes, GET /nodes/{node_type},
                  GET /nodes/{node_type}/config-schema,
                  GET /nodes/{node_type}/port-schema,
                  POST /nodes/{node_type}/validate-config,
                  GET /types, GET /nodes/compatible.
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain node registration logic — delegate to NodeRegistry.
Dependencies:     fastapi, pydantic, app.core.nodes.registry,
                  app.core.nodes.compat.
Reason To Change: New node catalogue endpoint added, or response schema changes.
"""
from __future__ import annotations

from typing import Any

import pydantic
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.nodes.errors import NodeNotFoundError
from app.core.host.registry_runtime import get_registry

router = APIRouter(tags=["nodes"])

# ── helpers ───────────────────────────────────────────────────────────────────

def _node_response(node_type: str, registry) -> dict[str, Any]:
    """Build the standard node response dict for a given node_type."""
    meta = registry.get_metadata(node_type)
    return {
        "node_type": meta.node_type,
        "label": meta.label,
        "description": meta.description,
        "category": meta.category,
        "version": meta.version,
        "tags": meta.tags,
        "input_ports": meta.input_ports,
        "output_ports": meta.output_ports,
        "config_schema": registry.get_config_schema(node_type),
        # Req 5.4.1, 5.4.2 — capability metadata for MCP/agent consumption
        "capability_metadata": {
            "requires_gpu":            meta.requires_gpu,
            "supports_cpu":            meta.supports_cpu,
            "supports_edge":           meta.supports_edge,
            "deterministic":           meta.deterministic,
            "cacheable":               meta.cacheable,
            "streaming_support":       meta.streaming_support,
            "realtime_support":        meta.realtime_support,
            "memory_requirements":     meta.memory_requirements,
            "dependency_requirements": meta.dependency_requirements,
            "batch_support":           meta.batch_support,
        },
    }


# ── /types — must be registered BEFORE /nodes/{node_type} ────────────────────

@router.get("/types", summary="List all registered port data types")
def list_types():
    """Return a list of fully-qualified port data type name strings."""
    registry = get_registry()
    return registry.type_catalogue.list_types()


# ── /nodes/compatible — must be registered BEFORE /nodes/{node_type} ─────────

@router.get("/nodes/compatible", summary="Find nodes compatible with a port type")
def find_compatible_nodes(
    output_type: str = Query(..., description="Fully-qualified port data type name"),
    direction: str = Query("input", description="'input' or 'output'"),
):
    """Return nodes whose ports are compatible with the given port type."""
    if direction not in ("input", "output"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid direction '{direction}'. Must be 'input' or 'output'.",
        )

    registry = get_registry()
    try:
        resolved = registry.type_catalogue.resolve_expr(output_type)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown port type '{output_type}'. "
                "See GET /api/v1/types for available types."
            ),
        )

    try:
        nodes = registry.find_compatible_nodes(resolved, direction=direction)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Compatibility check failed: {exc}",
        )
    return [n.model_dump(mode="json") for n in nodes]


# ── /nodes/check-connection — must be registered BEFORE /nodes/{node_type} ───

class ConnectionCheck(BaseModel):
    """Result of a wire-time port compatibility check (F19 / F-22)."""

    compatible: bool
    source_type: str | None = None
    target_type: str | None = None
    reason: str | None = None


def _short_type(label: str | None) -> str:
    import re as _re

    if not label:
        return "untyped"
    return _re.sub(r"[A-Za-z_][\w-]*(?:\.[A-Za-z_][\w-]*)+", lambda m: m.group(0).rsplit(".", 1)[-1], label)


@router.get(
    "/nodes/check-connection",
    summary="Check whether an output port can feed an input port",
    response_model=ConnectionCheck,
)
def check_connection(
    src_node_type: str = Query(..., description="Upstream node type"),
    dst_node_type: str = Query(..., description="Downstream node type"),
    src_port: str = Query("output", description="Upstream output port"),
    dst_port: str = Query("input", description="Downstream input port"),
) -> ConnectionCheck:
    """Same rule the graph validator applies (VAL-TYPE), for one prospective edge.

    The builder calls this when a wire is dropped so an incompatible connection
    is refused up front instead of failing validation later.
    """
    from app.core.nodes.compat import CompatibilityChecker
    from app.core.nodes.type_names import type_label

    registry = get_registry()
    try:
        src_cls = registry.get_class(src_node_type)
        dst_cls = registry.get_class(dst_node_type)
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    src_p = (getattr(src_cls, "output_ports", None) or {}).get(src_port)
    dst_p = (getattr(dst_cls, "input_ports", None) or {}).get(dst_port)
    if src_p is None:
        return ConnectionCheck(
            compatible=False,
            reason=f"{src_node_type} has no output named '{src_port}'.",
        )
    if dst_p is None:
        return ConnectionCheck(
            compatible=False,
            source_type=type_label(src_p.data_type),
            reason=f"{dst_node_type} has no input named '{dst_port}'.",
        )
    s_label, d_label = type_label(src_p.data_type), type_label(dst_p.data_type)
    ok = CompatibilityChecker.are_compatible(src_p.data_type, dst_p.data_type)
    return ConnectionCheck(
        compatible=ok,
        source_type=s_label,
        target_type=d_label,
        reason=None
        if ok
        else (
            f"{src_node_type}.{src_port} produces {_short_type(s_label)}, "
            f"but {dst_node_type}.{dst_port} expects {_short_type(d_label)}."
        ),
    )


# ── /nodes ────────────────────────────────────────────────────────────────────

@router.get("/nodes", summary="List all registered nodes")
def list_nodes(
    category: str | None = Query(None, description="Filter by category"),
    envelope: str | None = Query(None, description="List envelope (default on). Pass 0/false/no/off for bare array."),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Return metadata for all registered nodes, optionally filtered by category.

    Envelope by default (API-PAGE-001 P1). Pass ``?envelope=0`` for bare array.
    """
    from app.api.pagination import maybe_envelope, parse_envelope_flag

    registry = get_registry()
    metas = registry.list_nodes(category=category)
    items = [_node_response(m.node_type, registry) for m in metas]
    total = len(items)
    page = items[offset : offset + limit]
    return maybe_envelope(
        page,
        envelope=parse_envelope_flag(envelope),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/nodes/{node_type}", summary="Get a single node's metadata")
def get_node(node_type: str):
    """Return metadata for a specific node type."""
    registry = get_registry()
    try:
        registry.get_metadata(node_type)
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node type '{node_type}' not found")
    return _node_response(node_type, registry)


@router.get("/nodes/{node_type}/config-schema", summary="Get a node's config JSON Schema")
def get_config_schema(node_type: str):
    """Return the Pydantic-generated JSON Schema for a node's Config model."""
    registry = get_registry()
    try:
        return registry.get_config_schema(node_type)
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node type '{node_type}' not found")


@router.get("/nodes/{node_type}/port-schema", summary="Get a node's port schema")
def get_port_schema(node_type: str):
    """Return the input and output port descriptors for a node."""
    registry = get_registry()
    try:
        return registry.get_port_schema(node_type)
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node type '{node_type}' not found")


class ValidateConfigRequest(BaseModel):
    config: dict


@router.post("/nodes/{node_type}/validate-config", summary="Validate a node config")
def validate_node_config(node_type: str, payload: ValidateConfigRequest):
    """Validate a config dict against a node's Pydantic Config model.

    Returns ``{"valid": true, "errors": {}}`` on success or
    ``{"valid": false, "errors": {"field": "message"}}`` on failure.
    """
    registry = get_registry()
    try:
        node_class = registry.get_class(node_type)
    except NodeNotFoundError:
        raise HTTPException(status_code=404, detail=f"Node type '{node_type}' not found")

    config_cls = getattr(node_class, "Config", None)
    if config_cls is None:
        # Node has no Config class — any config dict is trivially valid.
        return {"valid": True, "errors": {}}
    try:
        config_cls.model_validate(payload.config)
        return {"valid": True, "errors": {}}
    except pydantic.ValidationError as exc:
        errors = {}
        for err in exc.errors():
            field = ".".join(str(loc) for loc in err["loc"]) if err["loc"] else "config"
            errors[field] = err["msg"]
        return {"valid": False, "errors": errors}
