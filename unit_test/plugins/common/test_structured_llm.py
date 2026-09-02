
"""Tests for the structured_llm plugin (mock provider, no API keys)."""
from __future__ import annotations

import os

import pytest

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


def test_mock_fills_schema(installed_cls):
    node = installed_cls(config={"provider": "mock", "json_schema": SCHEMA}, seed=0)
    out = node.process({"input": {"text": "the customer is unhappy"}})["output"]
    assert out.data["pain"] == "mock_pain"
    assert out.data["objections"] == ["mock_objections"]
    assert out.data["score"] == 0
    assert out.provider == "mock"


def test_empty_input_still_fills(installed_cls):
    node = installed_cls(config={"provider": "mock", "json_schema": SCHEMA}, seed=0)
    out = node.process({"input": None})["output"]
    assert "pain" in out.data


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
