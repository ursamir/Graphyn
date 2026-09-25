# app/api/pagination.py
"""
Bounded Context:  REST API Layer
Responsibility:   List response envelope helper (SRS API-PAGE-001).
Owns:             list_envelope, maybe_envelope, parse_envelope_flag.
Public Surface:   Same symbols.
Must NOT:         Hit storage or auth.
Dependencies:     typing only.
Reason To Change: Envelope schema or default-migration policy changes.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence


def parse_envelope_flag(raw: Any) -> bool:
    """Return True when client requested ``?envelope=1`` (or true/yes)."""
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    return s in ("1", "true", "yes", "on")


def list_envelope(
    items: Sequence[Any],
    *,
    total: Optional[int] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> dict[str, Any]:
    """Build normative list envelope."""
    items_list = list(items)
    tot = int(total) if total is not None else len(items_list)
    lim = int(limit) if limit is not None else len(items_list)
    off = max(0, int(offset or 0))
    next_offset: int | None
    if off + len(items_list) < tot:
        next_offset = off + len(items_list)
    else:
        next_offset = None
    return {
        "items": items_list,
        "total": tot,
        "limit": lim,
        "offset": off,
        "next_offset": next_offset,
    }


def maybe_envelope(
    items: Sequence[Any],
    *,
    envelope: bool,
    total: Optional[int] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> Any:
    """Return bare list or envelope depending on ``envelope`` flag (additive P0)."""
    if not envelope:
        return list(items)
    return list_envelope(items, total=total, limit=limit, offset=offset)
