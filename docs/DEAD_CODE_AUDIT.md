# Dead Code & Unused Functionality Audit

**Date:** 2026-05-18  
**Scope:** All files under `app/` and `PluginPackage/`  
**Method:** Full import tracing, grep-based call-site analysis, cross-reference with tests and production interfaces

---

## Summary

The codebase is in good shape. Most code is actively used. The dead code falls into three clear categories:

| Category | Count | Action |
|---|---|---|
| **Safe to delete** — zero callers anywhere | 7 symbols | Delete |
| **Production-dead** — tested but never wired to any interface | 4 symbols | Wire up or delete |
| **Entire file dead in production** — abstraction never connected | 1 file | Wire up or delete |

---

## Category 1 — Safe to Delete (zero callers anywhere)

These symbols have no callers in production code, tests, or examples.

### 1. `pipeline.py` — `_count_payload()` and `_payload_count()`

```python
# app/core/pipeline.py  (under "Legacy helpers" comment block)
def _count_payload(output_type, payload): ...
def _payload_count(output_type, payload) -> int: ...
```

**Status:** Zero call sites anywhere in the codebase. Both are orphaned legacy helpers from a prior implementation. The current executor uses inline counting logic directly. Safe to delete both.

---

### 2. `sdk.py` — `Pipeline.to_yaml()` and `Pipeline._to_config_dict()`

```python
# app/core/sdk.py
def to_yaml(self, path: str) -> None: ...
def _to_config_dict(self) -> dict: ...
```

**Status:** `to_yaml()` has zero call sites anywhere. `_to_config_dict()` is only called by `to_yaml()`, so it is also dead. The CLI uses `Pipeline.from_yaml()` (deprecated load path) but never calls `to_yaml()`. Safe to delete both together.

---

### 3. `sdk.py` — `PipelineNode.to_dict()`

```python
# app/core/sdk.py
def to_dict(self) -> dict: ...
```

**Status:** Zero call sites anywhere. Documented as "legacy dict representation." Safe to delete.

---

### 4. `validation.py` — `validate_node_config()`

```python
# app/core/validation.py
def validate_node_config(node_type: str, config: dict, schema: dict) -> dict:
    """Legacy shim — returns error dict from old schema-based validation."""
    errors: dict[str, str] = {}
    return errors   # always returns empty dict — does nothing
```

**Status:** The function body is literally `return {}`. It is never imported anywhere in the codebase. The docstring even says "Deprecated." Safe to delete.

---

### 5. `artifact_store.py` — `ArtifactStore.get_versions()`

```python
# app/core/artifact_store.py
def get_versions(self, artifact_name: str) -> list[ArtifactRecord]: ...
```

**Status:** Zero callers anywhere — no API endpoint, no CLI command, no MCP tool, no test. Safe to delete.

---

### 6. `logger.py` — `PipelineLogger.summary()`

```python
# app/core/logger.py
def summary(self) -> None: ...
```

**Status:** Superseded by `pipeline_done()` which is the structured equivalent called throughout `pipeline.py`. `summary()` has no callers outside its own class. Safe to delete.

---

## Category 2 — Production-Dead (tested but never wired to any interface)

These symbols are covered by tests but are never called from the REST API, CLI, SDK, or MCP server. They represent Phase 4 provenance features that were implemented and tested but never exposed.

### 7. `provenance.py` — `ProvenanceStore.find_reproducible()`

```python
# app/core/provenance.py
def find_reproducible(self, graph_hash: str) -> list[ProvenanceRecord]: ...
```

**Status:** Only called from `tests/test_provenance.py` and `unit_test/core/test_provenance.py`. No API endpoint, CLI command, or MCP tool exposes it. The feature is useful — it finds all prior runs with the same graph hash, enabling reproducibility checks. **Recommendation: wire it up** to `GET /api/v1/runs?graph_hash=X` or the `inspect_run` MCP tool, or add a CLI `graphyn runs find-reproducible <hash>` command.

---

### 8. `run_manager.py` — `RunManager.get_provenance_summary()`

```python
# app/core/run_manager.py
def get_provenance_summary(self) -> dict: ...
```

**Status:** Only called from `tests/test_run_manager_phase4.py`. No API endpoint, CLI command, or MCP tool calls it. The method returns a complete `{run_id, graph_hash, artifacts, provenance_records}` dict — exactly what `GET /api/v1/runs/{run_id}/provenance` should return. **Recommendation: wire it up** to that endpoint (the endpoint exists in `runs.py` but currently builds its own response dict instead of delegating here).

