# Design Document — unit_test Suite

> **Requirements:** `requirements.md` · `requirements-per-file.md`
> **Linked detail files:** `design-folder-structure.md` · `design-conftest.md` · `design-test-patterns.md`

---

## 1. Overview

A brand-new `unit_test/` folder at the project root replaces the outdated `tests/` folder.
The suite is runnable with a single command: `venv/bin/pytest unit_test/`

Three design principles drive every decision:

1. **Isolation** — each test file owns its dependencies via fixtures; no shared global state.
2. **Speed** — unit tests mock I/O and threads; only integration tests touch the filesystem.
3. **Completeness** — every source file in `app/` and every plugin in `PluginPackage/` has a corresponding test file.

---

## 2. Folder Structure

See `design-folder-structure.md` for the full tree.

Summary:

```
unit_test/
├── conftest.py                  ← shared fixtures (see design-conftest.md)
├── core/                        ← app/core/** tests
│   ├── nodes/                   ← base, registry, discovery, ports, etc.
│   ├── ir/                      ← IR models, loader, yaml_shim, migrate
│   └── plugins/                 ← manifest, manager, loader, store, index
├── api/                         ← app/api/routers/** tests (TestClient)
├── mcp/                         ← app/mcp/handlers/** + auth + tool_registry
├── cli/                         ← app/cli/main.py (Click test runner)
├── models/                      ← app/models/** tests
└── plugins/
    ├── audio/                   ← PluginPackage/Audio/** tests
    └── common/                  ← PluginPackage/Common/** tests
```

---

## 3. Shared Fixtures (`conftest.py`)

See `design-conftest.md` for full fixture code.

| Fixture | Scope | Purpose |
|---|---|---|
| `fresh_registry` | `function` | New `NodeRegistry()` per test; prevents cross-test contamination |
| `tmp_plugin_dir` | `function` | `tmp_path / "plugins"` — plugin install target; real `plugins/` never touched |
| `make_audio_sample` | `function` | Factory: `make_audio_sample(sr=16000, n=1600, label="test")` → `AudioSample` |
| `patch_threads` | `function`, autouse | Patches `ThreadPoolExecutor.submit` and `Thread.start` to no-ops in all tests |
| `api_client` | `function` | `TestClient(app)` for REST API tests |
| `tmp_workspace` | `function` | Isolated `workspace/` dir under `tmp_path`; sets `GRAPHYN_PROJECT_DIR` env var |

---

## 4. Test Patterns

See `design-test-patterns.md` for code templates.

### 4.1 Unit test (isolated, mocked)
```python
# unit_test/core/test_conditions.py
from app.core.conditions import evaluate_condition, ConditionEvaluationError

def test_len_gt_passes():
    assert evaluate_condition("len(output['output']) > 2", {"output": [1,2,3]}) is True

def test_import_raises():
    with pytest.raises(ConditionEvaluationError):
        evaluate_condition("import os", {})
```

### 4.2 Registry test (uses `fresh_registry` fixture)
```python
def test_register_and_get(fresh_registry, minimal_node_cls, minimal_meta):
    fresh_registry.register("my_node", minimal_node_cls, minimal_meta)
    assert fresh_registry.get_class("my_node") is minimal_node_cls
```

### 4.3 Plugin install test (uses `tmp_plugin_dir` + `fresh_registry`)
```python
def test_audio_conditioner_registers(tmp_plugin_dir, fresh_registry):
    mgr = PluginManager(registry=fresh_registry)
    mgr.install("PluginPackage/Audio/audio_conditioner/", plugins_dir=tmp_plugin_dir)
    assert "audio_conditioner" in fresh_registry
```

### 4.4 API test (uses `api_client` fixture)
```python
def test_health(api_client):
    resp = api_client.get("/api/v1/system/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
```

### 4.5 Property-based test (Hypothesis)
```python
from hypothesis import given, settings
from hypothesis import strategies as st

@given(st.floats(min_value=0.0, max_value=60.0, allow_nan=False),
       st.floats(min_value=1.0, max_value=10.0, allow_nan=False),
       st.integers(min_value=0, max_value=9))
@settings(max_examples=100)
def test_retry_monotonic(backoff_s, multiplier, attempt):
    p = RetryPolicy(max_attempts=10, backoff_seconds=backoff_s, backoff_multiplier=multiplier)
    if attempt > 0:
        assert p.wait_before_attempt(attempt) >= p.wait_before_attempt(attempt - 1)
```

---

## 5. File-to-Test Mapping

