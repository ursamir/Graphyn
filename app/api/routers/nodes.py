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
from app.core.registry_runtime import get_registry

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
        resolved = registry.type_catalogue.resolve(output_type)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown port type '{output_type}'. "
                "See GET /api/v1/types for available types."
            ),
        )

    nodes = registry.find_compatible_nodes(resolved, direction=direction)
    return [n.model_dump(mode="json") for n in nodes]


# ── /nodes ────────────────────────────────────────────────────────────────────

@router.get("/nodes", summary="List all registered nodes")
def list_nodes(category: str | None = Query(None, description="Filter by category")):
    """Return metadata for all registered nodes, optionally filtered by category."""
    registry = get_registry()
    metas = registry.list_nodes(category=category)
    return [_node_response(m.node_type, registry) for m in metas]


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

    try:
        node_class.Config.model_validate(payload.config)
        return {"valid": True, "errors": {}}
    except pydantic.ValidationError as exc:
        errors = {}
        for err in exc.errors():
            field = ".".join(str(loc) for loc in err["loc"]) if err["loc"] else "config"
            errors[field] = err["msg"]
        return {"valid": False, "errors": errors}
