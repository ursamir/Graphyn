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
    """Return whether the list envelope should be used (API-PAGE-001 P1).

    Default **ON** when the query param is omitted (``None``).
    Escape hatch for bare arrays: ``?envelope=0`` / ``false`` / ``no`` / ``off``.
    Explicit on: ``?envelope=1`` / ``true`` / ``yes`` / ``on``.
    """
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("0", "false", "no", "off"):
        return False
    if s in ("1", "true", "yes", "on"):
        return True
    # Unknown non-empty values keep the normative default (envelope on).
    return True


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
    """Return envelope (default) or bare list when ``envelope`` is False."""
    if not envelope:
        return list(items)
    return list_envelope(items, total=total, limit=limit, offset=offset)
