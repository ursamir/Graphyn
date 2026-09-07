
"""Tests for the structured_llm plugin (real openai_compat only)."""
from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/structured_llm/"
NODE_TYPE = "structured_llm"

SCHEMA = {
    "type": "object",
    "properties": {
        "pain": {"type": "string"},
        "objections": {"type": "array", "items": {"type": "string"}},
        "next_step": {"type": "string"},
        "owner": {"type": "string"},
        "score": {"type": "integer"},
    },
    "required": ["pain", "next_step", "owner"],
}


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("structured_llm_plugins")
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
        installed_cls(config={"provider": "mock", "json_schema": SCHEMA}, seed=0)


def test_http_missing_key(installed_cls):
    os.environ.pop("OPENAI_API_KEY", None)
    node = installed_cls(config={"provider": "openai_compat", "json_schema": SCHEMA}, seed=0)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        node.process({"input": "hello"})


def test_default_provider_is_not_mock(installed_cls, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    node = installed_cls(config={"json_schema": SCHEMA}, seed=0)
    assert node.config.provider == "openai_compat"
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        node.process({"input": "hello"})


def test_openai_extract_httpx_mocked(installed_cls, monkeypatch):
    from unittest.mock import MagicMock, patch
    import json as _json

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    node = installed_cls(config={"provider": "openai_compat", "json_schema": SCHEMA}, seed=0)
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": _json.dumps({
            "pain": "latency",
            "objections": ["price"],
            "next_step": "demo",
            "owner": "sam",
            "score": 3,
        })}}],
    }
    with patch("httpx.post", return_value=mock_resp) as mocked:
        out = node.process({"input": "the customer is unhappy"})["output"]
    assert out.data["pain"] == "latency"
    assert out.provider == "openai_compat"
    mocked.assert_called_once()
