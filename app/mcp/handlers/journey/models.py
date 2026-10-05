# app/mcp/handlers/journey/models.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   Model registry MCP tools.
Owns:             list/get/register/request/approve model handlers and schemas
Public Surface:   *_handler, *_DESCRIPTION, *_SCHEMA in this module
Must NOT:         Import app.domain except through journey.common; never return secret values.
Dependencies:     app.mcp.handlers.journey.common and the core package this tool calls.
Reason To Change: That MCP tool's arguments or result shape change.
"""
from __future__ import annotations

from typing import Any

from app.mcp.handlers.journey.common import handler_error, meta_props, require_project_dir

from app.mcp.auth import resolve_mcp_actor

# ── Models (J2) ───────────────────────────────────────────────────────────────

LIST_MODELS_DESCRIPTION = "List registered models (stage pointers)."
LIST_MODELS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {**meta_props()},
    "additionalProperties": False,
}

GET_MODEL_DESCRIPTION = "Get one registered model by name."
GET_MODEL_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        **meta_props(),
    },
    "required": ["name"],
    "additionalProperties": False,
}

REGISTER_MODEL_DESCRIPTION = "Register a model stage pointer from a run artifact slug."
REGISTER_MODEL_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "run_id": {"type": "string"},
        "slug": {"type": "string"},
        "stage": {"type": "string"},
        "description": {"type": "string"},
        "actor": {"type": "string"},
        "model_path": {"type": "string"},
        "node_id": {"type": "string"},
        "allow_untrained": {"type": "boolean"},
        **meta_props(),
    },
    "required": ["name", "run_id", "slug"],
    "additionalProperties": False,
}

REQUEST_MODEL_PROD_DESCRIPTION = "Request prod stage for a model (pending approval)."
REQUEST_MODEL_PROD_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "run_id": {"type": "string"},
        "actor": {"type": "string"},
        **meta_props(),
    },
    "required": ["name"],
    "additionalProperties": False,
}

APPROVE_MODEL_PROD_DESCRIPTION = "Approve pending prod stage for a model."
APPROVE_MODEL_PROD_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "actor": {"type": "string"},
        **meta_props(),
    },
    "required": ["name"],
    "additionalProperties": False,
}
def list_models_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.mlops.model_registry import list_models

    models = list_models()
    return {"models": models, "count": len(models)}


def get_model_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.mlops.model_registry import get_model

    args = arguments or {}
    name = str(args.get("name") or "").strip()
    try:
        return get_model(name)
    except FileNotFoundError as exc:
        return handler_error("not_found", str(exc))
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))


def _full_run_id(run_id: str) -> str:
    """Unique prefix (>= 8 chars) → full run id (the registry stores full ids).

    Raises ``RunIdAmbiguous`` (a ``LookupError``) for ambiguous prefixes.
    """
    if not run_id:
        return run_id
    from app.core.config import runs_dir
    from app.core.runs.run_resolve import resolve_run_id_soft

    return resolve_run_id_soft(runs_dir(), run_id)


def register_model_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.mlops.model_registry import register_model

    args = arguments or {}
    try:
        return register_model(
            str(args.get("name") or "").strip(),
            run_id=_full_run_id(str(args.get("run_id") or "").strip()),
            slug=str(args.get("slug") or "").strip(),
            stage=str(args.get("stage") or "staging"),
            description=args.get("description"),
            actor=str(resolve_mcp_actor(args)["actor"]),
            node_id=(str(args["node_id"]).strip() or None) if args.get("node_id") else None,
            model_path=(str(args["model_path"]).strip() or None) if args.get("model_path") else None,
            allow_untrained=bool(args.get("allow_untrained")),
        )
    except (ValueError, LookupError) as exc:
        # ModelUntrained message names ``compiled_untrained`` / allow_untrained;
        # LookupError = ambiguous run id prefix.
        return handler_error("validation_failed", str(exc))


def request_model_prod_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.mlops.model_registry import request_prod

    args = arguments or {}
    try:
        return request_prod(
            str(args.get("name") or "").strip(),
            run_id=_full_run_id(str(args["run_id"]).strip()) if args.get("run_id") else args.get("run_id"),
            actor=str(resolve_mcp_actor(args)["actor"]),
        )
    except FileNotFoundError as exc:
        return handler_error("not_found", str(exc))
    except (ValueError, LookupError) as exc:
        return handler_error("validation_failed", str(exc))


def approve_model_prod_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.mlops.model_registry import approve_prod

    args = arguments or {}
    try:
        return approve_prod(
            str(args.get("name") or "").strip(),
            actor=str(resolve_mcp_actor(args)["actor"]),
        )
    except FileNotFoundError as exc:
        return handler_error("not_found", str(exc))
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))