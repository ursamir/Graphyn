# app/core/credentials/resolve.py
"""Resolve connection id → secret payload for one step.

Precedence:
  1. Explicit connection id (node config / call arg)
  2. Workspace default connection for the kind
  3. Env / named-secret fallback for the kind (bootstrap only)

Fail-closed: raises NeedsCredentialsError when nothing resolves.
Never logs secret values.
"""
from __future__ import annotations

import os
from typing import Any

from app.core.credentials.errors import (
    CredentialNotFoundError,
    NeedsCredentialsError,
)
from app.core.credentials.kinds import get_kind, require_kind
from app.core.credentials import store as cred_store


def _env_fallback_payload(kind_id: str) -> dict[str, Any]:
    kind = get_kind(kind_id)
    if kind is None:
        return {}
    out: dict[str, Any] = {}
    for field_name, env_name in (kind.env_fallbacks or {}).items():
        val = ""
        # Prefer named secret store, then process env (same as secrets.resolve_secret).
        try:
            from app.core.secrets import resolve_secret
            val = resolve_secret(env_name) or ""
        except Exception:
            val = (os.environ.get(env_name) or "").strip()
        if not val:
            val = (os.environ.get(env_name) or "").strip()
        if val != "":
            out[field_name] = val
    # SMTP extras not always in env_fallbacks map completely
    if kind_id == "smtp":
        if "port" not in out:
            port_raw = (os.environ.get("GRAPHYN_SMTP_PORT") or "").strip()
            if port_raw:
                try:
                    out["port"] = int(port_raw)
                except ValueError:
                    out["port"] = 587
        tls_raw = (os.environ.get("GRAPHYN_SMTP_TLS") or "").strip().lower()
        if tls_raw:
            out["tls"] = tls_raw in {"1", "true", "yes", "on"}
        dry_raw = (os.environ.get("GRAPHYN_SMTP_DRY_RUN") or "").strip().lower()
        if dry_raw:
            out["dry_run"] = dry_raw in {"1", "true", "yes", "on"}
        # Password via GRAPHYN_SMTP_PASSWORD_SECRET
        if not out.get("password"):
            secret_name = (os.environ.get("GRAPHYN_SMTP_PASSWORD_SECRET") or "").strip()
            if secret_name:
                try:
                    from app.core.secrets import resolve_secret
                    out["password"] = resolve_secret(secret_name) or ""
                except Exception:
                    out["password"] = (os.environ.get(secret_name) or "").strip()
    if kind_id == "gemini" and not out.get("api_key"):
        try:
            from app.core.secrets import resolve_secret
            alt = resolve_secret("GOOGLE_API_KEY") or os.environ.get("GOOGLE_API_KEY", "").strip()
        except Exception:
            alt = os.environ.get("GOOGLE_API_KEY", "").strip()
        if alt:
            out["api_key"] = alt
    if kind_id == "openai_compat" and not out.get("api_key"):
        base = out.get("base_url") or os.environ.get("OPENAI_BASE_URL") or ""
        if "groq.com" in str(base).lower():
            try:
                from app.core.secrets import resolve_secret
                g = resolve_secret("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY", "").strip()
            except Exception:
                g = os.environ.get("GROQ_API_KEY", "").strip()
            if g:
                out["api_key"] = g
    return out


