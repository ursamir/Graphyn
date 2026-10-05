"""HttpRequestNode — generic HTTP call with credential-store or env-name auth.

Safety properties:
- egress policy validated before any network I/O; redirects are never followed;
- retries only on retryable statuses (``retry_on_status``) or connection
  errors, and only for idempotent methods unless ``idempotency_key`` is set
  (sent as ``Idempotency-Key``); exponential backoff with jitter and a cap;
- the response body is streamed and the request aborted once it exceeds
  ``max_response_bytes``;
- every attempt is recorded via ``Node.record_external_call`` (redacted URL +
  body hashes) for the sealed run audit.
"""
from __future__ import annotations

import importlib
import base64
import json
import logging
import random
import time
from typing import Any, ClassVar, Literal
from pydantic import Field
from urllib.parse import urlencode, urlsplit

from app.core.trust.egress import validate_http_egress_url

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


IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
DEFAULT_RETRY_STATUSES = [429, 500, 502, 503, 504]
DEFAULT_MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class _ResponseTooLarge(RuntimeError):
    pass


def _is_connection_error(exc: BaseException) -> bool:
    """Transport-level failure (connect/read/timeout) — safe to retry for idempotent calls."""
    try:
        import httpx

        if isinstance(exc, httpx.TransportError):
            return True
    except ImportError:
        pass
    return isinstance(exc, (ConnectionError, TimeoutError))


def _retry_after_s(headers: dict) -> float | None:
    for k, v in (headers or {}).items():
        if str(k).lower() == "retry-after":
            try:
                return max(0.0, float(str(v).strip()))
            except ValueError:
                return None
    return None


