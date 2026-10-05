
"""Tests for the http_webhook plugin (httpx mocked, no network)."""
from __future__ import annotations
from unit_test.plugins._helpers import materialize_isolated_class

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/http_webhook/"
NODE_TYPE = "http_webhook"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("http_webhook_plugins")
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


def test_missing_url(installed_cls):
    node = installed_cls(config={"url": ""}, seed=0)
    with pytest.raises(RuntimeError, match="url"):
        node.process({"input": {"ok": True}})


def test_post_json_mocked(installed_cls):
    node = installed_cls(config={"url": "https://example.com/hook", "timeout_s": 1.0}, seed=0)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '{"ok":true}'
    with patch("httpx.post", return_value=mock_resp) as mocked:
        out = node.process({"input": {"hello": "world"}})["output"]
    assert out.ok is True
    assert out.status_code == 200
    mocked.assert_called_once()
    kwargs = mocked.call_args.kwargs
    assert kwargs["timeout"] == 1.0
    assert b"hello" in kwargs["content"]


def test_hmac_header(installed_cls, monkeypatch):
    monkeypatch.setenv("HOOK_HMAC_KEY", "s3cret")
    node = installed_cls(
        config={"url": "https://example.com/hook", "hmac_env": "HOOK_HMAC_KEY"},
        seed=0,
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 204
    mock_resp.text = ""
    with patch("httpx.post", return_value=mock_resp) as mocked:
        node.process({"input": {"a": 1}})
    headers = mocked.call_args.kwargs["headers"]
    assert "X-Graphyn-Signature" in headers
    assert headers["X-Graphyn-Signature"].startswith("sha256=")


def test_http_error(installed_cls):
    node = installed_cls(config={"url": "https://example.com/hook"}, seed=0)
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "nope"
    with patch("httpx.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            node.process({"input": {}})


def test_mock_provider_rejected(installed_cls):
    with pytest.raises((ValidationError, ValueError, RuntimeError)):
        installed_cls(config={
            "url": "https://example.com/hook",
            "provider": "mock",
        }, seed=0)


def test_restricted_egress_blocks_metadata(installed_cls, monkeypatch):
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_MODE", "restricted")
    node = installed_cls(config={"url": "http://169.254.169.254/latest/meta-data/"}, seed=0)
    with patch("httpx.post") as mocked:
        with pytest.raises(RuntimeError, match="egress|blocked|private|link-local"):
            node.process({"input": {"x": 1}})
    mocked.assert_not_called()


# ── review fixes: no inline secret, no urllib fallback, connection, audit ─────

def test_inline_hmac_secret_field_removed(installed_cls):
    with pytest.raises((ValidationError, ValueError, TypeError)):
        installed_cls(config={"url": "https://example.com/hook", "hmac_secret": "s3cret"}, seed=0)


def test_no_urllib_fallback_when_httpx_missing(installed_cls, monkeypatch):
    import builtins
    real_import = builtins.__import__

    def _imp(name, *a, **k):
        if name == "httpx":
            raise ImportError("no httpx")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _imp)
    node = installed_cls(config={"url": "https://example.com/hook"}, seed=0)
    with patch("urllib.request.urlopen") as uo:
        with pytest.raises(RuntimeError, match="httpx is required"):
            node.process({"input": {}})
    uo.assert_not_called()


def test_redirects_not_followed_and_audited(installed_cls):
    node = installed_cls(config={"url": "https://example.com/hooks/T0K3N?sig=abc"}, seed=0)
    mock_resp = MagicMock()
    mock_resp.status_code = 302
    mock_resp.text = ""
    with patch("httpx.post", return_value=mock_resp) as mocked:
        with pytest.raises(RuntimeError, match="HTTP 302") as ei:
            node.process({"input": {}})
    assert mocked.call_args.kwargs["follow_redirects"] is False
    assert "T0K3N" not in str(ei.value)
    calls = node.take_external_calls()
    assert calls[0]["url"] == "https://example.com/***" and calls[0]["status"] == 302


def test_connection_id_webhook_kind(installed_cls, monkeypatch):
    import app.core.credentials.resolve as res
    monkeypatch.setattr(res, "get_payload", lambda cid: ("webhook", {"url": "https://hooks.example.com/services/SECRET"}))
    node = installed_cls(config={"connection_id": "wh1"}, seed=0)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"
    with patch("httpx.post", return_value=mock_resp) as mocked:
        out = node.process({"input": {"a": 1}})["output"]
    assert mocked.call_args.args[0] == "https://hooks.example.com/services/SECRET"
    assert "SECRET" not in out.url
    assert node.take_external_calls()[0]["connection_id"] == "wh1"
