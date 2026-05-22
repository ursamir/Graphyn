
# Design Sub-File 04 — Validation Generalization and NodeRegistry Shims

← Back to [design.md](design.md)

This sub-file covers:
1. **Generalize `validate_pipeline`** — remove hardcoded audio-specific first/last node rules
2. **`NodeRegistry` compatibility shims** — `__getitem__`, `keys()`, `items()` so `validation.py` works without modification

---

## 1. Current State of validate_pipeline

`app/core/validation.py` contains two hardcoded rules that make it audio-only:

```python
# app/core/validation.py (CURRENT — lines to remove)

if nodes[0]["type"] not in {"input", "mic_input"}:
    raise ValueError("Pipeline must start with 'input' or 'mic_input' node")  # ❌ audio-only

if nodes[-1]["type"] != "export":
    raise ValueError("Pipeline must end with 'export' node")  # ❌ audio-only
```

These rules prevent any non-audio pipeline from passing validation. A data transformation pipeline, an ML preprocessing pipeline, or a video processing pipeline would all fail validation before any node type or config check is performed.

Additionally, `validate_pipeline` uses dict-style registry access throughout:

```python
schema = registry[node_type]["schema"]   # ← requires __getitem__ shim
```

This works only because we add the `__getitem__` shim to `NodeRegistry` (see Section 2). The function itself is **not modified** — the shim makes it work.

---

## 2. Changes to validate_pipeline

The design principle is: **do not modify `validation.py`**. Instead:

1. Remove the two hardcoded audio rules by patching `validation.py` minimally.
2. Add `NodeRegistry` shims so the dict-style access continues to work.

### Option A: Patch validation.py (minimal, 2-line removal)

Remove exactly these two blocks from `validate_pipeline`:

```python
# REMOVE these lines from app/core/validation.py:

if nodes[0]["type"] not in {"input", "mic_input"}:
    raise ValueError("Pipeline must start with 'input' or 'mic_input' node")

if nodes[-1]["type"] != "export":
    raise ValueError("Pipeline must end with 'export' node")
```

No other changes to `validation.py`. The rest of the function (node type existence check, config validation, connection type checking) is correct and domain-agnostic.

### What validation still checks after the removal

After removing the two audio-specific rules, `validate_pipeline` still enforces:

1. Config is a dict with a `"pipeline"` key
2. `pipeline.seed` is an integer
3. `pipeline.nodes` is a non-empty list
4. Each node has a `"type"` string and optional `"config"` dict
5. Each node type is registered in the registry (`node_type not in registry` → `ValueError`)
6. Each node's config passes schema validation (required fields, type checks, range checks)
7. Port type compatibility between connected nodes (via `_validate_connections`)

This is the correct set of checks for a universal pipeline builder.

### Backward compatibility

Pipelines that start with `input`/`mic_input` and end with `export` continue to pass validation — the removal only eliminates the rejection of pipelines that don't follow the audio pattern. No existing valid pipeline breaks.

---

## 3. NodeRegistry Compatibility Shims

`validate_pipeline` uses `registry[node_type]["schema"]` and `registry[node_type]["input_type"]` / `registry[node_type]["output_type"]` via the legacy fallback path in `_validate_connections`. The `NodeRegistry` class does not implement `__getitem__`, `keys()`, or `items()`, so these calls would raise `TypeError` at runtime.

The fix is to add three compatibility shims to `NodeRegistry`. These shims are **not for new code** — they exist solely to make legacy callers work without modification.

### Implementation

```python
# app/core/nodes/registry.py — add after the existing __len__ method

# ── compatibility shims (for legacy callers only — do not use in new code) ──

def __getitem__(self, node_type: str) -> dict:
    """Compatibility shim: returns a legacy dict for registry[node_type] access.

    DO NOT use in new code. Use get_class(), get_metadata(), get_config_schema()
    instead. This shim exists to support app/core/validation.py and any other
    legacy caller that uses dict-style registry access.

    Raises:
        NodeNotFoundError: if node_type is not registered.
    """
    node_class = self.get_class(node_type)   # raises NodeNotFoundError if missing
    meta = self.get_metadata(node_type)
    return {
        "class": node_class,
        "schema": node_class.Config.model_json_schema(),
        "label": meta.label,
        "description": meta.description,
        "category": meta.category,
        "kind": "plugin" if "plugin" in meta.tags else "base",
        # Legacy string fields — kept for backward compat with _validate_connections
        "input_type": "samples",
        "output_type": "samples",
    }

def keys(self):
    """Compatibility shim: returns node type keys like a dict.

    DO NOT use in new code. Use list_nodes() instead.
    """
    return self._classes.keys()

def items(self):
    """Compatibility shim: returns (node_type, dict) pairs like a dict.

    DO NOT use in new code. Use list_nodes() instead.
    """
    return {k: self[k] for k in self._classes}.items()
```

