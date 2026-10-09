
"""Tests for the http_request plugin."""
from __future__ import annotations
from unit_test.plugins._helpers import materialize_isolated_class

import os

import pytest
from pydantic import ValidationError

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/http_request/"
NODE_TYPE = "http_request"


class _FakeResp:
    def __init__(self, status=200, text="", headers=None, chunk=None):
        self.status_code = status
        self._raw = text.encode("utf-8") if isinstance(text, str) else text
        self.headers = dict(headers or {})
        self._chunk = chunk

    def iter_bytes(self):
        if self._chunk:
            for i in range(0, len(self._raw), self._chunk):
                yield self._raw[i:i + self._chunk]
        else:
            yield self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _stream(*responses):
    """patch target for httpx.stream: returns each response (or raises) in order."""
    from unittest.mock import MagicMock

    seq = list(responses)

    def _side(*_a, **_k):
        item = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(item, BaseException):
            raise item
        return item

    return MagicMock(side_effect=_side)


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("http_request_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return materialize_isolated_class(reg.get_class(NODE_TYPE))


def test_registers(tmp_plugin_dir, fresh_registry):
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_plugin_dir))
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(PLUGIN_SOURCE)
    assert NODE_TYPE in fresh_registry


def test_metadata(installed_cls):
    meta = installed_cls.metadata
    assert meta.label and meta.category and meta.version


def test_mock_provider_rejected(installed_cls):
    with pytest.raises((ValidationError, ValueError, RuntimeError)):
        installed_cls(config={
            "provider": "mock",
            "url": "https://example.invalid/x",
            "method": "GET",
        }, seed=0)


def test_missing_url(installed_cls):
    node = installed_cls(config={"provider": "http", "url": ""}, seed=0)
    with pytest.raises(RuntimeError, match="url"):
        node.process({"input": None})


def test_auth_env_not_secret_in_config(installed_cls, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "s3cret-token")
    node = installed_cls(config={
        "provider": "http",
        "url": "https://example.com/api",
        "method": "GET",
        "auth_env": "GITHUB_TOKEN",
    }, seed=0)
    dumped = node.config.model_dump()
    assert "s3cret-token" not in str(dumped)
    assert dumped["auth_env"] == "GITHUB_TOKEN"
    from unittest.mock import patch
    with patch("app.core.trust.egress.egress_stream", _stream(_FakeResp(201, '{"ok":true}'))) as mocked:
        out = node.process({"input": {}})["output"]
    assert out.status_code == 201
    headers = mocked.call_args.kwargs.get("headers") or {}
    assert "s3cret-token" in headers.get("Authorization", "")


