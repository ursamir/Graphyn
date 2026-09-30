"""Security regressions: LLM key/endpoint binding, secret env fallback, PATCH merge."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.credentials import create_connection
from app.core.credentials.errors import CredentialError
from app.core.credentials.store import get_payload, update_connection
from app.core.ml.llm_client import NeedsCredentialsError, chat_completion, resolve_api_key
from app.core.trust.secrets import env_secret_name_allowed, resolve_secret


@pytest.fixture
def cred_home(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "ghome"))
    monkeypatch.delenv("GRAPHYN_CREDENTIALS_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("GRAPHYN_SECRET_ENV_ALLOWLIST", raising=False)
    monkeypatch.delenv("GRAPHYN_LLM_BASE_URL_ALLOWLIST", raising=False)
    return tmp_path


def _ok_resp():
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    return r


MSG = [{"role": "user", "content": "hi"}]


def test_connection_key_not_sent_to_node_base_url(cred_home):
    meta = create_connection(
        name="c", kind="openai_compat",
        payload={"api_key": "sk-conn", "base_url": "https://api.openai.com/v1"},
    )
    with patch("httpx.post", return_value=_ok_resp()) as mocked:
        with pytest.raises(NeedsCredentialsError, match="base_url"):
            chat_completion(
                messages=MSG, provider="openai_compat",
                connection_id=meta["id"], base_url="https://evil.example/v1",
            )
    mocked.assert_not_called()


def test_connection_matching_base_url_ok(cred_home):
    meta = create_connection(
        name="c", kind="openai_compat",
        payload={"api_key": "sk-conn", "base_url": "https://api.openai.com/v1"},
    )
    with patch("app.core.ml.llm_client.validate_http_egress_url"), \
            patch("httpx.post", return_value=_ok_resp()) as mocked:
        out = chat_completion(
            messages=MSG, provider="openai_compat",
            connection_id=meta["id"], base_url="https://api.openai.com/v1/",
        )
    assert out["content"] == "ok"
    assert mocked.called


def test_env_key_not_sent_to_node_base_url(cred_home, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    with patch("httpx.post", return_value=_ok_resp()) as mocked:
        with pytest.raises(NeedsCredentialsError):
            chat_completion(messages=MSG, provider="openai_compat", base_url="https://evil.example/v1")
    mocked.assert_not_called()


def test_env_key_base_url_allowlist(cred_home, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk")
    monkeypatch.setenv("GRAPHYN_LLM_BASE_URL_ALLOWLIST", "api.groq.com")
    with patch("app.core.ml.llm_client.validate_http_egress_url"), \
            patch("httpx.post", return_value=_ok_resp()):
        out = chat_completion(
            messages=MSG, provider="openai_compat",
            base_url="https://api.groq.com/openai/v1", api_secret_name="GROQ_API_KEY",
        )
    assert out["content"] == "ok"


@pytest.mark.parametrize("name", ["GRAPHYN_CREDENTIALS_KEY", "GRAPHYN_API_TOKEN", "HOME", "PATH"])
def test_internal_env_never_resolved(cred_home, monkeypatch, name):
    monkeypatch.setenv(name, "internal-value")
    assert not env_secret_name_allowed(name)
    assert resolve_secret(name) == ""
    assert resolve_api_key(name) == ""
    with patch("httpx.post", return_value=_ok_resp()) as mocked:
        with pytest.raises(NeedsCredentialsError):
            chat_completion(messages=MSG, provider="openai_compat", api_secret_name=name)
    mocked.assert_not_called()


def test_env_allowlist_and_conventional_names(cred_home, monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "v1")
    assert resolve_secret("MY_API_KEY") == "v1"
    monkeypatch.setenv("GRAPHYN_CUSTOM_THING", "v2")
    assert resolve_secret("GRAPHYN_CUSTOM_THING") == ""
    monkeypatch.setenv("GRAPHYN_SECRET_ENV_ALLOWLIST", "GRAPHYN_CUSTOM_THING")
    assert resolve_secret("GRAPHYN_CUSTOM_THING") == "v2"


def test_patch_base_url_requires_secret(cred_home):
    meta = create_connection(
        name="c", kind="openai_compat",
        payload={"api_key": "sk-conn", "base_url": "https://api.openai.com/v1"},
    )
    with pytest.raises(CredentialError, match="re-supplying"):
        update_connection(meta["id"], payload={"base_url": "https://evil.example/v1"})
    _, payload = get_payload(meta["id"])
    assert payload["base_url"] == "https://api.openai.com/v1"
    # Re-supplying the secret is allowed
    update_connection(meta["id"], payload={"base_url": "https://api.groq.com/openai/v1", "api_key": "gsk"})
    _, payload = get_payload(meta["id"])
    assert payload == {**payload, "api_key": "gsk", "base_url": "https://api.groq.com/openai/v1"}
    # Non-endpoint merges keep working without the secret
    update_connection(meta["id"], payload={"default_model": "llama3"})
