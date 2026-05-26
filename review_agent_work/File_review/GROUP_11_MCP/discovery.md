# Functional Review — app/mcp/handlers/discovery.py

**Group:** 11 — MCP
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/mcp/handlers/discovery.py
FUNCTION:    _serialize_node_metadata
CATEGORY:    Performance
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Convert a NodeMetadata object to a JSON-serialisable dict with all 10
required fields.

WHAT IT ACTUALLY DOES:
Calls `get_registry()` on every invocation to fetch the registry singleton,
then calls `registry.get_config_schema(meta.node_type)`. When `list_nodes_handler`
returns all nodes (no filter), `_serialize_node_metadata` is called once per
registered node. Each call invokes `get_registry()` — which is a singleton
lookup (cheap) — but also calls `registry.get_config_schema(meta.node_type)`,
which may involve Pydantic schema generation. If the registry has 29 nodes,
this is 29 schema generation calls per `list_nodes` invocation.

THE BUG / RISK:
Performance: if `get_config_schema` is not cached inside the registry, each
call to `list_nodes` with no filter triggers 29 Pydantic schema generations.
Pydantic schema generation is not free — it involves reflection and JSON
serialisation. Under load (many `list_nodes` calls), this can be slow.

This is a performance correctness issue: the function claims to be a simple
serialiser but has hidden O(n) schema generation cost per call.

EVIDENCE:
Lines ~113–124:
```python
def _serialize_node_metadata(meta) -> dict[str, Any]:
    registry = get_registry()
    return {
        ...
        "config_schema": registry.get_config_schema(meta.node_type),
        ...
    }
```
Called once per node in the list path.

REPRODUCTION SCENARIO:
Call `list_nodes` with no arguments when 29 nodes are registered. This
triggers 29 `get_config_schema` calls. If schema generation is not cached,
this is 29 Pydantic model introspections.

IMPACT:
Slow `list_nodes` responses under load. Not a correctness bug — results
are always correct.

FIX DIRECTION:
Cache schema results in the registry (if not already done). Or cache in
`_serialize_node_metadata` using a module-level dict:
```python
_SCHEMA_CACHE: dict[str, dict] = {}
def _serialize_node_metadata(meta) -> dict[str, Any]:
    registry = get_registry()
    if meta.node_type not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[meta.node_type] = registry.get_config_schema(meta.node_type)
    return {..., "config_schema": _SCHEMA_CACHE[meta.node_type], ...}
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/handlers/discovery.py
FUNCTION:    list_nodes_handler
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Filter by `output_type + direction`; return compatible nodes.

WHAT IT ACTUALLY DOES:
When `output_type` is provided but `direction` is `None` (not provided),
returns `{"error_type": "invalid_direction", "message": "direction must be
'input' or 'output', got None."}`. This is correct.

However, the check `if output_type is not None` fires even when
`output_type` is an empty string `""`. An empty string is falsy in Python
but `is not None` is True. So `output_type = ""` triggers the direction
check, then `registry.type_catalogue.resolve("")` is called, which will
likely raise or return an error. The error is caught and returns
`{"error_type": "unknown_port_type", ...}` — which is technically correct
but the root cause is an empty string input, not an unknown type.

THE BUG / RISK:
Edge case: `output_type = ""` triggers the port-type resolution path
instead of falling through to the category/capability filter path. The
result is a misleading `unknown_port_type` error for what is effectively
a missing argument.

EVIDENCE:
Line ~183: `if output_type is not None:`
An empty string `""` passes this check.

REPRODUCTION SCENARIO:
Call `list_nodes` with `{"output_type": ""}`. Response: `{"error_type":
"unknown_port_type", "message": "Port data type '' is not registered."}`.

IMPACT:
Misleading error message. No functional impact — the caller gets an error
either way.

FIX DIRECTION:
```python
if output_type:  # truthy check instead of `is not None`
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/handlers/discovery.py
FUNCTION:    list_nodes_handler
CATEGORY:    Silent Failure Risk
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return all nodes when no arguments are provided.

WHAT IT ACTUALLY DOES:
When `registry.list_nodes()` raises an exception (e.g. registry not
initialized, internal error), the exception propagates out of
`list_nodes_handler` uncaught. The server's generic handler in `server.py`
catches it and returns `{"error": True, "error_type": "...", "message": "..."}`.
This is technically handled, but the handler itself has no local error
handling for registry failures.

THE BUG / RISK:
Low severity: the server's outer catch handles it. But the error type
will be the raw exception class name (e.g. `"RuntimeError"`) rather than
a documented MCP error type. This is inconsistent with the error contract.

EVIDENCE:
The handler calls `registry.list_nodes(category=category)` with no
try/except around it.

REPRODUCTION SCENARIO:
Registry raises `RuntimeError("Registry not initialized")`. Response:
`{"error": True, "error_type": "RuntimeError", "message": "Registry not initialized"}`.

IMPACT:
Undocumented error type in response. Low impact.

FIX DIRECTION:
Wrap registry calls in try/except and return a documented error type.
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | LOW |
| Silent Failures | 0 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `_serialize_node_metadata` calls `get_config_schema` once per node — potential O(n) Pydantic schema generation on every `list_nodes` call with no filter. |
