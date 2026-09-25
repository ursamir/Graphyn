# app/core/run_status.py
"""
Bounded Context:  BC6 — Observability & Storage / Runtime
Responsibility:   Canonical run status names and transition matrix (SRS §13.2).

Wire canonical statuses (writers emit these):
  pending | running | paused | succeeded | failed | cancelled

Legacy storage alias: ``completed`` is treated as ``succeeded`` on read
(Wave A: migrate writes to ``succeeded``; map old journals on read).

Public Surface:   normalize_status, TERMINAL_STATUSES, ACTIVE_STATUSES,
                  FINISHED_STATUSES, can_transition, next_status,
                  InvalidTransition, load_durable_status
Must NOT:         Import app.api.
Dependencies:     pathlib, json (for durable meta load).
Reason To Change: SRS Current×Action matrix changes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# Canonical wire values (SRS §13.2)
CANONICAL_STATUSES = frozenset(
    {"pending", "running", "paused", "succeeded", "failed", "cancelled"}
)
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
ACTIVE_STATUSES = frozenset({"pending", "running", "paused"})
# Finished for cleanup purposes (includes legacy completed)
FINISHED_STATUSES = frozenset({"succeeded", "completed", "failed", "cancelled"})

# Legacy aliases accepted on read → canonical
_READ_ALIASES = {
    "completed": "succeeded",
    "active": "running",
    "in-progress": "running",
    "queued": "pending",
}

# Operator actions and internal succeed/fail
# Current × Action → Next | None means illegal
_MATRIX: dict[str, dict[str, Optional[str]]] = {
    "pending": {
        "start": "running",
        "pause": None,
        "resume": None,
        "cancel": "cancelled",
        "succeed": None,
        "fail": None,
    },
    "running": {
        "start": None,
        "pause": "paused",
        "resume": None,
        "cancel": "cancelled",
        "succeed": "succeeded",
        "fail": "failed",
    },
    "paused": {
        "start": None,
        "pause": None,
        "resume": "running",
        "cancel": "cancelled",
        "succeed": None,
        "fail": "failed",
    },
    "succeeded": {
        "start": None,
        "pause": None,
        "resume": None,
        "cancel": None,
        "succeed": None,
        "fail": None,
    },
    "failed": {
        "start": None,
        "pause": None,
        "resume": None,
        "cancel": None,
        "succeed": None,
        "fail": None,
    },
    "cancelled": {
        "start": None,
        "pause": None,
        "resume": None,
        "cancel": "cancelled",  # idempotent ack
        "succeed": None,
        "fail": None,
    },
}


class InvalidTransition(ValueError):
    """Illegal Current×Action transition (maps to HTTP 409 invalid_transition)."""

    def __init__(self, current: str, action: str) -> None:
        self.current = current
        self.action = action
        super().__init__(f"invalid_transition: cannot {action} from status={current}")


def normalize_status(status: Optional[str]) -> str:
    """Map storage/legacy status to canonical wire value."""
    if not status or not isinstance(status, str):
        return "unknown"
    s = status.strip().lower()
    if s in _READ_ALIASES:
        return _READ_ALIASES[s]
    if s in CANONICAL_STATUSES:
        return s
    return s  # unknown passthrough


def can_transition(current: str, action: str) -> bool:
    cur = normalize_status(current)
    row = _MATRIX.get(cur)
    if row is None:
        return False
    return row.get(action) is not None


def next_status(current: str, action: str) -> str:
    """Return next status or raise InvalidTransition.

    Special case: cancel on cancelled returns cancelled (idempotent).
    """
    cur = normalize_status(current)
    row = _MATRIX.get(cur)
    if row is None:
        raise InvalidTransition(cur, action)
    nxt = row.get(action)
    if nxt is None:
        raise InvalidTransition(cur, action)
    return nxt


def load_durable_status(run_dir: Path | str) -> Optional[str]:
    """Read normalized status from run meta.json, or None if missing."""
    path = Path(run_dir) / "meta.json"
    if not path.exists():
        return None
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(meta, dict):
        return None
    raw = meta.get("status")
    if not isinstance(raw, str):
        return None
    return normalize_status(raw)
