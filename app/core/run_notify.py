# app/core/run_notify.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Fire ops webhooks (and optional SMTP) on terminal run statuses (best-effort).
Owns:             notify_run_terminal().
Public Surface:   notify_run_terminal(status, run_id, **meta).
Must NOT:         Raise to callers; import app.api.
Dependencies:     app.core.webhook.WebhookService (lazy); app.core.smtp_notify (lazy).
Reason To Change: New webhook event types, email sink, or payload schema.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_EVENT_MAP = {
    "completed": "pipeline_complete",
    "succeeded": "pipeline_complete",
    "failed": "pipeline_failed",
    "cancelled": "pipeline_failed",
}


def notify_run_terminal(
    status: str,
    run_id: str,
    *,
    graph_name: str | None = None,
    error: str | None = None,
    project: str | None = None,
) -> None:
    """Notify configured webhooks (and optional email) for a terminal run status (never raises)."""
    event = _EVENT_MAP.get((status or "").strip().lower())
    if not event:
        return
    payload: dict[str, Any] = {
        "run_id": run_id,
        "status": status,
    }
    if graph_name:
        payload["graph_name"] = graph_name
    if project:
        payload["project"] = project
    if error:
        payload["error"] = error
    try:
        from app.core.webhook import WebhookService

        WebhookService().notify(event, payload)
    except Exception as exc:
        logger.debug("run webhook notify skipped: %s", exc)
    try:
        _maybe_email_notify(event, payload)
    except Exception as exc:
        logger.debug("run email notify skipped: %s", exc)


def _maybe_email_notify(event: str, payload: dict[str, Any]) -> None:
    """Optional SMTP sink when GRAPHYN_NOTIFY_EMAIL_TO is set (never raises to caller)."""
    to = (os.environ.get("GRAPHYN_NOTIFY_EMAIL_TO") or "").strip()
    if not to:
        return
    subject = f"[Graphyn] {event} run={payload.get('run_id')}"
    lines = [
        f"event: {event}",
        f"run_id: {payload.get('run_id')}",
        f"status: {payload.get('status')}",
    ]
    if payload.get("graph_name"):
        lines.append(f"graph_name: {payload['graph_name']}")
    if payload.get("project"):
        lines.append(f"project: {payload['project']}")
    if payload.get("error"):
        lines.append(f"error: {payload['error']}")
    from app.core.smtp_notify import send_email

    send_email(to=to, subject=subject, body="\n".join(lines))
