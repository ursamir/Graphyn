# app/mcp/handlers/audit_ops.py
"""MCP tools for audit list/export (J6 accountability).

Export always re-serialises events through ``normalize_audit_event`` (which
redacts webhook URLs) — the raw ``events.jsonl`` is never returned verbatim.
"""
from __future__ import annotations

from typing import Any


def _err(error_type: str, message: str) -> dict[str, Any]:
    return {"error": True, "error_type": error_type, "message": message}


def _meta_props() -> dict[str, Any]:
    return {
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        }
    }


GET_AUDIT_EVENTS_DESCRIPTION = "List recent audit events (newest first)."
GET_AUDIT_EVENTS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "limit": {"type": "integer"},
        **_meta_props(),
    },
    "additionalProperties": False,
}

EXPORT_AUDIT_DESCRIPTION = (
    "Export audit events as JSONL text (AUD-003). Returns content string."
)
EXPORT_AUDIT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "limit": {"type": "integer", "description": "Max events (default 1000)"},
        **_meta_props(),
    },
    "additionalProperties": False,
}


def get_audit_events_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.trust.audit import list_audit

    args = arguments or {}
    limit = int(args.get("limit") or 100)
    events = list_audit(limit=limit)
    return {"events": events, "count": len(events)}


def export_audit_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    import json

    from app.core.trust.audit import audit_events_path, normalize_audit_event

    args = arguments or {}
    limit = max(1, min(int(args.get("limit") or 1000), 10000))
    path = audit_events_path()
    # Always go through normalize_audit_event (redacts webhook URLs etc.);
    # never return the raw events.jsonl bytes, whatever the limit.
    events: list[dict[str, Any]] = []
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            return _err("internal_error", f"Failed to read audit log: {type(exc).__name__}")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                events.append(normalize_audit_event(obj))
    # Chronological (oldest first), most recent *limit* events.
    events = events[-limit:]
    lines = [json.dumps(ev, ensure_ascii=False, default=str) for ev in events]
    content = "\n".join(lines) + ("\n" if lines else "")
    return {
        "format": "jsonl",
        "path": str(path),
        "content": content,
        "count": len(lines),
        "bytes": len(content.encode("utf-8")),
    }
