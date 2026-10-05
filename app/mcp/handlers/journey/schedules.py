# app/mcp/handlers/journey/schedules.py
"""
Bounded Context:  Application Layer — MCP Interface
Responsibility:   Schedule and outbound webhook MCP tools.
Owns:             schedule and webhook handlers and schemas
Public Surface:   *_handler, *_DESCRIPTION, *_SCHEMA in this module
Must NOT:         Import app.domain except through journey.common; never return secret values.
Dependencies:     app.mcp.handlers.journey.common and the core package this tool calls.
Reason To Change: That MCP tool's arguments or result shape change.
"""
from __future__ import annotations

from typing import Any

from app.mcp.handlers.journey.common import handler_error, meta_props, require_project_dir

# ── Schedules / webhooks (J3) ─────────────────────────────────────────────────

LIST_SCHEDULES_DESCRIPTION = "List interval / cron schedules."
LIST_SCHEDULES_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {**meta_props()},
    "additionalProperties": False,
}

UPSERT_SCHEDULE_DESCRIPTION = (
    "Create a schedule, or update enabled flag when schedule_id is provided."
)
UPSERT_SCHEDULE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "schedule_id": {"type": "string"},
        "name": {"type": "string"},
        "project": {"type": "string"},
        "pipeline": {"type": "string"},
        "interval_minutes": {"type": "integer"},
        "cron": {"type": "string", "description": "Optional 5-field cron (UTC); overrides interval_minutes"},
        "enabled": {"type": "boolean"},
        "env": {"type": "string"},
        **meta_props(),
    },
    "additionalProperties": False,
}

ENABLE_SCHEDULE_DESCRIPTION = "Enable or disable a schedule by id."
ENABLE_SCHEDULE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "schedule_id": {"type": "string"},
        "enabled": {"type": "boolean"},
        **meta_props(),
    },
    "required": ["schedule_id"],
    "additionalProperties": False,
}

DELETE_SCHEDULE_DESCRIPTION = "Delete a schedule by id."
DELETE_SCHEDULE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "schedule_id": {"type": "string"},
        **meta_props(),
    },
    "required": ["schedule_id"],
    "additionalProperties": False,
}

RUN_SCHEDULE_NOW_DESCRIPTION = "Trigger a schedule immediately."
RUN_SCHEDULE_NOW_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "schedule_id": {"type": "string"},
        **meta_props(),
    },
    "required": ["schedule_id"],
    "additionalProperties": False,
}

GET_WEBHOOKS_DESCRIPTION = "Get outbound webhook configuration (url + events)."
GET_WEBHOOKS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {**meta_props()},
    "additionalProperties": False,
}

PUT_WEBHOOKS_DESCRIPTION = "Set outbound webhook URL and event list."
PUT_WEBHOOKS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "url": {"type": "string"},
        "events": {"type": "array", "items": {"type": "string"}},
        "actor": {"type": "string"},
        **meta_props(),
    },
    "required": ["url"],
    "additionalProperties": False,
}

TEST_WEBHOOK_DESCRIPTION = "Send a test webhook notification to the configured URL."
TEST_WEBHOOK_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "actor": {"type": "string"},
        **meta_props(),
    },
    "additionalProperties": False,
}


def list_schedules_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.pipelines.schedules import list_schedules

    items = list_schedules()
    return {"schedules": items, "count": len(items)}


def upsert_schedule_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.pipelines.schedules import create_schedule, set_schedule_enabled

    args = arguments or {}
    schedule_id = str(args.get("schedule_id") or "").strip()
    if schedule_id:
        enabled = args.get("enabled")
        if enabled is None:
            enabled = True
        try:
            updated = set_schedule_enabled(schedule_id, bool(enabled))
            return {"ok": True, "schedule": updated, "upsert": "update"}
        except KeyError:
            return handler_error("not_found", f"Schedule '{schedule_id}' not found")
        except ValueError as exc:
            return handler_error("validation_failed", str(exc))
    try:
        item = create_schedule(
            name=str(args.get("name") or "").strip(),
            project=str(args.get("project") or "").strip(),
            pipeline=str(args.get("pipeline") or "").strip(),
            interval_minutes=int(args.get("interval_minutes") or 60),
            enabled=bool(args.get("enabled") if args.get("enabled") is not None else True),
            env=str(args.get("env") or "prod"),
            cron=(str(args.get("cron")).strip() or None) if args.get("cron") else None,
        )
        return {"ok": True, "schedule": item, "upsert": "create"}
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))


def enable_schedule_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.pipelines.schedules import set_schedule_enabled

    args = arguments or {}
    schedule_id = str(args.get("schedule_id") or "").strip()
    enabled = bool(args.get("enabled") if args.get("enabled") is not None else True)
    try:
        return set_schedule_enabled(schedule_id, enabled)
    except KeyError:
        return handler_error("not_found", f"Schedule '{schedule_id}' not found")
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))


def delete_schedule_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.pipelines.schedules import delete_schedule

    args = arguments or {}
    schedule_id = str(args.get("schedule_id") or "").strip()
    try:
        delete_schedule(schedule_id)
        return {"ok": True, "deleted": schedule_id}
    except KeyError:
        return handler_error("not_found", f"Schedule '{schedule_id}' not found")
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))


def run_schedule_now_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.pipelines.schedules import run_schedule_now

    args = arguments or {}
    schedule_id = str(args.get("schedule_id") or "").strip()
    try:
        return run_schedule_now(schedule_id)
    except KeyError:
        return handler_error("not_found", f"Schedule '{schedule_id}' not found")
    except FileNotFoundError as exc:
        return handler_error("not_found", str(exc))
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))


def get_webhooks_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.notify.webhook import WebhookService

    # Never return the raw URL (path/query commonly carries the secret).
    return WebhookService().public_config()


def put_webhooks_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.trust.audit import record_audit
    from app.core.notify.webhook import WebhookService

    args = arguments or {}
    url = str(args.get("url") or "").strip()
    events = args.get("events") if isinstance(args.get("events"), list) else []
    try:
        WebhookService().save(url, [str(e) for e in events])
    except ValueError as exc:
        return handler_error("validation_failed", str(exc))
    from app.core.trust.egress import redact_webhook_url_for_api

    redacted_url = redact_webhook_url_for_api(url)
    record_audit(
        actor=str(args.get("actor") or "mcp"),
        action="webhook.set",
        resource_type="webhook",
        resource_id=redacted_url[:64] or "webhook",
        meta={"events": list(events)},
    )
    return {"ok": True, "url": redacted_url, "url_configured": bool(url), "events": events}


def test_webhook_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.trust.audit import record_audit
    from app.core.notify.webhook import WebhookService

    args = arguments or {}
    svc = WebhookService()
    config = svc.load()
    url = config.get("url")
    if not url:
        return {"ok": False, "reason": "No webhook URL configured"}
    svc.notify("test", {"message": "Test notification from Graphyn MCP"})
    from app.core.trust.egress import redact_webhook_url_for_api

    redacted_url = redact_webhook_url_for_api(str(url))
    record_audit(
        actor=str(args.get("actor") or "mcp"),
        action="webhook.test",
        resource_type="webhook",
        resource_id=redacted_url[:64] or "webhook",
        meta={},
    )
    return {"ok": True, "url": redacted_url}
