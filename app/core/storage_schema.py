# app/core/storage_schema.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Shared on-disk schema version for workspace persistence.
Owns:             STATE_SCHEMA_VERSION, assert_storage_schema_version()
Public Surface:   STATE_SCHEMA_VERSION, assert_storage_schema_version
Must NOT:         Import from app.domain or app.api.
Dependencies:     stdlib typing only.
Reason To Change: Breaking changes to artifact/provenance/registry envelopes.
"""
from __future__ import annotations

from typing import Any

STATE_SCHEMA_VERSION = "1.0"
_SUPPORTED = frozenset({STATE_SCHEMA_VERSION})


def assert_storage_schema_version(
    data: dict[str, Any],
    *,
    context: str,
) -> None:
    """Reject records whose schema_version is newer than this runtime supports."""
    if not isinstance(data, dict):
        raise ValueError(f"{context}: record must be a JSON object")
    version = str(data.get("schema_version") or STATE_SCHEMA_VERSION)
    if version not in _SUPPORTED:
        raise ValueError(
            f"{context}: unsupported schema_version {version!r} "
            f"(supported: {sorted(_SUPPORTED)})"
        )
