"""Unit tests for multi-provider llm_client (mocks; no live keys)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.llm_client import NeedsCredentialsError, chat_completion


def test_stub():
    out = chat_completion(messages=[{"role": "user", "content": "hi"}], provider="stub")
    assert out["provider"] == "stub"
    assert "stub" in out["content"].lower()


def test_openai_compat_needs_credentials(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(NeedsCredentialsError, match="needs-credentials"):
        chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            provider="openai_compat",
        )


def test_anthropic_needs_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(NeedsCredentialsError, match="needs-credentials"):
        chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            provider="anthropic",
        )


def test_gemini_needs_credentials(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(NeedsCredentialsError, match="needs-credentials"):
        chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            provider="gemini",
        )


def test_anthropic_httpx_mocked(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "content": [{"type": "text", "text": "anthropic-hi"}],
        "usage": {"input_tokens": 1, "output_tokens": 2},
    }
    with patch("httpx.post", return_value=mock_resp) as mocked:
        out = chat_completion(
            messages=[
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "hi"},
            ],
            provider="anthropic",
            model="claude-3-5-haiku-latest",
        )
    assert out["content"] == "anthropic-hi"
    assert out["provider"] == "anthropic"
    kwargs = mocked.call_args.kwargs
    assert kwargs["headers"]["x-api-key"] == "sk-ant-test"
    assert "anthropic-version" in kwargs["headers"]
    assert kwargs["json"]["system"] == "be brief"
    assert kwargs["json"]["messages"][0]["role"] == "user"


def test_gemini_httpx_mocked(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-test")
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "gemini-hi"}]}}],
        "usageMetadata": {"totalTokenCount": 3},
    }
    with patch("httpx.post", return_value=mock_resp) as mocked:
        out = chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            provider="gemini",
            model="gemini-2.0-flash",
        )
    assert out["content"] == "gemini-hi"
    assert out["provider"] == "gemini"
    assert "x-goog-api-key" in mocked.call_args.kwargs["headers"]
    assert "generateContent" in mocked.call_args.args[0]


def test_ollama_no_auth_header(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "tinyllama")
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "local"}}],
    }
    with patch("httpx.post", return_value=mock_resp) as mocked:
        out = chat_completion(
            messages=[{"role": "user", "content": "ping"}],
            provider="ollama",
            model="tinyllama",
            base_url="http://127.0.0.1:11434/v1",
            api_secret_name="",
        )
    assert out["content"] == "local"
    headers = mocked.call_args.kwargs.get("headers") or {}
    assert "Authorization" not in headers
