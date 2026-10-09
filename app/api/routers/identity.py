# app/api/routers/identity.py
"""
Bounded Context:  REST API Layer
Responsibility:   Tell the caller who the audit trail will record them as.
Owns:             GET /me (identity + roles / permissions / memberships).
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
                  (authenticated like every /api/v1 route).
Must NOT:         Return token values or the token map.
Dependencies:     fastapi, app.api.actor, app.core.trust.identity, app.core.config.
Reason To Change: Identity policy or the Access page payload changes.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["identity"])


@router.get("/me", summary="Caller identity as recorded in the audit trail")
def get_me(request: Request):
    """``{actor, actor_verified, token_mapped, claimed_actor, auth_configured,
    token_map_configured}``.

    ``actor_verified`` is true only when the bearer token maps to a name via
    GRAPHYN_API_TOKENS / GRAPHYN_API_TOKENS_FILE; then ``actor`` is that name
    and a differing X-Actor is reported as ``claimed_actor``. Otherwise
    ``actor`` is the X-Actor header (or ``"unidentified"``).
    """
    from app.api.actor import resolve_identity
    from app.core.trust.identity import load_token_map, token_auth_configured

    from app.core.trust.rbac import ROLE_PERMISSIONS, permissions_for

    ident = resolve_identity(request)
    kind = ident.get("kind")
    if kind in ("user", "agent"):
        roles = list(ident.get("roles") or [])
        perms = sorted(permissions_for(roles))
    elif kind == "worker":
        roles, perms = [], []
    else:
        # Shared API token / unauthenticated dev: break-glass admin.
        roles, perms = ["admin"], sorted(ROLE_PERMISSIONS["admin"])
    return {
        "actor": ident["actor"],
        "actor_verified": bool(ident["actor_verified"]),
        "token_mapped": bool(ident["token_mapped"]),
        "claimed_actor": ident.get("claimed_actor"),
        "auth_configured": token_auth_configured(),
        "token_map_configured": bool(load_token_map()),
        "kind": kind,
        "auth_method": ident.get("auth_method"),
        "user_id": ident.get("user_id"),
        "agent_id": ident.get("agent_id"),
        "agent_slug": ident.get("agent_slug"),
        "credential_id": ident.get("credential_id"),
        "roles": roles,
        "approver_roles": list(ident.get("approver_roles") or []),
        "permissions": perms,
        "memberships": dict(ident.get("memberships") or {}),
        "org_id": ident.get("org_id"),
        "org_role": ident.get("org_role"),
        "orgs": list(ident.get("orgs") or []),
    }
