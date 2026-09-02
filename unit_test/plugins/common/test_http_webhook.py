
"""Tests for the http_webhook plugin (httpx mocked, no network)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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
    return reg.get_class(NODE_TYPE)


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


def test_hmac_header(installed_cls):
    node = installed_cls(
        config={"url": "https://example.com/hook", "hmac_secret": "s3cret"},
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


def test_mock_provider_no_network(installed_cls):
    node = installed_cls(config={"url": "https://example.com/hook", "provider": "mock", "mock_response": {"status_code": 200, "body": {"ok": True}}}, seed=0)
    out = node.process({"input": {"hello": "world"}})["output"]
    assert out.ok is True
    assert out.status_code == 200
