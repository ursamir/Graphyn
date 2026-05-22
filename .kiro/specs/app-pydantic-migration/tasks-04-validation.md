# Tasks 04 — Validation Generalization

← Back to [tasks.md](tasks.md) | Design: [design-04-validation.md](design-04-validation.md)

**Requirements covered:** 14, 15

**Files changed:**
- `app/core/nodes/registry.py` — no shims; update any remaining dict-style callers to use new API
- `app/core/validation.py` — remove 2 audio-specific rules, update to use `registry.get_class()` directly, add `_validate_dag_edges`
- `tests/test_migration.py` — new/updated unit tests
- `tests/test_properties.py` — Property 12

**Execution order note:** Complete before Group 03 (API Redesign). The API's `POST /api/v1/pipelines/validate` depends on the generalized `validate_pipeline`.

---

## Task 4.1 — Migrate `app/core/validation.py` to use `registry.get_class()` directly

**Requirement:** 15.1–15.7

Remove all dict-style `registry[node_type]` access from `app/core/validation.py` and replace with the proper `registry.get_class()` / `registry.get_metadata()` API. No shim methods are added to `NodeRegistry`.

### Sub-tasks

- [x] 4.1.1 Read `app/core/validation.py` to locate every `registry[node_type]` access pattern
- [x] 4.1.2 Replace `registry[node_type]["class"]` with `registry.get_class(node_type)` — catch `NodeNotFoundError` and re-raise as `ValueError`
- [x] 4.1.3 Replace `registry[node_type]["schema"]` with `registry.get_config_schema(node_type)` where schema dict access is needed
- [x] 4.1.4 Replace any `for node_type, info in registry.items()` iteration with `for meta in registry.list_nodes(): node_type = meta.node_type; node_class = registry.get_class(node_type)`
- [x] 4.1.5 Replace any `for node_type in registry.keys()` iteration with `[meta.node_type for meta in registry.list_nodes()]`
- [x] 4.1.6 Replace `validate_node_config(config, schema)` calls (if any remain) with `node_class.Config.model_validate(config)` — catch `pydantic.ValidationError` and re-raise as `ValueError`
- [x] 4.1.7 Confirm zero occurrences of `registry[` remain in `app/core/validation.py`

### Acceptance checks
- `app/core/validation.py` contains zero occurrences of `registry[` ✅
- `validate_pipeline` still raises `ValueError` for unknown node types (via `NodeNotFoundError` → `ValueError`) ✅
- `validate_pipeline` still raises `ValueError` for invalid node configs (via `pydantic.ValidationError` → `ValueError`) ✅
- `NodeRegistry` has no `__getitem__`, `keys()`, or `items()` shim methods ✅

---

## Task 4.2 — Remove hardcoded audio-specific first/last node rules from `validate_pipeline`

**Requirement:** 14.1–14.7

Remove exactly two validation blocks from `app/core/validation.py` that enforce audio-specific pipeline structure.

### Sub-tasks

- [x] 4.2.1 Read `app/core/validation.py` to locate the two audio-specific checks
- [x] 4.2.2 Remove the first-node check block entirely
- [x] 4.2.3 Remove the last-node check block entirely
- [x] 4.2.4 Verify no other logic in `validation.py` is changed by this task
- [x] 4.2.5 Confirm a standard audio pipeline (`input → clean → export`) still passes validation after removal

### Acceptance checks
- `validate_pipeline` with a `clean`-only pipeline does NOT raise `ValueError` about first/last node ✅
- `validate_pipeline` with `input → clean → export` still passes (no regression) ✅
- `validate_pipeline` still raises `ValueError` for unknown node types ✅
- `validate_pipeline` still raises `ValueError` for invalid node configs ✅

---

## Task 4.3 — Add `_validate_dag_edges` function to `app/core/validation.py`

**Requirement:** 12.2, 14.5

Add a new `_validate_dag_edges(nodes, edges, registry)` function and update `validate_pipeline` to call it when the pipeline config contains an `edges` key.

