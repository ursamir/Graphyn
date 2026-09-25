# app/api/store_guard.py
"""
Bounded Context:  REST API Layer
Responsibility:   Map PERS-020 store integrity failures to HTTP 503 store_corrupt.
Owns:             ensure_store_readable, raise_http_store_corrupt.
Public Surface:   Same symbols.
Must NOT:         Perform integrity scans (delegate to app.core.store_integrity).
Dependencies:     fastapi, app.core.store_integrity.
Reason To Change: Error envelope shape or guard policy for critical reads.
"""
from __future__ import annotations

from typing import NoReturn

from fastapi import HTTPException

from app.core import store_integrity as _store_integrity
from app.core.store_integrity import StoreCorrupt, store_corrupt_http_detail


def raise_http_store_corrupt(
    message: str = "Critical store index corrupt",
    *,
    path: str | None = None,
    exc: BaseException | None = None,
) -> NoReturn:
    """Raise HTTP 503 with normative ``error.code=store_corrupt`` detail."""
    detail: dict = {"code": "store_corrupt", "message": message}
    if path:
        detail["path"] = path
    if isinstance(exc, StoreCorrupt):
        detail = store_corrupt_http_detail(exc)
    raise HTTPException(status_code=503, detail=detail) from exc


def ensure_store_readable() -> None:
    """Fail closed with 503 when readiness reports store_corrupt (PERS-020).

    Looks up ``readiness_store_corrupt`` on the store_integrity module so tests
    can monkeypatch ``app.core.store_integrity.readiness_store_corrupt``.
    """
    if _store_integrity.readiness_store_corrupt():
        raise_http_store_corrupt()
