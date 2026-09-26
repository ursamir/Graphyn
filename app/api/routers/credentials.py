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
        from app.core.audit import record_audit

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


@router.get("", summary="List credential connections (metadata / redacted only)")
def list_creds(
    kind: Optional[str] = Query(None),
    include_revoked: bool = Query(False),
):
    items = list_connections(kind=kind, include_revoked=include_revoked)
    return {"items": items, "total": len(items)}


@router.post("", summary="Create a credential connection")
def create_cred(body: CredentialCreateBody, request: Request):
    try:
        meta = create_connection(
            name=body.name,
            kind=body.kind,
            payload=body.payload or {},
            is_default=bool(body.is_default),
            meta=body.meta,
        )
    except (CredentialError, CredentialNotFoundError) as exc:
        raise _http(exc) from exc
    _audit(request, "credential.create", meta["id"], {"kind": meta["kind"], "name": meta["name"]})
    return JSONResponse(content={"ok": True, **meta})


@router.get("/{connection_id}", summary="Get one connection (redacted)")
def get_cred(connection_id: str):
    try:
        meta = get_connection(connection_id, include_revoked=True)
    except (CredentialError, CredentialNotFoundError) as exc:
        raise _http(exc) from exc
    return meta


@router.patch("/{connection_id}", summary="Update / rotate a connection")
@router.put("/{connection_id}", summary="Update / rotate a connection")
def update_cred(connection_id: str, body: CredentialUpdateBody, request: Request):
    try:
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
