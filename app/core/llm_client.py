# app/core/llm_client.py
"""Shared OpenAI-compatible chat client for plugin nodes.

Providers:
  - openai_compat: OpenAI / Groq / Azure-style / any */v1 base_url (needs API key)
  - ollama: local OpenAI-compatible server (default http://127.0.0.1:11434/v1; no key)
  - stub: deterministic offline reply (tests / dry graphs)

Fail-closed: openai_compat without a resolvable key raises RuntimeError mentioning
needs-credentials. Never embed raw secrets in IR — pass secret *names*.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from app.core.egress import validate_http_egress_url

logger = logging.getLogger(__name__)

_DEFAULT_OPENAI = "https://api.openai.com/v1"
_DEFAULT_OLLAMA = "http://127.0.0.1:11434/v1"


class NeedsCredentialsError(RuntimeError):
    """Raised when a provider requires a secret/env that is not configured."""


def resolve_api_key(secret_name: str | None, *, base_url: str = "") -> str:
    """Resolve API key from Graphyn secret store, then process env."""
    name = (secret_name or "").strip() or "OPENAI_API_KEY"
    try:
        from app.core.secrets import resolve_secret
        val = resolve_secret(name)
    except Exception:
        val = ""
    if val:
        return val
    val = os.environ.get(name, "").strip()
    if val:
        return val
    # Groq convenience when base_url points at groq
    if "groq.com" in (base_url or "").lower():
        try:
            from app.core.secrets import resolve_secret
            val = resolve_secret("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY", "").strip()
        except Exception:
            val = os.environ.get("GROQ_API_KEY", "").strip()
        if val:
            return val
    return ""


def resolve_base_url(provider: str, base_url: str | None = None) -> str:
    provider = (provider or "openai_compat").strip().lower()
    explicit = (base_url or "").strip()
    if explicit:
        return explicit.rstrip("/")
    if provider == "ollama":
        return (os.environ.get("OLLAMA_BASE_URL") or _DEFAULT_OLLAMA).rstrip("/")
    return (os.environ.get("OPENAI_BASE_URL") or _DEFAULT_OPENAI).rstrip("/")


def chat_completion(
    *,
    messages: list[dict[str, str]],
    provider: str = "openai_compat",
    model: str = "gpt-4o-mini",
    temperature: float = 0.2,
    base_url: str | None = None,
    api_secret_name: str = "OPENAI_API_KEY",
    timeout_s: float = 60.0,
    stub_content: str | None = None,
) -> dict[str, Any]:
    """Return {content, provider, model, base_url, usage?, raw?}."""
    provider = (provider or "openai_compat").strip().lower()
    if provider in {"stub", "local_stub"}:
        text = stub_content if stub_content is not None else "[stub] llm_client offline reply"
        return {
            "content": text,
            "provider": "stub",
            "model": model or "stub",
            "base_url": "",
            "usage": {},
            "raw": None,
        }

    if provider not in {"openai_compat", "ollama"}:
        raise RuntimeError(
            f"llm_client: unknown provider {provider!r}. "
            "Use openai_compat, ollama, or stub."
        )

    base = resolve_base_url(provider, base_url)
    url = f"{base}/chat/completions"
    api_key = ""
    if provider == "openai_compat":
        api_key = resolve_api_key(api_secret_name, base_url=base)
        if not api_key:
            raise NeedsCredentialsError(
                f"llm_client: provider='openai_compat' needs-credentials — set secret/env "
                f"{(api_secret_name or 'OPENAI_API_KEY')!r} (or GROQ_API_KEY for Groq base_url). "
                "For local/no-key use provider='ollama' or provider='stub'."
            )
    elif provider == "ollama":
        # Optional key (some proxies); empty is fine for stock Ollama
        api_key = resolve_api_key(api_secret_name, base_url=base) if api_secret_name else ""
        if not model or model.startswith("gpt-"):
            model = os.environ.get("OLLAMA_MODEL", "llama3.2").strip() or "llama3.2"

    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError(
            "llm_client: requires the 'httpx' package. Install httpx or use provider='stub'."
        ) from exc

    validate_http_egress_url(url)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
    }
    timeout = min(max(float(timeout_s or 60.0), 0.5), 300.0)
    resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    content = (((body.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    return {
        "content": content if isinstance(content, str) else str(content),
        "provider": provider,
        "model": model,
        "base_url": base,
        "usage": body.get("usage") or {},
        "raw": body,
    }
