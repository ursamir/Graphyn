# app/api/errors.py
"""
Bounded Context:  REST API Layer
Responsibility:   Normative SRS §9.0.1 error envelope helpers and FastAPI
                  exception-handler registration (API-ERR-001).
Owns:             error_body(), api_error(), register_exception_handlers(),
                  request_id resolution.
Public Surface:   error_body, api_error, register_exception_handlers,
                  get_or_set_request_id, STATUS_TO_CODE
Must NOT:         Contain business logic or route handlers.
Dependencies:     fastapi, starlette, uuid, typing.
Reason To Change: Error envelope schema or status→code map changes.

SRS API-ERR-001: every non-2xx JSON response under /api/v1/* shall use
``{"error": {code, message, request_id, retryable, ...}}``.  FastAPI
``detail`` may additionally appear for legacy clients.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

# Default machine codes for HTTP status when callers only supply a string detail.
STATUS_TO_CODE: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    412: "precondition_failed",
    422: "validation_failed",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}

_RETRYABLE_STATUSES = frozenset({429, 500, 503})

_REQUEST_ID_HEADER = "X-Request-Id"


def get_or_set_request_id(request: Request) -> str:
    """Return request_id from state/header or generate and stash a UUID."""
    existing = getattr(request.state, "request_id", None)
    if isinstance(existing, str) and existing.strip():
        return existing.strip()
    header = request.headers.get(_REQUEST_ID_HEADER) or request.headers.get("x-request-id")
    if isinstance(header, str) and header.strip():
        rid = header.strip()[:128]
    else:
        rid = str(uuid.uuid4())
    request.state.request_id = rid
    return rid


def error_body(
    *,
    code: str,
    message: str,
    request_id: str,
    detail: Optional[str] = None,
    field_errors: Optional[list[dict[str, Any]]] = None,
    resource: Optional[dict[str, Any]] = None,
    retryable: Optional[bool] = None,
    status_code: int = 400,
    legacy_detail: Any = None,
) -> dict[str, Any]:
    """Build the normative envelope (plus optional legacy ``detail``)."""
    err: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id,
        "retryable": bool(retryable) if retryable is not None else (status_code in _RETRYABLE_STATUSES),
    }
    if detail is not None:
        err["detail"] = detail
    if field_errors is not None:
        err["field_errors"] = field_errors
    if resource is not None:
        err["resource"] = resource
    body: dict[str, Any] = {"error": err}
    # SRS allows dual-emit of FastAPI detail for legacy clients.
    if legacy_detail is not None:
        body["detail"] = legacy_detail
    return body


def api_error(
    status_code: int,
    *,
    code: Optional[str] = None,
    message: str,
    request_id: str = "",
    detail: Optional[str] = None,
    field_errors: Optional[list[dict[str, Any]]] = None,
    resource: Optional[dict[str, Any]] = None,
    retryable: Optional[bool] = None,
    legacy_detail: Any = None,
    headers: Optional[dict[str, str]] = None,
) -> JSONResponse:
    """Return a JSONResponse with the normative error envelope."""
    body = error_body(
        code=code or STATUS_TO_CODE.get(status_code, "error"),
        message=message,
        request_id=request_id or str(uuid.uuid4()),
        detail=detail,
        field_errors=field_errors,
        resource=resource,
        retryable=retryable,
        status_code=status_code,
        legacy_detail=legacy_detail if legacy_detail is not None else message,
    )
    resp_headers = dict(headers or {})
    resp_headers.setdefault(_REQUEST_ID_HEADER, body["error"]["request_id"])
    return JSONResponse(status_code=status_code, content=body, headers=resp_headers)


def _code_from_detail(detail: Any, status_code: int) -> tuple[str, str, Any]:
    """Derive (code, message, legacy_detail) from an HTTPException detail."""
    legacy = detail
    if isinstance(detail, dict):
        code = detail.get("error") or detail.get("code") or STATUS_TO_CODE.get(status_code, "error")
        message = (
            detail.get("message")
            or detail.get("detail")
            or (str(code) if isinstance(code, str) else STATUS_TO_CODE.get(status_code, "error"))
        )
        if not isinstance(code, str):
            code = STATUS_TO_CODE.get(status_code, "error")
        if not isinstance(message, str):
            message = str(message)
        return code, message, legacy
    if isinstance(detail, list):
        return STATUS_TO_CODE.get(status_code, "error"), "Request validation failed", legacy
    if isinstance(detail, str) and detail.strip():
        return STATUS_TO_CODE.get(status_code, "error"), detail.strip(), legacy
    return STATUS_TO_CODE.get(status_code, "error"), STATUS_TO_CODE.get(status_code, "error"), legacy


def _resource_from_detail(detail: Any) -> Optional[dict[str, Any]]:
    if not isinstance(detail, dict):
        return None
    rid = detail.get("run_id") or detail.get("id")
    rtype = detail.get("resource_type")
    if rid and not rtype:
        if "run_id" in detail:
            rtype = "run"
    if rid or rtype:
        out: dict[str, Any] = {}
        if rtype:
            out["type"] = rtype
        if rid:
            out["id"] = str(rid)
        return out or None
    return None


def register_exception_handlers(app: FastAPI) -> None:
    """Install API-ERR-001 handlers on the FastAPI app (idempotent-safe)."""

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException):
        rid = get_or_set_request_id(request)
        code, message, legacy = _code_from_detail(exc.detail, exc.status_code)
        body = error_body(
            code=code,
            message=message,
            request_id=rid,
            resource=_resource_from_detail(exc.detail),
            status_code=exc.status_code,
            legacy_detail=legacy,
        )
        headers = dict(exc.headers) if exc.headers else {}
        headers[_REQUEST_ID_HEADER] = rid
        return JSONResponse(status_code=exc.status_code, content=body, headers=headers)

    @app.exception_handler(StarletteHTTPException)
    async def _starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
        rid = get_or_set_request_id(request)
        code, message, legacy = _code_from_detail(exc.detail, exc.status_code)
        body = error_body(
            code=code,
            message=message,
            request_id=rid,
            status_code=exc.status_code,
            legacy_detail=legacy,
        )
        headers = {_REQUEST_ID_HEADER: rid}
        return JSONResponse(status_code=exc.status_code, content=body, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(request: Request, exc: RequestValidationError):
        rid = get_or_set_request_id(request)
        errors = jsonable_encoder(exc.errors())
        if request.url.path.startswith("/api/v1/secrets"):
            cleaned = []
            for err in errors:
                item = dict(err)
                loc = item.get("loc") or []
                if any(part == "value" for part in loc):
                    item["input"] = "[redacted]"
                cleaned.append(item)
            errors = cleaned
        field_errors = []
        for err in errors:
            loc = err.get("loc") or []
            field = ".".join(str(p) for p in loc if p not in ("body", "query", "path", "header"))
            field_errors.append(
                {
                    "field": field or str(loc),
                    "message": str(err.get("msg") or "invalid"),
                    "code": str(err.get("type") or "value_error"),
                }
            )
        body = error_body(
            code="validation_failed",
            message="Request validation failed",
            request_id=rid,
            field_errors=field_errors,
            status_code=422,
            legacy_detail=errors,
        )
        return JSONResponse(
            status_code=422,
            content=body,
            headers={_REQUEST_ID_HEADER: rid},
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        rid = get_or_set_request_id(request)
        log.exception("Unhandled error request_id=%s path=%s", rid, request.url.path)
        body = error_body(
            code="internal_error",
            message="Internal server error",
            request_id=rid,
            status_code=500,
            retryable=True,
            legacy_detail="Internal server error",
        )
        return JSONResponse(
            status_code=500,
            content=body,
            headers={_REQUEST_ID_HEADER: rid},
        )