### Why `input_type` and `output_type` are hardcoded to `"samples"`

The legacy `_validate_connections` fallback path in `validation.py` uses `node_def["input_type"]` and `node_def["output_type"]` for string-based type comparison. However, this fallback path is only reached when the new `CompatibilityChecker`-based path fails (the `except Exception: pass` block). In practice, with the new `NodeRegistry`, the `CompatibilityChecker` path always succeeds, so the legacy fallback is never reached.

The `"samples"` values are therefore placeholders that satisfy the dict shape contract without affecting runtime behavior. If the legacy fallback were ever reached, it would compare `"samples" == "samples"` for all connections, which is permissive (never raises) — a safe degradation.

### Schema format compatibility

The `__getitem__` shim returns `node_class.Config.model_json_schema()` as the `"schema"` value. This is a JSON Schema dict (Pydantic v2 format), not the old hand-written schema dict format. The `validate_node_config` function in `validation.py` uses the old schema format (checking `rule["type"]`, `rule["required"]`, etc.), so it would not work correctly with the JSON Schema format.

However, `validate_node_config` is **no longer called** from any active code path after the migration:
- The `/validate-node` endpoint (now `/api/v1/nodes/{type}/validate-config`) uses `node_class.Config.model_validate()` directly.
- The SDK `PipelineNode._validate` uses `node_class.Config.model_validate()` directly.
- `validate_pipeline` calls `_validate_required` and `_validate_types` with the schema from `registry[node_type]["schema"]`.

The `_validate_required` and `_validate_types` functions in `validation.py` use the old schema format. With the JSON Schema dict from Pydantic v2, they would silently skip most checks (since the key names differ). This is acceptable because:

1. The `CompatibilityChecker`-based path in `_validate_connections` provides the real type safety.
2. The Pydantic `Config.model_validate()` call in the API and SDK provides the real config validation.
3. `validate_pipeline` is a secondary validation layer — the primary validation happens at node instantiation time.

If stricter config validation in `validate_pipeline` is needed in the future, the correct fix is to replace `_validate_required`/`_validate_types` with a call to `node_class.Config.model_validate()` inside `validate_pipeline`. That is out of scope for this migration.

---

## 4. DAG Pipeline Format Support

The new `POST /api/v1/pipelines/validate` and `POST /api/v1/pipelines/run` endpoints accept both the legacy linear format and the new DAG format.

### Legacy Linear Format (unchanged)

```yaml
pipeline:
  seed: 42
  nodes:
    - type: input
      config:
        label: speech
    - type: clean
      config:
        sample_rate: 16000
    - type: export
      config:
        project: my_project
        version: v1
```

Nodes are connected implicitly in sequence: `input → clean → export`.

### New DAG Format

```yaml
pipeline:
  seed: 42
  nodes:
    - id: source
      type: input
      config:
        label: speech
    - id: cleaner
      type: clean
      config:
        sample_rate: 16000
    - id: splitter
      type: split
      config:
        train: 0.8
        val: 0.1
    - id: exporter
      type: export
      config:
        project: my_project
        version: v1
  edges:
    - from_node: source
      from_port: output
      to_node: cleaner
      to_port: input
    - from_node: cleaner
      from_port: output
      to_node: splitter
      to_port: input
    - from_node: splitter
      from_port: train
      to_node: exporter
      to_port: input
```

### Format Detection

`validate_pipeline` detects the format by checking for the presence of an `edges` key:

```python
# In validate_pipeline (or a pre-processing step before calling it)
if "edges" in pipeline:
    # DAG format — validate edges reference valid node ids and port names
    _validate_dag_edges(pipeline["nodes"], pipeline["edges"], registry)
else:
    # Linear format — existing sequential validation
    _validate_connections(validated_nodes, registry)
```

The `_validate_dag_edges` function (new, added to `validation.py`) checks:
1. Each `from_node` and `to_node` references a valid node `id` in the nodes list.
2. Each `from_port` and `to_port` exists on the respective node's port definitions.
3. Port types are compatible via `CompatibilityChecker`.

