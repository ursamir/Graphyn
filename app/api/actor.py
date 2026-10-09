# app/api/actor.py
"""
Bounded Context:  REST API Layer
Responsibility:   Resolve the audit identity of an HTTP request, bound to its
                  bearer token (app.core.trust.identity).
Owns:             resolve_identity(), resolve_actor(), audit_identity_fields().
Public Surface:   resolve_identity(request, explicit=None) -> {actor,
                  actor_verified, token_mapped, claimed_actor};
                  resolve_actor(request, explicit=None) -> str;
                  audit_identity_fields(request) -> kwargs for record_audit.
Must NOT:         Import domain or execution; authenticate (main._auth_dep does).
Dependencies:     app.core.trust.identity.
Reason To Change: Actor header / identity policy changes.

Mapped token → actor is the mapped name (verified); X-Actor / body actor that
differs is only ``claimed_actor``. Unmapped token → X-Actor / body actor or
``"unidentified"`` (unverified). HTTP actions never record ``"system"``.
"""
from __future__ import annotations

from typing import Any

from app.core.trust.identity import bearer_from_header, identity_from_credentials


def _header(request: Any, name: str) -> str | None:
    try:
        value = request.headers.get(name)
    except Exception:
        return None
    return value if isinstance(value, str) else None


def resolve_identity(request: Any = None, explicit: str | None = None) -> dict[str, Any]:
    """Identity for audit: ``{actor, actor_verified, token_mapped, claimed_actor}``."""
    token = None
    claimed = None
    org_hdr = None
    if request is not None:
        token = bearer_from_header(_header(request, "authorization"))
        claimed = _header(request, "x-actor")
        org_hdr = _header(request, "x-graphyn-org-id")
    exp = explicit.strip() if isinstance(explicit, str) and explicit.strip() else None
    return identity_from_credentials(token, claimed, exp, header_org_id=org_hdr)


def resolve_actor(request: Any = None, explicit: str | None = None) -> str:
    """Actor string for audit (mapped token name > body actor > X-Actor > ``unidentified``)."""
    return str(resolve_identity(request, explicit)["actor"])


def audit_identity_fields(request: Any = None, explicit: str | None = None) -> dict[str, Any]:
    """``actor`` / ``actor_verified`` / ``claimed_actor`` kwargs for record_audit."""
    ident = resolve_identity(request, explicit)
    return {
        "actor": ident["actor"],
        "actor_verified": bool(ident["actor_verified"]),
        "claimed_actor": ident.get("claimed_actor"),
    }