def test_auth_env_missing_raises(installed_cls, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    node = installed_cls(config={
        "provider": "http",
        "url": "https://example.com/api",
        "auth_env": "GITHUB_TOKEN",
    }, seed=0)
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        node.process({"input": {}})


def test_http_mocked(installed_cls):
    from unittest.mock import patch
    node = installed_cls(config={
        "provider": "http",
        "method": "POST",
        "url": "https://example.com/api",
        "json_body": {"a": 1},
        "timeout_s": 1.0,
        "retry": 0,
    }, seed=0)
    with patch("app.core.trust.egress.egress_stream", _stream(_FakeResp(200, '{"ok":true}', {"content-type": "application/json"}))) as mocked:
        out = node.process({"input": {"ignored": True}})["output"]
    assert out.ok is True
    mocked.assert_called_once()


def test_default_provider_is_http(installed_cls):
    node = installed_cls(config={"url": "https://example.com"}, seed=0)
    assert node.config.provider == "http"
    assert node.config.provider != "mock"


def test_restricted_egress_blocks_private_before_httpx(installed_cls, monkeypatch):
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_MODE", "restricted")
    node = installed_cls(config={
        "provider": "http",
        "url": "http://127.0.0.1:9/secret",
        "method": "GET",
    }, seed=0)
    from unittest.mock import patch
    with patch("app.core.trust.egress.egress_stream") as mocked:
        with pytest.raises(RuntimeError, match="egress|blocked|private|loopback"):
            node.process({"input": None})
    mocked.assert_not_called()


def test_trusted_egress_allows_private_literal(installed_cls, monkeypatch):
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_MODE", "trusted")
    node = installed_cls(config={
        "provider": "http",
        "url": "http://127.0.0.1:9/x",
        "method": "GET",
    }, seed=0)
    from unittest.mock import patch
    with patch("app.core.trust.egress.egress_stream", _stream(_FakeResp(200, "ok"))) as mocked:
        out = node.process({"input": None})["output"]
    assert out.ok is True
    mocked.assert_called_once()


# ── retry / size cap / credential connection / audit (review fixes) ──────────

def _node(installed_cls, **cfg):
    base = {"provider": "http", "url": "https://example.com/api", "retry_backoff_s": 0.0}
    base.update(cfg)
    return installed_cls(config=base, seed=0)


def test_metadata_not_deterministic_or_cacheable(installed_cls):
    assert installed_cls.metadata.deterministic is False
    assert installed_cls.metadata.cacheable is False


def test_retries_only_retryable_status_for_get(installed_cls):
    from unittest.mock import patch
    node = _node(installed_cls, retry=2)
    with patch("app.core.trust.egress.egress_stream", _stream(_FakeResp(503, "busy"), _FakeResp(200, '{"ok":1}'))) as m:
        out = node.process({"input": None})["output"]
    assert out.ok and out.metadata["attempts"] == 2 and m.call_count == 2


def test_non_retryable_4xx_fails_immediately(installed_cls):
    from unittest.mock import patch
    node = _node(installed_cls, retry=3)
    with patch("app.core.trust.egress.egress_stream", _stream(_FakeResp(404, "nope"))) as m:
        with pytest.raises(RuntimeError, match="404"):
            node.process({"input": None})
    assert m.call_count == 1


def test_post_not_retried_without_idempotency_key(installed_cls):
    from unittest.mock import patch
    node = _node(installed_cls, method="POST", retry=3, json_body={"a": 1})
    with patch("app.core.trust.egress.egress_stream", _stream(_FakeResp(503, "busy"))) as m:
        with pytest.raises(RuntimeError, match="503"):
            node.process({"input": None})
    assert m.call_count == 1


def test_post_retried_with_idempotency_key_header(installed_cls):
    from unittest.mock import patch
    node = _node(installed_cls, method="POST", retry=2, json_body={"a": 1}, idempotency_key="k-1")
    with patch("app.core.trust.egress.egress_stream", _stream(_FakeResp(429, "slow"), _FakeResp(200, "{}"))) as m:
        node.process({"input": None})
    assert m.call_count == 2
    assert m.call_args.kwargs["headers"]["Idempotency-Key"] == "k-1"
    assert m.call_args.kwargs["follow_redirects"] is False


def test_connection_error_retried_for_get(installed_cls):
    import httpx
    from unittest.mock import patch
    node = _node(installed_cls, retry=1)
    with patch("app.core.trust.egress.egress_stream", _stream(httpx.ConnectError("down"), _FakeResp(200, "{}"))) as m:
        node.process({"input": None})
    assert m.call_count == 2


def test_backoff_capped_with_jitter(installed_cls):
    node = _node(installed_cls, retry_backoff_s=1.0, retry_backoff_max_s=3.0)
    for attempt in range(6):
        assert 0.0 <= node._backoff(attempt, None) <= 3.0
    assert node._backoff(0, 100.0) == 3.0  # Retry-After is capped too


def test_response_size_cap_streams_and_stops(installed_cls):
    from unittest.mock import patch
    node = _node(installed_cls, max_response_bytes=10)
    with patch("app.core.trust.egress.egress_stream", _stream(_FakeResp(200, "x" * 100, chunk=4))):
        with pytest.raises(RuntimeError, match="max_response_bytes"):
            node.process({"input": None})
    with patch("app.core.trust.egress.egress_stream", _stream(_FakeResp(200, "ok", {"content-length": "999"}))):
        with pytest.raises(RuntimeError, match="Content-Length"):
            node.process({"input": None})


def test_external_calls_recorded_redacted(installed_cls):
    from unittest.mock import patch
    node = _node(installed_cls, url="https://example.com/api?token=SECRET", retry=1)
    with patch("app.core.trust.egress.egress_stream", _stream(_FakeResp(500, "x"), _FakeResp(200, "{}"))):
        node.process({"input": None})
    calls = node.take_external_calls()
    assert [c["status"] for c in calls] == [500, 200]
    assert all(c["url"] == "https://example.com/api" for c in calls)
    assert calls[1]["response_sha256"].startswith("sha256:")


@pytest.mark.parametrize(
    "payload,header,expected",
    [
        ({"scheme": "bearer", "token": "tok", "allowed_hosts": "example.com"}, "Authorization", "Bearer tok"),
        ({"scheme": "basic", "username": "u", "password": "p", "allowed_hosts": "example.com"}, "Authorization", "Basic dTpw"),
        ({"scheme": "header", "header_name": "X-API-Key", "header_value": "v", "allowed_hosts": "example.com"}, "X-API-Key", "v"),
    ],
)
def test_connection_id_http_auth(installed_cls, monkeypatch, payload, header, expected):
    from unittest.mock import patch
    import app.core.credentials.resolve as res
    monkeypatch.setattr(res, "get_payload", lambda cid: ("http_auth", payload))
    node = _node(installed_cls, connection_id="c1", auth_env="IGNORED_WHEN_CONNECTION")
    with patch("app.core.trust.egress.egress_stream", _stream(_FakeResp(200, "{}"))) as m:
        node.process({"input": None})
    assert m.call_args.kwargs["headers"][header] == expected
    assert node.take_external_calls()[0]["connection_id"] == "c1"


def test_connection_allowed_hosts_binding(installed_cls, monkeypatch):
    from unittest.mock import patch
    import app.core.credentials.resolve as res
    monkeypatch.setattr(res, "get_payload", lambda cid: (
        "http_auth", {"scheme": "bearer", "token": "t", "allowed_hosts": "api.github.com"}))
    node = _node(installed_cls, connection_id="c1")
    with patch("app.core.trust.egress.egress_stream") as m:
        with pytest.raises(RuntimeError, match="allowed_hosts"):
            node.process({"input": None})
    m.assert_not_called()


def test_connection_empty_allowed_hosts_fails_closed(installed_cls, monkeypatch):
    from unittest.mock import patch
    import app.core.credentials.resolve as res
    monkeypatch.setattr(res, "get_payload", lambda cid: (
        "http_auth", {"scheme": "bearer", "token": "t", "allowed_hosts": ""}))
    node = _node(installed_cls, connection_id="c1")
    with patch("app.core.trust.egress.egress_stream") as m:
        with pytest.raises(RuntimeError, match="empty allowed_hosts"):
            node.process({"input": None})
    m.assert_not_called()


def test_connection_wrong_kind_needs_credentials(installed_cls, monkeypatch):
    import app.core.credentials.resolve as res
    from app.core.credentials.errors import NeedsCredentialsError
    monkeypatch.setattr(res, "get_payload", lambda cid: ("webhook", {"url": "https://x"}))
    with pytest.raises(NeedsCredentialsError):
        _node(installed_cls, connection_id="c1").process({"input": None})