---

### 9. `pipeline.py` — `run_pipeline()` (YAML shim)

```python
# app/core/pipeline.py
def run_pipeline(config_path: str, ...) -> dict[str, Any]:
    """Deprecated: use run_pipeline_ir()..."""
```

**Status:** No production code calls this. The CLI calls `run_pipeline_ir()` directly. The only references are two tests in `test_migration.py` that inspect its signature via `inspect.signature`, not call it. The function emits `DeprecationWarning` and is self-documented as deprecated. **Recommendation: delete** along with the two signature-inspection tests.

---

### 10. `pipeline.py` — `_parse_pipeline_config()`

```python
# app/core/pipeline.py
def _parse_pipeline_config(raw: dict) -> PipelineConfig: ...
```

**Status:** Only called from tests (`test_pipeline_dag.py` ×8, `test_graph_ir_properties.py` ×2). No production path uses it — production goes through `_ir_to_pipeline_config()`. **Recommendation: delete** and update the 10 test call sites to use `_ir_to_pipeline_config()` instead, which is the live code path.

---

## Category 3 — Entire File Dead in Production

### 11. `app/core/runtime_backend.py` — entire file

```python
# app/core/runtime_backend.py
class RuntimeBackend(ABC): ...
class LocalPythonBackend(RuntimeBackend): ...
def register_backend(backend_id, backend_class): ...
def get_backend(backend_id) -> RuntimeBackend: ...
def list_backends() -> list[str]: ...
```

**Status:** The entire file is an unconnected abstraction. No production code (SDK, CLI, API, MCP) imports or uses it. `register_backend`, `get_backend`, and `list_backends` have **zero callers anywhere** — not even in tests. `LocalPythonBackend` and `RuntimeBackend` are only referenced in `unit_test/core/test_runtime_backend.py`.

The design intent was to make the execution backend pluggable (local Python, remote, distributed). `LocalPythonBackend.execute()` delegates to `run_pipeline_ir()` — the right idea — but it was never wired into the SDK, CLI, API, or MCP server, all of which call `run_pipeline_ir()` directly.

**Recommendation:** Either wire `LocalPythonBackend` as the default backend in `Pipeline.run()` (replacing the direct `run_pipeline_ir()` call), which would make the abstraction real and enable future distributed backends — or delete the file if the abstraction is not planned for the near term.

---

## What Is Fully Used (no dead code found)

| File | Verdict |
|---|---|
| `app/core/pipeline.py` (minus 4 symbols above) | ✅ All used |
| `app/core/sdk.py` (minus 3 symbols above) | ✅ All used |
| `app/core/conditions.py` | ✅ All used |
| `app/core/events.py` | ✅ All used |
| `app/core/ingestion.py` | ✅ All used |
| `app/core/logger.py` (minus `summary()`) | ✅ All used |
| `app/core/pipeline_cache.py` | ✅ All used |
| `app/core/project_manager.py` | ✅ All used |
| `app/core/quality_checker.py` | ✅ All used |
| `app/core/run_manager.py` (minus `get_provenance_summary()`) | ✅ All used |
| `app/core/webhook.py` | ✅ All used |
| `app/core/validation.py` (minus `validate_node_config()`) | ✅ All used |
| `app/core/nodes/base.py` | ✅ All used |
| `app/core/nodes/registry.py` | ✅ All used |
| `app/core/nodes/discovery.py` | ✅ All used |
| `app/core/nodes/catalogue.py` | ✅ All used |
| `app/core/nodes/compat.py` | ✅ All used |
| `app/core/nodes/errors.py` | ✅ All used |
| `app/core/nodes/metadata.py` | ✅ All used |
| `app/core/nodes/config.py` | ✅ All used |
| `app/core/nodes/retry.py` | ✅ Used in tests and examples (no production plugin uses it yet — see note) |
| `app/core/nodes/observers.py` | ✅ Used in tests and examples (see note) |
| `app/api/main.py` + all 10 routers | ✅ All wired |
| `app/mcp/` + all 15 handlers | ✅ All registered |
| `app/cli/main.py` + all 22 cmd_* functions | ✅ All wired |
| `app/models/audio_sample.py` | ✅ Used by 18 audio plugins |
| `app/models/feature_array.py` | ✅ Used by feature_frontend, embedding_generator, realtime_inference |
| `app/models/model_artifact.py` | ✅ Used by trainer, evaluator, edge_optimizer |
| `app/models/deployment_artifact.py` | ✅ Used by edge_optimizer, deployment_packager |
| `app/models/prediction_result.py` | ✅ Used by audio_classifier, realtime_inference |
| `app/models/tflite_artifact.py` | ⚠️ Registered in TypeCatalogue but no plugin uses it as a port type (edge_optimizer was updated to use `DeploymentArtifact` instead — see note) |
| `app/models/tensor_batch.py` | ⚠️ Registered in TypeCatalogue but no plugin uses it as a port type (see note) |
| `app/models/data_sample.py` | ✅ Used in examples (csv_pipeline, manifest_demo) as a base type |

