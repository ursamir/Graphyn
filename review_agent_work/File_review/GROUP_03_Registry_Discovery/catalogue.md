# Functional Review — app/core/nodes/catalogue.py

**Group:** 3 — Registry & Discovery  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/nodes/catalogue.py
FUNCTION:    TypeCatalogue.register
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Register a PortDataType subclass; raise `DuplicatePortTypeError` if the
fully-qualified name is already registered.

WHAT IT ACTUALLY DOES:
The duplicate check compares by fully-qualified name (FQN) string only. If
the same class is re-loaded under a different module path (e.g. once as
`app.models.audio_sample.AudioSample` and once as
`audio_sample.AudioSample` via a plugin loader), both registrations succeed
because the FQN strings differ — even though they are functionally the same
type. This means `TypeCatalogue` can hold two entries for what is logically
the same type, and `resolve()` will return different class objects depending
on which FQN string the caller uses.

EVIDENCE:
```python
name = _fqn(type_class)          # "module.qualname"
if name in self._types:
    raise DuplicatePortTypeError(...)
self._types[name] = type_class   # no identity check
```
No check for `type_class is existing_class` — same class object under two
FQN strings is allowed.

REPRODUCTION SCENARIO:
`AudioSample` is loaded by `AutoDiscovery` as `app.models.audio_sample.AudioSample`
and also by a plugin loader as `audio_sample.AudioSample`. Both are registered.
`CompatibilityChecker.are_compatible` uses `issubclass`, so runtime type
checks still work, but `resolve("audio_sample.AudioSample")` and
`resolve("app.models.audio_sample.AudioSample")` return different class
objects, breaking identity comparisons (`is`) in callers.

IMPACT:
Silent wrong result — type identity checks fail; port compatibility may be
incorrectly evaluated if callers use `is` instead of `issubclass`.

FIX DIRECTION:
After the FQN check, also scan for the same class object:
```python
for existing_cls in self._types.values():
    if existing_cls is type_class:
        return  # same object already registered under a different FQN — skip
```

--------------------------------------------------------------------
FILE:        app/core/nodes/catalogue.py
FUNCTION:    TypeCatalogue.register
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Raise `TypeError` if `type_class` is not a subclass of `PortDataType`.

WHAT IT ACTUALLY DOES:
The guard is `isinstance(type_class, type) and issubclass(type_class, PortDataType)`.
This correctly rejects non-type objects and non-subclasses. However, it also
rejects `PortDataType` itself (since `issubclass(PortDataType, PortDataType)`
is `True` but the intent is to reject the base class). The base class is
never passed in practice (AutoDiscovery filters it out), but the guard does
not explicitly exclude it — if it were passed, it would be registered under
the FQN `"app.core.nodes.ports.PortDataType"`, which could confuse
`resolve()` callers expecting only concrete subclasses.

EVIDENCE:
```python
if not (isinstance(type_class, type) and issubclass(type_class, PortDataType)):
    raise TypeError(...)
# PortDataType itself passes this check
```

REPRODUCTION SCENARIO:
`catalogue.register(PortDataType)` — succeeds silently, registering the
abstract base class as a concrete type.

IMPACT:
Low — unlikely in practice; no data loss.

FIX DIRECTION:
```python
if not (isinstance(type_class, type)
        and issubclass(type_class, PortDataType)
        and type_class is not PortDataType):
    raise TypeError(...)
```

--------------------------------------------------------------------
FILE:        app/core/nodes/catalogue.py
FUNCTION:    TypeCatalogue.resolve
CATEGORY:    Error Handling
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the Python type for the given fully-qualified name; raise
`PortTypeNotFoundError` if not registered.

WHAT IT ACTUALLY DOES:
The error message includes `sorted(self._types)` — the full list of all
registered type names. For a large catalogue (hundreds of types), this
produces an extremely long error message that may be truncated in logs or
overwhelm structured log systems.

EVIDENCE:
```python
raise PortTypeNotFoundError(
    f"Port type '{type_name}' is not registered in TypeCatalogue. "
    f"Registered types: {sorted(self._types)}"   # potentially hundreds of entries
)
```

REPRODUCTION SCENARIO:
A catalogue with 200 registered types. `resolve("unknown.Type")` raises an
exception with a 5000-character message.

IMPACT:
Log pollution; no functional impact.

FIX DIRECTION:
Limit the list in the error message:
```python
all_types = sorted(self._types)
sample = all_types[:10]
suffix = f" … and {len(all_types)-10} more" if len(all_types) > 10 else ""
raise PortTypeNotFoundError(
    f"Port type '{type_name}' is not registered. "
    f"Known types (sample): {sample}{suffix}"
)
```

--------------------------------------------------------------------
FILE:        app/core/nodes/catalogue.py
FUNCTION:    TypeCatalogue (class-level)
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
The docstring states: "Populated by AutoDiscovery for every PortDataType
subclass found during scanning. Used by the pipeline builder to resolve
string type references."

WHAT IT ACTUALLY DOES:
`TypeCatalogue` is instantiated as `self.type_catalogue = TypeCatalogue()`
inside `NodeRegistry.__init__`. There is no mechanism to detect or handle
the case where a node is registered in the `NodeRegistry` after the
`TypeCatalogue` has been built — the catalogue is populated incrementally
during `AutoDiscovery.run()`, but if a caller registers a node directly via
`registry.register(node_type, cls, meta)` without also calling
`catalogue.register(port_data_type)` for the node's port types, those port
types will be absent from the catalogue. The checkpoint focus area explicitly
calls this out: "Does `catalogue.py` stay consistent if a node is registered
after catalogue is built?"

The catalogue has no cross-check with the registry — it is purely additive.
A node registered via `registry.register()` directly (bypassing
`AutoDiscovery._register_node`) will have its port types absent from the
catalogue, causing `resolve()` to raise `PortTypeNotFoundError` at pipeline
build time.

EVIDENCE:
`NodeRegistry.register()` in registry.py:
```python
def register(self, node_type, node_class, metadata):
    with self._lock:
        self._classes[node_type] = node_class
        self._metadata[node_type] = metadata
        # ← no catalogue.register() call for port types
```

REPRODUCTION SCENARIO:
A test or plugin installer calls `registry.register("my_node", MyNode, meta)`
directly. `MyNode` uses `CustomAudioType` as a port type. Later, the pipeline
builder calls `catalogue.resolve("...CustomAudioType")` → `PortTypeNotFoundError`.

IMPACT:
Runtime crash at pipeline build time; confusing error with no indication that
the type was never catalogued.

FIX DIRECTION:
Either: (a) `NodeRegistry.register()` should also register the node's port
types into `type_catalogue`, or (b) document clearly that `register()` must
only be called via `AutoDiscovery._register_node()`.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | UNSAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `NodeRegistry.register()` bypasses `TypeCatalogue` — port types for directly-registered nodes are absent from the catalogue, causing `PortTypeNotFoundError` at pipeline build time with no actionable diagnosis. |