### Sub-tasks

- [x] 4.3.1 Add `_validate_dag_edges(nodes: list[dict], edges: list[dict], registry) -> None` to `validation.py` with full edge validation logic
- [x] 4.3.2 Update `validate_pipeline` to detect DAG format: `if "edges" in pipeline_config: _validate_dag_edges(nodes, edges, registry)`
- [x] 4.3.3 Ensure the linear format path (`_validate_connections`) is still called when no `edges` key is present
- [x] 4.3.4 Verify a valid DAG YAML with correct edges passes validation
- [x] 4.3.5 Verify a DAG YAML with an edge referencing an unknown node id raises `ValueError`
- [x] 4.3.6 Verify a DAG YAML with an edge referencing an unknown port name raises `ValueError`

### Acceptance checks
- DAG pipeline YAML with valid edges passes `validate_pipeline` ✅
- DAG pipeline YAML with `from_node: "nonexistent"` raises `ValueError` containing `"nonexistent"` ✅
- DAG pipeline YAML with `from_port: "nonexistent_port"` raises `ValueError` containing `"nonexistent_port"` ✅
- Linear pipeline YAML (no `edges` key) still uses the `_validate_connections` path ✅

---

## Task 4.4 — Write unit tests for Group 04

**Requirement:** 14.1–15.7

Add or update unit tests in `tests/test_migration.py` covering all Group 04 changes.

### Tests to implement

- [x] 4.4.1 `test_registry_no_dict_access_in_validation` — assert `app/core/validation.py` source contains zero occurrences of `registry[`
- [x] 4.4.2 `test_registry_no_shim_methods` — assert `NodeRegistry` has no `__getitem__`, `keys`, or `items` attributes
- [x] 4.4.3 `test_validate_pipeline_uses_get_class` — assert `validate_pipeline` calls `registry.get_class()`
- [x] 4.4.4 `test_validate_pipeline_no_input_constraint` — assert a pipeline starting with `"clean"` passes validation
- [x] 4.4.5 `test_validate_pipeline_no_export_constraint` — assert a pipeline ending with `"split"` passes validation
- [x] 4.4.6 `test_validate_pipeline_audio_pipeline_still_works` — assert `input → clean → export` pipeline still passes validation
- [x] 4.4.7 `test_validate_pipeline_unknown_node_type` — assert a pipeline with `type: "nonexistent_node"` raises `ValueError`
- [x] 4.4.8 `test_validate_pipeline_invalid_config` — assert a pipeline with an invalid node config raises `ValueError`
- [x] 4.4.9 `test_validate_pipeline_dag_format` — assert a valid DAG YAML with explicit edges passes validation
- [x] 4.4.10 `test_validate_pipeline_dag_unknown_node_id` — assert a DAG edge referencing an unknown node id raises `ValueError`
- [x] 4.4.11 `test_validate_pipeline_dag_unknown_port` — assert a DAG edge referencing an unknown port name raises `ValueError`

### Acceptance checks
- All tests in `tests/test_migration.py` pass for Group 04 items ✅

---

## Task 4.5 — Write property-based test: Property 12

**Requirement:** 15.1, 15.6

Add a property-based test to `tests/test_properties.py` using Hypothesis.

### Test to implement

- [x] 4.5.1 **Property 12 — `registry.get_class()` / `get_config_schema()` consistency** (`test_property_12_registry_api_consistency`)
  - `# Feature: app-pydantic-migration, Property 12: registry.get_class and get_config_schema consistency`
  - **Validates: Requirements 15.1, 15.6**
  - Strategy: `@given(node_meta=st.sampled_from(registry.list_nodes()))`
  - Assert: `registry.get_class(node_type).Config.model_json_schema()` equals `registry.get_config_schema(node_type)`
  - Use `@settings(max_examples=100)`

### Acceptance checks
- Property 12 passes with `max_examples=100` ✅
- Test is annotated with `# Feature:` and `# Validates:` comments ✅
