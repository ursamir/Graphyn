# app/core/host/__init__.py
"""
Bounded Context:  Process host
Responsibility:   Shutdown, readiness, and the node-registry accessor.
Owns:             Re-exports of this package's public names.
Public Surface:   lazy __getattr__ exports listed in _EXPORTS.
Must NOT:         Import heavy submodules at package import time.
Dependencies:     Submodules of this package (lazy).
Reason To Change: A public name moves to another package.
"""
from __future__ import annotations

_EXPORTS: dict[str, str] = {
    "assert_accepting_runs": "app.core.host.shutdown",
    "begin_drain": "app.core.host.shutdown",
    "clear_readiness_cache": "app.core.host.readiness",
    "drain_active_runs": "app.core.host.shutdown",
    "get_registry": "app.core.host.registry_runtime",
    "is_draining": "app.core.host.shutdown",
    "list_local_active_run_ids": "app.core.host.shutdown",
    "readiness_snapshot": "app.core.host.readiness",
    "reset_drain_for_tests": "app.core.host.shutdown",
    "resolve_capability": "app.core.host.registry_runtime",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    module = importlib.import_module(module_name)
    return getattr(module, name)


__all__ = sorted(_EXPORTS)
