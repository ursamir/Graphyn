# Functional Review — app/core/nodes/registry.py

**Group:** 3 — Registry & Discovery  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/nodes/registry.py
FUNCTION:    NodeRegistry.list_nodes
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return metadata for all registered nodes, optionally filtered by category.

WHAT IT ACTUALLY DOES:
Acquires the lock, snapshots `_metadata.values()` into a list, then releases
the lock before applying the category filter (lines ~100–106).

THE BUG / RISK:
The category filter loop runs outside the lock. This is safe for the snapshot
itself, but the returned list contains live `NodeMetadata` objects. If a
caller mutates a returned `NodeMetadata` (e.g. sets `meta.input_ports = …`),
that mutation is visible to all subsequent callers because the registry holds
the same object reference. There is no copy-on-return protection.

EVIDENCE:
```python
with self._lock:
    all_meta = list(self._metadata.values())   # snapshot of references, not copies
if category is None:
    return all_meta                             # live objects returned
return [m for m in all_meta if m.category == category]
```

REPRODUCTION SCENARIO:
```python
metas = registry.list_nodes()
metas[0].display_name = "HACKED"   # mutates the live registry entry
registry.get_metadata("some_type").display_name  # → "HACKED"
```

IMPACT:
Silent wrong result — downstream callers (API /nodes endpoint, MCP discovery
handler) see corrupted metadata without any error.

FIX DIRECTION:
Return deep copies, or make `NodeMetadata` frozen (Pydantic `model_config =
ConfigDict(frozen=True)`). Cheapest fix:
```python
return [m.model_copy() for m in all_meta if category is None or m.category == category]
```

--------------------------------------------------------------------
FILE:        app/core/nodes/registry.py
FUNCTION:    NodeRegistry.find_compatible_nodes
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return metadata for nodes whose ports are compatible with port_type.

WHAT IT ACTUALLY DOES:
Iterates `node_class.input_ports.values()` (or output_ports) and calls
`CompatibilityChecker.are_compatible` for each port. If a node has zero
ports in the requested direction, the `any(...)` call returns `False` and
the node is silently excluded.

THE BUG / RISK:
A node with zero input ports (e.g. a source node) will never appear in
`find_compatible_nodes(..., direction="input")` results even if the caller
is looking for "any node that can accept this type". This is arguably
correct behaviour, but the docstring does not document it, so callers may
be surprised. More critically: if `port.data_type` is `None` (optional
port), `CompatibilityChecker.are_compatible(port_type, None)` is called —
the behaviour of that call is not validated here and may raise or silently
return `False`.

EVIDENCE:
```python
ports = node_class.input_ports.values()
if any(
    CompatibilityChecker.are_compatible(port_type, p.data_type)
    for p in ports
):
```
`p.data_type` can be `None` for optional ports (see ports.py).

REPRODUCTION SCENARIO:
Register a node with one optional input port (`data_type=None`). Call
`find_compatible_nodes(AudioSample, "input")`. If `are_compatible` raises
on `None`, the exception propagates uncaught from `find_compatible_nodes`.

IMPACT:
Crash or silent omission of valid nodes from discovery results.

FIX DIRECTION:
Guard against `None` data_type before calling `are_compatible`:
```python
if any(
    p.data_type is not None and
    CompatibilityChecker.are_compatible(port_type, p.data_type)
    for p in ports
):
```

--------------------------------------------------------------------
FILE:        app/core/nodes/registry.py
FUNCTION:    NodeRegistry.get_config_schema
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the JSON Schema for the node's Config Pydantic model.

WHAT IT ACTUALLY DOES:
Calls `node_class.Config.model_json_schema()`. If the node class does not
define an inner `Config` class (or defines one that is not a Pydantic model),
this raises `AttributeError` with no context about which node_type failed.

EVIDENCE:
```python
def get_config_schema(self, node_type: str) -> dict[str, Any]:
    node_class = self.get_class(node_type)
    return node_class.Config.model_json_schema()   # AttributeError if Config absent
```

REPRODUCTION SCENARIO:
A plugin node that inherits `Config` from a non-Pydantic base, or a node
that accidentally shadows `Config` with a plain dict. Calling
`get_config_schema("that_node")` raises `AttributeError: type object 'X'
has no attribute 'Config'` with no indication of which node_type caused it.

IMPACT:
Confusing traceback surfaced to API callers; no actionable error message.

FIX DIRECTION:
```python
cfg = getattr(node_class, "Config", None)
if cfg is None or not hasattr(cfg, "model_json_schema"):
    raise NodeNotFoundError(
        f"Node '{node_type}' has no Pydantic Config class."
    )
return cfg.model_json_schema()
```

--------------------------------------------------------------------
FILE:        app/core/nodes/registry.py
FUNCTION:    NodeRegistry.get_port_schema
CATEGORY:    Error Handling
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the port schema dict (inputs + outputs) for the node.

WHAT IT ACTUALLY DOES:
Calls `node_class.port_schemas()`. If `port_schemas` is not defined on the
class (e.g. a plugin node that doesn't inherit from the correct base), this
raises `AttributeError` with no context.

EVIDENCE:
```python
def get_port_schema(self, node_type: str) -> dict[str, Any]:
    node_class = self.get_class(node_type)
    return node_class.port_schemas()   # AttributeError if method absent
```

REPRODUCTION SCENARIO:
A plugin node that accidentally overrides `port_schemas` with a non-callable
attribute. Calling `get_port_schema("that_node")` raises `AttributeError`.

IMPACT:
Confusing traceback; no actionable error message.

FIX DIRECTION:
Wrap in a try/except and raise `NodeNotFoundError` with context, or assert
the method exists after `get_class`.

--------------------------------------------------------------------
FILE:        app/core/nodes/registry.py
FUNCTION:    NodeRegistry.parse_metadata_list
CATEGORY:    Error Handling
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Reconstruct a NodeMetadata list from a JSON string produced by `to_json()`.

WHAT IT ACTUALLY DOES:
Raises `ValueError` for invalid JSON and `pydantic.ValidationError` for
schema mismatches. However, if `json.loads` returns a non-list (e.g. a JSON
object `{}`), the subsequent list comprehension `[NodeMetadata.model_validate(item)
for item in raw]` will iterate over dict keys (strings), and
`NodeMetadata.model_validate("some_key")` will raise a `ValidationError`
with a confusing message rather than a clear "expected a list" error.

EVIDENCE:
```python
raw = json.loads(json_str)   # could be dict, int, str, etc.
return [NodeMetadata.model_validate(item) for item in raw]
```

REPRODUCTION SCENARIO:
`NodeRegistry.parse_metadata_list('{"node_type": "x"}')` — `raw` is a dict,
iteration yields string keys, `model_validate("node_type")` raises a
confusing `ValidationError`.

IMPACT:
Confusing error message; no data loss.

FIX DIRECTION:
```python
if not isinstance(raw, list):
    raise ValueError(f"Expected a JSON array, got {type(raw).__name__}")
```

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
| Top Risk | `list_nodes()` returns live `NodeMetadata` references — caller mutation silently corrupts the registry for all subsequent callers. |
