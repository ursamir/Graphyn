# app/core/credentials/__init__.py
"""Live Graphyn credential (connection) store.

Credentials belong to the Graphyn platform — graphs/nodes store only
connection id refs. Runtime resolves id → secret for that step only.

Public surface used by API/MCP/plugins:
  create_connection, list_connections, get_connection, update_connection,
  revoke_connection, set_default, resolve_connection, resolve_llm_credentials,
  register_kind, list_kinds, NeedsCredentialsError
"""
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
