# app/api/actor.py
"""
Bounded Context:  REST API Layer
Responsibility:   Resolve a human/agent actor string for audit records.
Owns:             resolve_actor().
Public Surface:   resolve_actor(request) -> str
Must NOT:         Import domain or execution; must not authenticate.
Dependencies:     fastapi Request (typing only via Request).
Reason To Change: Actor header / default policy changes.
"""
from __future__ import annotations

from typing import Any


def resolve_actor(request: Any = None, explicit: str | None = None) -> str:
    """Return actor for audit: explicit body > X-Actor header > ``api``."""
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()[:128]
    if request is not None:
        try:
            header = request.headers.get("x-actor") or request.headers.get("X-Actor")
        except Exception:
            header = None
        if isinstance(header, str) and header.strip():
            return header.strip()[:128]
    return "api"
