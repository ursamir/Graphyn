# app/core/credentials/kinds.py
"""Extensible credential-kind registry.

Built-in kinds: openai_compat, anthropic, gemini, ollama, smtp, webhook,
http_auth (generic HTTP auth for http_request: bearer | basic | custom header).
Plugins may call register_kind() at import/load time — no API restart needed
for *using* an already-registered kind with an existing connection.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.credentials.errors import CredentialError

# Secret field names that must never appear in API/MCP list/get responses.
_ALWAYS_SECRET = frozenset({
    "api_key", "password", "token", "secret", "webhook_url", "url",
    "authorization", "private_key", "header_value",
})

HTTP_AUTH_SCHEMES = ("bearer", "basic", "header")


@dataclass(frozen=True)
class KindField:
    name: str
    secret: bool = False
    required: bool = False
    description: str = ""
    default: Any = None


@dataclass
class CredentialKind:
    id: str
    label: str
    description: str
    fields: list[KindField] = field(default_factory=list)
    env_fallbacks: dict[str, str] = field(default_factory=dict)
    # Map logical field → env var name(s) for bootstrap when no connection id.


_REGISTRY: dict[str, CredentialKind] = {}


def register_kind(kind: CredentialKind, *, replace: bool = False) -> None:
    kid = (kind.id or "").strip().lower()
    if not kid:
        raise CredentialError("credential kind id must be non-empty")
    if kid in _REGISTRY and not replace:
        raise CredentialError(f"credential kind {kid!r} already registered")
    _REGISTRY[kid] = CredentialKind(
        id=kid,
        label=kind.label or kid,
        description=kind.description or "",
        fields=list(kind.fields or []),
        env_fallbacks=dict(kind.env_fallbacks or {}),
    )


def get_kind(kind_id: str) -> CredentialKind | None:
    return _REGISTRY.get((kind_id or "").strip().lower())


def list_kinds() -> list[CredentialKind]:
    return [ _REGISTRY[k] for k in sorted(_REGISTRY) ]


def require_kind(kind_id: str) -> CredentialKind:
    kind = get_kind(kind_id)
    if kind is None:
        raise CredentialError(
            f"Unknown credential kind {kind_id!r}. "
            f"Known: {', '.join(sorted(_REGISTRY)) or '(none)'}"
        )
    return kind


def secret_field_names(kind_id: str) -> frozenset[str]:
    kind = get_kind(kind_id)
    names = set(_ALWAYS_SECRET)
    if kind:
        for f in kind.fields:
            if f.secret:
                names.add(f.name)
    return frozenset(names)


def validate_payload(kind_id: str, payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    """Validate and normalize a kind payload. Never logs values."""
    kind = require_kind(kind_id)
    if not isinstance(payload, dict):
        raise CredentialError("credential payload must be an object")
    known = {f.name for f in kind.fields}
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in known:
            # Allow forward-compatible extra non-secret metadata keys? Fail closed.
            raise CredentialError(f"Unknown field {key!r} for kind {kind.id!r}")
        cleaned[key] = value
    if not partial:
        for f in kind.fields:
            if f.required and (f.name not in cleaned or cleaned[f.name] in (None, "")):
                raise CredentialError(
                    f"Field {f.name!r} is required for kind {kind.id!r}"
                )
    # Apply defaults for missing optional fields on create
    if not partial:
        for f in kind.fields:
            if f.name not in cleaned and f.default is not None:
                cleaned[f.name] = f.default
    if kind.id == "http_auth":
        _validate_http_auth(cleaned, partial=partial)
    return cleaned


def _validate_http_auth(payload: dict[str, Any], *, partial: bool) -> None:
    """Scheme-specific checks for ``http_auth`` (never echoes secret values)."""
    scheme = payload.get("scheme")
    if scheme is None and partial:
        return
    scheme = str(scheme or "").strip().lower()
    if scheme not in HTTP_AUTH_SCHEMES:
        raise CredentialError(
            f"http_auth.scheme must be one of {', '.join(HTTP_AUTH_SCHEMES)}"
        )
    payload["scheme"] = scheme
    if partial:
        return
    need = {"bearer": ("token",), "basic": ("username", "password"), "header": ("header_name", "header_value")}
    for name in need[scheme]:
        if payload.get(name) in (None, ""):
            raise CredentialError(f"Field {name!r} is required for http_auth scheme {scheme!r}")
    if scheme == "header":
        hn = str(payload.get("header_name") or "")
        if not hn.replace("-", "").replace("_", "").isalnum():
            raise CredentialError("http_auth.header_name must be a plain HTTP header token")


def redact_payload(kind_id: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return a redacted copy suitable for API/MCP responses."""
    secrets = secret_field_names(kind_id)
    out: dict[str, Any] = {}
    for k, v in (payload or {}).items():
        if k in secrets:
            if v in (None, ""):
                out[k] = ""
            else:
                out[k] = "***"
        else:
            out[k] = v
    return out


