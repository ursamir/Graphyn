# app/mcp/handlers/journey/notifications.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   In-app notification MCP tools.
Owns:             list_notifications and mark_notifications_read handlers and schemas
Public Surface:   *_handler, *_DESCRIPTION, *_SCHEMA in this module
Must NOT:         Import app.domain except through journey.common; never return secret values.
Dependencies:     app.mcp.handlers.journey.common and the core package this tool calls.
Reason To Change: That MCP tool's arguments or result shape change.
"""
from __future__ import annotations

from typing import Any

from app.mcp.handlers.journey.common import handler_error, meta_props, require_project_dir

LIST_NOTIFICATIONS_DESCRIPTION = (
    "List in-app notifications (newest first). Optional unread_only filter."
)
LIST_NOTIFICATIONS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "unread_only": {"type": "boolean"},
        "limit": {"type": "integer"},
        "offset": {"type": "integer"},
        **meta_props(),
    },
    "additionalProperties": False,
}

MARK_NOTIFICATIONS_READ_DESCRIPTION = (
    "Mark in-app notifications as read by id list, or all when all=true."
)
MARK_NOTIFICATIONS_READ_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "ids": {"type": "array", "items": {"type": "string"}},
        "all": {"type": "boolean"},
        "actor": {"type": "string"},
        **meta_props(),
    },
    "additionalProperties": False,
}


def list_notifications_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.notify.in_app_notify import list_notifications

    args = arguments or {}
    return list_notifications(
        unread_only=bool(args.get("unread_only")),
        limit=int(args.get("limit") or 50),
        offset=int(args.get("offset") or 0),
    )


def mark_notifications_read_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.trust.audit import record_audit
    from app.core.notify.in_app_notify import mark_read

    args = arguments or {}
    ids = args.get("ids") if isinstance(args.get("ids"), list) else []
    all_read = bool(args.get("all"))
    result = mark_read([str(i) for i in ids], all_read=all_read)
    try:
        record_audit(
            actor=str(args.get("actor") or "mcp"),
            action="notifications.mark_read",
            resource_type="notification",
            resource_id="all" if all_read else ",".join(str(i) for i in ids[:8]) or "none",
            meta={"marked": result.get("marked"), "all": all_read},
        )
    except Exception:
        pass
    return result
