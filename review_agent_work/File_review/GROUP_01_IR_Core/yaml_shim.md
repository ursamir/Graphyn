# Functional Review — app/core/ir/yaml_shim.py

**Group:** 1 — IR Core  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/ir/yaml_shim.py
FUNCTION:    yaml_config_to_ir
CATEGORY:    Silent Failure
SEVERITY:    CRITICAL
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Convert a raw YAML config dict to a GraphIR object. Supports both legacy linear format and explicit-edge format.

WHAT IT ACTUALLY DOES:
Accesses `n["type"]` directly (line ~55) without a `.get()` or existence check. If a node entry in the YAML is missing the `type` key, this raises a bare `KeyError: 'type'` with no context about which node or file caused the error.

THE BUG / RISK:
A YAML file with a node missing the `type` field causes an unhandled `KeyError` that propagates up the call stack with no useful error message. The caller (e.g. `load_yaml_with_deprecation` or `migrate_yaml_to_ir_file`) has no way to distinguish this from other `KeyError` exceptions.

EVIDENCE:
```python
# ~line 55
node_type = n["type"]   # KeyError if 'type' is absent
```

REPRODUCTION SCENARIO:
```yaml
pipeline:
  name: test
  seed: 0
  nodes:
    - id: n1
      config: {}   # 'type' key missing
```
`yaml_config_to_ir(raw)` → `KeyError: 'type'`

IMPACT:
Crash with an unhelpful error message; user cannot tell which node is malformed or what field is missing.

FIX DIRECTION:
```python
node_type = n.get("type")
if not node_type:
    raise ValueError(
        f"Node at index {i} is missing required 'type' field: {n!r}"
    )
```

--------------------------------------------------------------------
FILE:        app/core/ir/yaml_shim.py
FUNCTION:    yaml_config_to_ir
CATEGORY:    Silent Failure
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Convert a raw YAML config dict to a GraphIR. Handles missing `pipeline` key with a default of `{}`.

WHAT IT ACTUALLY DOES:
Uses `raw.get("pipeline", {})` — if the YAML file has no `pipeline` key (e.g. an empty file, or a file with a different top-level structure), `pipeline` becomes `{}`. Then `name` defaults to `"pipeline"`, `seed` defaults to `0`, and `raw_nodes` becomes `[]`. This produces a valid but empty GraphIR with no nodes and no edges — silently, with no warning or error.

THE BUG / RISK:
A completely wrong YAML file (e.g. a Kubernetes manifest, a Docker Compose file, or an empty file) will be silently converted to an empty pipeline named "pipeline" with seed 0. The caller receives a valid `GraphIR` object and has no indication that the input was malformed.

EVIDENCE:
```python
# ~lines 48-51
pipeline = raw.get("pipeline", {})
seed = pipeline.get("seed", 0)
name = pipeline.get("name", "pipeline")
raw_nodes = pipeline.get("nodes", [])
```
All fields have silent defaults; no validation that `pipeline` key exists.

REPRODUCTION SCENARIO:
```python
yaml_config_to_ir({"apiVersion": "v1", "kind": "Pod"})
# Returns GraphIR(nodes=[], edges=[], metadata=IRMetadata(name="pipeline", seed=0))
# No error, no warning
```

IMPACT:
Silent wrong result — a completely wrong input file produces a valid empty pipeline. Downstream execution will run an empty graph successfully, masking the configuration error.

FIX DIRECTION:
Validate that the `pipeline` key exists and is a dict:
```python
if "pipeline" not in raw or not isinstance(raw.get("pipeline"), dict):
    raise ValueError(
        "YAML config must have a top-level 'pipeline' key with a dict value. "
        f"Got top-level keys: {list(raw.keys()) if isinstance(raw, dict) else type(raw).__name__}"
    )
```

--------------------------------------------------------------------
FILE:        app/core/ir/yaml_shim.py
FUNCTION:    yaml_config_to_ir
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Build IREdge list from explicit-edge format. Supports list format `{"from": [src_id, src_port], "to": [dst_id, dst_port]}`.

