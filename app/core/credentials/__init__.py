# app/core/credentials/__init__.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Public API for connection records. Graphs store connection ids;
                  runtime resolves an id to a secret for one step.
Owns:             Re-exports of errors, kinds, store, and resolve.
Public Surface:   create_connection, list_connections, get_connection,
                  update_connection, revoke_connection, set_default,
                  resolve_connection, resolve_llm_credentials, register_kind,
                  list_kinds, NeedsCredentialsError.
Must NOT:         Return raw secret fields from list/get. Must not import app.api.
Dependencies:     app.core.credentials.{errors,kinds,store,resolve}
Reason To Change: A connection operation or kind is added to the public API.
"""
from __future__ import annotations

from app.core.credentials.errors import (
    CredentialError,
    CredentialNotFoundError,
    NeedsCredentialsError,
)
from app.core.credentials.kinds import (
    CredentialKind,
    KindField,
    get_kind,
    list_kinds,
    redact_payload,
    register_kind,
    require_kind,
)
from app.core.credentials.resolve import resolve_connection, resolve_llm_credentials
from app.core.credentials.store import (
    connection_exists,
    create_connection,
    get_connection,
    get_default_for_kind,
    get_payload,
    list_connections,
    revoke_connection,
    set_default,
    update_connection,
)

__all__ = [
    "CredentialError",
    "CredentialNotFoundError",
    "NeedsCredentialsError",
    "CredentialKind",
    "KindField",
    "register_kind",
    "list_kinds",
    "get_kind",
    "require_kind",
    "redact_payload",
    "create_connection",
    "list_connections",
    "get_connection",
    "get_payload",
    "update_connection",
    "revoke_connection",
    "set_default",
    "get_default_for_kind",
    "connection_exists",
    "resolve_connection",
    "resolve_llm_credentials",
]

# Append-only extra kinds registered from their own modules.
from app.core.credentials import inbound_webhook as _inbound_webhook  # noqa: E402,F401
