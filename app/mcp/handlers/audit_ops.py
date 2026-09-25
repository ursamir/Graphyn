# app/mcp/handlers/audit_ops.py
"""MCP tools for audit list/export (J6 accountability)."""
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
    from app.core.audit import list_audit

    args = arguments or {}
    limit = int(args.get("limit") or 100)
    events = list_audit(limit=limit)
    return {"events": events, "count": len(events)}


def export_audit_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    import json

    from app.core.audit import audit_events_path, list_audit

    args = arguments or {}
    limit = max(1, min(int(args.get("limit") or 1000), 10000))
    # Prefer raw JSONL file when present and limit covers all; else rebuild.
    path = audit_events_path()
    if path.is_file() and limit >= 10000:
        try:
            content = path.read_text(encoding="utf-8")
            return {
                "format": "jsonl",
                "path": str(path),
                "content": content,
                "bytes": len(content.encode("utf-8")),
            }
        except Exception as exc:
            return _err("internal_error", f"Failed to read audit log: {exc}")
    events = list_audit(limit=limit)
    # list_audit returns newest first; export chronological (oldest first)
    lines = [
        json.dumps(ev, ensure_ascii=False, default=str)
        for ev in reversed(events)
        if isinstance(ev, dict)
    ]
    content = "\n".join(lines) + ("\n" if lines else "")
    return {
        "format": "jsonl",
        "path": str(path),
        "content": content,
        "count": len(lines),
        "bytes": len(content.encode("utf-8")),
    }
