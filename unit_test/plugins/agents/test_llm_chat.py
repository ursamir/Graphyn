"""Tests for llm_chat multi-provider node."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from unit_test.plugins._helpers import materialize_isolated_class
from app.core.plugins.manager import PluginManager
from app.core.ml.llm_client import NeedsCredentialsError

PLUGIN_SOURCE = "PluginPackage/Agents/llm_chat/"
NODE_TYPE = "llm_chat"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("llm_chat_plugins")
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
    assert NODE_TYPE in {n.node_type for n in fresh_registry.list_nodes()}


def test_stub_is_labelled_echo(installed_cls):
    node = installed_cls(config={"stub": True}, seed=0)
    out = node.process({"input": "hello"})["output"]
    assert out.role == "assistant"
    assert out.content == "hello"
    assert out.metadata["provider"] == "echo" and out.metadata["is_llm"] is False


_LLM_ENVS = ("OLLAMA_BASE_URL", "OPENAI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY",
             "GEMINI_API_KEY", "GOOGLE_API_KEY")


def test_default_provider_is_auto_and_fails_clearly_without_llm(installed_cls, monkeypatch):
    """F19 (F-10): the default is a real LLM — never a silent echo."""
    from app.core.credentials.errors import NeedsCredentialsError

    for k in _LLM_ENVS:
        monkeypatch.delenv(k, raising=False)
    node = installed_cls(config={}, seed=0)
    assert node.config.provider == "auto"
    with pytest.raises(NeedsCredentialsError, match="no LLM provider is configured"):
        node.process({"input": "hello"})


def test_auto_uses_local_ollama_when_configured(installed_cls, monkeypatch):
    for k in _LLM_ENVS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://172.17.0.1:11434/v1")
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_INTERNAL_ALLOW", "172.17.0.1:11434")
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": "real answer"}}]}
    with patch("app.core.trust.egress.egress_post", return_value=mock_resp) as mocked:
        out = installed_cls(config={}, seed=0).process({"input": "ping"})["output"]
    assert out.content == "real answer"
    assert out.metadata["provider"] == "ollama" and out.metadata["is_llm"] is True
    assert mocked.call_args[0][0].startswith("http://172.17.0.1:11434/v1")


def test_legacy_local_provider_maps_to_auto_not_echo(installed_cls, monkeypatch):
    from app.core.credentials.errors import NeedsCredentialsError

    for k in _LLM_ENVS:
        monkeypatch.delenv(k, raising=False)
    node = installed_cls(config={"provider": "local"}, seed=0)
    assert node.config.provider == "auto"
    with pytest.raises(NeedsCredentialsError):
        node.process({"input": "hello"})


def test_echo_unwraps_code_result(installed_cls):
    from app.core.nodes.payload import unwrap_payload  # noqa: F401

    class CodeResult:  # same shape/name as python_code's wrapper
        def __init__(self, data):
            self.data = data
            self.metadata = {}

    node = installed_cls(config={"provider": "echo"}, seed=0)
    out = node.process({"input": CodeResult("from code")})["output"]
    assert out.content == "from code"


def test_openai_compat_needs_credentials(installed_cls, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    node = installed_cls(config={"stub": False, "provider": "openai_compat"}, seed=0)
    with pytest.raises(NeedsCredentialsError, match="needs-credentials"):
        node.process({"input": "hello"})


def test_openai_compat_httpx_mocked(installed_cls, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    node = installed_cls(
        config={"stub": False, "provider": "openai_compat", "model": "gpt-4o-mini"},
        seed=0,
    )
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "mocked reply"}}],
        "usage": {},
    }
    with patch("app.core.trust.egress.egress_post", return_value=mock_resp) as mocked:
        out = node.process({"messages": [{"role": "user", "content": "hi"}]})["output"]
    assert out.content == "mocked reply"
    mocked.assert_called_once()


def test_ollama_provider_mocked(installed_cls, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_INTERNAL_ALLOW", "127.0.0.1:11434")
    node = installed_cls(
        config={"stub": False, "provider": "ollama", "model": "llama3.2", "base_url": "http://127.0.0.1:11434/v1"},
        seed=0,
    )
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "local ollama"}}],
    }
    with patch("app.core.trust.egress.egress_post", return_value=mock_resp) as mocked:
        out = node.process({"input": "ping"})["output"]
    assert out.content == "local ollama"
    mocked.assert_called_once()
    # no Authorization required for stock ollama
    headers = mocked.call_args.kwargs.get("headers") or mocked.call_args[1].get("headers")
    assert "Authorization" not in (headers or {})
