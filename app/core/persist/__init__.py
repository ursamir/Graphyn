# app/core/persist/__init__.py
"""
Bounded Context:  BC6 — Persistence primitives
Responsibility:   File locks, storage schema version, and store integrity checks.
Owns:             Re-exports of this package's public names.
Public Surface:   lazy __getattr__ exports listed in _EXPORTS.
Must NOT:         Import heavy submodules at package import time.
Dependencies:     Submodules of this package (lazy).
Reason To Change: A public name moves to another package.
"""
from __future__ import annotations

_EXPORTS: dict[str, str] = {
    "LockUnavailable": "app.core.persist.file_lock",
    "StoreCorrupt": "app.core.persist.store_integrity",
    "acquire": "app.core.persist.file_lock",
    "assert_storage_schema_version": "app.core.persist.storage_schema",
    "ensure_store_ok": "app.core.persist.store_integrity",
    "raise_if_store_corrupt": "app.core.persist.store_integrity",
    "readiness_store_corrupt": "app.core.persist.store_integrity",
    "release": "app.core.persist.file_lock",
    "store_corrupt_http_detail": "app.core.persist.store_integrity",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    module = importlib.import_module(module_name)
    return getattr(module, name)


__all__ = sorted(_EXPORTS)
