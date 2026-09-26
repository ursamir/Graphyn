"""Tests for rag_generate LLM providers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from unit_test.plugins._helpers import materialize_isolated_class
from app.core.plugins.manager import PluginManager
from app.core.llm_client import NeedsCredentialsError

PLUGIN_SOURCE = "PluginPackage/RAG/rag_generate/"
NODE_TYPE = "rag_generate"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("rag_generate_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return materialize_isolated_class(reg.get_class(NODE_TYPE))


def test_stub(installed_cls):
    out = installed_cls(config={"stub": True}, seed=0).process({"prompt": "q"})["output"]
    assert "stub" in out.answer.lower()


def test_needs_credentials(installed_cls, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    node = installed_cls(config={"stub": False, "provider": "openai_compat"}, seed=0)
    with pytest.raises(NeedsCredentialsError, match="needs-credentials"):
        node.process({"prompt": {"system": "s", "user": "u"}})


def test_mocked_completion(installed_cls, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    node = installed_cls(config={"stub": False, "provider": "openai_compat"}, seed=0)
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": "rag answer"}}]}
    with patch("httpx.post", return_value=mock_resp):
        out = node.process({"prompt": "What is Graphyn?"})["output"]
    assert out.answer == "rag answer"
    assert out.metadata.get("stub") is False
