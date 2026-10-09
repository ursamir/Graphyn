# app/api/routers/agents.py
"""
Bounded Context:  REST API Layer
Responsibility:   Agent principal CRUD + token mint/revoke (Wave 6 / F17).
Owns:             /agents* routes.
Public Surface:   router (authenticated; admin for mutate).
Must NOT:         Return token secrets except once on mint.
Dependencies:     fastapi, app.core.trust.agents, audit, identity, rbac.
Reason To Change: Agent API surface changes.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.trust.agents import AgentStoreError, get_agent_store

router = APIRouter(tags=["agents"])


def _ident() -> dict[str, Any]:
    from app.core.trust.identity import current_identity

    return current_identity() or {}


def _err(exc: AgentStoreError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


def _require_admin() -> dict[str, Any]:
    ident = _ident()
    if ident.get("kind") == "user":
        from app.core.trust.rbac import permissions_for

        perms = permissions_for(ident.get("roles") or [])
        if "users.admin" in perms or "admin" in perms:
            return ident
        raise HTTPException(status_code=403, detail="Agent admin requires users.admin")
    if ident.get("kind") in (None, "operator", "token"):
        return ident
    raise HTTPException(status_code=403, detail="Agent admin requires users.admin")


def _audit(action: str, resource_id: str, meta: dict | None = None) -> None:
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=str(_ident().get("actor") or "api"),
            action=action,
            resource_type="agent",
            resource_id=resource_id,
            meta=meta or {},
        )
    except Exception:
        pass


class AgentCreateBody(BaseModel):
    slug: str = Field(..., min_length=2, max_length=64)
    name: str = Field("", max_length=128)
    roles: list[str] = Field(default_factory=lambda: ["builder"])
    memberships: dict[str, str] = Field(default_factory=dict)
    org_id: Optional[str] = None
    oidc_client_id: Optional[str] = Field(None, max_length=128)
    notes: str = Field("", max_length=512)


class AgentPatchBody(BaseModel):
    name: Optional[str] = Field(None, max_length=128)
    roles: Optional[list[str]] = None
    memberships: Optional[dict[str, str]] = None
    org_id: Optional[str] = None
    disabled: Optional[bool] = None
    oidc_client_id: Optional[str] = Field(None, max_length=128)
    clear_oidc: bool = False
    notes: Optional[str] = Field(None, max_length=512)


class AgentTokenBody(BaseModel):
    name: str = Field("", max_length=128)
    ttl_s: Optional[float] = Field(None, ge=60, le=365 * 86400)


@router.get("/agents", summary="List agent principals")
def list_agents(org_id: Optional[str] = None, include_disabled: bool = False):
    _require_admin()
    rows = get_agent_store().list_agents(org_id=org_id, include_disabled=include_disabled)
    return [a.public() for a in rows]


@router.post("/agents", summary="Create an agent principal")
def create_agent(body: AgentCreateBody):
    ident = _require_admin()
    store = get_agent_store()
    org = body.org_id or ident.get("org_id")
    try:
        agent = store.create_agent(
            body.slug,
            body.name,
            roles=body.roles,
            memberships=body.memberships,
            org_id=org,
            created_by=str(ident.get("actor") or ""),
            oidc_client_id=body.oidc_client_id,
            notes=body.notes,
        )
    except AgentStoreError as exc:
        raise _err(exc)
    _audit("agent.create", agent.id, {"slug": agent.slug, "roles": agent.roles})
    return agent.public()


@router.get("/agents/{agent_id}", summary="Get one agent")
def get_agent(agent_id: str):
    _require_admin()
    agent = get_agent_store().get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent.public()


@router.patch("/agents/{agent_id}", summary="Update agent")
def patch_agent(agent_id: str, body: AgentPatchBody):
    _require_admin()
    try:
        after = get_agent_store().update_agent(
            agent_id,
            name=body.name,
            roles=body.roles,
            memberships=body.memberships,
            org_id=body.org_id,
            disabled=body.disabled,
            oidc_client_id=body.oidc_client_id,
            clear_oidc=body.clear_oidc,
            notes=body.notes,
        )
    except AgentStoreError as exc:
        raise _err(exc)
    _audit("agent.update", after.id, body.model_dump(exclude_none=True))
    return after.public()


@router.get("/agents/{agent_id}/tokens", summary="List agent API/MCP tokens")
def list_agent_tokens(agent_id: str, include_inactive: bool = False):
    _require_admin()
    try:
        return get_agent_store().list_tokens(agent_id, include_inactive=include_inactive)
    except AgentStoreError as exc:
        raise _err(exc)


@router.post("/agents/{agent_id}/tokens", summary="Mint agent token (shown once)")
def mint_agent_token(agent_id: str, body: AgentTokenBody):
    ident = _require_admin()
    try:
        token, info = get_agent_store().mint_token(
            agent_id,
            name=body.name,
            ttl_s=body.ttl_s,
            created_by=str(ident.get("actor") or ""),
        )
    except AgentStoreError as exc:
        raise _err(exc)
    _audit(
        "agent.token_mint",
        agent_id,
        {"credential_id": info["credential_id"], "name": info.get("name")},
    )
    return info


@router.delete("/agents/{agent_id}/tokens/{credential_id}", summary="Revoke agent token")
def revoke_agent_token(agent_id: str, credential_id: str):
    _require_admin()
    try:
        ok = get_agent_store().revoke_token(agent_id, credential_id)
    except AgentStoreError as exc:
        raise _err(exc)
    if not ok:
        raise HTTPException(status_code=404, detail="Credential already revoked or missing")
    _audit("agent.token_revoke", agent_id, {"credential_id": credential_id})
    return {"ok": True, "credential_id": credential_id}
