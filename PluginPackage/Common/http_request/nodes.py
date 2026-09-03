"""HttpRequestNode — generic HTTP call with mock provider and env-name auth."""
from __future__ import annotations

import importlib
import json
import logging
import os
import time
from typing import Any, ClassVar, Literal
from pydantic import Field
from urllib.parse import urlencode

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("http_request.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

HttpResponse = _types.HttpResponse

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


class HttpRequestNode(Node):
    """Issue an HTTP request. Mock mode needs no network."""

    node_type: ClassVar[str] = "http_request"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="http_request",
        label="HTTP Request",
        description=(
            "HTTP request with method/url/headers/query/json body, timeout, retry, "
            "and auth_env for Authorization from an env var NAME (not a secret in IR)."
        ),
        category="Output",
        version="1.0.0",
        tags=["http", "request", "workflow", "common"],
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
            data_type=object | None,
            cardinality="single",
            required=False,
            description="Optional body/payload merged into json when json_body is empty",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=object,
            description="HttpResponse",
        )
    }

    class Config(NodeConfig):
        method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = Field(default='GET', title="Method", description="HTTP method. One of: GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS.")
        url: str = Field(default='', title="URL", description="HTTP URL.")
        headers: dict = Field(default={}, title="Headers", description="Headers.")
        query: dict = Field(default={}, title="Query", description="Query.")
        json_body: dict | list | None = Field(default=None, title="Json Body", description="Json Body.")
        body: str = Field(default='', title="Body", description="Body.")
        timeout_s: float = Field(default=30.0, title="Timeout S", description="Timeout in seconds.")
        retry: int = Field(default=0, title="Retry", description="Retry.")
        provider: Literal["http", "mock"] = Field(default='http', title="Provider", description="Remote or local service provider. One of: http, mock.")
        mock_response: dict = Field(default={}, title="Mock Response", description="Mock Response.")
        auth_env: str = Field(default='', title="Auth Env", description="Auth Env.")
        auth_header: str = Field(default='Authorization', title="Auth Header", description="Auth Header.")
        auth_prefix: str = Field(default='Bearer ', title="Auth Prefix", description="Auth Prefix.")

    def process(self, inputs):
        payload = inputs.get("input") if isinstance(inputs, dict) else inputs
        url = (self.config.url or "").strip()
        method = (self.config.method or "GET").upper()
        headers = {str(k): str(v) for k, v in dict(self.config.headers or {}).items()}
        auth_env = (self.config.auth_env or "").strip()
        provider = (self.config.provider or "http").strip().lower()
        if auth_env:
            try:
                from app.core.secrets import resolve_secret
                token = resolve_secret(auth_env)
            except Exception:
                token = os.environ.get(auth_env, "").strip()
            if not token and provider != "mock":
                raise RuntimeError(
                    f"HttpRequestNode: auth_env={auth_env!r} is set but secret/env "
                    f"{auth_env} is empty. Store it with `graphyn secrets set {auth_env}` "
                    "or export the env var. Do not put API keys in Graph IR."
                )
            if token:
                prefix = self.config.auth_prefix if self.config.auth_prefix is not None else "Bearer "
                headers[self.config.auth_header or "Authorization"] = f"{prefix}{token}"
        query = dict(self.config.query or {})
        json_body = self.config.json_body
        if json_body is None and payload is not None and method in {"POST", "PUT", "PATCH"}:
            json_body = _jsonable(payload) if not isinstance(payload, str) else None
        body = self.config.body or ""
        if provider == "mock":
            mock = dict(self.config.mock_response or {})
            status = int(mock.get("status_code", mock.get("status", 200)))
            mock_body = mock.get("body", mock.get("json", {"ok": True, "mock": True}))
            text = mock.get("text")
            if text is None:
                text = mock_body if isinstance(mock_body, str) else json.dumps(_jsonable(mock_body))
            parsed = mock_body
            if isinstance(mock_body, str):
                try:
                    parsed = json.loads(mock_body)
                except Exception:
                    parsed = mock_body
            return {"output": HttpResponse(
                url=url or "mock://http_request",
                method=method,
                status_code=status,
                ok=200 <= status < 300,
                headers=dict(mock.get("headers") or {}),
                body=parsed,
                text=str(text)[:65536],
                metadata={"provider": "mock", "query": query},
            )}
        if not url:
            raise RuntimeError("HttpRequestNode: config.url is required unless provider='mock'.")
        if query:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{urlencode({str(k): str(v) for k, v in query.items()})}"
        attempts = max(1, int(self.config.retry or 0) + 1)
        last_exc = None
        timeout = float(self.config.timeout_s or 30.0)
        for i in range(attempts):
            try:
                status, text, resp_headers = self._request(
                    method, url, headers, json_body, body, timeout
                )
                parsed = text
                try:
                    parsed = json.loads(text) if text else None
                except Exception:
                    parsed = text
                ok = 200 <= int(status) < 300
                if not ok:
                    raise RuntimeError(
                        f"HttpRequestNode: {method} {url} failed with HTTP {status}: {str(text)[:200]}"
                    )
                return {"output": HttpResponse(
                    url=url,
                    method=method,
                    status_code=int(status),
                    ok=ok,
                    headers=resp_headers,
                    body=parsed,
                    text=str(text)[:65536],
                    metadata={"attempts": i + 1},
                )}
            except Exception as exc:
                last_exc = exc
                if i + 1 < attempts:
                    time.sleep(min(0.05 * (2 ** i), 1.0))
                    continue
                raise
        raise last_exc

    def _request(self, method, url, headers, json_body, body, timeout):
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "HttpRequestNode: httpx is required for provider='http'. "
                "Install httpx or use provider='mock'."
            ) from exc
        kwargs = {"headers": headers or None, "timeout": timeout}
        if json_body is not None:
            kwargs["json"] = _jsonable(json_body)
        elif body:
            kwargs["content"] = body.encode("utf-8") if isinstance(body, str) else body
        resp = httpx.request(method, url, **kwargs)
        return int(resp.status_code), resp.text, dict(resp.headers)
