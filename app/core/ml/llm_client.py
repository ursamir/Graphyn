# app/core/ml/llm_client.py
"""Shared multi-provider chat client for plugin nodes.

Providers:
  - openai_compat: OpenAI / Groq / Azure-style / any */v1 base_url (needs API key)
  - ollama: local OpenAI-compatible server (default http://127.0.0.1:11434/v1; no key)
  - anthropic: native Anthropic Messages API (needs ANTHROPIC_API_KEY)
  - gemini: native Google Generative Language API (needs GEMINI_API_KEY / GOOGLE_API_KEY)
  - stub: deterministic offline reply (tests / dry graphs)

Fail-closed: cloud providers without a resolvable key raise NeedsCredentialsError.
Never embed raw secrets in IR — pass secret *names*.

Endpoint binding: a resolved API key is only sent to the ``base_url`` bound to
its credential (connection base_url, else provider default). A differing node
``base_url`` is refused (env/secret keys: unless the host is listed in
``GRAPHYN_LLM_BASE_URL_ALLOWLIST``). ``api_secret_name`` may not name
``GRAPHYN_*`` internals (see ``app.core.trust.secrets.env_secret_name_allowed``).
Plugins that build their own request body (e.g. structured_llm's
``response_format``) resolve key + endpoint via ``resolve_llm_endpoint()`` so
the same precedence and binding apply.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from app.core.trust.egress import validate_http_egress_url

logger = logging.getLogger(__name__)

_DEFAULT_OPENAI = "https://api.openai.com/v1"
_DEFAULT_OLLAMA = "http://127.0.0.1:11434/v1"
_DEFAULT_ANTHROPIC = "https://api.anthropic.com"
_DEFAULT_GEMINI = "https://generativelanguage.googleapis.com/v1beta"
_ANTHROPIC_VERSION = "2023-06-01"

_CLOUD_PROVIDERS = frozenset({"openai_compat", "anthropic", "gemini"})
_ALL_PROVIDERS = frozenset({"openai_compat", "ollama", "anthropic", "gemini", "stub", "local_stub"})


# Canonical definition lives in app.core.credentials; re-exported here for
# existing plugin imports (`from app.core.ml.llm_client import NeedsCredentialsError`).
from app.core.credentials.errors import NeedsCredentialsError  # noqa: F401


def resolve_api_key(secret_name: str | None, *, base_url: str = "") -> str:
    """Resolve API key from Graphyn secret store, then process env."""
    name = (secret_name or "").strip() or "OPENAI_API_KEY"
    try:
        from app.core.trust.secrets import resolve_secret
        val = resolve_secret(name)
    except Exception:
        val = ""
    if val:
        return val
    try:
        from app.core.trust.secrets import env_secret_name_allowed
        env_ok = env_secret_name_allowed(name)
    except Exception:
        env_ok = False
    val = os.environ.get(name, "").strip() if env_ok else ""
    if val:
        return val
    # Groq convenience when base_url points at groq
    if "groq.com" in (base_url or "").lower():
        try:
            from app.core.trust.secrets import resolve_secret
            val = resolve_secret("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY", "").strip()
        except Exception:
            val = os.environ.get("GROQ_API_KEY", "").strip()
        if val:
            return val
    return ""


def _checked_secret_name(name: str | None) -> str | None:
    """Refuse node-selected secret names that would read internal env vars.

    A name is usable if it exists in the Graphyn secret store, or if process env
    fallback is permitted for it (see ``app.core.trust.secrets.env_secret_name_allowed``).
    """
    cleaned = (name or "").strip()
    if not cleaned:
        return name
    from app.core.trust.secrets import env_secret_name_allowed, get_secret

    if env_secret_name_allowed(cleaned):
        return cleaned
    try:
        stored = get_secret(cleaned)
    except Exception:
        stored = ""
    if stored:
        return cleaned
    raise NeedsCredentialsError(
        f"llm_client: api_secret_name={cleaned!r} is not a permitted secret name "
        "(GRAPHYN_* internals and non secret-shaped env vars are refused). Store it via "
        "the Credentials/Secrets store or add it to GRAPHYN_SECRET_ENV_ALLOWLIST."
    )


def _norm_base(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def _base_url_override_allowlisted(url: str) -> bool:
    raw = os.environ.get("GRAPHYN_LLM_BASE_URL_ALLOWLIST", "") or ""
    allowed = {h.strip().lower() for h in raw.split(",") if h.strip()}
    if not allowed:
        return False
    from urllib.parse import urlsplit

    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return bool(host) and host in allowed


def _enforce_base_url_binding(
    *, provider: str, explicit_base: str, cred: dict[str, Any], api_key: str
) -> None:
    """Refuse sending a resolved API key to a node-chosen endpoint.

    A connection / workspace default binds its key to its own ``base_url``
    (or the provider default when unset). Env / named-secret keys bind to the
    provider default (``*_BASE_URL`` env) unless the override host is listed in
    ``GRAPHYN_LLM_BASE_URL_ALLOWLIST``.
    """
    if not explicit_base or not api_key:
        return
    bound = str(cred.get("base_url") or "") or resolve_base_url(provider, None)
    if _norm_base(explicit_base) == _norm_base(bound):
        return
    source = str(cred.get("source") or "")
    if source not in {"connection", "workspace_default"} and _base_url_override_allowlisted(explicit_base):
        return
    raise NeedsCredentialsError(
        f"llm_client: node base_url differs from the endpoint bound to the resolved "
        f"credential (source={source or 'env'}); refusing to send its API key to a "
        "different host. Create a connection with that base_url, or (env/secret keys "
        "only) list the host in GRAPHYN_LLM_BASE_URL_ALLOWLIST."
    )


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


def resolve_llm_endpoint(
    *,
    provider: str = "openai_compat",
    base_url: str | None = None,
    api_secret_name: str | None = "OPENAI_API_KEY",
    connection_id: str | None = None,
) -> dict[str, Any]:
    """Resolve ``{api_key, base_url, source, default_model, connection_id}``.

    For plugins that need a bespoke request body (e.g. ``response_format``)
    but must honour the same credential precedence and endpoint binding as
    :func:`chat_completion`: connection id > workspace default > env/secret,
    the api_secret_name guard, and :func:`_enforce_base_url_binding` (a
    resolved key is never sent to a node-chosen ``base_url`` that differs from
    the one bound to its credential unless allowlisted for env/secret keys).
    Raises :class:`NeedsCredentialsError` (fail closed).
    """
    provider = (provider or "openai_compat").strip().lower()
    if provider not in _ALL_PROVIDERS or provider in {"stub", "local_stub"}:
        raise RuntimeError(f"llm_client: resolve_llm_endpoint unsupported provider {provider!r}")
    from app.core.credentials.resolve import resolve_llm_credentials

    checked = _checked_secret_name(api_secret_name)
    secret = checked
    if provider == "anthropic" and (not secret or secret == "OPENAI_API_KEY"):
        secret = "ANTHROPIC_API_KEY"
    if provider == "gemini" and (not secret or secret == "OPENAI_API_KEY"):
        secret = "GEMINI_API_KEY"
    try:
        cred = resolve_llm_credentials(
            provider=provider,
            connection_id=connection_id,
            api_secret_name=secret if provider != "ollama" else (checked or None),
        )
    except NeedsCredentialsError:
        if provider != "openai_compat":
            raise
        cred = {"api_key": "", "base_url": "", "source": "none", "connection_id": None}

    explicit_base = (base_url or "").strip()
    api_key = str(cred.get("api_key") or "")
    if provider == "openai_compat" and not api_key:
        base_hint = resolve_base_url(provider, explicit_base or str(cred.get("base_url") or "") or None)
        api_key = resolve_api_key(checked, base_url=base_hint)
        if api_key:
            cred = {**cred, "source": "env", "base_url": ""}
    _enforce_base_url_binding(
        provider=provider, explicit_base=explicit_base, cred=cred, api_key=api_key
    )
    if provider in _CLOUD_PROVIDERS and not api_key:
        raise NeedsCredentialsError(
            f"llm_client: provider={provider!r} needs-credentials — set a connection "
            f"(kind={provider}) or secret/env {(secret or 'OPENAI_API_KEY')!r}."
        )
    base = resolve_base_url(provider, explicit_base or str(cred.get("base_url") or "") or None)
    return {
        "api_key": api_key,
        "base_url": base,
        "source": str(cred.get("source") or ""),
        "default_model": str(cred.get("default_model") or ""),
        "connection_id": cred.get("connection_id"),
    }


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
    connection_id: str | None = None,
    credentials: dict[str, Any] | None = None,
    timeout_s: float = 60.0,
    stub_content: str | None = None,
) -> dict[str, Any]:
    """Return {content, provider, model, base_url, usage?, raw?}.

    Credential precedence (see docs/ops/CREDENTIAL_STORE.md):
      explicit connection_id / credentials dict > workspace default for kind > env/secret.
    """
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

    # Optional pre-resolved credentials dict (from caller) short-circuits store.
    cred: dict[str, Any]
    if isinstance(credentials, dict) and (
        credentials.get("api_key") is not None or credentials.get("base_url") is not None
        or credentials.get("payload") is not None
    ):
        payload = credentials.get("payload") if isinstance(credentials.get("payload"), dict) else credentials
        cred = {
            "api_key": str(payload.get("api_key") or ""),
            "base_url": str(payload.get("base_url") or ""),
            "default_model": str(payload.get("default_model") or ""),
            "source": credentials.get("source") or "inline",
            "connection_id": credentials.get("connection_id") or connection_id,
        }
    else:
        from app.core.credentials.resolve import resolve_llm_credentials
        api_secret_name = _checked_secret_name(api_secret_name)  # type: ignore[assignment]
        secret = api_secret_name
        if provider == "anthropic" and (not secret or secret == "OPENAI_API_KEY"):
            secret = "ANTHROPIC_API_KEY"
        if provider == "gemini" and (not secret or secret == "OPENAI_API_KEY"):
            secret = "GEMINI_API_KEY"
        cred = resolve_llm_credentials(
            provider=provider,
            connection_id=connection_id,
            api_secret_name=secret if provider != "ollama" else (api_secret_name or None),
        )

    explicit_base = (base_url or "").strip()
    resolved_base = explicit_base or str(cred.get("base_url") or "")
    base = resolve_base_url(provider, resolved_base or None)
    api_key = str(cred.get("api_key") or "")
    if cred.get("default_model") and (not model or str(model).startswith("gpt-")):
        model = str(cred["default_model"])

    if provider == "openai_compat":
        if not api_key:
            # Legacy path still tries resolve_api_key when connection path missed.
            api_key = resolve_api_key(_checked_secret_name(api_secret_name), base_url=base)
            if api_key:
                cred = {**cred, "source": "env", "base_url": ""}
        _enforce_base_url_binding(
            provider=provider, explicit_base=explicit_base, cred=cred, api_key=api_key
        )
        if not api_key:
            raise NeedsCredentialsError(
                f"llm_client: provider='openai_compat' needs-credentials — set connection "
                f"(kind=openai_compat) or secret/env {(api_secret_name or 'OPENAI_API_KEY')!r}. "
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

    # Non-openai providers: bind resolved keys to their endpoint too.
    _enforce_base_url_binding(
        provider=provider, explicit_base=explicit_base, cred=cred, api_key=api_key
    )

    if provider == "ollama":
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
        if not api_key:
            raise NeedsCredentialsError(
                "llm_client: provider='anthropic' needs-credentials — set connection "
                "(kind=anthropic) or secret/env ANTHROPIC_API_KEY."
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
    if not api_key:
        raise NeedsCredentialsError(
            "llm_client: provider='gemini' needs-credentials — set connection "
            "(kind=gemini) or secret/env GEMINI_API_KEY / GOOGLE_API_KEY."
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
