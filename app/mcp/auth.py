# app/mcp/auth.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   Token authentication middleware for MCP tool invocations.
Owns:             check_auth() — validates _meta.auth_token against
                  GRAPHYN_API_TOKEN, a GRAPHYN_API_TOKENS mapped token or an
                  issued user token (then checks the tool's RBAC permission
                  via mcp_tool_permission() + project membership). Reads token
                  on every call (no caching) so rotation takes effect immediately.
                  resolve_mcp_actor() — bind audit actor to the token map.
Public Surface:   check_auth(arguments, tool_name=None) -> dict | None,
                  mcp_tool_permission(tool_name) -> str,
                  resolve_mcp_actor(arguments) -> identity dict
Must NOT:         Cache the API token at module level. Must not import from
                  app.domain or any execution module.
Dependencies:     app.core.config (api_token, auth_required),
                  app.core.trust.identity (token map), stdlib (typing).
Reason To Change: Auth scheme changes (e.g. JWT, OAuth), or token location
                  in arguments changes.
"""
from __future__ import annotations

from typing import Any

from app.core.config import api_token as _api_token
from app.core.config import auth_required as _auth_required
from app.core.config import graphyn_env as _graphyn_env


_FAIL_CLOSED_MSG = (
    "Authentication required. GRAPHYN_AUTH_REQUIRED=1 or "
    "GRAPHYN_ENV=production/staging forbids an empty GRAPHYN_API_TOKEN. "
    "Set GRAPHYN_API_TOKEN and pass it in _meta.auth_token."
)


def resolve_mcp_actor(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Bind MCP audit actor to ``_meta.auth_token`` (same policy as gate decide).

    Returns ``{actor, actor_verified, claimed_actor, token_mapped}``.
    A mapped token always wins over a client ``actor`` string (kept as
    ``claimed_actor`` when it differs). Unmapped / no token →
    ``mcp:<claimed or mcp>`` with ``actor_verified=False``.
    """
    from app.core.trust.identity import identity_from_credentials

    args = arguments or {}
    meta = args.get("_meta") if isinstance(args.get("_meta"), dict) else {}
    token = str(meta.get("auth_token") or "") or None
    claimed = args.get("actor") if isinstance(args.get("actor"), str) else None
    ident = identity_from_credentials(token, claimed)
    if ident.get("token_mapped"):
        return {
            "actor": str(ident["actor"]),
            "actor_verified": True,
            "token_mapped": True,
            "claimed_actor": ident.get("claimed_actor"),
        }
    label = (claimed or "mcp").strip()[:128] or "mcp"
    if label == "mcp":
        actor = "mcp"
    elif label.startswith("mcp:"):
        actor = label[:128]
    else:
        actor = f"mcp:{label}"[:128]
    return {
        "actor": actor,
        "actor_verified": False,
        "token_mapped": False,
        "claimed_actor": None,
    }


def check_auth(arguments: dict[str, Any], tool_name: str | None = None) -> dict[str, Any] | None:
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
    from app.core.trust.identity import token_accepted, token_auth_configured

    # Read on every call — never cached at module level. GRAPHYN_API_TOKEN
    # or any GRAPHYN_API_TOKENS mapped token is accepted.
    if not (_api_token() or token_auth_configured()):
        if _auth_required():
            return {
                "error": True,
                "error_type": "unauthorized",
                "message": _FAIL_CLOSED_MSG,
                "graphyn_env": _graphyn_env(),
            }
        return None  # development convenience — allow all

    provided = (arguments or {}).get("_meta", {}).get("auth_token", "") or ""
    if not token_accepted(str(provided)):
        return {
            "error": True,
            "error_type": "unauthorized",
            "message": (
                "Authentication required. Provide the API token in "
                "_meta.auth_token."
            ),
        }
    from app.core.trust.identity import identity_from_credentials

    ident = identity_from_credentials(str(provided))
    if ident.get("kind") == "worker":
        # Worker-scoped tokens only speak the job protocol (TRUST_MODEL §1).
        return {
            "error": True,
            "error_type": "forbidden",
            "message": "Worker-scoped tokens cannot call MCP tools — use an operator token.",
        }
    if tool_name and ident.get("kind") == "user":
        from app.core.trust.rbac import check_project_permission

        args = arguments or {}
        project = args.get("project") or args.get("workspace")
        project = str(project).strip() if isinstance(project, str) and project.strip() else None
        msg = check_project_permission(ident, project, mcp_tool_permission(tool_name))
        if msg:
            return {"error": True, "error_type": "forbidden", "message": msg}
    return None


# Non-read MCP tools → permission (same names as app.core.trust.rbac).
_MCP_TOOL_PERMISSIONS: dict[str, str] = {
    "execute_pipeline": "runs.execute",
    "pause_run": "runs.execute",
    "resume_run": "runs.execute",
    "cancel_run": "runs.execute",
    "replay_run": "runs.execute",
    "run_schedule_now": "runs.execute",
    "accept_proposal": "approve",
    "reject_proposal": "approve",
    "approve_model_prod": "approve",
    "promote_pipeline": "approve",
    "promote_ship_package": "approve",
    "decide_gate": "approve",
    "install_plugin": "plugins.admin",
    "manage_plugin": "plugins.admin",
    "create_credential": "credentials.admin",
    "update_credential": "credentials.admin",
    "revoke_credential": "credentials.admin",
    "get_webhooks": "system.admin",
    "put_webhooks": "system.admin",
    "test_webhook": "system.admin",
    "get_audit_events": "audit.read",
    "export_audit": "audit.read",
    "list_workers": "read",
    "list_jobs": "read",
    "mark_notifications_read": "read",
}
_READ_PREFIXES = ("list_", "get_", "describe_", "search_", "inspect_", "validate_", "compare_", "generate_", "optimize_")


def mcp_tool_permission(tool_name: str) -> str:
    """Permission a user needs to call ``tool_name`` (unknown writes → ``pipelines.write``)."""
    name = str(tool_name or "")
    if name in _MCP_TOOL_PERMISSIONS:
        return _MCP_TOOL_PERMISSIONS[name]
    if name.startswith(_READ_PREFIXES):
        return "read"
    return "pipelines.write"
