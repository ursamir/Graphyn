# app/mcp/handlers/journey/pipelines.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   Project pipeline list/get/save/publish/promote/rollback MCP tools.
Owns:             list/get/save/publish/promote/rollback pipeline handlers and schemas
Public Surface:   *_handler, *_DESCRIPTION, *_SCHEMA in this module
Must NOT:         Import app.domain except through journey.common; never return secret values.
Dependencies:     app.mcp.handlers.journey.common and the core package this tool calls.
Reason To Change: That MCP tool's arguments or result shape change.
"""
from __future__ import annotations

from typing import Any

from app.mcp.handlers.journey.common import handler_error, meta_props, require_project_dir

# ── Pipelines (J1) ────────────────────────────────────────────────────────────

LIST_PIPELINES_DESCRIPTION = (
    "List workspace pipelines for a project, including env pointers when present."
)
LIST_PIPELINES_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string", "description": "Workspace/project name."},
        **meta_props(),
    },
    "required": ["project"],
    "additionalProperties": False,
}

GET_PIPELINE_DESCRIPTION = (
    "Get a project pipeline draft IR, or an env-resolved graph when env is set."
)
GET_PIPELINE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "pipeline": {"type": "string"},
        "env": {
            "type": "string",
            "description": "draft (default), staging, or prod",
        },
        **meta_props(),
    },
    "required": ["project", "pipeline"],
    "additionalProperties": False,
}

SAVE_PIPELINE_DESCRIPTION = (
    "Save draft Graph IR for a project pipeline (secret fail-closed)."
)
SAVE_PIPELINE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "pipeline": {"type": "string"},
        "graph": {"type": "object", "description": "Graph IR payload"},
        **meta_props(),
    },
    "required": ["project", "pipeline", "graph"],
    "additionalProperties": False,
}

PUBLISH_PIPELINE_DESCRIPTION = (
    "Publish draft pipeline to a new version; optional set_env staging|prod."
)
PUBLISH_PIPELINE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "pipeline": {"type": "string"},
        "message": {"type": "string"},
        "set_env": {"type": "string"},
        "actor": {"type": "string"},
        **meta_props(),
    },
    "required": ["project", "pipeline"],
    "additionalProperties": False,
}

PROMOTE_PIPELINE_DESCRIPTION = (
    "Promote a pipeline version to staging/prod (prod requires approve=true)."
)
PROMOTE_PIPELINE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "pipeline": {"type": "string"},
        "to_env": {"type": "string"},
        "version": {"type": "string"},
        "from_env": {"type": "string"},
        "approve": {"type": "boolean"},
        "actor": {"type": "string"},
        **meta_props(),
    },
    "required": ["project", "pipeline", "to_env"],
    "additionalProperties": False,
}

ROLLBACK_PIPELINE_DESCRIPTION = (
    "Copy a published pipeline version back onto the draft head."
)
ROLLBACK_PIPELINE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "pipeline": {"type": "string"},
        "version": {"type": "string"},
        "actor": {"type": "string"},
        **meta_props(),
    },
    "required": ["project", "pipeline", "version"],
    "additionalProperties": False,
}


def list_pipelines_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.pipelines.pipeline_environments import enrich_pipeline_summary
    from app.core.pipelines.project_pipelines import list_pipelines

    args = arguments or {}
    try:
        project_dir, _ = require_project_dir(str(args.get("project") or ""))
    except FileNotFoundError as exc:
        return handler_error("not_found", str(exc))
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))
    rows = [enrich_pipeline_summary(project_dir, row) for row in list_pipelines(project_dir)]
    return {"pipelines": rows, "count": len(rows)}


def get_pipeline_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.pipelines.pipeline_environments import get_environment_graph
    from app.core.pipelines.project_pipelines import get_pipeline

    args = arguments or {}
    pipeline = str(args.get("pipeline") or "").strip()
    env = str(args.get("env") or "draft").strip().lower()
    try:
        project_dir, _ = require_project_dir(str(args.get("project") or ""))
        if env and env != "draft":
            return get_environment_graph(project_dir, pipeline, env)
        return get_pipeline(project_dir, pipeline)
    except FileNotFoundError as exc:
        return handler_error("not_found", str(exc))
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))


def save_pipeline_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.ir.secret_policy import InlineSecretError
    from app.core.pipelines.project_pipelines import put_pipeline

    args = arguments or {}
    pipeline = str(args.get("pipeline") or "").strip()
    graph = args.get("graph")
    if not isinstance(graph, dict):
        return handler_error("validation_failed", "graph object required")
    try:
        project_dir, name = require_project_dir(str(args.get("project") or ""))
        return put_pipeline(project_dir, pipeline, graph, project_name=name)
    except FileNotFoundError as exc:
        return handler_error("not_found", str(exc))
    except InlineSecretError as exc:
        return handler_error("secret_in_ir", str(exc))
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))


def publish_pipeline_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.pipelines.pipeline_environments import publish_version

    args = arguments or {}
    try:
        project_dir, name = require_project_dir(str(args.get("project") or ""))
        return publish_version(
            project_dir,
            str(args.get("pipeline") or "").strip(),
            project_name=name,
            message=args.get("message"),
            set_env=args.get("set_env"),
            actor=str(args.get("actor") or "mcp"),
        )
    except FileNotFoundError as exc:
        return handler_error("not_found", str(exc))
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))


def promote_pipeline_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.pipelines.pipeline_environments import promote_environment

    args = arguments or {}
    try:
        project_dir, _ = require_project_dir(str(args.get("project") or ""))
        return promote_environment(
            project_dir,
            str(args.get("pipeline") or "").strip(),
            to_env=str(args.get("to_env") or "").strip(),
            version=args.get("version"),
            from_env=args.get("from_env"),
            approve=bool(args.get("approve")),
            actor=str(args.get("actor") or "mcp"),
        )
    except FileNotFoundError as exc:
        return handler_error("not_found", str(exc))
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))


def rollback_pipeline_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.trust.audit import record_audit
    from app.core.pipelines.pipeline_environments import rollback_draft_to_version

    args = arguments or {}
    pipeline = str(args.get("pipeline") or "").strip()
    version = str(args.get("version") or "").strip()
    try:
        project_dir, name = require_project_dir(str(args.get("project") or ""))
        graph = rollback_draft_to_version(
            project_dir, pipeline, version, project_name=name
        )
        record_audit(
            actor=str(args.get("actor") or "mcp"),
            action="pipeline.rollback",
            resource_type="pipeline",
            resource_id=f"{name}/{pipeline}@{version}",
            meta={},
        )
        return {"pipeline": pipeline, "version": version, "graph": graph}
    except FileNotFoundError as exc:
        return handler_error("not_found", str(exc))
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))
