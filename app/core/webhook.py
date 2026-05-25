"""
WebhookService — fire-and-forget HTTP POST notifications.

Persists webhook configuration to workspace/webhooks.json.
Sends notifications in background threads using httpx.
Never raises on notification failure.
"""

import ipaddress
import json
import logging
import socket
import threading
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

from app.core.config import webhooks_path as _webhooks_path

# Allowed URL schemes for webhook targets (SSRF prevention)
_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _is_private_host(hostname: str) -> bool:
    """Return True if hostname resolves to a private, loopback, or link-local address.

    Raises ValueError if the hostname cannot be resolved.
    Used to block SSRF attacks via webhook URLs pointing at internal services.
    """
    try:
        addr_str = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(addr_str)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except socket.gaierror as exc:
        raise ValueError(f"Webhook URL hostname '{hostname}' could not be resolved: {exc}") from exc


class WebhookService:
    """Fire-and-forget HTTP POST webhook notifications."""

    def __init__(self) -> None:
        # Initialised here so notify() always has a well-defined cache state
        # regardless of whether save() was called first (BUG-3 fix).
        self._config_cache: dict | None = None

    @property
    def CONFIG_PATH(self):
        return _webhooks_path()

    def save(self, url: str, events: list[str]) -> None:
        """Persist webhook configuration to workspace/webhooks.json.

        Raises:
            ValueError: if ``url`` does not use http or https scheme, has no
                        valid host, or resolves to a private/loopback/link-local
                        IP address (SSRF prevention — SEC-3 fix).
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

        # Block RFC 1918, loopback, and link-local addresses (SSRF prevention).
        # Resolve at save() time so the check is not bypassable via DNS rebinding
        # after the config is written.
        hostname = parsed.hostname or ""
        if hostname:
            try:
                if _is_private_host(hostname):
                    raise ValueError(
                        f"Webhook URL '{url}' resolves to a private or loopback address. "
                        "Webhook targets must be publicly reachable hosts."
                    )
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError(
                    f"Webhook URL hostname validation failed for '{url}': {exc}"
                ) from exc

        self.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        config = {"url": url, "events": events}
        with self.CONFIG_PATH.open("w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        # Invalidate in-memory cache so next notify() picks up the new config
        self._config_cache = None

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
        # Use cached config to avoid a disk read on every event.
        # _config_cache is always initialised in __init__ so hasattr is not needed.
        if self._config_cache is None:
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
            # dropped. There is no retry or delivery guarantee.
            daemon=True,
        )
        thread.start()

    def _send(self, url: str, event: str, payload: dict[str, Any]) -> None:
        """Internal: perform the HTTP POST. Logs warning on failure."""
        try:
            import httpx

            # NEW-12 fix: re-validate the resolved IP at send time to prevent
            # DNS rebinding attacks. The save()-time check uses the DNS record
            # at configuration time; httpx resolves DNS fresh on every connection,
            # so an attacker can change the DNS record after save() passes.
            hostname = urlparse(url).hostname or ""
            if hostname:
                try:
                    if _is_private_host(hostname):
                        logger.warning(
                            "Webhook blocked: URL '%s' resolves to a private/loopback "
                            "address at send time (possible DNS rebinding attack).",
                            url,
                        )
                        return
                except Exception as exc:
                    logger.warning(
                        "Webhook send-time host validation failed for '%s': %s — skipping.",
                        url, exc,
                    )
                    return

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
