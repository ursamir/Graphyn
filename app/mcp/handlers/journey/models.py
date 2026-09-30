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


def register_model_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.mlops.model_registry import register_model

    args = arguments or {}
    try:
        return register_model(
            str(args.get("name") or "").strip(),
            run_id=str(args.get("run_id") or "").strip(),
            slug=str(args.get("slug") or "").strip(),
            stage=str(args.get("stage") or "staging"),
            description=args.get("description"),
            actor=str(args.get("actor") or "mcp"),
        )
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))


def request_model_prod_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.mlops.model_registry import request_prod

    args = arguments or {}
    try:
        return request_prod(
            str(args.get("name") or "").strip(),
            run_id=args.get("run_id"),
            actor=str(args.get("actor") or "mcp"),
        )
    except FileNotFoundError as exc:
        return handler_error("not_found", str(exc))
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))


def approve_model_prod_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.mlops.model_registry import approve_prod

    args = arguments or {}
    try:
        return approve_prod(
            str(args.get("name") or "").strip(),
            actor=str(args.get("actor") or "mcp"),
        )
    except FileNotFoundError as exc:
        return handler_error("not_found", str(exc))
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))