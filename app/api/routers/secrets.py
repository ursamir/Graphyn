# app/api/routers/secrets.py
"""REST endpoints for the local named secret store.

GET lists names only. PUT/POST set a value. DELETE removes. Values are never
returned in list/get responses. Invalid bodies on this router have ``value``
inputs redacted in 422 responses (see ``app.api.main`` validation handler).
Writes require the same shared Bearer gate as other ``/api/v1`` admin routes.

Optimistic concurrency (API-CONV-005): PUT/DELETE accept ``If-Match`` /
``resource_version``; mismatch → 412 or 409 ``version_conflict``.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.actor import resolve_actor
from app.api.concurrency import (
    etag_value,
    resolve_expected_version,
    version_conflict_http,
)
from app.api.pagination import maybe_envelope, parse_envelope_flag
from app.core.errors import VersionConflict
from app.core.secrets import (
    SecretError,
    delete_secret,
    list_secret_names,
    secret_meta,
    secret_resource_version,
    set_secret,
)

router = APIRouter(prefix="/secrets", tags=["secrets"])


class SecretSetBody(BaseModel):
    name: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)
    resource_version: Optional[str] = None


class SecretValueBody(BaseModel):
    value: str = Field(..., min_length=1)
    resource_version: Optional[str] = None


def _check_existing_version(name: str, expected: str | None, *, via_if_match: bool) -> None:
    if expected is None:
        return
    try:
        current = secret_resource_version(name) if name in list_secret_names() else "0"
    except SecretError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if str(expected) != str(current):
        raise VersionConflict(via_if_match=via_if_match, current=str(current))


@router.get("", summary="List secret names (values never returned)")
def list_secrets(
    envelope: Optional[str] = Query(None, description="Set to 1 for list envelope; omitted keeps {names} shape."),
):
    names = list_secret_names()
    items = [{"name": n} for n in names]
    # Secrets historically returned {"names": ...}, not a bare array — keep that
    # default; only emit API-PAGE-001 envelope when explicitly requested.
    if envelope is not None and parse_envelope_flag(envelope):
        return maybe_envelope(items, envelope=True, total=len(items), limit=len(items), offset=0)
    return {"names": names}


@router.post("", summary="Store a named secret")
def create_secret(body: SecretSetBody, request: Request):
    try:
        name = set_secret(body.name, body.value)
    except SecretError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        from app.core.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="secret.set",
            resource_type="secret",
            resource_id=name,
            meta={},
            request_id=getattr(request.state, "request_id", None),
        )
    except Exception:
        pass
    meta = secret_meta(name)
    resp = JSONResponse(content={"ok": True, **meta})
    resp.headers["ETag"] = etag_value(meta["resource_version"])
    return resp


@router.put("/{name}", summary="Store or replace a named secret")
def put_secret(name: str, body: SecretValueBody, request: Request):
    expected, via_if_match = resolve_expected_version(request, body.resource_version)
    try:
        _check_existing_version(name, expected, via_if_match=via_if_match)
        stored = set_secret(name, body.value)
    except VersionConflict as exc:
        raise version_conflict_http(exc) from exc
    except SecretError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        from app.core.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="secret.set",
            resource_type="secret",
            resource_id=stored,
            meta={},
            request_id=getattr(request.state, "request_id", None),
        )
    except Exception:
        pass
    meta = secret_meta(stored)
    resp = JSONResponse(content={"ok": True, **meta})
    resp.headers["ETag"] = etag_value(meta["resource_version"])
    return resp


@router.delete("/{name}", summary="Delete a named secret")
def remove_secret(name: str, request: Request):
    expected, via_if_match = resolve_expected_version(request, None)
    try:
        _check_existing_version(name, expected, via_if_match=via_if_match)
        found = delete_secret(name)
    except VersionConflict as exc:
        raise version_conflict_http(exc) from exc
    except SecretError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not found:
        raise HTTPException(status_code=404, detail=f"Secret {name!r} not found")
    try:
        from app.core.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="secret.delete",
            resource_type="secret",
            resource_id=name,
            meta={},
            request_id=getattr(request.state, "request_id", None),
        )
    except Exception:
        pass
    return {"ok": True, "name": name}
