"""ASR / structured_llm nodes call shared HTTP egress validation."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from app.core.egress import HttpEgressError
from app.core.plugins.manager import PluginManager

ASR_SOURCE = "PluginPackage/Common/asr_transcribe/"
LLM_SOURCE = "PluginPackage/Common/structured_llm/"


@pytest.fixture
def restricted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_MODE", "restricted")
    monkeypatch.delenv("GRAPHYN_HTTP_EGRESS_ALLOWLIST", raising=False)


@pytest.fixture
def asr_cls(tmp_path, fresh_registry):
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_path))
    mgr._plugins_dir = str(tmp_path)
    mgr.install(ASR_SOURCE)
    return fresh_registry.get_class("asr_transcribe")


@pytest.fixture
def llm_cls(tmp_path, fresh_registry):
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_path))
    mgr._plugins_dir = str(tmp_path)
    mgr.install(LLM_SOURCE)
    return fresh_registry.get_class("structured_llm")


def test_asr_http_post_validates_egress_restricted(asr_cls, restricted):
    node = asr_cls(config={"provider": "openai_compat"}, seed=0)
    with pytest.raises(HttpEgressError, match="blocked"):
        node._http_post("http://127.0.0.1/x", headers={})


def test_structured_llm_openai_compat_validates_egress_before_httpx(
    llm_cls, monkeypatch, restricted
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    node = llm_cls(
        config={"provider": "openai_compat", "base_url": "http://127.0.0.1/v1"},
        seed=0,
    )
    with pytest.raises(HttpEgressError, match="blocked"):
        node.process({"input": "hello"})


def test_asr_http_post_calls_validate(asr_cls):
    node = asr_cls(config={"provider": "openai_compat"}, seed=0)
    mod = sys.modules[asr_cls.__module__]
    with patch.object(mod, "validate_http_egress_url") as validate:
        with patch(
            "httpx.post",
            return_value=MagicMock(
                status_code=200,
                json=lambda: {},
                raise_for_status=lambda: None,
            ),
        ):
            node._http_post("https://api.example.com/x", headers={})
    validate.assert_called_once_with("https://api.example.com/x")
