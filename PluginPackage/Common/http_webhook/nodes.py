"""HttpWebhookNode — POST JSON to config.url (completion callback)."""
from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import logging
from typing import Any, ClassVar

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
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
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
        description="POST JSON to a completion callback URL with optional HMAC and timeout.",
        category="Output",
        version="1.0.0",
        tags=["http", "webhook", "callback", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
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
            data_type=object,
            description="WebhookReceipt (status, body) plus pass-through payload in metadata",
        )
    }

    class Config(NodeConfig):
        url: str = ""
        timeout_s: float = 10.0
        hmac_secret: str = ""
        hmac_header: str = "X-Graphyn-Signature"

    def process(self, payload):
        url = (self.config.url or "").strip()
        if not url:
            raise RuntimeError(
                "HttpWebhookNode: config.url is required (completion callback URL)."
            )
        body_obj = _jsonable(payload)
        raw = json.dumps(body_obj, default=str).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        secret = (self.config.hmac_secret or "").encode("utf-8")
        if secret:
            digest = hmac.new(secret, raw, hashlib.sha256).hexdigest()
            headers[self.config.hmac_header or "X-Graphyn-Signature"] = f"sha256={digest}"
        status, text = self._post(url, raw, headers, self.config.timeout_s)
        ok = 200 <= int(status) < 300
        if not ok:
            raise RuntimeError(
                f"HttpWebhookNode: POST {url} failed with HTTP {status}: {text[:200]}"
            )
        return WebhookReceipt(
            url=url,
            status_code=int(status),
            ok=ok,
            body=text[:4096],
            metadata={"bytes": len(raw)},
        )

    def _post(self, url: str, raw: bytes, headers: dict, timeout: float) -> tuple[int, str]:
        try:
            import httpx
        except ImportError:
            import urllib.request
            req = urllib.request.Request(url, data=raw, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return int(resp.status), resp.read().decode("utf-8", errors="replace")
            except Exception as exc:
                raise RuntimeError(f"HttpWebhookNode: POST {url} failed: {exc}") from exc
        try:
            resp = httpx.post(url, content=raw, headers=headers, timeout=timeout)
            return int(resp.status_code), resp.text
        except Exception as exc:
            raise RuntimeError(f"HttpWebhookNode: POST {url} failed: {exc}") from exc
