# Functional Review — app/core/registry_runtime.py

**Group:** 3 — Registry & Discovery  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/registry_runtime.py
FUNCTION:    get_registry
CATEGORY:    Contract Mismatch
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Return the fully-populated NodeRegistry singleton."

WHAT IT ACTUALLY DOES:
Returns `registry` — the module-level object imported from `app.core.nodes`
at module load time via `from app.core.nodes import registry`. This import
happens when `registry_runtime.py` is first imported, which may be before
`AutoDiscovery.run()` has been called. The function name and docstring claim
the registry is "fully-populated", but there is no guard, assertion, or
check that discovery has actually completed. Callers that import
`registry_runtime` early (e.g. at module level in a router or handler) will
receive an empty registry and may cache it, never seeing the nodes registered
later by `AutoDiscovery`.

EVIDENCE:
```python
from app.core.nodes import registry   # imported at module load time

def get_registry():
    """Return the fully-populated NodeRegistry singleton."""
    return registry   # no check that discovery has run
```

REPRODUCTION SCENARIO:
A router module does `from app.core.registry_runtime import get_registry`
at module level, then calls `get_registry()` in a request handler before
the application startup event fires `AutoDiscovery.run()`. The handler
receives an empty registry and raises `NodeNotFoundError` for every node
type.

IMPACT:
Silent wrong result at startup — empty registry returned with no error;
all node lookups fail with confusing `NodeNotFoundError`.

FIX DIRECTION:
Add a readiness flag or raise if the registry is empty:
```python
def get_registry():
    if len(registry) == 0:
        import warnings
        warnings.warn(
            "get_registry() called before AutoDiscovery.run() — registry is empty.",
            RuntimeWarning, stacklevel=2,
        )
    return registry
```
Or document explicitly that callers must not call this before startup
completes, and enforce it with an assertion in debug mode.

--------------------------------------------------------------------
FILE:        app/core/registry_runtime.py
FUNCTION:    resolve_capability
CATEGORY:    Silent Failure Risk
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Falls back to IRCapabilityMetadata() defaults for unknown node types."

WHAT IT ACTUALLY DOES:
The bare `except Exception: return IRCapabilityMetadata()` swallows ALL
exceptions from `registry.get_metadata(ir_node.node_type)` — including
`NodeNotFoundError` (unknown node type, which is expected and documented),
but also `AttributeError` if `ir_node` has no `node_type` attribute,
`TypeError` from a malformed `ir_node`, and any future exceptions from
`IRCapabilityMetadata(...)` constructor itself. The caller receives a
default `IRCapabilityMetadata()` with no indication that anything went wrong.

EVIDENCE:
```python
try:
    meta = registry.get_metadata(ir_node.node_type)
    return IRCapabilityMetadata(...)
except Exception:          # ← catches everything, including programming errors
    return IRCapabilityMetadata()
```

REPRODUCTION SCENARIO:
`ir_node` is `None` (passed by a buggy caller). `None.node_type` raises
`AttributeError`. The function silently returns default capability metadata.
The pipeline proceeds with wrong capability assumptions (e.g. `requires_gpu=False`
when the node actually requires GPU), causing silent incorrect scheduling.

IMPACT:
Silent wrong result — incorrect capability metadata used for scheduling;
GPU nodes may be scheduled on CPU-only workers with no error.

FIX DIRECTION:
Narrow the except clause to only the expected case:
```python
from app.core.nodes.errors import NodeNotFoundError
try:
    meta = registry.get_metadata(ir_node.node_type)
    return IRCapabilityMetadata(
        requires_gpu=meta.requires_gpu,
        ...
    )
except NodeNotFoundError:
    return IRCapabilityMetadata()   # unknown node type — use defaults
# All other exceptions propagate
```

--------------------------------------------------------------------
FILE:        app/core/registry_runtime.py
FUNCTION:    resolve_capability
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Precedence: IRNode.capability_metadata > NodeMetadata capability fields."

WHAT IT ACTUALLY DOES:
```python
if ir_node.capability_metadata is not None:
    return ir_node.capability_metadata
```
If `ir_node` does not have a `capability_metadata` attribute at all (e.g.
a mock or a non-IRNode object passed by a test), `getattr` is not used —
the direct attribute access raises `AttributeError`, which is then swallowed
by the bare `except Exception` in the outer try block, returning default
capability metadata silently.

EVIDENCE:
```python
if ir_node.capability_metadata is not None:   # AttributeError if attr absent
    return ir_node.capability_metadata
```
This line is OUTSIDE the try/except block, so `AttributeError` here
propagates uncaught to the caller (not swallowed). This is inconsistent
with the documented "pure function — no side effects" contract: it can raise
on malformed input.

REPRODUCTION SCENARIO:
`resolve_capability(mock_node, registry)` where `mock_node` has no
`capability_metadata` attribute. `AttributeError` propagates to the caller,
which may not expect it from a "pure function with fallback defaults".

IMPACT:
Unexpected crash in callers that pass non-IRNode objects; inconsistent with
the documented fallback behaviour.

FIX DIRECTION:
Use `getattr` with a default:
```python
cap_meta = getattr(ir_node, "capability_metadata", None)
if cap_meta is not None:
    return cap_meta
```

--------------------------------------------------------------------
FILE:        app/core/registry_runtime.py
FUNCTION:    resolve_capability
CATEGORY:    Testability
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"This is a pure function — no side effects, no I/O."

WHAT IT ACTUALLY DOES:
Contains a lazy import inside the function body:
```python
from app.core.ir.models import IRCapabilityMetadata  # lazy — avoids circular import
```
This is not a side effect in the strict sense, but it means the function
modifies `sys.modules` on first call (a global side effect). More
practically, it makes the function harder to test in isolation: tests must
ensure `app.core.ir.models` is importable, or mock `sys.modules`. The
comment "avoids circular import at module level" is valid, but the claim
of "pure function" is slightly misleading.

EVIDENCE:
```python
def resolve_capability(ir_node, registry):
    """... This is a pure function — no side effects, no I/O."""
    from app.core.ir.models import IRCapabilityMetadata  # side effect on first call
```

REPRODUCTION SCENARIO:
Not a runtime bug — documentation inaccuracy and minor testability concern.

IMPACT:
Low — informational only.

FIX DIRECTION:
Update docstring: "This is a stateless function — no I/O, no mutable state.
(Contains a lazy import to avoid circular imports at module level.)"

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | PARTIAL |
| Top Risk | `resolve_capability` uses a bare `except Exception` that swallows `AttributeError` on `None` input and returns default capability metadata silently — GPU nodes may be scheduled on CPU-only workers with no error or warning. |
