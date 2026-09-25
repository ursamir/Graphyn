# app/mcp/tool_registry.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   Register all MCP tools on the server instance at startup.
                  Single place that wires handler functions to tool names.
Owns:             register_all_tools() — imports all handlers and calls register().
Public Surface:   register_all_tools(register_fn)
Must NOT:         Contain handler logic. Must not import from app.domain.
Dependencies:     app.mcp.handlers.* (all handler modules).
Reason To Change: A new MCP tool is added or removed, or a handler is renamed.
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
    from app.mcp.handlers.plugins import (
        INSTALL_PLUGIN_DESCRIPTION,
        INSTALL_PLUGIN_SCHEMA,
        LIST_PLUGINS_DESCRIPTION,
        LIST_PLUGINS_SCHEMA,
        MANAGE_PLUGIN_DESCRIPTION,
        MANAGE_PLUGIN_SCHEMA,
        install_plugin_handler,
        list_plugins_handler,
        manage_plugin_handler,
    )
    from app.mcp.handlers.secrets import (
        SECRETS_LIST_DESCRIPTION,
        SECRETS_LIST_SCHEMA,
        SECRETS_SET_DESCRIPTION,
        SECRETS_SET_SCHEMA,
        secrets_list_handler,
        secrets_set_handler,
    )

    from app.mcp.handlers.proposals import (
        ACCEPT_PROPOSAL_DESCRIPTION,
        ACCEPT_PROPOSAL_SCHEMA,
        GET_PROPOSAL_DESCRIPTION,
        GET_PROPOSAL_SCHEMA,
        LIST_PROPOSALS_DESCRIPTION,
        LIST_PROPOSALS_SCHEMA,
        PROPOSE_GRAPH_DESCRIPTION,
        PROPOSE_GRAPH_SCHEMA,
        REJECT_PROPOSAL_DESCRIPTION,
        REJECT_PROPOSAL_SCHEMA,
        accept_proposal_handler,
        get_proposal_handler,
        list_proposals_handler,
        propose_graph_handler,
        reject_proposal_handler,
    )
    from app.mcp.handlers.workspace import (
        GET_TRACE_DESCRIPTION,
        GET_TRACE_SCHEMA,
        LIST_DATA_INPUTS_DESCRIPTION,
        LIST_DATA_INPUTS_SCHEMA,
        LIST_EXPERIMENTS_DESCRIPTION,
        LIST_EXPERIMENTS_SCHEMA,
        LIST_PROJECTS_DESCRIPTION,
        LIST_PROJECTS_SCHEMA,
        get_trace_handler,
        list_data_inputs_handler,
        list_experiments_handler,
        list_projects_handler,
    )
    from app.mcp.handlers.journey import (
        APPROVE_MODEL_PROD_DESCRIPTION,
        APPROVE_MODEL_PROD_SCHEMA,
        COMPARE_RUNS_DESCRIPTION,
        COMPARE_RUNS_SCHEMA,
        DELETE_SCHEDULE_DESCRIPTION,
        DELETE_SCHEDULE_SCHEMA,
        ENABLE_SCHEDULE_DESCRIPTION,
        ENABLE_SCHEDULE_SCHEMA,
        GET_MODEL_DESCRIPTION,
        GET_MODEL_SCHEMA,
        GET_PIPELINE_DESCRIPTION,
        GET_PIPELINE_SCHEMA,
        GET_READINESS_DESCRIPTION,
        GET_READINESS_SCHEMA,
        GET_RUN_DESCRIPTION,
        GET_RUN_OUTPUTS_DESCRIPTION,
        GET_RUN_OUTPUTS_SCHEMA,
        GET_RUN_SCHEMA,
        GET_TEMPLATE_DESCRIPTION,
        GET_TEMPLATE_SCHEMA,
        GET_WEBHOOKS_DESCRIPTION,
        GET_WEBHOOKS_SCHEMA,
        INSTANTIATE_TEMPLATE_DESCRIPTION,
        INSTANTIATE_TEMPLATE_SCHEMA,
        LIST_MODELS_DESCRIPTION,
        LIST_MODELS_SCHEMA,
        LIST_PIPELINES_DESCRIPTION,
        LIST_PIPELINES_SCHEMA,
        LIST_RUNS_DESCRIPTION,
        LIST_RUNS_SCHEMA,
        LIST_SCHEDULES_DESCRIPTION,
        LIST_SCHEDULES_SCHEMA,
        LIST_TEMPLATES_DESCRIPTION,
        LIST_TEMPLATES_SCHEMA,
        PROMOTE_PIPELINE_DESCRIPTION,
        PROMOTE_PIPELINE_SCHEMA,
        PUBLISH_PIPELINE_DESCRIPTION,
        PUBLISH_PIPELINE_SCHEMA,
        PUT_WEBHOOKS_DESCRIPTION,
        PUT_WEBHOOKS_SCHEMA,
        REGISTER_MODEL_DESCRIPTION,
        REGISTER_MODEL_SCHEMA,
        REQUEST_MODEL_PROD_DESCRIPTION,
        REQUEST_MODEL_PROD_SCHEMA,
        ROLLBACK_PIPELINE_DESCRIPTION,
        ROLLBACK_PIPELINE_SCHEMA,
        RUN_SCHEDULE_NOW_DESCRIPTION,
        RUN_SCHEDULE_NOW_SCHEMA,
        SAVE_PIPELINE_DESCRIPTION,
        SAVE_PIPELINE_SCHEMA,
        TEST_WEBHOOK_DESCRIPTION,
        TEST_WEBHOOK_SCHEMA,
        UPSERT_SCHEDULE_DESCRIPTION,
        UPSERT_SCHEDULE_SCHEMA,
        approve_model_prod_handler,
        compare_runs_handler,
        delete_schedule_handler,
        enable_schedule_handler,
        get_model_handler,
        get_pipeline_handler,
        get_readiness_handler,
        get_run_handler,
        get_run_outputs_handler,
        get_template_handler,
        get_webhooks_handler,
        instantiate_template_handler,
        list_models_handler,
        list_pipelines_handler,
        list_runs_handler,
        list_schedules_handler,
        list_templates_handler,
        promote_pipeline_handler,
        publish_pipeline_handler,
        put_webhooks_handler,
        register_model_handler,
        request_model_prod_handler,
        rollback_pipeline_handler,
        run_schedule_now_handler,
        save_pipeline_handler,
        test_webhook_handler,
        upsert_schedule_handler,
    )
    from app.mcp.handlers.ship_ops import (
        CREATE_SHIP_PACKAGE_DESCRIPTION,
        CREATE_SHIP_PACKAGE_SCHEMA,
        DOWNLOAD_SHIP_PACKAGE_DESCRIPTION,
        DOWNLOAD_SHIP_PACKAGE_SCHEMA,
        GET_SHIP_PACKAGE_DESCRIPTION,
        GET_SHIP_PACKAGE_SCHEMA,
        LIST_SHIP_PACKAGES_DESCRIPTION,
        LIST_SHIP_PACKAGES_SCHEMA,
        PROMOTE_SHIP_PACKAGE_DESCRIPTION,
        PROMOTE_SHIP_PACKAGE_SCHEMA,
        create_ship_package_handler,
        download_ship_package_handler,
        get_ship_package_handler,
        list_ship_packages_handler,
        promote_ship_package_handler,
    )
    from app.mcp.handlers.audit_ops import (
        EXPORT_AUDIT_DESCRIPTION,
        EXPORT_AUDIT_SCHEMA,
        GET_AUDIT_EVENTS_DESCRIPTION,
        GET_AUDIT_EVENTS_SCHEMA,
        export_audit_handler,
        get_audit_events_handler,
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
    register("install_plugin", INSTALL_PLUGIN_DESCRIPTION, INSTALL_PLUGIN_SCHEMA, install_plugin_handler)
    register("list_plugins", LIST_PLUGINS_DESCRIPTION, LIST_PLUGINS_SCHEMA, list_plugins_handler)
    register("manage_plugin", MANAGE_PLUGIN_DESCRIPTION, MANAGE_PLUGIN_SCHEMA, manage_plugin_handler)
    register("secrets_list", SECRETS_LIST_DESCRIPTION, SECRETS_LIST_SCHEMA, secrets_list_handler)
    register("secrets_set", SECRETS_SET_DESCRIPTION, SECRETS_SET_SCHEMA, secrets_set_handler)
    register("propose_graph", PROPOSE_GRAPH_DESCRIPTION, PROPOSE_GRAPH_SCHEMA, propose_graph_handler)
    register("list_proposals", LIST_PROPOSALS_DESCRIPTION, LIST_PROPOSALS_SCHEMA, list_proposals_handler)
    register("get_proposal", GET_PROPOSAL_DESCRIPTION, GET_PROPOSAL_SCHEMA, get_proposal_handler)
    from app.core.config import mcp_human_approval_enabled

    if mcp_human_approval_enabled():
        register("accept_proposal", ACCEPT_PROPOSAL_DESCRIPTION, ACCEPT_PROPOSAL_SCHEMA, accept_proposal_handler)
    register("reject_proposal", REJECT_PROPOSAL_DESCRIPTION, REJECT_PROPOSAL_SCHEMA, reject_proposal_handler)
    register("list_experiments", LIST_EXPERIMENTS_DESCRIPTION, LIST_EXPERIMENTS_SCHEMA, list_experiments_handler)
    register("get_trace", GET_TRACE_DESCRIPTION, GET_TRACE_SCHEMA, get_trace_handler)
    register("list_projects", LIST_PROJECTS_DESCRIPTION, LIST_PROJECTS_SCHEMA, list_projects_handler)
    register("list_data_inputs", LIST_DATA_INPUTS_DESCRIPTION, LIST_DATA_INPUTS_SCHEMA, list_data_inputs_handler)

    # Wave A — P0 J1–J3 journey tools
    register("list_pipelines", LIST_PIPELINES_DESCRIPTION, LIST_PIPELINES_SCHEMA, list_pipelines_handler)
    register("get_pipeline", GET_PIPELINE_DESCRIPTION, GET_PIPELINE_SCHEMA, get_pipeline_handler)
    register("save_pipeline", SAVE_PIPELINE_DESCRIPTION, SAVE_PIPELINE_SCHEMA, save_pipeline_handler)
    register("publish_pipeline", PUBLISH_PIPELINE_DESCRIPTION, PUBLISH_PIPELINE_SCHEMA, publish_pipeline_handler)
    register("promote_pipeline", PROMOTE_PIPELINE_DESCRIPTION, PROMOTE_PIPELINE_SCHEMA, promote_pipeline_handler)
    register("rollback_pipeline", ROLLBACK_PIPELINE_DESCRIPTION, ROLLBACK_PIPELINE_SCHEMA, rollback_pipeline_handler)
    register("list_runs", LIST_RUNS_DESCRIPTION, LIST_RUNS_SCHEMA, list_runs_handler)
    register("get_run", GET_RUN_DESCRIPTION, GET_RUN_SCHEMA, get_run_handler)
    register("get_run_outputs", GET_RUN_OUTPUTS_DESCRIPTION, GET_RUN_OUTPUTS_SCHEMA, get_run_outputs_handler)
    register("list_templates", LIST_TEMPLATES_DESCRIPTION, LIST_TEMPLATES_SCHEMA, list_templates_handler)
    register("get_template", GET_TEMPLATE_DESCRIPTION, GET_TEMPLATE_SCHEMA, get_template_handler)
    register("instantiate_template", INSTANTIATE_TEMPLATE_DESCRIPTION, INSTANTIATE_TEMPLATE_SCHEMA, instantiate_template_handler)
    register("register_model", REGISTER_MODEL_DESCRIPTION, REGISTER_MODEL_SCHEMA, register_model_handler)
    register("list_models", LIST_MODELS_DESCRIPTION, LIST_MODELS_SCHEMA, list_models_handler)
    register("get_model", GET_MODEL_DESCRIPTION, GET_MODEL_SCHEMA, get_model_handler)
    register("request_model_prod", REQUEST_MODEL_PROD_DESCRIPTION, REQUEST_MODEL_PROD_SCHEMA, request_model_prod_handler)
    register("approve_model_prod", APPROVE_MODEL_PROD_DESCRIPTION, APPROVE_MODEL_PROD_SCHEMA, approve_model_prod_handler)
    register("compare_runs", COMPARE_RUNS_DESCRIPTION, COMPARE_RUNS_SCHEMA, compare_runs_handler)
    register("list_schedules", LIST_SCHEDULES_DESCRIPTION, LIST_SCHEDULES_SCHEMA, list_schedules_handler)
    register("upsert_schedule", UPSERT_SCHEDULE_DESCRIPTION, UPSERT_SCHEDULE_SCHEMA, upsert_schedule_handler)
    register("enable_schedule", ENABLE_SCHEDULE_DESCRIPTION, ENABLE_SCHEDULE_SCHEMA, enable_schedule_handler)
    register("delete_schedule", DELETE_SCHEDULE_DESCRIPTION, DELETE_SCHEDULE_SCHEMA, delete_schedule_handler)
    register("run_schedule_now", RUN_SCHEDULE_NOW_DESCRIPTION, RUN_SCHEDULE_NOW_SCHEMA, run_schedule_now_handler)
    register("get_webhooks", GET_WEBHOOKS_DESCRIPTION, GET_WEBHOOKS_SCHEMA, get_webhooks_handler)
    register("put_webhooks", PUT_WEBHOOKS_DESCRIPTION, PUT_WEBHOOKS_SCHEMA, put_webhooks_handler)
    register("test_webhook", TEST_WEBHOOK_DESCRIPTION, TEST_WEBHOOK_SCHEMA, test_webhook_handler)
    register("get_readiness", GET_READINESS_DESCRIPTION, GET_READINESS_SCHEMA, get_readiness_handler)

    # Wave A — ship + audit (after ship REST)
    register("create_ship_package", CREATE_SHIP_PACKAGE_DESCRIPTION, CREATE_SHIP_PACKAGE_SCHEMA, create_ship_package_handler)
    register("get_ship_package", GET_SHIP_PACKAGE_DESCRIPTION, GET_SHIP_PACKAGE_SCHEMA, get_ship_package_handler)
    register("list_ship_packages", LIST_SHIP_PACKAGES_DESCRIPTION, LIST_SHIP_PACKAGES_SCHEMA, list_ship_packages_handler)
    register("download_ship_package", DOWNLOAD_SHIP_PACKAGE_DESCRIPTION, DOWNLOAD_SHIP_PACKAGE_SCHEMA, download_ship_package_handler)
    register("promote_ship_package", PROMOTE_SHIP_PACKAGE_DESCRIPTION, PROMOTE_SHIP_PACKAGE_SCHEMA, promote_ship_package_handler)
    register("get_audit_events", GET_AUDIT_EVENTS_DESCRIPTION, GET_AUDIT_EVENTS_SCHEMA, get_audit_events_handler)
    register("export_audit", EXPORT_AUDIT_DESCRIPTION, EXPORT_AUDIT_SCHEMA, export_audit_handler)
