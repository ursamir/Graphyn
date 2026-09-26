# app/mcp/handlers/credentials.py
"""MCP tools for the live credential store. Never returns raw secrets."""
from __future__ import annotations

from typing import Any

_META = {
    "type": "object",
    "properties": {"auth_token": {"type": "string"}},
}

LIST_CREDENTIALS_DESCRIPTION = (
    "List Graphyn credential connections (metadata + redacted fields only). "
    "Never returns raw secret values. Optional kind filter."
)
LIST_CREDENTIALS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "kind": {"type": "string", "description": "Optional kind filter (openai_compat, smtp, …)."},
        "include_revoked": {"type": "boolean", "default": False},
        "_meta": _META,
    },
    "additionalProperties": False,
}

CREATE_CREDENTIAL_DESCRIPTION = (
    "Create a Graphyn credential connection for a kind "
    "(openai_compat, anthropic, gemini, ollama, smtp, webhook). "
    "Payload secrets are stored encrypted under GRAPHYN_HOME/credentials; "
    "the result is redacted (secrets shown as ***)."
)
CREATE_CREDENTIAL_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "kind": {"type": "string"},
        "payload": {"type": "object", "description": "Kind-specific fields (api_key, host, …)."},
        "is_default": {"type": "boolean", "default": False},
        "meta": {"type": "object"},
        "_meta": _META,
    },
    "required": ["name", "kind", "payload"],
    "additionalProperties": False,
}

GET_CREDENTIAL_DESCRIPTION = (
    "Get one credential connection by id (redacted). Never returns raw secrets."
)
GET_CREDENTIAL_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Connection id."},
        "_meta": _META,
    },
    "required": ["id"],
    "additionalProperties": False,
}

UPDATE_CREDENTIAL_DESCRIPTION = (
    "Update or rotate a credential connection. Pass rotate=true to replace the "
    "payload entirely. Result is redacted."
)
UPDATE_CREDENTIAL_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "payload": {"type": "object"},
        "is_default": {"type": "boolean"},
        "rotate": {"type": "boolean", "default": False},
        "meta": {"type": "object"},
        "_meta": _META,
    },
    "required": ["id"],
    "additionalProperties": False,
}

REVOKE_CREDENTIAL_DESCRIPTION = (
    "Revoke (soft) or permanently delete a credential connection."
)
REVOKE_CREDENTIAL_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "delete": {"type": "boolean", "default": False, "description": "Hard delete when true."},
        "_meta": _META,
    },
    "required": ["id"],
    "additionalProperties": False,
}


def _err(exc: Exception) -> dict[str, Any]:
    from app.core.credentials import CredentialError, CredentialNotFoundError

    if isinstance(exc, CredentialNotFoundError):
        return {"error": True, "error_type": "not_found", "message": str(exc)}
    if isinstance(exc, CredentialError):
        return {"error": True, "error_type": "invalid_credential", "message": str(exc)}
    return {"error": True, "error_type": "credential_error", "message": str(exc)}


def list_credentials_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.credentials import list_connections

    args = arguments or {}
    items = list_connections(
        kind=args.get("kind"),
        include_revoked=bool(args.get("include_revoked") or False),
    )
    return {"items": items, "total": len(items)}


def create_credential_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.credentials import create_connection

    args = arguments or {}
    name = args.get("name")
    kind = args.get("kind")
    payload = args.get("payload")
    if not name or not kind:
        return {
            "error": True,
            "error_type": "missing_argument",
            "message": "create_credential requires name and kind.",
        }
    if not isinstance(payload, dict):
        return {
            "error": True,
            "error_type": "missing_argument",
            "message": "create_credential requires a payload object.",
        }
    try:
        meta = create_connection(
            name=str(name),
            kind=str(kind),
            payload=payload,
            is_default=bool(args.get("is_default") or False),
            meta=args.get("meta") if isinstance(args.get("meta"), dict) else None,
        )
    except Exception as exc:
        return _err(exc)
    return {"ok": True, **meta}


def get_credential_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.credentials import get_connection

    args = arguments or {}
    cid = args.get("id")
    if not cid:
        return {
            "error": True,
            "error_type": "missing_argument",
            "message": "get_credential requires 'id'.",
        }
    try:
        return get_connection(str(cid), include_revoked=True)
    except Exception as exc:
        return _err(exc)


def update_credential_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.credentials import update_connection

    args = arguments or {}
    cid = args.get("id")
    if not cid:
        return {
            "error": True,
            "error_type": "missing_argument",
            "message": "update_credential requires 'id'.",
        }
    try:
        meta = update_connection(
            str(cid),
            name=args.get("name"),
            payload=args.get("payload") if isinstance(args.get("payload"), dict) else None,
            is_default=args.get("is_default"),
            meta=args.get("meta") if isinstance(args.get("meta"), dict) else None,
            rotate=bool(args.get("rotate") or False),
        )
    except Exception as exc:
        return _err(exc)
    return {"ok": True, **meta}


def revoke_credential_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.credentials import revoke_connection

    args = arguments or {}
    cid = args.get("id")
    if not cid:
        return {
            "error": True,
            "error_type": "missing_argument",
            "message": "revoke_credential requires 'id'.",
        }
    try:
        result = revoke_connection(str(cid), delete=bool(args.get("delete") or False))
    except Exception as exc:
        return _err(exc)
    return {"ok": True, **result}
