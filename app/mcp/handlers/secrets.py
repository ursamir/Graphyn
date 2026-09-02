# app/mcp/handlers/secrets.py
"""MCP tools for the local named secret store. List returns names only."""
from __future__ import annotations

from typing import Any

SECRETS_LIST_DESCRIPTION = (
    "List names of secrets stored under GRAPHYN_HOME/secrets. "
    "Never returns secret values."
)

SECRETS_LIST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "additionalProperties": False,
}

SECRETS_SET_DESCRIPTION = (
    "Store a named secret in GRAPHYN_HOME/secrets (file-per-secret, mode 0600). "
    "The value argument is accepted for local MCP and is not echoed in the result."
)

SECRETS_SET_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "Env-style secret name (e.g. OPENAI_API_KEY).",
        },
        "value": {
            "type": "string",
            "description": "Secret value. Stored locally; never returned.",
        },
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        },
    },
    "required": ["name", "value"],
    "additionalProperties": False,
}


def secrets_list_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.secrets import list_secret_names

    return {"names": list_secret_names()}


def secrets_set_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.secrets import SecretError, set_secret

    args = arguments or {}
    name = args.get("name")
    value = args.get("value")
    if not name:
        return {
            "error": True,
            "error_type": "missing_argument",
            "message": "secrets_set requires 'name'.",
        }
    if value is None or value == "":
        return {
            "error": True,
            "error_type": "missing_argument",
            "message": "secrets_set requires a non-empty 'value'.",
        }
    try:
        stored = set_secret(str(name), str(value))
    except SecretError as exc:
        return {"error": True, "error_type": "invalid_secret_name", "message": str(exc)}
    return {"ok": True, "name": stored}
