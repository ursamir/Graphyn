
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


def test_local_heuristic_provider(installed_cls):
    node = installed_cls(
        config={"provider": "local_heuristic", "json_schema": SCHEMA, "schema_name": "crm"},
        seed=0,
    )
    out = node.process({"input": "Alex is blocked by pricing. Next we will schedule a demo."})["output"]
    assert out.provider == "local_heuristic"
    assert isinstance(out.data, dict)
    assert out.data.get("pain")
    assert out.data.get("next_step")
    assert out.data.get("owner")


def test_openai_compat_groq_key_fallback(installed_cls, monkeypatch):
    from unittest.mock import MagicMock, patch
    import json as _json

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    node = installed_cls(
        config={
            "provider": "openai_compat",
            "json_schema": SCHEMA,
            "base_url": "https://api.groq.com/openai/v1",
            "model": "llama-3.1-8b-instant",
        },
        seed=0,
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": _json.dumps({
            "pain": "price", "objections": [], "next_step": "call", "owner": "Sam", "score": 1
        })}}]
    }
    with patch("httpx.post", return_value=mock_resp) as post:
        out = node.process({"input": "hello"})["output"]
    assert out.data["pain"] == "price"
    headers = post.call_args.kwargs.get("headers") or {}
    assert headers.get("Authorization") == "Bearer gsk-test"
