# app/api/routers/credentials.py
"""REST endpoints for the live Graphyn credential (connection) store.

Never returns raw secret values. Auth matches other /api/v1 admin routes.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.actor import resolve_actor
from app.core.credentials import (
    CredentialError,
    CredentialNotFoundError,
    create_connection,
    get_connection,
    list_connections,
    list_kinds,
    revoke_connection,
    set_default,
    update_connection,
)

router = APIRouter(prefix="/credentials", tags=["credentials"])


class CredentialCreateBody(BaseModel):
    name: str = Field(..., min_length=1)
    kind: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
    meta: Optional[dict[str, Any]] = None


class CredentialUpdateBody(BaseModel):
    name: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    is_default: Optional[bool] = None
    meta: Optional[dict[str, Any]] = None
    rotate: bool = False


def _audit(request: Request, action: str, resource_id: str, meta: dict | None = None) -> None:
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action=action,
            resource_type="credential",
            resource_id=resource_id,
            meta=meta or {},
            request_id=getattr(request.state, "request_id", None),
        )
    except Exception:
        pass


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, CredentialNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, CredentialError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="credential store error")


@router.get("/kinds", summary="List registered credential kinds")
def get_kinds():
    kinds = []
    for k in list_kinds():
        kinds.append({
            "id": k.id,
            "label": k.label,
            "description": k.description,
            "fields": [
                {
                    "name": f.name,
                    "secret": bool(f.secret),
                    "required": bool(f.required),
                    "description": f.description,
                    "default": f.default,
                }
                for f in k.fields
            ],
            "env_fallbacks": dict(k.env_fallbacks or {}),
        })
    return {"kinds": kinds}


def _active_org_id() -> str | None:
    from app.core.trust.identity import current_identity

    ident = current_identity() or {}
    if ident.get("kind") == "user":
        return ident.get("org_id")
    return None


@router.get("", summary="List credential connections (metadata / redacted only)")
def list_creds(
    kind: Optional[str] = Query(None),
    include_revoked: bool = Query(False),
):
    org_id = _active_org_id()
    items = list_connections(kind=kind, include_revoked=include_revoked, org_id=org_id)
    return {"items": items, "total": len(items)}


@router.post("", summary="Create a credential connection")
def create_cred(body: CredentialCreateBody, request: Request):
    try:
        from app.core.trust.metering import MeterStoreError, get_meter_store, record_meter_event

        org_id = _active_org_id()
        if org_id:
            try:
                get_meter_store().check_quota(org_id, "credentials")
            except MeterStoreError as exc:
                raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc
        meta = create_connection(
            name=body.name,
            kind=body.kind,
            payload=body.payload or {},
            is_default=bool(body.is_default),
            meta=body.meta,
            org_id=_active_org_id(),
        )
    except (CredentialError, CredentialNotFoundError) as exc:
        raise _http(exc) from exc
    _audit(request, "credential.create", meta["id"], {"kind": meta["kind"], "name": meta["name"]})
    if org_id:
        record_meter_event(org_id, "credential.created", resource_type="credential", resource_id=meta["id"])
    return JSONResponse(content={"ok": True, **meta})



def _org_allowed(meta: dict) -> bool:
    org_id = _active_org_id()
    if not org_id:
        return True
    return (meta.get("org_id") or None) == org_id


def _require_org_cred(connection_id: str) -> dict:
    meta = get_connection(connection_id, include_revoked=True)
    if not _org_allowed(meta):
        raise CredentialNotFoundError(f"Credential connection {connection_id!r} not found")
    return meta

@router.get("/{connection_id}", summary="Get one connection (redacted)")
def get_cred(connection_id: str):
    try:
        return _require_org_cred(connection_id)
    except (CredentialError, CredentialNotFoundError) as exc:
        raise _http(exc) from exc


@router.patch("/{connection_id}", summary="Update / rotate a connection")
@router.put("/{connection_id}", summary="Update / rotate a connection")
def update_cred(connection_id: str, body: CredentialUpdateBody, request: Request):
    try:
        _require_org_cred(connection_id)
        meta = update_connection(
            connection_id,
            name=body.name,
            payload=body.payload,
            is_default=body.is_default,
            meta=body.meta,
            rotate=bool(body.rotate),
        )
    except (CredentialError, CredentialNotFoundError) as exc:
        raise _http(exc) from exc
    _audit(request, "credential.update", meta["id"], {"kind": meta["kind"]})
    return {"ok": True, **meta}


@router.post("/{connection_id}/default", summary="Bind as workspace default for kind")
def bind_default(connection_id: str, request: Request):
    try:
        _require_org_cred(connection_id)
        meta = set_default(connection_id)
    except (CredentialError, CredentialNotFoundError) as exc:
        raise _http(exc) from exc
    _audit(request, "credential.bind_default", meta["id"], {"kind": meta["kind"]})
    return {"ok": True, **meta}


@router.delete("/{connection_id}", summary="Revoke or delete a connection")
def delete_cred(
    connection_id: str,
    request: Request,
    delete: bool = Query(False, description="Permanently delete instead of soft-revoke"),
):
    try:
        _require_org_cred(connection_id)
        result = revoke_connection(connection_id, delete=bool(delete))
    except (CredentialError, CredentialNotFoundError) as exc:
        raise _http(exc) from exc
    _audit(
        request,
        "credential.delete" if result.get("deleted") else "credential.revoke",
        connection_id,
        {},
    )
    return {"ok": True, **result}
