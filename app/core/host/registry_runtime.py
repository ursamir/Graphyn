# app/core/host/registry_runtime.py
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
    """Return the fully-populated NodeRegistry singleton.

    Warns at runtime if called before AutoDiscovery.run() has populated the
    registry (i.e. the registry is empty).  Callers must not invoke this
    function before the application startup event fires.
    """
    if len(registry) == 0:
        import warnings
        warnings.warn(
            "get_registry() called before AutoDiscovery.run() — registry is empty.",
            RuntimeWarning,
            stacklevel=2,
        )
    return registry


def resolve_capability(ir_node: Any, registry: Any) -> "IRCapabilityMetadata":
    """Resolve capability metadata for a node instance.

    Precedence: fields *explicitly set* on IRNode.capability_metadata >
    NodeMetadata capability fields (unset IR fields never override plugin metadata).
    Falls back to IRCapabilityMetadata() defaults for unknown node types.

    This is a stateless function — no I/O, no mutable state.
    (Contains a lazy import to avoid circular imports at module level.)

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
    from app.core.nodes.errors import NodeNotFoundError

    # Use getattr so that objects without capability_metadata (e.g. mocks)
    # fall through to the registry lookup rather than raising AttributeError.
    cap_meta = getattr(ir_node, "capability_metadata", None)

    try:
        meta = registry.get_metadata(ir_node.node_type)
        base = IRCapabilityMetadata(
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
    except NodeNotFoundError:
        # Unknown node type — IR metadata (if any) over safe defaults.
        return cap_meta if cap_meta is not None else IRCapabilityMetadata()
    except Exception:
        if cap_meta is not None:
            return cap_meta
        raise

    if cap_meta is None:
        return base
    return _merge_ir_capability(base, cap_meta)


def _merge_ir_capability(base: Any, cap_meta: Any) -> Any:
    """Overlay IR-authored capability fields onto plugin-derived ``base``.

    Only fields the IR explicitly set (``model_fields_set``) AND whose value
    differs from the IRCapabilityMetadata default are applied. Replacing the
    plugin metadata wholesale would reset unset fields to defaults (e.g.
    ``cacheable=True``), silently making side-effect nodes cacheable. The
    default-value filter matters because a dump_ir/load_ir round-trip (run
    scoping, UI saves) marks *every* field as set; a value equal to the model
    default is indistinguishable from serializer padding, so it never
    overrides the plugin's declared capability.
    """
    explicit = getattr(cap_meta, "model_fields_set", None)
    if explicit is None:
        return cap_meta
    fields = type(cap_meta).model_fields
    overrides: dict[str, Any] = {}
    for name in explicit:
        if name not in fields:
            continue
        value = getattr(cap_meta, name)
        default = fields[name].get_default(call_default_factory=True)
        if value == default:
            continue
        overrides[name] = value
    if not overrides:
        return base
    return base.model_copy(update=overrides)


