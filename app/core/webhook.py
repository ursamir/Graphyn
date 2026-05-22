"""
WebhookService — fire-and-forget HTTP POST notifications.

Persists webhook configuration to workspace/webhooks.json.
Sends notifications in background threads using httpx.
Never raises on notification failure.
"""

import json
import logging
import threading
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

from app.core.config import webhooks_path as _webhooks_path

# Allowed URL schemes for webhook targets (SSRF prevention)
_ALLOWED_SCHEMES = frozenset({"http", "https"})


class WebhookService:
    @property
    def CONFIG_PATH(self):
        return _webhooks_path()

    def save(self, url: str, events: list[str]) -> None:
        """Persist webhook configuration to workspace/webhooks.json.

        Raises:
            ValueError: if ``url`` does not use http or https scheme, or has
                        no valid host (prevents SSRF via file:// or bare paths).
        """
        parsed = urlparse(url)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise ValueError(
                f"Webhook URL must use http or https scheme, "
                f"got {parsed.scheme!r}. URL: {url!r}"
            )
        if not parsed.netloc:
            raise ValueError(
                f"Webhook URL must have a valid host. URL: {url!r}"
            )
        self.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        config = {"url": url, "events": events}
        with self.CONFIG_PATH.open("w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        # Invalidate in-memory cache so next notify() picks up the new config
        self._config_cache: dict | None = None

    def load(self) -> dict:
        """Read webhook configuration. Returns {} if not configured."""
        if not self.CONFIG_PATH.exists():
            return {}
        try:
            with self.CONFIG_PATH.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Failed to read webhooks.json: %s", exc)
            return {}

    def notify(self, event: str, payload: dict[str, Any]) -> None:
        """Fire-and-forget HTTP POST in a background thread.

        Reads the configured URL and events list from an in-memory cache
        (populated on first call, invalidated by save()). If the event is
        in the subscribed events list (or the list is empty/absent, meaning
        all events), sends a POST request with the payload.
        Logs a warning on failure. Never raises.
        """
        # Use cached config to avoid a disk read on every event
        if not hasattr(self, "_config_cache") or self._config_cache is None:
            self._config_cache = self.load()
        config = self._config_cache

        url = config.get("url")
        if not url:
            return

        subscribed_events = config.get("events", [])
        # Empty list means subscribe to all events
        if subscribed_events and event not in subscribed_events:
            return

        thread = threading.Thread(
            target=self._send,
            args=(url, event, payload),
            # daemon=True: the notification thread will not block process exit.
            # This is intentional fire-and-forget behaviour — if the process
            # exits before the HTTP POST completes, the notification is silently
            # dropped. There is no retry or delivery guarantee. Operators who
            # need guaranteed delivery should consume the structured event queue
            # instead of relying on webhooks for critical notifications.
            daemon=True,
        )
        thread.start()

    def _send(self, url: str, event: str, payload: dict[str, Any]) -> None:
        """Internal: perform the HTTP POST. Logs warning on failure."""
        try:
            import httpx

            body = {"event": event, "payload": payload}
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=body)
                response.raise_for_status()
        except Exception as exc:
            logger.warning(
                "Webhook notification failed for event '%s' to '%s': %s",
                event,
                url,
                exc,
            )
