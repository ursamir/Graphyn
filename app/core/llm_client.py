# app/core/llm_client.py
"""Shared multi-provider chat client for plugin nodes.

Providers:
  - openai_compat: OpenAI / Groq / Azure-style / any */v1 base_url (needs API key)
  - ollama: local OpenAI-compatible server (default http://127.0.0.1:11434/v1; no key)
  - anthropic: native Anthropic Messages API (needs ANTHROPIC_API_KEY)
  - gemini: native Google Generative Language API (needs GEMINI_API_KEY / GOOGLE_API_KEY)
  - stub: deterministic offline reply (tests / dry graphs)

Fail-closed: cloud providers without a resolvable key raise NeedsCredentialsError.
Never embed raw secrets in IR — pass secret *names*.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from app.core.egress import validate_http_egress_url

logger = logging.getLogger(__name__)

_DEFAULT_OPENAI = "https://api.openai.com/v1"
_DEFAULT_OLLAMA = "http://127.0.0.1:11434/v1"
_DEFAULT_ANTHROPIC = "https://api.anthropic.com"
_DEFAULT_GEMINI = "https://generativelanguage.googleapis.com/v1beta"
_ANTHROPIC_VERSION = "2023-06-01"

_CLOUD_PROVIDERS = frozenset({"openai_compat", "anthropic", "gemini"})
_ALL_PROVIDERS = frozenset({"openai_compat", "ollama", "anthropic", "gemini", "stub", "local_stub"})


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
    if provider == "anthropic":
        return (os.environ.get("ANTHROPIC_BASE_URL") or _DEFAULT_ANTHROPIC).rstrip("/")
    if provider == "gemini":
        return (os.environ.get("GEMINI_BASE_URL") or _DEFAULT_GEMINI).rstrip("/")
    return (os.environ.get("OPENAI_BASE_URL") or _DEFAULT_OPENAI).rstrip("/")


def _require_httpx():
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError(
            "llm_client: requires the 'httpx' package. Install httpx or use provider='stub'."
        ) from exc
    return httpx


def _split_system(messages: list[dict[str, str]]) -> tuple[str | None, list[dict[str, str]]]:
    system_parts: list[str] = []
    rest: list[dict[str, str]] = []
    for m in messages or []:
        role = str((m or {}).get("role") or "user")
        content = str((m or {}).get("content") or "")
        if role == "system":
            if content:
                system_parts.append(content)
        else:
            rest.append({"role": role if role in {"user", "assistant"} else "user", "content": content})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, rest


def _chat_openai_compat(
    *,
    messages: list[dict[str, str]],
    provider: str,
    model: str,
    temperature: float,
    base: str,
    api_key: str,
    timeout_s: float,
) -> dict[str, Any]:
    httpx = _require_httpx()
    url = f"{base}/chat/completions"
    validate_http_egress_url(url)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
    }
    # Prefer CPU for small local Ollama models when env asks (FaceRecognition-safe).
    if provider == "ollama":
        num_gpu = (os.environ.get("OLLAMA_NUM_GPU") or "").strip()
        if num_gpu != "":
            try:
                payload["options"] = {"num_gpu": int(num_gpu)}
            except ValueError:
                pass
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


def _chat_anthropic(
    *,
    messages: list[dict[str, str]],
    model: str,
    temperature: float,
    base: str,
    api_key: str,
    timeout_s: float,
) -> dict[str, Any]:
    httpx = _require_httpx()
    system, rest = _split_system(messages)
    if not rest:
        rest = [{"role": "user", "content": ""}]
    url = f"{base}/v1/messages"
    validate_http_egress_url(url)
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": os.environ.get("ANTHROPIC_VERSION", _ANTHROPIC_VERSION).strip()
        or _ANTHROPIC_VERSION,
    }
    payload: dict[str, Any] = {
        "model": model or "claude-3-5-haiku-latest",
        "max_tokens": int(os.environ.get("ANTHROPIC_MAX_TOKENS", "1024") or 1024),
        "messages": rest,
        "temperature": float(temperature),
    }
    if system:
        payload["system"] = system
    timeout = min(max(float(timeout_s or 60.0), 0.5), 300.0)
    resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    blocks = body.get("content") or []
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
        elif isinstance(block, str):
            parts.append(block)
    content = "".join(parts)
    usage = body.get("usage") or {}
    return {
        "content": content,
        "provider": "anthropic",
        "model": model,
        "base_url": base,
        "usage": usage,
        "raw": body,
    }


def _chat_gemini(
    *,
    messages: list[dict[str, str]],
    model: str,
    temperature: float,
    base: str,
    api_key: str,
    timeout_s: float,
) -> dict[str, Any]:
    httpx = _require_httpx()
    system, rest = _split_system(messages)
    model_id = (model or "gemini-2.0-flash").strip()
    if model_id.startswith("models/"):
        model_id = model_id[len("models/") :]
    url = f"{base}/models/{model_id}:generateContent"
    validate_http_egress_url(url)
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    contents: list[dict[str, Any]] = []
    for m in rest:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    if not contents:
        contents = [{"role": "user", "parts": [{"text": ""}]}]
    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {"temperature": float(temperature)},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    timeout = min(max(float(timeout_s or 60.0), 0.5), 300.0)
    resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    candidates = body.get("candidates") or []
    text = ""
    if candidates:
        parts = (((candidates[0] or {}).get("content") or {}).get("parts")) or []
        text = "".join(str(p.get("text") or "") for p in parts if isinstance(p, dict))
    usage = body.get("usageMetadata") or {}
    return {
        "content": text,
        "provider": "gemini",
        "model": model_id,
        "base_url": base,
        "usage": usage,
        "raw": body,
    }


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

    if provider not in _ALL_PROVIDERS:
        raise RuntimeError(
            f"llm_client: unknown provider {provider!r}. "
            "Use openai_compat, ollama, anthropic, gemini, or stub."
        )

    base = resolve_base_url(provider, base_url)

    if provider == "openai_compat":
        api_key = resolve_api_key(api_secret_name, base_url=base)
        if not api_key:
            raise NeedsCredentialsError(
                f"llm_client: provider='openai_compat' needs-credentials — set secret/env "
                f"{(api_secret_name or 'OPENAI_API_KEY')!r} (or GROQ_API_KEY for Groq base_url). "
                "For local/no-key use provider='ollama' or provider='stub'."
            )
        return _chat_openai_compat(
            messages=messages,
            provider=provider,
            model=model,
            temperature=temperature,
            base=base,
            api_key=api_key,
            timeout_s=timeout_s,
        )

    if provider == "ollama":
        api_key = ""
        if api_secret_name:
            api_key = resolve_api_key(api_secret_name, base_url=base)
        if not model or str(model).startswith("gpt-"):
            model = os.environ.get("OLLAMA_MODEL", "tinyllama").strip() or "tinyllama"
        return _chat_openai_compat(
            messages=messages,
            provider=provider,
            model=model,
            temperature=temperature,
            base=base,
            api_key=api_key,
            timeout_s=timeout_s,
        )

    if provider == "anthropic":
        secret = (api_secret_name or "").strip()
        if not secret or secret == "OPENAI_API_KEY":
            secret = "ANTHROPIC_API_KEY"
        api_key = resolve_api_key(secret, base_url=base)
        if not api_key:
            raise NeedsCredentialsError(
                "llm_client: provider='anthropic' needs-credentials — set secret/env "
                "ANTHROPIC_API_KEY. For local/no-key use provider='ollama' or provider='stub'."
            )
        if not model or str(model).startswith("gpt-"):
            model = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest").strip() or (
                "claude-3-5-haiku-latest"
            )
        return _chat_anthropic(
            messages=messages,
            model=model,
            temperature=temperature,
            base=base,
            api_key=api_key,
            timeout_s=timeout_s,
        )

    # gemini
    secret = (api_secret_name or "").strip()
    if not secret or secret == "OPENAI_API_KEY":
        secret = "GEMINI_API_KEY"
    api_key = resolve_api_key(secret, base_url=base)
    if not api_key:
        # Google often uses GOOGLE_API_KEY
        api_key = resolve_api_key("GOOGLE_API_KEY", base_url=base)
    if not api_key:
        raise NeedsCredentialsError(
            "llm_client: provider='gemini' needs-credentials — set secret/env "
            "GEMINI_API_KEY or GOOGLE_API_KEY. For local/no-key use provider='ollama' "
            "or provider='stub'."
        )
    if not model or str(model).startswith("gpt-"):
        model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip() or "gemini-2.0-flash"
    return _chat_gemini(
        messages=messages,
        model=model,
        temperature=temperature,
        base=base,
        api_key=api_key,
        timeout_s=timeout_s,
    )
