# Functional Review — app/core/ir/models.py

**Group:** 1 — IR Core  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/ir/models.py
FUNCTION:    IRNode._deep_copy_config
CATEGORY:    Silent Failure
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Deep-copy config on construction to prevent external mutation (P-23 fix), wrapping the result in MappingProxyType.

WHAT IT ACTUALLY DOES:
Wraps the dict in `MappingProxyType(copy.deepcopy(v))`, which makes the top-level mapping read-only. However, any nested dicts or lists inside the config remain plain mutable Python objects. The `MappingProxyType` only prevents assignment at the top level (`node.config["key"] = x` raises `TypeError`), but `node.config["nested_dict"]["key"] = x` succeeds silently.

THE BUG / RISK:
The docstring and the P-23 fix comment claim full mutation protection. Callers who rely on this guarantee and pass nested config dicts will find their data mutated by downstream code that modifies nested structures. This is a silent data-corruption risk.

EVIDENCE:
```python
# validator at ~line 97
if isinstance(v, dict):
    return MappingProxyType(copy.deepcopy(v))
```
`MappingProxyType` is shallow — only the top-level keys are protected.

REPRODUCTION SCENARIO:
```python
raw = {"nested": {"lr": 0.01}}
node = IRNode(id="n1", node_type="T", config=raw)
node.config["nested"]["lr"] = 999   # succeeds silently
```

IMPACT:
Silent wrong result — downstream nodes receive mutated config values without any error.

FIX DIRECTION:
Use a recursive `MappingProxyType` wrapper, or document clearly that only the top-level is protected and callers must deep-copy nested dicts themselves. A minimal recursive helper:
```python
def _deep_freeze(v):
    if isinstance(v, dict):
        return MappingProxyType({k: _deep_freeze(vv) for k, vv in v.items()})
    if isinstance(v, list):
        return tuple(_deep_freeze(i) for i in v)
    return v
```

--------------------------------------------------------------------
FILE:        app/core/ir/models.py
FUNCTION:    IRNode._deep_copy_config
CATEGORY:    Type Safety
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Accepts `config: Any` and wraps dicts in MappingProxyType.

WHAT IT ACTUALLY DOES:
The `mode="before"` validator only wraps `dict` instances. If `config` is a `list`, `int`, `str`, or any other non-dict type, it is returned as-is without any protection or type error. The field type annotation is `Any`, so Pydantic will not reject it.

THE BUG / RISK:
A caller passing `config=[1, 2, 3]` or `config="bad"` will produce an `IRNode` with a non-dict config. Downstream code that does `node.config.get(...)` or `node.config.items()` will raise `AttributeError` at runtime, far from the construction site.

EVIDENCE:
```python
# ~line 93-97
@field_validator("config", mode="before")
@classmethod
def _deep_copy_config(cls, v: Any) -> Any:
    if isinstance(v, dict):
        return MappingProxyType(copy.deepcopy(v))
    return v   # ← non-dict passes through unchecked
```

REPRODUCTION SCENARIO:
```python
node = IRNode(id="n1", node_type="T", config=[1, 2, 3])
node.config.get("key")  # AttributeError: 'list' object has no attribute 'get'
```

IMPACT:
Crash deep in execution layer with a confusing traceback; no validation error at construction time.

FIX DIRECTION:
Add a type check and raise `ValueError` for non-dict, non-None config values:
```python
if v is not None and not isinstance(v, dict):
    raise ValueError(f"IRNode.config must be a dict, got {type(v).__name__}")
```

--------------------------------------------------------------------
FILE:        app/core/ir/models.py
FUNCTION:    IRMetadata._name_non_empty
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validates that `name` is non-empty and strips whitespace (P-24 fix).

WHAT IT ACTUALLY DOES:
Strips and stores the normalised value. However, `IRMetadata` is `frozen=True`, meaning the returned stripped value is stored correctly. The issue is that a name of all-whitespace (e.g. `"   "`) is correctly rejected, but a name of a single space after stripping becomes `""` and is also correctly rejected. This is actually correct behavior.

THE BUG / RISK:
No bug here — this validator is correct. Noted for completeness.

EVIDENCE:
Lines ~67-70: validator strips and returns, frozen model stores the stripped value.

REPRODUCTION SCENARIO:
N/A — behavior is correct.

IMPACT:
None.

FIX DIRECTION:
No fix needed.

