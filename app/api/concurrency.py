# app/api/concurrency.py
"""
Bounded Context:  REST API Layer
Responsibility:   Optimistic concurrency helpers for If-Match / resource_version
                  (SRS API-CONV-005).
Owns:             resolve_expected_version, assert_version_match,
                  version_conflict_http, etag_value, attach_etag.
Public Surface:   Same symbols.
Must NOT:         Persist resources or contain domain logic.
Dependencies:     fastapi HTTPException.
Reason To Change: Concurrency token rules or status mapping change.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


from app.core.errors import VersionConflict  # re-export


def strip_etag(value: str | None) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.startswith("W/"):
        s = s[2:].strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return s


def resolve_expected_version(
    request: Request,
    body_resource_version: Any = None,
) -> tuple[str | None, bool]:
    """Return (expected_token, via_if_match).

    Prefer ``If-Match`` when present; else body/query ``resource_version``.
    """
    raw = request.headers.get("If-Match") or request.headers.get("if-match")
    if raw is not None and str(raw).strip():
        return strip_etag(str(raw)), True
    if body_resource_version is not None and str(body_resource_version).strip() != "":
        return str(body_resource_version).strip(), False
    # Also accept query param for clients that cannot send body field
    q = request.query_params.get("resource_version")
    if q is not None and str(q).strip() != "":
        return str(q).strip(), False
    return None, False


def assert_version_match(
    current: Any,
    expected: str | None,
    *,
    via_if_match: bool,
) -> None:
    """Raise VersionConflict when expected is set and does not match current."""
    if expected is None:
        return
    cur = str(current) if current is not None else ""
    if str(expected) != cur:
        raise VersionConflict(via_if_match=via_if_match, current=cur or None)


def version_conflict_http(exc: VersionConflict | Exception) -> HTTPException:
    """Map VersionConflict / version_conflict ValueError to 412 or 409."""
    via_if_match = isinstance(exc, VersionConflict) and exc.via_if_match
    current = getattr(exc, "current", None) if isinstance(exc, VersionConflict) else None
    detail: dict[str, Any] = {
        "error": "version_conflict" if not via_if_match else "precondition_failed",
        "code": "version_conflict" if not via_if_match else "precondition_failed",
        "message": "resource_version / If-Match mismatch",
    }
    if current is not None:
        detail["current_resource_version"] = current
    status = 412 if via_if_match else 409
    return HTTPException(status_code=status, detail=detail)


def etag_value(resource_version: Any) -> str:
    return f'"{resource_version}"'


def attach_etag(response: JSONResponse | Any, resource_version: Any) -> Any:
    """Set ETag header when response supports headers."""
    try:
        response.headers["ETag"] = etag_value(resource_version)
    except Exception:
        pass
    return response


def optional_resource_version_from_payload(payload: dict | None) -> Any:
    if not isinstance(payload, dict):
        return None
    return payload.get("resource_version")
