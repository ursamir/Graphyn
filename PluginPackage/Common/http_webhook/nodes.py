"""HttpWebhookNode — POST JSON to config.url (completion callback)."""
from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import logging
import time
from typing import Any, ClassVar, Literal
from pydantic import Field

from app.core.trust.egress import redact_webhook_url_for_api, validate_http_egress_url

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("http_webhook.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

WebhookReceipt = _types.WebhookReceipt

log = logging.getLogger(__name__)


def _jsonable(obj: Any) -> Any:
    from app.core.nodes.payload import unwrap_payload, wrapper_field

    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if wrapper_field(obj) is not None:
        # F19 (F-06): send the payload (CodeResult.data, …), not the wrapper.
        return _jsonable(unwrap_payload(obj))
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except Exception:
            return obj.model_dump()
    return str(obj)


class HttpWebhookNode(Node):
    """POST the input payload as JSON to a webhook URL."""

    node_type: ClassVar[str] = "http_webhook"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="http_webhook",
        label="HTTP Webhook",
        description="POST JSON to a completion callback URL (or a webhook credential connection) with optional HMAC (hmac_env) and timeout. Never follows redirects.",
        category="Output",
        version="1.1.0",
        tags=["http", "webhook", "callback", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=False,
        cacheable=False,
        idempotent=False,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=object,
            cardinality="single",
            required=True,
            description="JSON-serializable payload (PortDataType, dict, list, …)",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=WebhookReceipt,
            description="WebhookReceipt (status, body) plus pass-through payload in metadata",
        )
    }

    class Config(NodeConfig):
        url: str = Field(default='', title="Callback URL", description="HTTPS URL to POST completion JSON. Leave empty when connection_id supplies the URL.")
        connection_id: str = Field(default='', title="Webhook connection id", description="Credential store connection (kind webhook); its URL is a secret and is never logged or audited beyond scheme://host. Takes precedence over url.")
        timeout_s: float = Field(default=10.0, title="Timeout (s)", description="Request/operation timeout in seconds.")
        hmac_env: str = Field(default='', title="HMAC env / secret name", description="Env var or Graphyn secret name holding the HMAC key (never put the key itself in IR).")
        hmac_header: str = Field(default='X-Graphyn-Signature', title="HMAC header", description="Header that carries the HMAC signature.")
        provider: Literal["http"] = Field(default='http', title="Provider", description="HTTP provider. Only http (real network) is supported.")

    @classmethod
    def missing_run_config(cls, config):
        if not (str(getattr(config, "url", "") or "").strip() or str(getattr(config, "connection_id", "") or "").strip()):
            return [("url", "HttpWebhookNode: config.url (or connection_id) is required (completion callback URL).")]
        return []

    def _target(self) -> tuple[str, str | None]:
        cid = (getattr(self.config, "connection_id", "") or "").strip()
        if cid:
            from app.core.credentials.resolve import resolve_connection

            resolved = resolve_connection(kind="webhook", connection_id=cid, required=True)
            url = str((resolved.get("payload") or {}).get("url") or "").strip()
            if not url:
                raise RuntimeError(f"HttpWebhookNode: webhook connection {cid!r} has no url")
            return url, cid
        return (self.config.url or "").strip(), None

    def process(self, payload):
        url, conn_id = self._target()
        body_obj = _jsonable(payload)
        raw = json.dumps(body_obj, default=str).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        hmac_env = (getattr(self.config, "hmac_env", "") or "").strip()
        secret_text = ""
        if hmac_env:
            # Guarded env fallback (no GRAPHYN_* internals / non-secret env vars).
            from app.core.trust.secrets import resolve_secret
            secret_text = resolve_secret(hmac_env) or ""
            if not secret_text:
                raise RuntimeError(
                    f"HttpWebhookNode: hmac_env={hmac_env!r} is set but the secret/env is empty."
                )
        secret = secret_text.encode("utf-8") if secret_text else b""
        if secret:
            digest = hmac.new(secret, raw, hashlib.sha256).hexdigest()
            headers[self.config.hmac_header or "X-Graphyn-Signature"] = f"sha256={digest}"
        provider = (self.config.provider or "http").strip().lower()
        if provider != "http":
            raise RuntimeError(
                f"HttpWebhookNode: unknown provider {provider!r}. Use provider='http'."
            )
        timeout = min(max(float(self.config.timeout_s or 10.0), 0.05), 30.0)
        if not url:
            raise RuntimeError(
                "HttpWebhookNode: config.url (or connection_id) is required (completion callback URL)."
            )
        validate_http_egress_url(url)
        label = redact_webhook_url_for_api(url)
        t0 = time.monotonic()
        try:
            status, text = self._post(url, raw, headers, timeout)
        except Exception as exc:
            self.record_external_call("webhook", "POST", label, None, request_sha256=raw,
                                      duration_ms=(time.monotonic() - t0) * 1000.0,
                                      connection_id=conn_id, error=type(exc).__name__)
            raise
        self.record_external_call("webhook", "POST", label, int(status), request_sha256=raw,
                                  response_sha256=text, duration_ms=(time.monotonic() - t0) * 1000.0,
                                  connection_id=conn_id)
        ok = 200 <= int(status) < 300
        if not ok:
            raise RuntimeError(
                f"HttpWebhookNode: POST {label} failed with HTTP {status}: {text[:200]}"
            )
        return WebhookReceipt(
            # A connection URL is a secret — only scheme://host/*** leaves the node.
            url=label if conn_id else url,
            status_code=int(status),
            ok=ok,
            body=text[:4096],
            metadata={"bytes": len(raw), **({"connection_id": conn_id} if conn_id else {})},
        )

    def _post(self, url: str, raw: bytes, headers: dict, timeout: float) -> tuple[int, str]:
        # httpx only: no urllib fallback (urllib follows redirects, which would
        # bypass the egress check on the redirect target). Redirects are never
        # followed; a 3xx is reported as a failed delivery.
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "HttpWebhookNode: httpx is required (pip install httpx)."
            ) from exc
        label = redact_webhook_url_for_api(url)
        try:
            from app.core.trust import egress as _egress

            # F19: resolve-then-connect (IP pinned); redirects never followed.
            resp = _egress.egress_post(url, content=raw, headers=headers, timeout=timeout, follow_redirects=False)
            return int(resp.status_code), str(resp.text or "")
        except Exception as exc:
            from app.core.trust.egress import HttpEgressError

            if isinstance(exc, HttpEgressError):  # message is already URL-redacted
                raise RuntimeError(f"HttpWebhookNode: POST {label} refused: {exc}") from exc
            raise RuntimeError(f"HttpWebhookNode: POST {label} failed: {type(exc).__name__}") from exc
