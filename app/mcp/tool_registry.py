# app/mcp/tool_registry.py
"""Registers all MCP tools on the server instance.

Req 1.1, 1.2, 1.7
"""
from __future__ import annotations

from typing import Any, Callable


def register_all_tools(register: Callable) -> None:
    """Import all handlers and register them.

    Args:
        register: The _register() function from server.py.
                  Signature: (name, description, input_schema, handler) -> None
    """
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
    from app.mcp.handlers.execution import (
        EXECUTE_PIPELINE_DESCRIPTION,
        EXECUTE_PIPELINE_SCHEMA,
        execute_pipeline_handler,
    )
    from app.mcp.handlers.artifacts import (
        INSPECT_RUN_DESCRIPTION,
        INSPECT_RUN_SCHEMA,
        inspect_run_handler,
    )
    from app.mcp.handlers.run_control import (
        PAUSE_RUN_DESCRIPTION,
        PAUSE_RUN_SCHEMA,
        RESUME_RUN_DESCRIPTION,
        RESUME_RUN_SCHEMA,
        CANCEL_RUN_DESCRIPTION,
        CANCEL_RUN_SCHEMA,
        handle_pause_run,
        handle_resume_run,
        handle_cancel_run,
    )
    from app.mcp.handlers.provenance import (
        list_artifacts_handler,
        LIST_ARTIFACTS_DESCRIPTION,
        LIST_ARTIFACTS_SCHEMA,
        get_artifact_lineage_handler,
        GET_ARTIFACT_LINEAGE_DESCRIPTION,
        GET_ARTIFACT_LINEAGE_SCHEMA,
        replay_run_handler,
        REPLAY_RUN_DESCRIPTION,
        REPLAY_RUN_SCHEMA,
    )
    from app.mcp.handlers.optimization import (
        optimize_execution_handler,
        OPTIMIZE_EXECUTION_DESCRIPTION,
        OPTIMIZE_EXECUTION_SCHEMA,
    )

    register("list_nodes", LIST_NODES_DESCRIPTION, LIST_NODES_SCHEMA, list_nodes_handler)
    register("generate_graph", GENERATE_GRAPH_DESCRIPTION, GENERATE_GRAPH_SCHEMA, generate_graph_handler)
    register("validate_graph", VALIDATE_GRAPH_DESCRIPTION, VALIDATE_GRAPH_SCHEMA, validate_graph_handler)
    register("get_graph_schema", GET_GRAPH_SCHEMA_DESCRIPTION, GET_GRAPH_SCHEMA_SCHEMA, get_graph_schema_handler)
    register("get_graph_capability_summary", GET_GRAPH_CAPABILITY_SUMMARY_DESCRIPTION, GET_GRAPH_CAPABILITY_SUMMARY_SCHEMA, get_graph_capability_summary_handler)
    register("get_event_schema", GET_EVENT_SCHEMA_DESCRIPTION, GET_EVENT_SCHEMA_SCHEMA, get_event_schema_handler)
    register("execute_pipeline", EXECUTE_PIPELINE_DESCRIPTION, EXECUTE_PIPELINE_SCHEMA, execute_pipeline_handler)
    register("inspect_run", INSPECT_RUN_DESCRIPTION, INSPECT_RUN_SCHEMA, inspect_run_handler)
    register("pause_run", PAUSE_RUN_DESCRIPTION, PAUSE_RUN_SCHEMA, handle_pause_run)
    register("resume_run", RESUME_RUN_DESCRIPTION, RESUME_RUN_SCHEMA, handle_resume_run)
    register("cancel_run", CANCEL_RUN_DESCRIPTION, CANCEL_RUN_SCHEMA, handle_cancel_run)
    register("list_artifacts", LIST_ARTIFACTS_DESCRIPTION, LIST_ARTIFACTS_SCHEMA, list_artifacts_handler)
    register("get_artifact_lineage", GET_ARTIFACT_LINEAGE_DESCRIPTION, GET_ARTIFACT_LINEAGE_SCHEMA, get_artifact_lineage_handler)
    register("replay_run", REPLAY_RUN_DESCRIPTION, REPLAY_RUN_SCHEMA, replay_run_handler)
    register("optimize_execution", OPTIMIZE_EXECUTION_DESCRIPTION, OPTIMIZE_EXECUTION_SCHEMA, optimize_execution_handler)
