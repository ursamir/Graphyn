# app/core/notify/webhook.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Fire-and-forget HTTP POST webhook notifications. Persists
                  webhook configuration and sends notifications in background
                  threads with SSRF protection.
Owns:             WebhookService — save(), load(), notify(), _send().
Public Surface:   WebhookService.save(url, events), .notify(event, payload)
Must NOT:         Import from app.domain or app.api at module level.
                  Must never raise on notification failure (fire-and-forget).
Dependencies:     stdlib (json, logging, threading, urllib),
                  httpx (lazy, inside _send()), app.core.config (webhooks_path),
                  app.core.trust.egress (validate_webhook_target_url, webhook_url_log_label).
Reason To Change: Webhook delivery guarantees change (e.g. retry added),
                  SSRF protection policy evolves, or new event types are added.

Logs never include the webhook path/query (the secret): targets are logged via
webhook_url_log_label() and exception text is URL-redacted.
"""

import json
import logging
import re
import threading
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

from app.core.config import webhooks_path as _webhooks_path
from app.core.trust.egress import validate_webhook_target_url, webhook_url_log_label

# Allowed URL schemes for webhook targets (SSRF prevention)
_ALLOWED_SCHEMES = frozenset({"http", "https"})

_URL_IN_TEXT_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>]+")


def _redact_exc_text(exc: BaseException, url: str) -> str:
    """Exception text with every URL reduced to scheme://host (httpx errors
    embed the full request URL, whose path/query is often the webhook secret)."""
    from app.core.trust.egress import redact_webhook_url_for_api

    text = str(exc)
    if url:
        text = text.replace(url, redact_webhook_url_for_api(url))
    return _URL_IN_TEXT_RE.sub(lambda m: redact_webhook_url_for_api(m.group(0)), text)


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

    def save(self, url: str, events: list[str]) -> dict:
        """Persist webhook configuration to workspace/webhooks.json.

        An empty (or whitespace-only) ``url`` clears the configured webhook —
        it skips the scheme/host/SSRF checks below (which only make sense for
        a URL that will actually be dialed) and persists ``url: ""``, matching
        what ``load()`` returns when no webhook has ever been configured.
        Without this, a previously-saved URL could never be removed: any
        non-empty scheme check would reject the empty string outright.

        Raises:
            ValueError: if ``url`` is non-empty and does not use http or https
                        scheme, has no valid host, or resolves to a
                        private/loopback/link-local IP address (SSRF
                        prevention — SEC-3 fix).
        """
        url = (url or "").strip()
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in _ALLOWED_SCHEMES:
                raise ValueError(
                    f"Webhook URL must use http or https scheme, "
                    f"got {parsed.scheme!r}."
                )
            if not parsed.netloc:
                raise ValueError(
                    "Webhook URL must have a valid host."
                )

            validate_webhook_target_url(url)

        self.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        prev = self.load()
        try:
            cur_rv = int(prev.get("resource_version") or 0)
        except (TypeError, ValueError):
            cur_rv = 0
        config = {"url": url, "events": events, "resource_version": cur_rv + 1}
        with self.CONFIG_PATH.open("w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        # Invalidate class-level cache so all instances pick up the new config.
        WebhookService._class_config_cache = None
        return self.load()

    def load(self) -> dict:
        """Read webhook configuration. Always returns ``url`` + ``events`` keys."""
        empty = {"url": "", "events": [], "resource_version": "0", "secret_name": None}
        if not self.CONFIG_PATH.exists():
            return dict(empty)
        try:
            with self.CONFIG_PATH.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                return dict(empty)
            events = raw.get("events")
            rv = raw.get("resource_version")
            try:
                rv_int = int(rv) if rv is not None else 0
            except (TypeError, ValueError):
                rv_int = 0
            # Also derive from mtime when missing for If-Match clients
            if rv_int == 0:
                try:
                    rv_int = int(self.CONFIG_PATH.stat().st_mtime_ns)
                except OSError:
                    rv_int = 0
            return {
                "url": str(raw.get("url") or ""),
                "events": list(events) if isinstance(events, list) else [],
                "resource_version": str(rv_int),
                "secret_name": raw.get("secret_name"),
            }
        except Exception as exc:
            logger.warning(
                "Failed to read webhooks config at %s: %s — webhook notifications disabled.",
                self.CONFIG_PATH,
                exc,
            )
            return dict(empty)


    def public_config(self) -> dict:
        """Return webhook config safe for API responses (URL redacted).

        Persisted ``url`` remains available via :meth:`load` for delivery;
        clients only ever see host/path (or empty / ``***``).
        """
        from app.core.trust.egress import redact_webhook_url_for_api

        cfg = self.load()
        out = dict(cfg)
        out["url"] = redact_webhook_url_for_api(str(cfg.get("url") or ""))
        out["url_configured"] = bool(str(cfg.get("url") or "").strip())
        return out

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

        SSRF protection: re-validates the destination, then POSTs through a
        transport pinned to one of those resolved public IPs (Host/SNI stay on
        the original hostname) so DNS rebinding cannot change the connect target.
        """
        log_target = webhook_url_log_label(url)
        try:
            import httpx

            from app.core.trust.egress import validated_webhook_ips

            ips = validated_webhook_ips(url)
            body = {"event": event, "payload": payload}
            pinned = ips[0]
            parsed = urlparse(url)
            hostname = parsed.hostname or ""

            class _PinTransport(httpx.HTTPTransport):
                def handle_request(self, request: httpx.Request) -> httpx.Response:
                    request.headers["Host"] = hostname
                    request.extensions["sni_hostname"] = hostname
                    request.url = request.url.copy_with(host=pinned)
                    return super().handle_request(request)

            with httpx.Client(timeout=10.0, transport=_PinTransport()) as client:
                response = client.post(url, json=body)
                response.raise_for_status()
        except ValueError as exc:
            logger.warning(
                "Webhook blocked for event '%s' to %s: %s",
                event,
                log_target,
                _redact_exc_text(exc, url),
            )
        except Exception as exc:
            logger.warning(
                "Webhook notification failed for event '%s' to %s: %s: %s",
                event,
                log_target,
                type(exc).__name__,
                _redact_exc_text(exc, url),
            )
