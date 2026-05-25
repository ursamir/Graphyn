# app/mcp/handlers/__init__.py
"""
Bounded Context:  MCP Server
Responsibility:   Public API surface for the MCP tool handlers package.
                  Re-exports all handler functions, descriptions, and schemas
                  so the tool registry uses a single import path.
Owns:             Re-export declarations for all MCP tool handlers and their
                  associated description/schema constants.
Public Surface:   list_nodes_handler, generate_graph_handler,
                  validate_graph_handler, get_graph_schema_handler,
                  get_graph_capability_summary_handler, get_event_schema_handler,
                  inspect_run_handler, and all *_DESCRIPTION / *_SCHEMA constants.
Must NOT:         Contain handler logic — delegate to the individual handler
                  modules (discovery, graph, execution, artifacts, etc.).
Dependencies:     app.mcp.handlers.{discovery, graph, artifacts}.
Reason To Change: New MCP tool handler is added or an existing one is renamed.
"""
from __future__ import annotations

__all__ = [
    "list_nodes_handler",
    "LIST_NODES_DESCRIPTION",
    "LIST_NODES_SCHEMA",
    "generate_graph_handler",
    "validate_graph_handler",
    "get_graph_schema_handler",
    "get_graph_capability_summary_handler",
    "get_event_schema_handler",
    "GENERATE_GRAPH_DESCRIPTION",
    "GENERATE_GRAPH_SCHEMA",
    "VALIDATE_GRAPH_DESCRIPTION",
    "VALIDATE_GRAPH_SCHEMA",
    "GET_GRAPH_SCHEMA_DESCRIPTION",
    "GET_GRAPH_SCHEMA_SCHEMA",
    "GET_GRAPH_CAPABILITY_SUMMARY_DESCRIPTION",
    "GET_GRAPH_CAPABILITY_SUMMARY_SCHEMA",
    "GET_EVENT_SCHEMA_DESCRIPTION",
    "GET_EVENT_SCHEMA_SCHEMA",
    "inspect_run_handler",
    "INSPECT_RUN_DESCRIPTION",
    "INSPECT_RUN_SCHEMA",
]

from app.mcp.handlers.discovery import (
    LIST_NODES_DESCRIPTION,
    LIST_NODES_SCHEMA,
    list_nodes_handler,
)
from app.mcp.handlers.graph import (
    GENERATE_GRAPH_DESCRIPTION,
    GENERATE_GRAPH_SCHEMA,
    GET_EVENT_SCHEMA_DESCRIPTION,
    GET_EVENT_SCHEMA_SCHEMA,
    GET_GRAPH_CAPABILITY_SUMMARY_DESCRIPTION,
    GET_GRAPH_CAPABILITY_SUMMARY_SCHEMA,
    GET_GRAPH_SCHEMA_DESCRIPTION,
    GET_GRAPH_SCHEMA_SCHEMA,
    VALIDATE_GRAPH_DESCRIPTION,
    VALIDATE_GRAPH_SCHEMA,
    generate_graph_handler,
    get_event_schema_handler,
    get_graph_capability_summary_handler,
    get_graph_schema_handler,
    validate_graph_handler,
)
from app.mcp.handlers.artifacts import (
    INSPECT_RUN_DESCRIPTION,
    INSPECT_RUN_SCHEMA,
    inspect_run_handler,
)