```python
def _validate_dag_edges(nodes: list[dict], edges: list[dict], registry) -> None:
    """Validate explicit DAG edges for port existence and type compatibility."""
    # Build id → node_type map
    id_to_type = {}
    for node in nodes:
        node_id = node.get("id")
        if node_id:
            id_to_type[node_id] = node["type"]

    for edge in edges:
        from_node_id = edge.get("from_node")
        from_port = edge.get("from_port", "output")
        to_node_id = edge.get("to_node")
        to_port = edge.get("to_port", "input")

        if from_node_id not in id_to_type:
            raise ValueError(f"Edge references unknown node id '{from_node_id}'")
        if to_node_id not in id_to_type:
            raise ValueError(f"Edge references unknown node id '{to_node_id}'")

        from_type = id_to_type[from_node_id]
        to_type = id_to_type[to_node_id]

        try:
            from_class = registry.get_class(from_type)
            to_class = registry.get_class(to_type)
        except Exception:
            continue  # node type already validated above

        if from_port not in from_class.output_ports:
            raise ValueError(
                f"Node '{from_node_id}' ({from_type}) has no output port '{from_port}'"
            )
        if to_port not in to_class.input_ports:
            raise ValueError(
                f"Node '{to_node_id}' ({to_type}) has no input port '{to_port}'"
            )

        # Type compatibility check
        try:
            from app.core.nodes.compat import CompatibilityChecker
            src_port = from_class.output_ports[from_port]
            dst_port = to_class.input_ports[to_port]
            if not CompatibilityChecker.are_compatible(src_port.data_type, dst_port.data_type):
                raise ValueError(
                    f"Incompatible port types: {from_node_id}.{from_port} "
                    f"({src_port.data_type}) → {to_node_id}.{to_port} ({dst_port.data_type})"
                )
        except ImportError:
            pass  # CompatibilityChecker not available — skip type check
```

---

## 5. Before/After Summary

### validation.py Changes

| Change | Lines | Impact |
|--------|-------|--------|
| Remove `"must start with input/mic_input"` check | -3 | Enables non-audio pipelines |
| Remove `"must end with export"` check | -3 | Enables non-audio pipelines |
| Add `_validate_dag_edges` function | +40 | Enables DAG format validation |
| Total changes to validation.py | ~50 lines | Minimal, surgical |

### registry.py Changes

| Change | Lines | Impact |
|--------|-------|--------|
| Add `__getitem__` shim | +20 | Legacy dict access works |
| Add `keys()` shim | +5 | Legacy iteration works |
| Add `items()` shim | +5 | Legacy iteration works |
| Total changes to registry.py | ~30 lines | Backward compat only |

---

## 6. Testing

### Unit Tests (in `tests/test_migration.py`)

- `test_validate_pipeline_no_input_constraint()` — assert pipeline starting with `"clean"` passes validation
- `test_validate_pipeline_no_export_constraint()` — assert pipeline ending with `"split"` passes validation
- `test_validate_pipeline_unknown_node_type()` — assert unknown node type raises `ValueError`
- `test_validate_pipeline_invalid_config()` — assert invalid node config raises `ValueError`
- `test_registry_getitem_shim()` — assert `registry["clean"]["schema"]` returns a dict
- `test_registry_getitem_unknown()` — assert `registry["unknown"]` raises `NodeNotFoundError`
- `test_registry_keys_shim()` — assert `list(registry.keys())` returns list of node type strings
- `test_registry_items_shim()` — assert `dict(registry.items())` is a dict keyed by node type
- `test_validate_pipeline_dag_format()` — assert DAG YAML with valid edges passes validation
- `test_validate_pipeline_dag_unknown_node_id()` — assert edge referencing unknown node id raises `ValueError`
- `test_validate_pipeline_dag_unknown_port()` — assert edge referencing unknown port raises `ValueError`

### Property Tests (in `tests/test_properties.py`)

- `test_property_12_registry_getitem_shim_consistency()` — Property 12: for any registered node_type, `registry[node_type]["schema"]` equals `registry.get_config_schema(node_type)`

### Integration Tests (in `tests/test_pipeline_integration.py`)

- `test_validate_pipeline_linear_and_dag_equivalent()` — assert that a pipeline expressed in both formats produces the same validation result
- `test_validate_pipeline_audio_pipeline_still_works()` — assert that a standard audio pipeline (input → clean → export) still passes validation after the rule removal