WHAT IT ACTUALLY DOES:
Accesses `e["from"][0]`, `e["from"][1]`, `e["to"][0]`, `e["to"][1]` without checking that these lists have at least 2 elements. If a YAML edge has `from: [src_id]` (only one element), this raises `IndexError: list index out of range` with no context.

THE BUG / RISK:
A malformed edge in the YAML (missing port in the list) causes an `IndexError` with no useful error message identifying which edge is malformed.

EVIDENCE:
```python
# ~lines 65-66
src_id, src_port = e["from"][0], e["from"][1]
dst_id, dst_port = e["to"][0], e["to"][1]
```
No length check on `e["from"]` or `e["to"]`.

REPRODUCTION SCENARIO:
```yaml
edges:
  - from: [node_a]   # missing port
    to: [node_b, input]
```
`yaml_config_to_ir(raw)` → `IndexError: list index out of range`

IMPACT:
Crash with unhelpful error; user cannot identify which edge is malformed.

FIX DIRECTION:
```python
from_list = e.get("from", [])
to_list = e.get("to", [])
if len(from_list) != 2 or len(to_list) != 2:
    raise ValueError(
        f"Edge 'from'/'to' lists must each have exactly 2 elements "
        f"[node_id, port_name], got from={from_list!r}, to={to_list!r}"
    )
src_id, src_port = from_list
dst_id, dst_port = to_list
```

--------------------------------------------------------------------
FILE:        app/core/ir/yaml_shim.py
FUNCTION:    yaml_config_to_ir
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Build IRNode list from raw YAML nodes. Assigns auto-generated IDs when `id` is absent (Req 4.1.5).

WHAT IT ACTUALLY DOES:
Auto-generates IDs as `f"{node_type}_{i}"`. If two nodes have the same `node_type` and neither has an explicit `id`, they will get IDs like `"AudioClassifier_0"` and `"AudioClassifier_1"` — which are unique. However, if one node has an explicit `id` of `"AudioClassifier_1"` and another node of the same type at index 1 has no `id`, both will get the ID `"AudioClassifier_1"`, causing a duplicate ID error in `GraphIR._validate_graph`.

THE BUG / RISK:
Collision between explicit IDs and auto-generated IDs produces a `pydantic.ValidationError` with a message about duplicate node IDs. The error is correct but the root cause (auto-ID collision with explicit ID) is not surfaced.

EVIDENCE:
```python
# ~line 56
node_id = n.get("id") or f"{node_type}_{i}"
```
No check that the auto-generated ID does not collide with any explicit ID in the same graph.

REPRODUCTION SCENARIO:
```yaml
nodes:
  - type: AudioClassifier
    id: AudioClassifier_1   # explicit
  - type: AudioClassifier   # no id → auto-generates "AudioClassifier_1"
```
`GraphIR._validate_graph` raises `ValueError: Duplicate node id 'AudioClassifier_1'`

IMPACT:
Confusing error — user sees "duplicate node id" but does not know it was caused by auto-ID generation.

FIX DIRECTION:
After building the node list, check for collisions and raise a descriptive error, or use a counter that skips already-used IDs.

--------------------------------------------------------------------
FILE:        app/core/ir/yaml_shim.py
FUNCTION:    yaml_config_to_ir
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Handle legacy linear format: auto-chain output → input for consecutive nodes.

WHAT IT ACTUALLY DOES:
When `raw_edges` is falsy (None, empty list, or absent), auto-chains all consecutive nodes. However, `raw_edges` is checked with `if raw_edges:` — an empty list `[]` is falsy, so a YAML file that explicitly provides `edges: []` (meaning "no edges, this is a source-only graph") will be treated as the legacy linear format and have edges auto-generated. This silently overrides the user's explicit intent.

THE BUG / RISK:
A user who explicitly writes `edges: []` to indicate a single-node or disconnected graph will have edges auto-generated between all nodes, silently changing the graph topology.