| Source file | Test file |
|---|---|
| `app/core/conditions.py` | `unit_test/core/test_conditions.py` |
| `app/core/events.py` | `unit_test/core/test_events.py` |
| `app/core/executor.py` | `unit_test/core/test_executor.py` |
| `app/core/ingestion.py` | `unit_test/core/test_ingestion.py` |
| `app/core/logger.py` | `unit_test/core/test_logger.py` |
| `app/core/pipeline.py` | `unit_test/core/test_pipeline.py` |
| `app/core/pipeline_cache.py` | `unit_test/core/test_pipeline_cache.py` |
| `app/core/project_manager.py` | `unit_test/core/test_project_manager.py` |
| `app/core/provenance.py` | `unit_test/core/test_provenance.py` |
| `app/core/artifact_store.py` | `unit_test/core/test_artifact_store.py` |
| `app/core/quality_checker.py` | `unit_test/core/test_quality_checker.py` |
| `app/core/registry_runtime.py` | `unit_test/core/test_registry_runtime.py` |
| `app/core/run_manager.py` | `unit_test/core/test_run_manager.py` |
| `app/core/runtime_backend.py` | `unit_test/core/test_runtime_backend.py` |
| `app/core/sdk.py` | `unit_test/core/test_sdk.py` |
| `app/core/validation.py` | `unit_test/core/test_validation.py` |
| `app/core/webhook.py` | `unit_test/core/test_webhook.py` |
| `app/core/ir/models.py` | `unit_test/core/ir/test_ir_models.py` |
| `app/core/ir/loader.py` | `unit_test/core/ir/test_ir_loader.py` |
| `app/core/ir/yaml_shim.py` | `unit_test/core/ir/test_yaml_shim.py` |
| `app/core/ir/migrate.py` | `unit_test/core/ir/test_ir_migrate.py` |
| `app/core/nodes/base.py` | `unit_test/core/nodes/test_node_base.py` |
| `app/core/nodes/registry.py` | `unit_test/core/nodes/test_registry.py` |
| `app/core/nodes/discovery.py` | `unit_test/core/nodes/test_discovery.py` |
| `app/core/nodes/catalogue.py` | `unit_test/core/nodes/test_catalogue.py` |
| `app/core/nodes/compat.py` | `unit_test/core/nodes/test_compat.py` |
| `app/core/nodes/config.py` | `unit_test/core/nodes/test_node_config.py` |
| `app/core/nodes/errors.py` | `unit_test/core/nodes/test_errors.py` |
| `app/core/nodes/metadata.py` | `unit_test/core/nodes/test_metadata.py` |
| `app/core/nodes/observers.py` | `unit_test/core/nodes/test_observers.py` |
| `app/core/nodes/ports.py` | `unit_test/core/nodes/test_ports.py` |
| `app/core/nodes/retry.py` | `unit_test/core/nodes/test_retry.py` |
| `app/core/plugins/manifest.py` | `unit_test/core/plugins/test_manifest.py` |
| `app/core/plugins/manager.py` | `unit_test/core/plugins/test_manager.py` |
| `app/core/plugins/loader.py` | `unit_test/core/plugins/test_loader.py` |
| `app/core/plugins/store.py` | `unit_test/core/plugins/test_store.py` |
| `app/core/plugins/index.py` | `unit_test/core/plugins/test_index.py` |
| `app/core/plugins/dependencies.py` | `unit_test/core/plugins/test_dependencies.py` |
| `app/core/plugins/installer.py` | `unit_test/core/plugins/test_installer.py` |
| `app/models/audio_sample.py` | `unit_test/models/test_audio_sample.py` |
| `app/models/feature_array.py` | `unit_test/models/test_feature_array.py` |
| `app/models/tensor_batch.py` | `unit_test/models/test_tensor_batch.py` |
| `app/models/model_artifact.py` | `unit_test/models/test_model_artifact.py` |
| `app/models/tflite_artifact.py` | `unit_test/models/test_tflite_artifact.py` |
| `app/models/prediction_result.py` | `unit_test/models/test_prediction_result.py` |
| `app/models/deployment_artifact.py` | `unit_test/models/test_deployment_artifact.py` |
| `app/models/data_sample.py` | `unit_test/models/test_data_sample.py` |
| `app/api/routers/nodes.py` | `unit_test/api/test_nodes_router.py` |
| `app/api/routers/pipelines.py` | `unit_test/api/test_pipelines_router.py` |
| `app/api/routers/runs.py` | `unit_test/api/test_runs_router.py` |
| `app/api/routers/run_control.py` | `unit_test/api/test_run_control_router.py` |
| `app/api/routers/artifacts.py` | `unit_test/api/test_artifacts_router.py` |
| `app/api/routers/data.py` | `unit_test/api/test_data_router.py` |
| `app/api/routers/ingest.py` | `unit_test/api/test_ingest_router.py` |
| `app/api/routers/projects.py` | `unit_test/api/test_projects_router.py` |
| `app/api/routers/plugins.py` | `unit_test/api/test_plugins_router.py` |
| `app/api/routers/system.py` | `unit_test/api/test_system_router.py` |
| `app/mcp/auth.py` | `unit_test/mcp/test_auth.py` |
| `app/mcp/tool_registry.py` | `unit_test/mcp/test_tool_registry.py` |
| `app/mcp/handlers/discovery.py` | `unit_test/mcp/test_handler_discovery.py` |
| `app/mcp/handlers/graph.py` | `unit_test/mcp/test_handler_graph.py` |
| `app/mcp/handlers/execution.py` | `unit_test/mcp/test_handler_execution.py` |
| `app/mcp/handlers/artifacts.py` | `unit_test/mcp/test_handler_artifacts.py` |
| `app/mcp/handlers/run_control.py` | `unit_test/mcp/test_handler_run_control.py` |
| `app/mcp/handlers/provenance.py` | `unit_test/mcp/test_handler_provenance.py` |
| `app/mcp/handlers/optimization.py` | `unit_test/mcp/test_handler_optimization.py` |
| `app/cli/main.py` | `unit_test/cli/test_cli.py` |
| `PluginPackage/Audio/audio_conditioner/` | `unit_test/plugins/audio/test_audio_conditioner.py` |
| `PluginPackage/Audio/feature_frontend/` | `unit_test/plugins/audio/test_feature_frontend.py` |
| `PluginPackage/Audio/dataset_ingest/` | `unit_test/plugins/audio/test_dataset_ingest.py` |
| `PluginPackage/Audio/stream_ingest/` | `unit_test/plugins/audio/test_stream_ingest.py` |
| `PluginPackage/Audio/audio_quality_gate/` | `unit_test/plugins/audio/test_audio_quality_gate.py` |
| `PluginPackage/Audio/segmenter/` | `unit_test/plugins/audio/test_segmenter.py` |
| `PluginPackage/Audio/audio_annotator/` | `unit_test/plugins/audio/test_audio_annotator.py` |
| `PluginPackage/Audio/alignment_node/` | `unit_test/plugins/audio/test_alignment_node.py` |
| `PluginPackage/Audio/speech_enhancer/` | `unit_test/plugins/audio/test_speech_enhancer.py` |
| `PluginPackage/Audio/speaker_separator/` | `unit_test/plugins/audio/test_speaker_separator.py` |
| `PluginPackage/Audio/environment_simulator/` | `unit_test/plugins/audio/test_environment_simulator.py` |
| `PluginPackage/Audio/augmentation_pipeline/` | `unit_test/plugins/audio/test_augmentation_pipeline.py` |
| `PluginPackage/Audio/audio_event_detector/` | `unit_test/plugins/audio/test_audio_event_detector.py` |
| `PluginPackage/Audio/audio_classifier/` | `unit_test/plugins/audio/test_audio_classifier.py` |
| `PluginPackage/Audio/speech_synthesizer/` | `unit_test/plugins/audio/test_speech_synthesizer.py` |
| `PluginPackage/Audio/voice_converter/` | `unit_test/plugins/audio/test_voice_converter.py` |
| `PluginPackage/Audio/audio_generator/` | `unit_test/plugins/audio/test_audio_generator.py` |
| `PluginPackage/Audio/stream_processor/` | `unit_test/plugins/audio/test_stream_processor.py` |
| `PluginPackage/Common/dataset_builder/` | `unit_test/plugins/common/test_dataset_builder.py` |
| `PluginPackage/Common/trainer/` | `unit_test/plugins/common/test_trainer.py` |
| `PluginPackage/Common/evaluator/` | `unit_test/plugins/common/test_evaluator.py` |
| `PluginPackage/Common/edge_optimizer/` | `unit_test/plugins/common/test_edge_optimizer.py` |
| `PluginPackage/Common/realtime_inference/` | `unit_test/plugins/common/test_realtime_inference.py` |
| `PluginPackage/Common/dataset_balancer/` | `unit_test/plugins/common/test_dataset_balancer.py` |
| `PluginPackage/Common/dataset_versioner/` | `unit_test/plugins/common/test_dataset_versioner.py` |
| `PluginPackage/Common/experiment_tracker/` | `unit_test/plugins/common/test_experiment_tracker.py` |
| `PluginPackage/Common/deployment_packager/` | `unit_test/plugins/common/test_deployment_packager.py` |
| `PluginPackage/Common/embedding_generator/` | `unit_test/plugins/common/test_embedding_generator.py` |
| `PluginPackage/Common/multimodal_fusion/` | `unit_test/plugins/common/test_multimodal_fusion.py` |

---

## 6. Key Design Decisions

| Decision | Rationale |
|---|---|
| `fresh_registry` is `function`-scoped | Prevents node registration from one test leaking into another |
| `tmp_plugin_dir` via `tmp_path` | pytest's `tmp_path` is automatically cleaned up; real `plugins/` dir is never touched |
| `patch_threads` is autouse | Prevents any test from accidentally spawning real background threads |
| Plugin tests use the real `PluginPackage/` source | Tests verify the actual plugin code, not a synthetic fixture |
| API tests use `TestClient` (sync) | No async test runner needed; simpler setup |
| Property-based tests use `@settings(max_examples=100)` | Balances coverage with speed |
| Plugin node tests install via `PluginManager` | Tests the full install path, not just the node class directly |
| `module`-scoped fixture for bulk plugin install (Req 7.19) | Installs all 18 Audio plugins once per module, not once per test |
