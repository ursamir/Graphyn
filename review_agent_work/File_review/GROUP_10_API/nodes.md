# Functional Review — app/api/routers/nodes.py

**Group:** 10 — API  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/api/routers/nodes.py
FUNCTION:    list_nodes
CATEGORY:    Performance
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return metadata for all registered nodes, optionally filtered by category.

WHAT IT ACTUALLY DOES:
`registry.list_nodes(category=category)` returns a list of metadata objects.
Then `_node_response(m.node_type, registry)` is called for EACH node, and
inside `_node_response`, `registry.get_config_schema(node_type)` is called.
If `get_config_schema` triggers Pydantic schema generation (which can be
expensive for complex models), this is O(n) schema generations per list
request. For a registry with 29 nodes, this is 29 schema generations on
every `GET /nodes` call.

THE BUG / RISK:
Schema generation is not cached at the registry level (or if it is, this
cannot be verified from this file). If schema generation is expensive and
uncached, `GET /nodes` is significantly slower than necessary. Under load,
this can cause high CPU usage.

EVIDENCE:
`nodes.py` lines ~55–57: `return [_node_response(m.node_type, registry) for m in metas]`
`nodes.py` lines ~28–45: `_node_response` calls `registry.get_config_schema(node_type)`.

REPRODUCTION SCENARIO:
`GET /nodes` with 29 registered nodes → 29 calls to `get_config_schema`.
Under 100 concurrent requests, this is 2,900 schema generation calls/second.

IMPACT:
High CPU usage under load. Latency on `GET /nodes` grows with registry size.

FIX DIRECTION:
Cache schema generation results in the registry (if not already done). Or
make `GET /nodes` return lightweight metadata without config schemas, and
require clients to call `GET /nodes/{node_type}/config-schema` for the schema.

--------------------------------------------------------------------
FILE:        app/api/routers/nodes.py
FUNCTION:    find_compatible_nodes
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return nodes whose ports are compatible with the given port type.

WHAT IT ACTUALLY DOES:
`registry.type_catalogue.resolve(output_type)` is called inside a bare
`except Exception` block that raises HTTP 400 "Unknown port type". However,
`registry.find_compatible_nodes(resolved, direction=direction)` is called
OUTSIDE any try/except. If `find_compatible_nodes` raises (e.g. due to an
internal registry inconsistency or a type comparison error), the exception
propagates as an unhandled 500.

EVIDENCE:
`nodes.py` lines ~68–82:
```python
try:
    resolved = registry.type_catalogue.resolve(output_type)
except Exception:
    raise HTTPException(status_code=400, ...)
nodes = registry.find_compatible_nodes(resolved, direction=direction)  # unguarded
```

REPRODUCTION SCENARIO:
If `find_compatible_nodes` raises `TypeError` due to a type comparison bug,
the client receives a 500 with a raw traceback.

IMPACT:
Unhandled 500 for internal registry errors. Raw traceback potentially exposed.

FIX DIRECTION:
```python
try:
    nodes = registry.find_compatible_nodes(resolved, direction=direction)
except Exception as exc:
    raise HTTPException(status_code=500, detail=f"Compatibility check failed: {exc}")
```

--------------------------------------------------------------------
FILE:        app/api/routers/nodes.py
FUNCTION:    validate_node_config
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate a config dict against a node's Pydantic Config model. Returns
`{"valid": true, "errors": {}}` on success or `{"valid": false, "errors": {...}}`
on failure.

WHAT IT ACTUALLY DOES:
`node_class.Config.model_validate(payload.config)` — if `node_class` does not
have a `Config` attribute (e.g. a node that uses a different config pattern),
this raises `AttributeError` which propagates as an unhandled 500. The
docstring implies this always works for any registered node type.

EVIDENCE:
`nodes.py` line ~107: `node_class.Config.model_validate(payload.config)`
No check that `node_class.Config` exists.

REPRODUCTION SCENARIO:
Register a node class without a `Config` inner class. `POST /nodes/{node_type}/validate-config`
→ 500 `AttributeError: type object 'MyNode' has no attribute 'Config'`.

IMPACT:
Unhandled 500 for nodes without a Config class. Low probability if all nodes
follow the standard pattern, but a latent risk.

FIX DIRECTION:
```python
config_cls = getattr(node_class, "Config", None)
if config_cls is None:
    return {"valid": True, "errors": {}}  # no config schema = always valid
config_cls.model_validate(payload.config)
```

--------------------------------------------------------------------
FILE:        app/api/routers/nodes.py
FUNCTION:    _node_response
CATEGORY:    Error Handling
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Build the standard node response dict for a given node_type.

WHAT IT ACTUALLY DOES:
`meta.input_ports` and `meta.output_ports` are included directly in the
response. If these are Pydantic model instances or other non-JSON-serializable
objects, FastAPI's JSON serialization will raise `ValueError` / `TypeError`
when building the response. The error propagates as an unhandled 500.

EVIDENCE:
`nodes.py` lines ~30–31: `"input_ports": meta.input_ports, "output_ports": meta.output_ports`
No serialization guard.

REPRODUCTION SCENARIO:
A node's port metadata contains a non-serializable field (e.g. a Python type
object). `GET /nodes/{node_type}` → 500 JSON serialization error.

IMPACT:
Unhandled 500 for nodes with non-serializable port metadata. Low probability
if all nodes follow the standard pattern.

FIX DIRECTION:
Use `mode="json"` serialization if port metadata is a Pydantic model, or
wrap in a try/except with a 500 + meaningful message.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 0 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | GET /nodes triggers O(n) schema generations per request with no caching guard in this layer, causing high CPU under load. |