--------------------------------------------------------------------
FILE:        app/core/ir/models.py
FUNCTION:    GraphIR._validate_graph (model_validator)
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validates node ID uniqueness and edge reference integrity (Req 1.4.3, 1.9.1, 1.9.2).

WHAT IT ACTUALLY DOES:
Validates that `src_id` and `dst_id` reference known node IDs. Does NOT validate that `src_port` and `dst_port` are non-empty strings. An edge with `src_port=""` or `dst_port=""` passes validation silently.

THE BUG / RISK:
An IREdge with blank port names will pass all validation and be stored in the GraphIR. Downstream code (planner, executor) that uses port names as dict keys will either silently use an empty-string key or fail with a confusing error.

EVIDENCE:
```python
# model_validator ~lines 175-200
# Only checks src_id/dst_id membership in seen_ids.
# No check on src_port, dst_port, or condition string validity.
```

REPRODUCTION SCENARIO:
```python
graph = GraphIR(
    schema_version="1.1",
    metadata=IRMetadata(name="g", seed=0),
    nodes=[IRNode(id="a", node_type="T"), IRNode(id="b", node_type="T")],
    edges=[IREdge(src_id="a", src_port="", dst_id="b", dst_port="")]
)
# Passes validation — empty port names stored silently
```

IMPACT:
Silent wrong result or confusing crash in the planner/executor when port lookup fails.

FIX DIRECTION:
Add port name non-empty validation to `IREdge` field validators or to the `GraphIR` model validator:
```python
@field_validator("src_port", "dst_port")
@classmethod
def _port_non_empty(cls, v: str) -> str:
    if not v.strip():
        raise ValueError("Port name must be a non-empty string")
    return v
```

--------------------------------------------------------------------
FILE:        app/core/ir/models.py
FUNCTION:    GraphIR._validate_graph (model_validator)
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validates graph structural integrity.

WHAT IT ACTUALLY DOES:
Does not validate self-loops (an edge where `src_id == dst_id`). A node connected to itself passes all validation.

THE BUG / RISK:
A self-loop in the IR will pass validation and be stored. The planner's topological sort will detect the cycle and raise, but the error will be attributed to the planner rather than the IR, making debugging harder. The IR model should be the single source of truth for structural validity.

EVIDENCE:
The model_validator only checks ID uniqueness and edge reference integrity — no self-loop check.

REPRODUCTION SCENARIO:
```python
IREdge(src_id="a", src_port="out", dst_id="a", dst_port="in")
# Passes GraphIR validation
```

IMPACT:
Confusing error surfaced at planner time rather than at load time.

FIX DIRECTION:
Add to the model_validator:
```python
for edge in self.edges:
    if edge.src_id == edge.dst_id:
        raise ValueError(f"Self-loop detected on node '{edge.src_id}'")
```

--------------------------------------------------------------------
FILE:        app/core/ir/models.py
FUNCTION:    IRMetadata
CATEGORY:    Type Safety
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Stores graph-level metadata including `tags: list[str]`.

WHAT IT ACTUALLY DOES:
`tags` defaults to `[]` (a mutable list). Because `IRMetadata` is `frozen=True`, the list reference itself cannot be replaced, but the list contents can be mutated in place: `metadata.tags.append("x")` succeeds silently.

THE BUG / RISK:
The `frozen=True` contract implies immutability, but the `tags` list is mutable. Two `IRMetadata` instances that share the same default list object (Pydantic creates a new list per instance, so this is not a shared-default bug) can still have their tags mutated by callers.

EVIDENCE:
```python
# ~line 62
tags: list[str] = []
```
`frozen=True` prevents `metadata.tags = [...]` but not `metadata.tags.append(...)`.

REPRODUCTION SCENARIO:
```python
m = IRMetadata(name="g", seed=0)
m.tags.append("injected")  # succeeds silently
```

IMPACT:
Silent state mutation; callers relying on immutability of tags will see unexpected values.

FIX DIRECTION:
Change to `tags: tuple[str, ...] = ()` for true immutability, or use `field(default_factory=lambda: [])` with a note that mutation is allowed.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 3 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | N/A |
| Test Hostile | NO |
| Top Risk | `IRNode._deep_copy_config` wraps config in a shallow `MappingProxyType` — nested dicts remain mutable, silently violating the P-23 immutability guarantee. |
