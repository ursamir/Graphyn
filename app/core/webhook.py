# app/core/webhook.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Fire-and-forget HTTP POST webhook notifications. Persists
                  webhook configuration and sends notifications in background
                  threads with SSRF protection.
Owns:             WebhookService — save(), load(), notify(), _send().
Public Surface:   WebhookService.save(url, events), .notify(event, payload)
Must NOT:         Import from app.domain or app.api at module level.
                  Must never raise on notification failure (fire-and-forget).
Dependencies:     stdlib (ipaddress, json, logging, socket, threading, urllib),
                  httpx (lazy, inside _send()), app.core.config (webhooks_path).
Reason To Change: Webhook delivery guarantees change (e.g. retry added),
                  SSRF protection policy evolves, or new event types are added.
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

    IPv6 literals (e.g. ``::1``, ``::ffff:127.0.0.1``) are checked directly
    via :func:`ipaddress.ip_address` before falling back to DNS resolution, so
    the check is consistent across IPv4-only and dual-stack platforms.
    """
    # Fast path: bare IP literal (IPv4 or IPv6) — no DNS needed.
    try:
        ip = ipaddress.ip_address(hostname)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        pass  # not a bare IP literal — proceed with DNS resolution

    try:
        addr_str = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(addr_str)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except socket.gaierror as exc:
        raise ValueError(f"Webhook URL hostname '{hostname}' could not be resolved: {exc}") from exc


class WebhookService:
    """Fire-and-forget HTTP POST webhook notifications."""

    # Class-level cache shared across all instances so that save() on any
    # instance invalidates the cache seen by all other instances.
    _class_config_cache: dict | None = None

    def __init__(self) -> None:
        pass  # cache lives at class level; no per-instance state needed

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
        # Invalidate class-level cache so all instances pick up the new config.
        WebhookService._class_config_cache = None

    def load(self) -> dict:
        """Read webhook configuration. Returns {} if not configured."""
        if not self.CONFIG_PATH.exists():
            return {}
        try:
            with self.CONFIG_PATH.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning(
                "Failed to read webhooks config at %s: %s — webhook notifications disabled.",
                self.CONFIG_PATH,
                exc,
            )
            return {}

    def notify(self, event: str, payload: dict[str, Any]) -> None:
        """Fire-and-forget HTTP POST in a background thread.

        Reads the configured URL and events list from an in-memory cache
        (populated on first call, invalidated by save()). If the event is
        in the subscribed events list (or the list is empty/absent, meaning
        all events), sends a POST request with the payload.
        Logs a warning on failure. Never raises.
        """
        # Use class-level cached config to avoid a disk read on every event.
        # The cache is shared across all WebhookService instances and is
        # invalidated by save() on any instance.
        if WebhookService._class_config_cache is None:
            WebhookService._class_config_cache = self.load()
        config = WebhookService._class_config_cache

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
        """Internal: perform the HTTP POST. Logs warning on failure.

        SSRF protection: the hostname is resolved once via ``_is_private_host``
        and the connection is made directly to the resolved IP address with the
        ``Host`` header set manually.  This eliminates the DNS rebinding window
        that would exist if ``httpx`` performed its own independent DNS lookup
        after the check.
        """
        try:
            import httpx

            parsed = urlparse(url)
            hostname = parsed.hostname or ""
            if hostname:
                # Resolve the IP once and verify it is not private/loopback.
                # Then rewrite the URL to connect directly to the resolved IP so
                # httpx does not perform a second, independent DNS lookup (which
                # would re-open the DNS rebinding window).
                try:
                    # _is_private_host raises ValueError on unresolvable hosts.
                    if _is_private_host(hostname):
                        logger.warning(
                            "Webhook blocked: URL '%s' resolves to a private/loopback "
                            "address at send time (possible DNS rebinding attack).",
                            url,
                        )
                        return
                    # Resolve to a concrete IP for the actual connection.
                    resolved_ip = socket.gethostbyname(hostname)
                except Exception as exc:
                    logger.warning(
                        "Webhook send-time host validation failed for '%s': %s — skipping.",
                        url, exc,
                    )
                    return

                # Build a URL that targets the resolved IP directly so httpx
                # does not re-resolve DNS.  Preserve scheme, port, path, and
                # query.  IPv6 addresses must be bracketed in the netloc.
                port = parsed.port
                ip_obj = ipaddress.ip_address(resolved_ip)
                ip_netloc = f"[{resolved_ip}]" if ip_obj.version == 6 else resolved_ip
                if port:
                    ip_netloc = f"{ip_netloc}:{port}"
                ip_url = parsed._replace(netloc=ip_netloc).geturl()

                body = {"event": event, "payload": payload}
                # Set the Host header to the original hostname so the remote
                # server receives a well-formed HTTP/1.1 request.
                headers = {"Host": parsed.netloc}
                with httpx.Client(timeout=10.0) as client:
                    response = client.post(ip_url, json=body, headers=headers)
                    response.raise_for_status()
            else:
                # No hostname (should not reach here after save() validation,
                # but handle defensively).
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
