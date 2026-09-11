# app/core/run_notify.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Fire ops webhooks on terminal run statuses (best-effort).
Owns:             notify_run_terminal().
Public Surface:   notify_run_terminal(status, run_id, **meta).
Must NOT:         Raise to callers; import app.api.
Dependencies:     app.core.webhook.WebhookService (lazy).
Reason To Change: New webhook event types or payload schema.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_EVENT_MAP = {
    "completed": "pipeline_complete",
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
    """Notify configured webhooks for a terminal run status (never raises)."""
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
