# app/mcp/auth.py
"""Token authentication middleware for MCP tool invocations.

Req 1.9, 1.10, 8.9
"""
from __future__ import annotations

import os
from typing import Any

from app.core.config import api_token as _api_token

_TOKEN = _api_token()


def check_auth(arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Validate the auth token in the tool arguments.

    Returns None if auth passes (or is not configured).
    Returns a structured error dict if auth fails.

    The token is expected at arguments["_meta"]["auth_token"].
    This mirrors the MCP _meta convention for out-of-band metadata.

    Req 1.9: token required when GRAPHYN_API_TOKEN is set.
    Req 1.10: no auth required when GRAPHYN_API_TOKEN is unset/empty.
    """
    if not _TOKEN:
        return None  # auth not configured — allow all

    provided = (arguments or {}).get("_meta", {}).get("auth_token", "")
    if provided != _TOKEN:
        return {
            "error": True,
            "error_type": "unauthorized",
            "message": (
                "Authentication required. Provide the API token in "
                "_meta.auth_token."
            ),
        }
    return None