---

## Notes on "Used in tests/examples only" items

### `RetryPolicy` — no production plugin uses it yet

`RetryPolicy` is fully implemented and wired into `NodeExecutor`. The infrastructure works. But none of the 29 plugin nodes in `PluginPackage/` actually declare a `retry_policy` ClassVar. It is only used in `examples/20_retry_fault_tolerance/` and tests. This is not dead code — it is a ready feature waiting to be adopted by plugin authors.

### `NodeObserver` / `LoggingObserver` / `CompositeObserver` — no production plugin uses them

The observer system is fully wired into `NodeExecutor` and accepted as a parameter by `run_pipeline_ir()`, `Pipeline.run()`, and the SDK. But no production interface (API, CLI, MCP) passes an observer by default, and no plugin node uses one. Only `examples/20_retry_fault_tolerance/` demonstrates the pattern. Again, not dead — a ready feature waiting to be adopted.

### `TFLiteArtifact` — superseded by `DeploymentArtifact`

`TFLiteArtifact` is registered in `TypeCatalogue` and exported from `app/models/`. However, `edge_optimizer` was updated to produce `DeploymentArtifact` (more general) instead. The comment in `edge_optimizer/nodes.py` explicitly says: *"Output is DeploymentArtifact instead of TFLiteArtifact (more general)"*. `TFLiteArtifact` is now an orphaned type — no plugin produces or consumes it. **Recommendation: either repurpose it for a TFLite-specific node, or remove it from `app/models/` and `app/models/__init__.py`.**

### `TensorBatch` — defined but no plugin uses it as a port type

`TensorBatch` is registered in `TypeCatalogue` and exported from `app/models/`. It was designed as the typed contract between feature extraction and dataset assembly nodes. However, the `dataset_builder` plugin uses its own `DatasetArtifact` type (defined in `PluginPackage/Common/dataset_builder/types.py`) rather than `TensorBatch`. No plugin currently produces or consumes `TensorBatch`. **Recommendation: either adopt it in a future node, or remove it.**

---

## Prioritised Action List

| Priority | Action | Effort | Risk |
|---|---|---|---|
| 1 | Delete `_count_payload()` and `_payload_count()` from `pipeline.py` | 5 min | None |
| 2 | Delete `Pipeline.to_yaml()` and `Pipeline._to_config_dict()` from `sdk.py` | 5 min | None |
| 3 | Delete `PipelineNode.to_dict()` from `sdk.py` | 2 min | None |
| 4 | Delete `validate_node_config()` from `validation.py` | 2 min | None |
| 5 | Delete `ArtifactStore.get_versions()` from `artifact_store.py` | 2 min | None |
| 6 | Delete `PipelineLogger.summary()` from `logger.py` | 2 min | None |
| 7 | Wire `RunManager.get_provenance_summary()` into `GET /api/v1/runs/{id}/provenance` | 30 min | Low |
| 8 | Wire `ProvenanceStore.find_reproducible()` into a new endpoint or MCP tool | 1 hr | Low |
| 9 | Delete `run_pipeline()` YAML shim from `pipeline.py` + update 2 tests | 20 min | Low |
| 10 | Delete `_parse_pipeline_config()` from `pipeline.py` + update 10 tests | 1 hr | Low |
| 11 | Decide on `runtime_backend.py`: wire it up or delete it | 2–4 hrs | Medium |
| 12 | Decide on `TFLiteArtifact`: repurpose or remove from `app/models/` | 30 min | Low |
| 13 | Decide on `TensorBatch`: adopt in a future node or remove from `app/models/` | 30 min | Low |