def secret_fields_set(kind_id: str, payload: dict[str, Any] | None) -> dict[str, bool]:
    """``{secret_field: is_set}`` for every secret field of the kind.

    Lets clients tell "redacted" (``"***"``, True) from "never set" (``""``,
    False) without ever seeing the value.
    """
    kind = get_kind(kind_id)
    secrets = secret_field_names(kind_id)
    names: list[str] = []
    if kind:
        names.extend(f.name for f in kind.fields if f.name in secrets)
    names.extend(k for k in (payload or {}) if k in secrets and k not in names)
    return {
        name: (payload or {}).get(name) not in (None, "")
        for name in names
    }


def _register_builtins() -> None:
    if _REGISTRY:
        return
    register_kind(CredentialKind(
        id="openai_compat",
        label="OpenAI-compatible",
        description="OpenAI / Groq / Azure-style chat API key + optional base_url.",
        fields=[
            KindField("api_key", secret=True, required=True, description="API key"),
            KindField("base_url", secret=False, required=False, description="Optional base URL", default=""),
            KindField("default_model", secret=False, required=False, description="Optional default model", default=""),
        ],
        env_fallbacks={"api_key": "OPENAI_API_KEY", "base_url": "OPENAI_BASE_URL"},
    ))
    register_kind(CredentialKind(
        id="anthropic",
        label="Anthropic",
        description="Anthropic Messages API key.",
        fields=[
            KindField("api_key", secret=True, required=True, description="API key"),
            KindField("base_url", secret=False, required=False, description="Optional base URL", default=""),
            KindField("default_model", secret=False, required=False, description="Optional default model", default=""),
        ],
        env_fallbacks={"api_key": "ANTHROPIC_API_KEY", "base_url": "ANTHROPIC_BASE_URL"},
    ))
    register_kind(CredentialKind(
        id="gemini",
        label="Google Gemini",
        description="Google Generative Language API key.",
        fields=[
            KindField("api_key", secret=True, required=True, description="API key"),
            KindField("base_url", secret=False, required=False, description="Optional base URL", default=""),
            KindField("default_model", secret=False, required=False, description="Optional default model", default=""),
        ],
        env_fallbacks={"api_key": "GEMINI_API_KEY", "base_url": "GEMINI_BASE_URL"},
    ))
    register_kind(CredentialKind(
        id="ollama",
        label="Ollama",
        description="Local Ollama OpenAI-compatible endpoint (key optional).",
        fields=[
            KindField("base_url", secret=False, required=False, description="Ollama base URL", default="http://127.0.0.1:11434/v1"),
            KindField("api_key", secret=True, required=False, description="Optional API key", default=""),
            KindField("default_model", secret=False, required=False, description="Optional default model", default=""),
        ],
        env_fallbacks={"base_url": "OLLAMA_BASE_URL", "default_model": "OLLAMA_MODEL"},
    ))
    register_kind(CredentialKind(
        id="smtp",
        label="SMTP",
        description="Outbound SMTP for send_email / run notify.",
        fields=[
            KindField("host", secret=False, required=True, description="SMTP host"),
            KindField("port", secret=False, required=False, description="SMTP port", default=587),
            KindField("user", secret=False, required=False, description="SMTP username", default=""),
            KindField("password", secret=True, required=False, description="SMTP password", default=""),
            KindField("from_addr", secret=False, required=False, description="From address", default=""),
            KindField("tls", secret=False, required=False, description="STARTTLS", default=True),
            KindField("dry_run", secret=False, required=False, description="Dry-run (no network)", default=False),
        ],
        env_fallbacks={
            "host": "GRAPHYN_SMTP_HOST",
            "port": "GRAPHYN_SMTP_PORT",
            "user": "GRAPHYN_SMTP_USER",
            "password": "GRAPHYN_SMTP_PASSWORD",
            "from_addr": "GRAPHYN_SMTP_FROM",
        },
    ))
    register_kind(CredentialKind(
        id="webhook",
        label="Webhook URL",
        description="Slack-style incoming webhook URL (or generic HTTPS POST target).",
        fields=[
            KindField("url", secret=True, required=True, description="Webhook URL"),
            KindField("events", secret=False, required=False, description="Optional event filter CSV", default=""),
        ],
        env_fallbacks={},
    ))
    register_kind(CredentialKind(
        id="http_auth",
        label="HTTP auth",
        description=(
            "Generic HTTP authentication for http_request: bearer token, basic "
            "username/password, or a custom header. allowed_hosts (CSV) binds "
            "the secret to specific hosts."
        ),
        fields=[
            KindField("scheme", secret=False, required=True, description="bearer | basic | header", default="bearer"),
            KindField("token", secret=True, required=False, description="Bearer token (scheme=bearer)", default=""),
            KindField("username", secret=False, required=False, description="Username (scheme=basic)", default=""),
            KindField("password", secret=True, required=False, description="Password (scheme=basic)", default=""),
            KindField("header_name", secret=False, required=False, description="Header name (scheme=header), e.g. X-API-Key", default=""),
            KindField("header_value", secret=True, required=False, description="Header value (scheme=header)", default=""),
            KindField(
                "allowed_hosts", secret=False, required=False, default="",
                description="CSV of hostnames this secret may be sent to (required at use — empty fails closed)",
            ),
        ],
        env_fallbacks={},
    ))


_register_builtins()
