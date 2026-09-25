# app/core/store_integrity.py
"""
Bounded Context:  Persistence integrity helpers (PERS-020).
Responsibility:   Raise a typed StoreCorrupt so critical read paths can map
                  to HTTP 503 error.code=store_corrupt.
Public Surface:   StoreCorrupt, raise_if_store_corrupt, store_corrupt_http_detail
Must NOT:         Import app.api.
"""
from __future__ import annotations

from typing import Any, Optional


class StoreCorrupt(RuntimeError):
    """Critical store index/record is corrupt (PERS-020 → HTTP 503)."""

    def __init__(self, message: str = "store_corrupt", *, path: str | None = None):
        self.path = path
        self.code = "store_corrupt"
        super().__init__(message)


def raise_if_store_corrupt(flag: bool, *, message: str = "Critical store index corrupt", path: str | None = None) -> None:
    if flag:
        raise StoreCorrupt(message, path=path)


def store_corrupt_http_detail(exc: StoreCorrupt | BaseException) -> dict[str, Any]:
    """Shape suitable for HTTPException(detail=...) / error envelope."""
    path = getattr(exc, "path", None)
    return {
        "code": "store_corrupt",
        "message": str(exc) or "store_corrupt",
        **({"path": path} if path else {}),
    }


def readiness_store_corrupt() -> bool:
    """True when readiness snapshot reports store_corrupt."""
    try:
        from app.core.readiness import readiness_snapshot

        snap = readiness_snapshot()
        checks = snap.get("checks") if isinstance(snap, dict) else None
        if isinstance(checks, dict):
            return bool(checks.get("store_corrupt"))
    except Exception:
        return False
    return False


def ensure_store_ok(*, message: str = "Critical store index corrupt") -> None:
    """Raise StoreCorrupt when readiness reports store_corrupt (callers map to 503)."""
    raise_if_store_corrupt(readiness_store_corrupt(), message=message)

