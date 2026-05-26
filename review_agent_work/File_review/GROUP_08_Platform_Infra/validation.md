# Functional Review — app/core/validation.py

**Group:** 8 — Platform Infra  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/validation.py
FUNCTION:    validate_pipeline
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate a pipeline config dict against the node registry; raises ValueError
if the config is structurally invalid, references unknown node types, or
contains invalid node configs.

WHAT IT ACTUALLY DOES:
Validates `pipeline.seed` with:
```python
if not (isinstance(seed, int) and not isinstance(seed, bool)):
    raise ValueError("pipeline.seed must be an integer")
```
But `seed` is obtained via `pipeline.get("seed")` with no default, so if
`"seed"` is absent from the config, `seed` is `None`. `isinstance(None, int)`
is `False`, so the condition `not (False and ...)` is `True` and it raises
`ValueError: pipeline.seed must be an integer` — even though seed is simply
absent, which should be a valid (optional) field.

THE BUG / RISK:
Any pipeline config that omits `pipeline.seed` is rejected with a confusing
error message. This is a contract mismatch: the docstring says nothing about
seed being required, and the IR schema treats it as optional.

EVIDENCE:
```python
# Lines ~175-177
seed = pipeline.get("seed")
if not (isinstance(seed, int) and not isinstance(seed, bool)):
    raise ValueError("pipeline.seed must be an integer")
```
`pipeline.get("seed")` returns `None` when absent → raises.

REPRODUCTION SCENARIO:
```python
config = {"pipeline": {"nodes": [{"type": "some_node"}]}}
validate_pipeline(config, registry)  # raises ValueError: pipeline.seed must be an integer
```

IMPACT:
All pipeline configs without an explicit `seed` field are rejected. This
likely breaks the CLI and API for any graph that doesn't set a seed.

FIX DIRECTION:
Make seed optional:
```python
seed = pipeline.get("seed")
if seed is not None and not (isinstance(seed, int) and not isinstance(seed, bool)):
    raise ValueError("pipeline.seed must be an integer")
```

--------------------------------------------------------------------
FILE:        app/core/validation.py
FUNCTION:    _validate_connections
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate port-to-port type compatibility for linear pipelines.

WHAT IT ACTUALLY DOES:
The outer `except Exception: pass` on lines ~130-131 silently swallows all
non-`ValueError` exceptions, including `AttributeError` (if `output_ports`
or `input_ports` is missing on a class), `TypeError`, and any unexpected
errors from `CompatibilityChecker.are_compatible()`.

THE BUG / RISK:
A bug in `CompatibilityChecker` or a malformed node class (missing
`output_ports`) causes `_validate_connections` to silently return without
validating anything. The pipeline proceeds with potentially incompatible
connections.

EVIDENCE:
```python
# Lines ~128-131
    except ValueError:
        raise
    except Exception:
        pass
```

REPRODUCTION SCENARIO:
If `CompatibilityChecker.are_compatible()` raises `AttributeError` due to a
bug, the entire compatibility check is silently skipped.

IMPACT:
Silent wrong result — incompatible pipelines pass validation and fail at
runtime with a confusing error deep in `process()`.

FIX DIRECTION:
Log the exception at WARNING level instead of silently passing:
```python
    except Exception as exc:
        logger.warning("_validate_connections skipped due to unexpected error: %s", exc)
```

--------------------------------------------------------------------
FILE:        app/core/validation.py
FUNCTION:    validate_pipeline
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate a pipeline config dict; raises ValueError for unknown node types.

WHAT IT ACTUALLY DOES:
When building the `available` list for the error message on unknown node type,
it calls `registry.list_nodes()` which may itself raise (e.g. if the registry
is not yet initialized). This exception is not caught, so the caller gets a
confusing registry error instead of a clean "unknown node type" ValueError.

EVIDENCE:
```python
# Lines ~215-220
        except Exception:
            available = sorted(m.node_type for m in registry.list_nodes())
            raise ValueError(
                f"Unknown node type '{node_type}'. "
                f"Available types: {', '.join(available)}"
            )
```
`registry.list_nodes()` is called inside the `except Exception` handler but
is not itself guarded.

REPRODUCTION SCENARIO:
Pass a registry whose `list_nodes()` raises `RuntimeError("not initialized")`.
The caller gets `RuntimeError` instead of `ValueError`.

IMPACT:
Confusing error message; callers expecting `ValueError` get a different
exception type.

FIX DIRECTION:
```python
        except Exception:
            try:
                available = sorted(m.node_type for m in registry.list_nodes())
            except Exception:
                available = ["<registry unavailable>"]
            raise ValueError(...)
```

--------------------------------------------------------------------
FILE:        app/core/validation.py
FUNCTION:    _validate_dag_edges
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate edges in a DAG-format pipeline config; raises ValueError for unknown
node IDs or ports.

WHAT IT ACTUALLY DOES:
The `id_to_type` mapping is built only from nodes that have an `"id"` key.
Nodes without `"id"` are silently skipped. If an edge references a node ID
that belongs to a node missing its `"id"` key, the edge check raises
`ValueError: Edge references unknown source node id '...'` — which is
technically correct but the root cause (missing `"id"` on the node) is not
surfaced.

EVIDENCE:
```python
# Lines ~47-49
    for node in nodes:
        if "id" in node:
            id_to_type[node["id"]] = node["type"]
```
Nodes without `"id"` are silently excluded from the map.

REPRODUCTION SCENARIO:
```python
nodes = [{"type": "foo"}, {"id": "b", "type": "bar"}]  # first node missing "id"
edges = [{"from_node": "a", "to_node": "b"}]
_validate_dag_edges(nodes, edges, registry)
# raises: "Edge references unknown source node id 'a'" — misleading
```

IMPACT:
Misleading error message. Low severity since validation still fails, just
with a confusing message.

FIX DIRECTION:
Add a pre-pass that raises `ValueError` for any node missing `"id"` in DAG
format, before building the map.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `validate_pipeline()` rejects all configs that omit `pipeline.seed`, breaking any pipeline that doesn't explicitly set a seed value. |
