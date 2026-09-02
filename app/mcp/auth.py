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
Dependencies:     app.core.config (api_token, auth_required), stdlib (typing).
Reason To Change: Auth scheme changes (e.g. JWT, OAuth), or token location
                  in arguments changes.
"""
from __future__ import annotations

import hmac
from typing import Any

from app.core.config import api_token as _api_token
from app.core.config import auth_required as _auth_required
from app.core.config import graphyn_env as _graphyn_env


_FAIL_CLOSED_MSG = (
    "Authentication required. GRAPHYN_AUTH_REQUIRED=1 or "
    "GRAPHYN_ENV=production/staging forbids an empty GRAPHYN_API_TOKEN. "
    "Set GRAPHYN_API_TOKEN and pass it in _meta.auth_token."
)


def check_auth(arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Validate the auth token in the tool arguments.

    Returns None if auth passes (or is not configured in development).
    Returns a structured error dict if auth fails.

    The token is expected at arguments["_meta"]["auth_token"].
    This mirrors the MCP _meta convention for out-of-band metadata.

    The token is read from the environment on every call so that:
    - Token rotation takes effect immediately without a process restart.
    - Late injection (secrets manager, container orchestrator) works correctly.

    Fail-closed: GRAPHYN_AUTH_REQUIRED=1 or GRAPHYN_ENV=production/staging
    rejects requests when GRAPHYN_API_TOKEN is empty.
    """
    token = _api_token()  # read on every call — never cached at module level
    if not token:
        if _auth_required():
            return {
                "error": True,
                "error_type": "unauthorized",
                "message": _FAIL_CLOSED_MSG,
                "graphyn_env": _graphyn_env(),
            }
        return None  # development convenience — allow all

    provided = (arguments or {}).get("_meta", {}).get("auth_token", "") or ""
    if not hmac.compare_digest(str(provided), token):
        return {
            "error": True,
            "error_type": "unauthorized",
            "message": (
                "Authentication required. Provide the API token in "
                "_meta.auth_token."
            ),
        }
    return None
