# app/core/trust/__init__.py
"""
Bounded Context:  Trust boundary
Responsibility:   Named secrets, egress checks, the audit log and the
                  token-bound audit identity.
Owns:             Re-exports of this package's public names.
Public Surface:   lazy __getattr__ exports listed in _EXPORTS.
Must NOT:         Import heavy submodules at package import time.
Dependencies:     Submodules of this package (lazy).
Reason To Change: A public name moves to another package.
"""
from __future__ import annotations

_EXPORTS: dict[str, str] = {
    "HttpEgressError": "app.core.trust.egress",
    "SecretError": "app.core.trust.secrets",
    "audit_category": "app.core.trust.audit",
    "audit_dir": "app.core.trust.audit",
    "audit_label": "app.core.trust.audit",
    "current_identity": "app.core.trust.identity",
    "load_token_map": "app.core.trust.identity",
    "token_accepted": "app.core.trust.identity",
    "token_auth_configured": "app.core.trust.identity",
    "audit_events_path": "app.core.trust.audit",
    "delete_secret": "app.core.trust.secrets",
    "env_secret_name_allowed": "app.core.trust.secrets",
    "file_mode": "app.core.trust.secrets",
    "get_secret": "app.core.trust.secrets",
    "host_on_allowlist": "app.core.trust.egress",
    "is_blocked_ip": "app.core.trust.egress",
    "list_audit": "app.core.trust.audit",
    "list_secret_names": "app.core.trust.secrets",
    "normalize_audit_event": "app.core.trust.audit",
    "record_audit": "app.core.trust.audit",
    "redact_webhook_url_for_api": "app.core.trust.egress",
    "resolve_secret": "app.core.trust.secrets",
    "secret_meta": "app.core.trust.secrets",
    "secret_resource_version": "app.core.trust.secrets",
    "set_secret": "app.core.trust.secrets",
    "validate_http_egress_url": "app.core.trust.egress",
    "validate_secret_name": "app.core.trust.secrets",
    "validate_webhook_target_url": "app.core.trust.egress",
    "validated_webhook_ips": "app.core.trust.egress",
    "webhook_url_log_label": "app.core.trust.egress",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    module = importlib.import_module(module_name)
    return getattr(module, name)


__all__ = sorted(_EXPORTS)
