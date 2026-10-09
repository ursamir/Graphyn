
"""Tests for the structured_llm plugin (real openai_compat only)."""
from __future__ import annotations
from unit_test.plugins._helpers import materialize_isolated_class

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
        installed_cls(config={"provider": "mock", "json_schema": SCHEMA}, seed=0)


def test_http_missing_key(installed_cls):
    os.environ.pop("OPENAI_API_KEY", None)
    node = installed_cls(config={"provider": "openai_compat", "json_schema": SCHEMA}, seed=0)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        node.process({"input": "hello"})


def test_default_provider_is_not_mock(installed_cls, monkeypatch):
    from app.core.credentials.errors import NeedsCredentialsError

    for k in ("OLLAMA_BASE_URL", "OPENAI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY",
              "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    node = installed_cls(config={"json_schema": SCHEMA}, seed=0)
    assert node.config.provider == "auto"
    with pytest.raises(NeedsCredentialsError, match="OPENAI_API_KEY"):
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
    with patch("app.core.trust.egress.egress_post", return_value=mock_resp) as mocked:
        out = node.process({"input": "the customer is unhappy"})["output"]
    assert out.data["pain"] == "latency"
    assert out.provider == "openai_compat"
    mocked.assert_called_once()


def test_rule_based_is_honest_not_filler(installed_cls):
    """F19 (F-23): legacy local_heuristic → rule_based; no first-sentence filler."""
    node = installed_cls(
        config={"provider": "local_heuristic", "json_schema": SCHEMA, "schema_name": "crm"},
        seed=0,
    )
    text = "Alex is blocked by a pricing problem. Next we will schedule a demo."
    out = node.process({"input": text})["output"]
    assert out.provider == "rule_based"
    assert out.metadata["is_llm"] is False
    assert out.data["pain"] == "Alex is blocked by a pricing problem."
    assert out.data["next_step"] == "Next we will schedule a demo."
    # No rule matches "owner"/"score": they stay null and are reported.
    assert out.data["owner"] is None and out.data["score"] is None
    assert set(out.metadata["unfilled"]) >= {"owner", "score"}
    assert out.data["pain"] != out.data["next_step"]


def test_rule_based_unwraps_code_result(installed_cls):
    class CodeResult:
        def __init__(self, data):
            self.data = data
            self.metadata = {}

    node = installed_cls(config={"provider": "rule_based", "json_schema": SCHEMA}, seed=0)
    out = node.process({"input": CodeResult("We have an issue with latency.")})
    out = out["output"] if isinstance(out, dict) else out
    assert out.raw_text == "We have an issue with latency."
    assert out.data["pain"] == "We have an issue with latency."


def test_auto_routes_to_ollama_when_configured(installed_cls, monkeypatch):
    from unittest.mock import MagicMock, patch

    for k in ("OPENAI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://172.17.0.1:11434/v1")
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_INTERNAL_ALLOW", "172.17.0.1:11434")
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": "```json\n{\"pain\": \"latency\"}\n```"}}]}
    with patch("app.core.trust.egress.egress_post", return_value=resp):
        out = installed_cls(config={"json_schema": SCHEMA}, seed=0).process({"input": "x"})
    out = out["output"] if isinstance(out, dict) else out
    assert out.provider == "ollama" and out.data == {"pain": "latency"}
    assert out.metadata["is_llm"] is True


def test_openai_compat_groq_key_fallback(installed_cls, monkeypatch):
    from unittest.mock import MagicMock, patch
    import json as _json

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    # Env-sourced keys are bound to their default endpoint; a node base_url on a
    # different host must be explicitly allowlisted (LLM base_url binding).
    monkeypatch.setenv("GRAPHYN_LLM_BASE_URL_ALLOWLIST", "api.groq.com")
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
    with patch("app.core.trust.egress.egress_post", return_value=mock_resp) as post:
        out = node.process({"input": "hello"})["output"]
    assert out.data["pain"] == "price"
    headers = post.call_args.kwargs.get("headers") or {}
    assert headers.get("Authorization") == "Bearer gsk-test"