def resolve_connection(
    *,
    kind: str,
    connection_id: str | None = None,
    required: bool = True,
) -> dict[str, Any]:
    """Resolve to ``{connection_id, kind, source, payload}``.

    *source* is one of: ``connection``, ``workspace_default``, ``env``.
    """
    kid = (kind or "").strip().lower()
    require_kind(kid)
    cid = (connection_id or "").strip() or None

    if cid:
        try:
            kind_found, payload = cred_store.get_payload(cid)
        except CredentialNotFoundError as exc:
            raise NeedsCredentialsError(
                f"needs-credentials: connection {cid!r} not found or revoked "
                f"(kind={kid!r})"
            ) from exc
        if kind_found != kid:
            raise NeedsCredentialsError(
                f"needs-credentials: connection {cid!r} is kind={kind_found!r}, "
                f"expected kind={kid!r}"
            )
        return {
            "connection_id": cid,
            "kind": kid,
            "source": "connection",
            "payload": payload,
        }

    default = cred_store.get_default_for_kind(kid)
    if default is not None:
        try:
            _, payload = cred_store.get_payload(default["id"])
        except CredentialNotFoundError:
            payload = None
        else:
            return {
                "connection_id": default["id"],
                "kind": kid,
                "source": "workspace_default",
                "payload": payload,
            }

    env_payload = _env_fallback_payload(kid)
    # Consider env usable when required secret fields are present (or ollama/smtp dry-run).
    usable = False
    if kid == "ollama":
        usable = True  # local endpoint; key optional
    elif kid == "smtp":
        usable = bool(env_payload.get("host") or env_payload.get("dry_run"))
    elif kid in {"openai_compat", "anthropic", "gemini"}:
        usable = bool(env_payload.get("api_key"))
    elif kid == "webhook":
        usable = bool(env_payload.get("url"))
    else:
        usable = bool(env_payload)

    if usable and env_payload is not None:
        return {
            "connection_id": None,
            "kind": kid,
            "source": "env",
            "payload": env_payload,
        }

    if not required:
        return {
            "connection_id": None,
            "kind": kid,
            "source": "none",
            "payload": {},
        }

    raise NeedsCredentialsError(
        f"needs-credentials: no connection for kind={kid!r}. "
        "Create one via POST /api/v1/credentials, set a workspace default, "
        "or provide env bootstrap (see docs/ops/CREDENTIAL_STORE.md). "
        "Precedence: explicit connection id > workspace default > env."
    )


def resolve_llm_credentials(
    *,
    provider: str,
    connection_id: str | None = None,
    api_secret_name: str | None = None,
) -> dict[str, Any]:
    """Helper for llm_client: map provider → kind and resolve api_key/base_url.

    Legacy *api_secret_name* still works as env/named-secret fallback when no
    connection id and no workspace default exist.
    """
    provider = (provider or "openai_compat").strip().lower()
    kind_map = {
        "openai_compat": "openai_compat",
        "anthropic": "anthropic",
        "gemini": "gemini",
        "ollama": "ollama",
    }
    if provider in {"stub", "local_stub"}:
        return {"api_key": "", "base_url": "", "source": "stub", "connection_id": None}
    kid = kind_map.get(provider)
    if kid is None:
        raise NeedsCredentialsError(f"needs-credentials: unknown LLM provider {provider!r}")

    # Prefer connection / default / kind env; then legacy secret name.
    try:
        resolved = resolve_connection(kind=kid, connection_id=connection_id, required=False)
    except NeedsCredentialsError:
        resolved = {"source": "none", "payload": {}, "connection_id": None}

    payload = dict(resolved.get("payload") or {})
    source = resolved.get("source") or "none"

    if not payload.get("api_key") and api_secret_name and provider != "ollama":
        try:
            from app.core.secrets import resolve_secret
            val = resolve_secret(api_secret_name) or os.environ.get(api_secret_name, "").strip()
        except Exception:
            val = os.environ.get(api_secret_name or "", "").strip()
        if val:
            payload["api_key"] = val
            source = source if source not in {"none", ""} else "env"

    if provider in {"openai_compat", "anthropic", "gemini"} and not payload.get("api_key"):
        raise NeedsCredentialsError(
            f"needs-credentials: provider={provider!r} requires a connection "
            f"(kind={kid}) or env/secret API key. "
            "Precedence: connection id > workspace default > env."
        )

    return {
        "api_key": str(payload.get("api_key") or ""),
        "base_url": str(payload.get("base_url") or ""),
        "default_model": str(payload.get("default_model") or ""),
        "source": source,
        "connection_id": resolved.get("connection_id"),
        "kind": kid,
        "payload": payload,
    }
