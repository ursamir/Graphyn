"""Leftover fixes: structured_llm uses llm_client endpoint binding.

A resolved API key (connection / env / secret) must never be sent to a node
``base_url`` it is not bound to (same rule as llm_client.chat_completion).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.ml.llm_client import NeedsCredentialsError, resolve_llm_endpoint

REPO = Path(__file__).resolve().parents[2]
SCHEMA = {"type": "object", "properties": {"pain": {"type": "string"}}}


@pytest.fixture
def cred_home(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "ghome"))
    for name in (
        "GRAPHYN_CREDENTIALS_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "GROQ_API_KEY",
        "GRAPHYN_SECRET_ENV_ALLOWLIST", "GRAPHYN_LLM_BASE_URL_ALLOWLIST",
    ):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


@pytest.fixture
def llm_cls():
    from app.core.nodes.discovery import AutoDiscovery
    from app.core.nodes.registry import NodeRegistry

    reg = NodeRegistry()
    disc = AutoDiscovery(reg)
    root = REPO / "PluginPackage" / "Common" / "structured_llm"
    for entry in ("types.py", "nodes.py"):
        path = root / entry
        if path.is_file():
            disc._process_module(disc._import_file(path, package_prefix=None))
    return reg.get_class("structured_llm")


def _ok():
    r = MagicMock()
    r.status_code = 200
    r.raise_for_status = MagicMock()
    r.json.return_value = {"choices": [{"message": {"content": json.dumps({"pain": "x"})}}]}
    return r


def _nodes_mod(cls):
    import sys

    return sys.modules[cls.__module__]


# ── resolve_llm_endpoint ─────────────────────────────────────────────────────


def test_endpoint_env_key_default_base(cred_home, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    ep = resolve_llm_endpoint(provider="openai_compat")
    assert ep["api_key"] == "sk-env"
    assert ep["base_url"] == "https://api.openai.com/v1"


def test_endpoint_env_key_refused_for_foreign_base(cred_home, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    with pytest.raises(NeedsCredentialsError, match="base_url"):
        resolve_llm_endpoint(provider="openai_compat", base_url="https://evil.example/v1")


def test_endpoint_allowlisted_override(cred_home, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("GRAPHYN_LLM_BASE_URL_ALLOWLIST", "llm.internal.example")
    ep = resolve_llm_endpoint(provider="openai_compat", base_url="https://llm.internal.example/v1/")
    assert ep["base_url"] == "https://llm.internal.example/v1"


def test_endpoint_connection_bound_base(cred_home):
    from app.core.credentials import create_connection

    meta = create_connection(
        name="c", kind="openai_compat",
        payload={"api_key": "sk-conn", "base_url": "https://api.groq.com/openai/v1"},
    )
    ep = resolve_llm_endpoint(provider="openai_compat", connection_id=meta["id"])
    assert ep["api_key"] == "sk-conn"
    assert ep["base_url"] == "https://api.groq.com/openai/v1"
    # Connection keys are never re-bound by the allowlist.
    with pytest.raises(NeedsCredentialsError):
        resolve_llm_endpoint(
            provider="openai_compat", connection_id=meta["id"], base_url="https://evil.example/v1",
        )


def test_endpoint_missing_key_names_secret(cred_home):
    with pytest.raises(NeedsCredentialsError, match="OPENAI_API_KEY"):
        resolve_llm_endpoint(provider="openai_compat")


def test_endpoint_internal_secret_name_refused(cred_home, monkeypatch):
    monkeypatch.setenv("GRAPHYN_API_TOKEN", "internal")
    with pytest.raises(NeedsCredentialsError):
        resolve_llm_endpoint(provider="openai_compat", api_secret_name="GRAPHYN_API_TOKEN")


# ── structured_llm node ──────────────────────────────────────────────────────


def test_structured_llm_env_key_not_sent_to_node_base_url(cred_home, monkeypatch, llm_cls):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    node = llm_cls(
        config={"provider": "openai_compat", "json_schema": SCHEMA,
                "base_url": "https://evil.example/v1"},
        seed=0,
    )
    with patch.object(_nodes_mod(llm_cls), "validate_http_egress_url"), \
            patch("httpx.post", return_value=_ok()) as post:
        with pytest.raises(RuntimeError, match="base_url"):
            node.process({"input": "hello"})
    post.assert_not_called()


def test_structured_llm_default_base_uses_env_key(cred_home, monkeypatch, llm_cls):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    node = llm_cls(config={"provider": "openai_compat", "json_schema": SCHEMA}, seed=0)
    with patch.object(_nodes_mod(llm_cls), "validate_http_egress_url"), \
            patch("httpx.post", return_value=_ok()) as post:
        out = node.process({"input": "hello"})["output"]
    assert out.data == {"pain": "x"}
    assert post.call_args.args[0] == "https://api.openai.com/v1/chat/completions"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-env"


def test_structured_llm_allowlisted_base(cred_home, monkeypatch, llm_cls):
    monkeypatch.setenv("GROQ_API_KEY", "gsk")
    monkeypatch.setenv("GRAPHYN_LLM_BASE_URL_ALLOWLIST", "api.groq.com")
    node = llm_cls(
        config={"provider": "openai_compat", "json_schema": SCHEMA,
                "base_url": "https://api.groq.com/openai/v1"},
        seed=0,
    )
    with patch.object(_nodes_mod(llm_cls), "validate_http_egress_url"), \
            patch("httpx.post", return_value=_ok()) as post:
        node.process({"input": "hello"})
    assert post.call_args.args[0] == "https://api.groq.com/openai/v1/chat/completions"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer gsk"


def test_structured_llm_connection_base_used(cred_home, llm_cls):
    from app.core.credentials import create_connection

    meta = create_connection(
        name="c", kind="openai_compat",
        payload={"api_key": "sk-conn", "base_url": "https://llm.example/v1"},
    )
    node = llm_cls(
        config={"provider": "openai_compat", "json_schema": SCHEMA, "connection_id": meta["id"]},
        seed=0,
    )
    with patch.object(_nodes_mod(llm_cls), "validate_http_egress_url"), \
            patch("httpx.post", return_value=_ok()) as post:
        node.process({"input": "hello"})
    assert post.call_args.args[0] == "https://llm.example/v1/chat/completions"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-conn"
    # Node config is not mutated with the connection's base_url.
    assert node.config.base_url == ""
