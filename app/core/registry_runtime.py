# app/core/registry_runtime.py
"""
Bounded Context:  BC3 — Node Catalog
Responsibility:   Provide the NodeRegistry singleton and capability resolution.
Owns:             get_registry() accessor, resolve_capability() pure function.
Public Surface:   get_registry(), resolve_capability(ir_node, registry)
Must NOT:         Import from BC4 (planner), BC5 (orchestrator/executor),
                  app.domain, or app.api.
Dependencies:     app.core.nodes (registry singleton),
                  app.core.ir.models (IRCapabilityMetadata, IRNode)
Reason To Change: Registry access pattern changes, or capability resolution
                  logic evolves (e.g. new capability fields added to IRNode).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.nodes import registry

if TYPE_CHECKING:
    from app.core.ir.models import IRCapabilityMetadata


def get_registry():
    """Return the fully-populated NodeRegistry singleton."""
    return registry


def resolve_capability(ir_node: Any, registry: Any) -> "IRCapabilityMetadata":
    """Resolve capability metadata for a node instance.

    Precedence: IRNode.capability_metadata > NodeMetadata capability fields.
    Falls back to IRCapabilityMetadata() defaults for unknown node types.

    This is a pure function — no side effects, no I/O.

    Extracted from orchestrator.py (SA-O5 fix) so that both the sequential
    orchestrator and the parallel executor can share a single implementation
    without either depending on the other.

    Args:
        ir_node: An IRNode instance (or any object with .capability_metadata
                 and .node_type attributes).
        registry: The NodeRegistry singleton (from get_registry()).

    Returns:
        An IRCapabilityMetadata instance with resolved capability values.
    """
    from app.core.ir.models import IRCapabilityMetadata  # lazy — avoids circular import at module level

    if ir_node.capability_metadata is not None:
        return ir_node.capability_metadata

    try:
        meta = registry.get_metadata(ir_node.node_type)
        return IRCapabilityMetadata(
            requires_gpu=meta.requires_gpu,
            supports_cpu=meta.supports_cpu,
            supports_edge=meta.supports_edge,
            deterministic=meta.deterministic,
            cacheable=meta.cacheable,
            streaming_support=meta.streaming_support,
            realtime_support=meta.realtime_support,
            memory_requirements=meta.memory_requirements,
            dependency_requirements=meta.dependency_requirements,
            batch_support=meta.batch_support,
        )
    except Exception:
        return IRCapabilityMetadata()
