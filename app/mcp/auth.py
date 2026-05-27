# app/mcp/auth.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   Token authentication middleware for MCP tool invocations.
Owns:             check_auth() — validates _meta.auth_token against
                  GRAPHYN_API_TOKEN. Reads token on every call (no caching)
                  so token rotation takes effect immediately.
Public Surface:   check_auth(arguments) -> dict | None
Must NOT:         Cache the API token at module level. Must not import from
                  app.domain or any execution module.
Dependencies:     app.core.config (api_token), stdlib (typing).
Reason To Change: Auth scheme changes (e.g. JWT, OAuth), or token location
                  in arguments changes.
"""
from __future__ import annotations

import hmac
from typing import Any

from app.core.config import api_token as _api_token


def check_auth(arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Validate the auth token in the tool arguments.

    Returns None if auth passes (or is not configured).
    Returns a structured error dict if auth fails.

    The token is expected at arguments["_meta"]["auth_token"].
    This mirrors the MCP _meta convention for out-of-band metadata.

    The token is read from the environment on every call so that:
    - Token rotation takes effect immediately without a process restart.
    - Late injection (secrets manager, container orchestrator) works correctly.

    Req 1.9: token required when GRAPHYN_API_TOKEN is set.
    Req 1.10: no auth required when GRAPHYN_API_TOKEN is unset/empty.
    """
    token = _api_token()  # read on every call — never cached at module level
    if not token:
        return None  # auth not configured — allow all

    provided = (arguments or {}).get("_meta", {}).get("auth_token", "")
    if not hmac.compare_digest(provided, token):
        return {
            "error": True,
            "error_type": "unauthorized",
            "message": (
                "Authentication required. Provide the API token in "
                "_meta.auth_token."
            ),
        }
    return None
