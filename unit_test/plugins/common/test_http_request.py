
"""Tests for the http_request plugin."""
from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/http_request/"
NODE_TYPE = "http_request"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("http_request_plugins")
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
    from unittest.mock import MagicMock, patch
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.text = '{"ok":true}'
    mock_resp.headers = {}
    with patch("httpx.request", return_value=mock_resp) as mocked:
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
    from unittest.mock import MagicMock, patch
    node = installed_cls(config={
        "provider": "http",
        "method": "POST",
        "url": "https://example.com/api",
        "json_body": {"a": 1},
        "timeout_s": 1.0,
        "retry": 0,
    }, seed=0)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '{"ok":true}'
    mock_resp.headers = {"content-type": "application/json"}
    with patch("httpx.request", return_value=mock_resp) as mocked:
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
    with patch("httpx.request") as mocked:
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
    from unittest.mock import MagicMock, patch
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"
    mock_resp.headers = {}
    with patch("httpx.request", return_value=mock_resp) as mocked:
        out = node.process({"input": None})["output"]
    assert out.ok is True
    mocked.assert_called_once()