EVIDENCE:
```python
# ~line 61
raw_edges = pipeline.get("edges")
if raw_edges:
    # explicit edges
else:
    # auto-chain — also triggered when edges: [] is explicitly set
```

REPRODUCTION SCENARIO:
```yaml
pipeline:
  nodes:
    - type: A
      id: a
    - type: B
      id: b
  edges: []   # user intends: no edges
```
Result: edges `[IREdge(src_id="a", ..., dst_id="b", ...)]` are auto-generated.

IMPACT:
Silent wrong result — graph topology differs from user intent.

FIX DIRECTION:
Distinguish `None` (key absent) from `[]` (key present but empty):
```python
raw_edges = pipeline.get("edges")  # None if absent
if raw_edges is None:
    # legacy auto-chain
elif raw_edges:
    # explicit edges
else:
    ir_edges = []  # explicit empty — no edges
```

--------------------------------------------------------------------
FILE:        app/core/ir/yaml_shim.py
FUNCTION:    load_yaml_with_deprecation
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Read a YAML file, convert to GraphIR, and emit a DeprecationWarning.

WHAT IT ACTUALLY DOES:
Opens the file with `open(path, "r", encoding="utf-8")` without any existence check. If the file does not exist, raises `FileNotFoundError`. If the file is valid YAML but `yaml.safe_load` returns `None` (empty file), `raw` is `None`. Then `yaml_config_to_ir(None)` is called, which calls `None.get("pipeline", {})` → `AttributeError: 'NoneType' object has no attribute 'get'`.

THE BUG / RISK:
An empty YAML file causes an `AttributeError` instead of a clear error message about the file being empty or invalid.

EVIDENCE:
```python
# ~lines 103-107
with open(path, "r", encoding="utf-8") as f:
    raw = yaml.safe_load(f)
# raw is None for empty file
return yaml_config_to_ir(raw)  # AttributeError
```

REPRODUCTION SCENARIO:
```python
# Create empty file
open("empty.yaml", "w").close()
load_yaml_with_deprecation("empty.yaml")
# AttributeError: 'NoneType' object has no attribute 'get'
```

IMPACT:
Crash with a confusing `AttributeError` instead of a clear "empty or invalid YAML file" message.

FIX DIRECTION:
```python
raw = yaml.safe_load(f)
if not isinstance(raw, dict):
    raise ValueError(
        f"YAML file '{path}' did not produce a dict. "
        f"Got: {type(raw).__name__}. Is the file empty?"
    )
```

--------------------------------------------------------------------
FILE:        app/core/ir/yaml_shim.py
FUNCTION:    yaml_config_to_ir
CATEGORY:    Testability
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Pure conversion function — no I/O, no warnings.

WHAT IT ACTUALLY DOES:
The function is indeed pure (no I/O). However, it has a hidden dependency on `CURRENT_IR_VERSION` from `app.core.ir.loader` — the output `GraphIR.schema_version` is always set to `CURRENT_IR_VERSION`. This means tests that check the output schema_version are implicitly coupled to the loader module's constant. If `CURRENT_IR_VERSION` changes, all tests that assert on the output schema_version will break without any change to `yaml_shim.py`.

EVIDENCE:
```python
# ~line 88
schema_version=CURRENT_IR_VERSION,
```

REPRODUCTION SCENARIO:
Bump `CURRENT_IR_VERSION` from `"1.1"` to `"1.2"` — all `yaml_config_to_ir` tests asserting `schema_version == "1.1"` fail.

IMPACT:
Test fragility; not a runtime bug.

FIX DIRECTION:
This is acceptable coupling — the shim should always produce the current version. Document this dependency explicitly in the docstring.

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
| Test Hostile | NO |
| Top Risk | `yaml_config_to_ir` silently converts any non-`pipeline`-keyed YAML dict (including wrong files) into a valid empty GraphIR with no error or warning, masking configuration errors entirely. |
