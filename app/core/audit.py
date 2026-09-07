# app/core/audit.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Thin append-only audit event log for accountability mutations.
Owns:             record_audit(), list_audit(), audit_path helpers.
Public Surface:   record_audit(actor, action, resource_type, resource_id, meta),
                  list_audit(limit).
Must NOT:         Import from app.api or execution orchestrators.
Dependencies:     stdlib, app.core.config.project_dir.
Reason To Change: Audit schema evolves or storage backend changes.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def audit_dir(base_dir: str | Path | None = None) -> Path:
    """Return ``{project}/audit`` (or ``{base_dir}/audit``)."""
    if base_dir is not None:
        return Path(base_dir) / "audit"
    from app.core.config import project_dir

    return project_dir() / "audit"


def audit_events_path(base_dir: str | Path | None = None) -> Path:
    return audit_dir(base_dir) / "events.jsonl"


def record_audit(
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str,
    meta: dict[str, Any] | None = None,
    *,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Append one audit event to ``audit/events.jsonl``. Never raises to callers.

    Events are JSONL (one JSON object per line). Failures are logged and
    swallowed so mutation endpoints stay available if the audit disk is full.
    """
    event: dict[str, Any] = {
        "event_id": uuid.uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat(),
        "actor": actor or "unknown",
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "meta": meta or {},
    }
    try:
        path = audit_events_path(base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, default=str) + "\n"
        with _lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception as exc:
        logger.warning("record_audit failed (%s): %s", action, exc)
    return event


def list_audit(
    limit: int = 100,
    *,
    base_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return the most recent audit events (newest first), up to ``limit``."""
    limit = max(1, min(int(limit or 100), 1000))
    path = audit_events_path(base_dir)
    if not path.exists():
        return []
    try:
        # Read whole file for simplicity (thin seed); cap by scanning from end.
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("list_audit read failed: %s", exc)
        return []

    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            events.append(obj)
    events.reverse()
    return events[:limit]
