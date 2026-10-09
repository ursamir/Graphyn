# app/core/nodes/idempotency.py
"""
Bounded Context:  Nodes — execution safety
Responsibility:   Decide whether a node execution may be repeated automatically
                  after infrastructure loss (expired Mode B lease, worker restart).
Public Surface:   node_is_idempotent(node_type, config) -> bool
Rule:             NodeMetadata.idempotent (default True); a node class may refine
                  per config with ``idempotent_for(config) -> bool`` (e.g.
                  http_request: GET/HEAD/OPTIONS only). Unknown types → True
                  (the same default the queue used before F19).
"""
from __future__ import annotations

from typing import Any


def node_is_idempotent(node_type: str, config: dict[str, Any] | None = None) -> bool:
    try:
        from app.core.host.registry_runtime import get_registry

        registry = get_registry()
        meta = registry.get_metadata(node_type)
        base = bool(getattr(meta, "idempotent", True))
        try:
            cls = registry.get_class(node_type)
        except Exception:
            cls = None
        hook = getattr(cls, "idempotent_for", None) if cls is not None else None
        if callable(hook):
            try:
                return bool(hook(dict(config or {})))
            except Exception:
                return base
        return base
    except Exception:
        return True
