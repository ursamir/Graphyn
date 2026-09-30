# app/core/notify/__init__.py
"""
Bounded Context:  BC6 — Notifications
Responsibility:   Webhook, SMTP, and in-app notification sinks.
Owns:             Re-exports of this package's public names.
Public Surface:   lazy __getattr__ exports listed in _EXPORTS.
Must NOT:         Import heavy submodules at package import time.
Dependencies:     Submodules of this package (lazy).
Reason To Change: A public name moves to another package.
"""
from __future__ import annotations

_EXPORTS: dict[str, str] = {
    "WebhookService": "app.core.notify.webhook",
    "append_notification": "app.core.notify.in_app_notify",
    "list_notifications": "app.core.notify.in_app_notify",
    "mark_read": "app.core.notify.in_app_notify",
    "notifications_path": "app.core.notify.in_app_notify",
    "notify_from_run_event": "app.core.notify.in_app_notify",
    "send_email": "app.core.notify.smtp_notify",
    "smtp_config_from_credentials": "app.core.notify.smtp_notify",
    "smtp_config_from_env": "app.core.notify.smtp_notify",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    module = importlib.import_module(module_name)
    return getattr(module, name)


__all__ = sorted(_EXPORTS)