def http_auth_headers(payload: dict) -> dict[str, str]:
    """Headers for a resolved ``http_auth`` credential payload (bearer | basic | header)."""
    scheme = str(payload.get("scheme") or "bearer").strip().lower()
    if scheme == "bearer":
        token = str(payload.get("token") or "")
        if not token:
            raise RuntimeError("HttpRequestNode: http_auth connection (bearer) has no token")
        return {"Authorization": f"Bearer {token}"}
    if scheme == "basic":
        user = str(payload.get("username") or "")
        pw = str(payload.get("password") or "")
        if not user:
            raise RuntimeError("HttpRequestNode: http_auth connection (basic) has no username")
        raw = base64.b64encode(f"{user}:{pw}".encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {raw}"}
    if scheme == "header":
        name = str(payload.get("header_name") or "").strip()
        value = str(payload.get("header_value") or "")
        if not name or not value:
            raise RuntimeError("HttpRequestNode: http_auth connection (header) needs header_name and header_value")
        return {name: value}
    raise RuntimeError(f"HttpRequestNode: unsupported http_auth scheme {scheme!r}")


def _host_allowed(url: str, allowed_csv: str) -> bool:
    allowed = [h.strip().lower().rstrip(".") for h in str(allowed_csv or "").split(",") if h.strip()]
    if not allowed:
        return True
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return host in allowed


class HttpRequestNode(Node):
    """Issue a real HTTP request (httpx)."""

    node_type: ClassVar[str] = "http_request"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="http_request",
        label="HTTP Request",
        description=(
            "HTTP request with method/url/headers/query/json body, timeout, safe retry "
            "(retryable statuses, idempotent methods or Idempotency-Key), response size cap, "
            "and auth from a credential connection (kind http_auth) or an env/secret NAME."
        ),
        category="Output",
        version="1.1.0",
        tags=["http", "request", "workflow", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        # Remote responses change over time; every execution is real egress.
        deterministic=False,
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
        url: str = Field(default='', title="URL", description="Full request URL (https recommended).")
        headers: dict = Field(default={}, title="Headers", description="HTTP headers as a JSON object of string keys to string values.")
        query: dict = Field(default={}, title="Query", description="URL query parameters as a JSON object.")
        json_body: dict | list | None = Field(default=None, title="JSON body", description="JSON request body (object or array). Prefer this over raw body for JSON APIs.")
        body: str = Field(default='', title="Body", description="Raw request body string used when json_body is empty.")
        timeout_s: float = Field(default=30.0, title="Timeout (s)", description="Request/operation timeout in seconds.")
        retry: int = Field(default=0, ge=0, le=10, title="Retries", description="Retries after a retryable failure (status in retry_on_status or a connection error). Non-idempotent methods (POST/PATCH) retry only when idempotency_key is set.")
        retry_on_status: list[int] = Field(default_factory=lambda: list(DEFAULT_RETRY_STATUSES), title="Retry on status", description="HTTP statuses that may be retried (default 429, 500, 502, 503, 504). Other 4xx/5xx fail immediately.")
        retry_backoff_s: float = Field(default=0.5, ge=0, title="Retry backoff (s)", description="Base delay for exponential backoff with jitter.")
        retry_backoff_max_s: float = Field(default=10.0, ge=0, title="Retry backoff cap (s)", description="Maximum delay between attempts (also caps Retry-After).")
        idempotency_key: str = Field(default='', title="Idempotency key", description="Sent as the Idempotency-Key header; enables retries for POST/PATCH.")
        max_response_bytes: int = Field(default=DEFAULT_MAX_RESPONSE_BYTES, ge=1, title="Max response bytes", description="Abort when the streamed response body exceeds this size (default 5 MB).")
        provider: Literal["http"] = Field(default='http', title="Provider", description="HTTP provider. Only http (real network) is supported.")
        connection_id: str = Field(default='', title="Credential connection id", description="Credential store connection (kind http_auth: bearer | basic | header). Takes precedence over auth_env. Only used when set explicitly.")
        auth_env: str = Field(default='', title="Auth env / secret name", description="Environment variable or Graphyn secret NAME for the bearer/token (never paste the secret into IR). Fallback when connection_id is empty.")
        auth_header: str = Field(default='Authorization', title="Auth header", description="HTTP header that receives the auth_env value (default Authorization).")
        auth_prefix: str = Field(default='Bearer ', title="Auth prefix", description="Prefix prepended to the auth_env secret (e.g. 'Bearer '). Use empty for raw tokens.")

    # ── auth ────────────────────────────────────────────────────────────────
    def _auth_headers(self, url: str) -> tuple[dict[str, str], str | None]:
        cid = (getattr(self.config, "connection_id", "") or "").strip()
        if cid:
            from app.core.credentials.resolve import resolve_connection

            resolved = resolve_connection(kind="http_auth", connection_id=cid, required=True)
            payload = resolved.get("payload") or {}
            if not _host_allowed(url, payload.get("allowed_hosts") or ""):
                raise RuntimeError(
                    f"HttpRequestNode: connection {cid!r} is not bound to host "
                    f"{urlsplit(url).hostname!r} (allowed_hosts)."
                )
            return http_auth_headers(payload), cid
        auth_env = (self.config.auth_env or "").strip()
        if not auth_env:
            return {}, None
        # Guarded env fallback (no GRAPHYN_* internals / non-secret env vars).
        from app.core.trust.secrets import resolve_secret
        token = resolve_secret(auth_env)
        if not token:
            raise RuntimeError(
                f"HttpRequestNode: auth_env={auth_env!r} is set but secret/env "
                f"{auth_env} is empty. Store it with `graphyn secrets set {auth_env}` "
                "or export the env var. Do not put API keys in Graph IR."
            )
        prefix = self.config.auth_prefix if self.config.auth_prefix is not None else "Bearer "
        return {self.config.auth_header or "Authorization": f"{prefix}{token}"}, None

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        cap = float(self.config.retry_backoff_max_s)
        if retry_after is not None:
            return min(cap, retry_after)
        base = float(self.config.retry_backoff_s) * (2 ** attempt)
        return min(cap, base) * random.uniform(0.5, 1.0)

    def process(self, inputs):
        payload = inputs.get("input") if isinstance(inputs, dict) else inputs
        url = (self.config.url or "").strip()
        method = (self.config.method or "GET").upper()
        headers = {str(k): str(v) for k, v in dict(self.config.headers or {}).items()}
        provider = (self.config.provider or "http").strip().lower()
        if provider != "http":
            raise RuntimeError(
                f"HttpRequestNode: unknown provider {provider!r}. Use provider='http'."
            )
        if not url:
            raise RuntimeError("HttpRequestNode: config.url is required.")
        query = dict(self.config.query or {})
        if query:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{urlencode({str(k): str(v) for k, v in query.items()})}"
        # SEC-003: egress policy (trusted default; restricted blocks SSRF ranges)
        # — validated BEFORE any credential is resolved or sent.
        validate_http_egress_url(url)
        auth, conn_id = self._auth_headers(url)
        headers.update(auth)
        idem = (getattr(self.config, "idempotency_key", "") or "").strip()
        if idem:
            headers["Idempotency-Key"] = idem
        json_body = self.config.json_body
        if json_body is None and payload is not None and method in {"POST", "PUT", "PATCH"}:
            json_body = _jsonable(payload) if not isinstance(payload, str) else None
        body = self.config.body or ""
        request_bytes: bytes | None = None
        if json_body is not None:
            request_bytes = json.dumps(_jsonable(json_body), sort_keys=True, default=str).encode("utf-8")
        elif body:
            request_bytes = body.encode("utf-8")

        can_retry = method in IDEMPOTENT_METHODS or bool(idem)
        retry_statuses = {int(x) for x in (self.config.retry_on_status or [])}
        attempts = max(1, int(self.config.retry or 0) + 1) if can_retry else 1
        timeout = float(self.config.timeout_s or 30.0)
        for i in range(attempts):
            t0 = time.monotonic()
            status: int | None = None
            raw = b""
            try:
                status, raw, resp_headers = self._request(
                    method, url, headers, json_body, body, timeout
                )
            except _ResponseTooLarge as exc:
                self.record_external_call("http", method, url, None, request_sha256=request_bytes,
                                          duration_ms=(time.monotonic() - t0) * 1000.0,
                                          connection_id=conn_id, error="response_too_large")
                raise RuntimeError(str(exc)) from exc
            except Exception as exc:
                self.record_external_call("http", method, url, None, request_sha256=request_bytes,
                                          duration_ms=(time.monotonic() - t0) * 1000.0,
                                          connection_id=conn_id, error=type(exc).__name__)
                if _is_connection_error(exc) and i + 1 < attempts:
                    time.sleep(self._backoff(i, None))
                    continue
                raise
            self.record_external_call("http", method, url, status, request_sha256=request_bytes,
                                      response_sha256=raw, duration_ms=(time.monotonic() - t0) * 1000.0,
                                      connection_id=conn_id)
            text = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
            ok = 200 <= int(status) < 300
            if not ok:
                if int(status) in retry_statuses and i + 1 < attempts:
                    time.sleep(self._backoff(i, _retry_after_s(resp_headers)))
                    continue
                raise RuntimeError(
                    f"HttpRequestNode: {method} {self.redact_url(url)} failed with HTTP {status}: {text[:200]}"
                )
            parsed: Any = text
            try:
                parsed = json.loads(text) if text else None
            except Exception:
                parsed = text
            return {"output": HttpResponse(
                url=url,
                method=method,
                status_code=int(status),
                ok=ok,
                headers=resp_headers,
                body=parsed,
                text=text[:65536],
                metadata={"attempts": i + 1, "bytes": len(raw)},
            )}
        raise RuntimeError("HttpRequestNode: retries exhausted")  # pragma: no cover

    def _request(self, method, url, headers, json_body, body, timeout):
        """Stream the response; abort past ``max_response_bytes``. Never follows redirects."""
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "HttpRequestNode: httpx is required for provider='http'. "
                "Install httpx (e.g. pip install httpx)."
            ) from exc
        kwargs: dict[str, Any] = {"headers": headers or None, "timeout": timeout, "follow_redirects": False}
        if json_body is not None:
            kwargs["json"] = _jsonable(json_body)
        elif body:
            kwargs["content"] = body.encode("utf-8") if isinstance(body, str) else body
        limit = int(self.config.max_response_bytes or DEFAULT_MAX_RESPONSE_BYTES)
        with httpx.stream(method, url, **kwargs) as resp:
            declared = resp.headers.get("content-length") if hasattr(resp.headers, "get") else None
            if declared and str(declared).isdigit() and int(declared) > limit:
                raise _ResponseTooLarge(
                    f"HttpRequestNode: response Content-Length {declared} exceeds max_response_bytes={limit}"
                )
            buf = bytearray()
            for chunk in resp.iter_bytes():
                buf.extend(chunk)
                if len(buf) > limit:
                    raise _ResponseTooLarge(
                        f"HttpRequestNode: response body exceeds max_response_bytes={limit}"
                    )
            return int(resp.status_code), bytes(buf), dict(resp.headers)
