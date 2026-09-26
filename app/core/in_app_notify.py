# app/core/in_app_notify.py
"""Minimal in-app notification store (JSONL) for run/ops events.

Persists under GRAPHYN_HOME so agents and REST can list/mark-read without a
full Slack OAuth / notification-center product. Bounded, best-effort, never
raises to callers of append helpers used from run_notify.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_MAX_EVENTS = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def notifications_path() -> Path:
    override = (os.environ.get("GRAPHYN_NOTIFICATIONS_PATH") or "").strip()
    if override:
        return Path(override)
    from app.core.config import graphyn_home

    return graphyn_home() / "notifications.jsonl"


def _read_all(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except OSError as exc:
        logger.debug("in_app_notify read failed: %s", exc)
        return []
    return out


def _write_all(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


def append_notification(
    *,
    title: str,
    body: str = "",
    level: str = "info",
    event: str | None = None,
    run_id: str | None = None,
    project: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one in-app notification. Returns the stored event dict."""
    path = notifications_path()
    item: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "created_at": _now_iso(),
        "title": (title or "").strip() or "(notification)",
        "body": body if body is not None else "",
        "level": (level or "info").strip().lower() or "info",
        "read": False,
        "event": (event or "").strip() or None,
        "run_id": (run_id or "").strip() or None,
        "project": (project or "").strip() or None,
        "meta": meta or {},
    }
    with _lock:
        events = _read_all(path)
        events.append(item)
        if len(events) > _MAX_EVENTS:
            events = events[-_MAX_EVENTS:]
        _write_all(path, events)
    return item


def list_notifications(
    *,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return newest-first notifications with pagination."""
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    path = notifications_path()
    with _lock:
        events = _read_all(path)
    events = list(reversed(events))  # newest first
    if unread_only:
        events = [e for e in events if not e.get("read")]
    total = len(events)
    page = events[offset : offset + limit]
    unread = sum(1 for e in _read_all(path) if not e.get("read"))
    return {
        "notifications": page,
        "count": len(page),
        "total": total,
        "unread_count": unread,
        "offset": offset,
        "limit": limit,
    }


def mark_read(ids: list[str] | None = None, *, all_read: bool = False) -> dict[str, Any]:
    """Mark selected (or all) notifications as read."""
    id_set = {str(i).strip() for i in (ids or []) if str(i).strip()}
    path = notifications_path()
    changed = 0
    with _lock:
        events = _read_all(path)
        for ev in events:
            if all_read or (ev.get("id") in id_set):
                if not ev.get("read"):
                    ev["read"] = True
                    ev["read_at"] = _now_iso()
                    changed += 1
        if changed:
            _write_all(path, events)
    return {"ok": True, "marked": changed, "all": bool(all_read)}


def notify_from_run_event(event: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Helper for run_notify: map terminal events into an in-app row (best-effort)."""
    try:
        status = str(payload.get("status") or "")
        run_id = str(payload.get("run_id") or "")
        level = "error" if event == "pipeline_failed" else "info"
        title = f"{event}: run {run_id or '?'}"
        lines = [f"status={status}"]
        if payload.get("graph_name"):
            lines.append(f"graph={payload['graph_name']}")
        if payload.get("project"):
            lines.append(f"project={payload['project']}")
        if payload.get("error"):
            lines.append(f"error={payload['error']}")
        return append_notification(
            title=title,
            body="\n".join(lines),
            level=level,
            event=event,
            run_id=run_id or None,
            project=str(payload.get("project") or "") or None,
            meta={"graph_name": payload.get("graph_name"), "status": status},
        )
    except Exception as exc:
        logger.debug("in_app_notify from run skipped: %s", exc)
        return None
