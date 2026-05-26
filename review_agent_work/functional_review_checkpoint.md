# Functional Review Checkpoint

## Status
current_group: 1
total_groups: 16
last_completed_group: 0
last_completed_name: none

## Groups

| # | Name | Status | Files |
|---|---|---|---|
| 1 | IR Core | pending | `app/core/ir/models.py`, `app/core/ir/loader.py`, `app/core/ir/yaml_shim.py`, `app/core/ir/migrate.py` |
| 2 | Node Base | pending | `app/core/nodes/base.py`, `app/core/nodes/ports.py`, `app/core/nodes/config.py`, `app/core/nodes/retry.py`, `app/core/nodes/metadata.py`, `app/core/nodes/observers.py`, `app/core/nodes/compat.py`, `app/core/nodes/errors.py` |
| 3 | Registry & Discovery | pending | `app/core/nodes/registry.py`, `app/core/nodes/discovery.py`, `app/core/nodes/catalogue.py`, `app/core/registry_runtime.py` |
| 4 | Plugin Ecosystem | pending | `app/core/plugins/manager.py`, `app/core/plugins/loader.py`, `app/core/plugins/installer.py`, `app/core/plugins/store.py`, `app/core/plugins/manifest.py`, `app/core/plugins/dependencies.py`, `app/core/plugins/errors.py`, `app/core/plugins/index.py` |
| 5 | Planner | pending | `app/core/planner.py` |
| 6 | Execution Runtime | pending | `app/core/orchestrator.py`, `app/core/node_executor.py`, `app/core/executor.py`, `app/core/conditions.py`, `app/core/events.py`, `app/core/runtime_backend.py` |
| 7 | Observability & Storage | pending | `app/core/checkpoint.py`, `app/core/pipeline_cache.py`, `app/core/artifact_store.py`, `app/core/artifact_serializer.py`, `app/core/run_journal.py`, `app/core/run_control.py`, `app/core/provenance.py`, `app/core/logger.py` |
| 8 | Platform Infra | pending | `app/core/config.py`, `app/core/validation.py`, `app/core/webhook.py`, `app/core/errors.py`, `app/core/utils/hash.py` |
| 9 | SDK & CLI | pending | `app/core/sdk.py`, `app/cli/main.py` |
| 10 | API | pending | `app/api/main.py`, `app/api/routers/pipelines.py`, `app/api/routers/runs.py`, `app/api/routers/artifacts.py`, `app/api/routers/run_control.py`, `app/api/routers/nodes.py`, `app/api/routers/plugins.py` |
| 11 | MCP | pending | `app/mcp/server.py`, `app/mcp/tool_registry.py`, `app/mcp/auth.py`, `app/mcp/handlers/execution.py`, `app/mcp/handlers/provenance.py`, `app/mcp/handlers/optimization.py`, `app/mcp/handlers/graph.py`, `app/mcp/handlers/discovery.py`, `app/mcp/handlers/run_control.py`, `app/mcp/handlers/artifacts.py` |
| 12 | Domain & Models | pending | `app/domain/ingestion.py`, `app/domain/project_manager.py`, `app/domain/quality_checker.py`, `app/models/audio_sample.py`, `app/models/audio_artifact_serializer.py`, `app/models/feature_array.py`, `app/models/model_artifact.py`, `app/models/prediction_result.py`, `app/models/tensor_batch.py`, `app/models/tflite_artifact.py`, `app/models/deployment_artifact.py` |
| 13 | Audio Plugins Batch 1 | pending | `PluginPackage/Audio/audio_classifier/nodes.py`, `PluginPackage/Audio/audio_conditioner/nodes.py`, `PluginPackage/Audio/audio_event_detector/nodes.py`, `PluginPackage/Audio/audio_exporter/nodes.py`, `PluginPackage/Audio/audio_generator/nodes.py`, `PluginPackage/Audio/audio_quality_gate/nodes.py` |
| 14 | Audio Plugins Batch 2 | pending | `PluginPackage/Audio/alignment_node/nodes.py`, `PluginPackage/Audio/audio_annotator/nodes.py`, `PluginPackage/Audio/augmentation_pipeline/nodes.py`, `PluginPackage/Audio/dataset_ingest/nodes.py`, `PluginPackage/Audio/feature_frontend/nodes.py`, `PluginPackage/Audio/input/nodes.py`, `PluginPackage/Audio/output/nodes.py` |
| 15 | Audio Plugins Batch 3 | pending | `PluginPackage/Audio/segmenter/nodes.py`, `PluginPackage/Audio/speaker_separator/nodes.py`, `PluginPackage/Audio/speech_enhancer/nodes.py`, `PluginPackage/Audio/speech_synthesizer/nodes.py`, `PluginPackage/Audio/stream_ingest/nodes.py`, `PluginPackage/Audio/stream_processor/nodes.py`, `PluginPackage/Audio/voice_converter/nodes.py`, `PluginPackage/Audio/environment_simulator/nodes.py` |
| 16 | Common Plugins | pending | `PluginPackage/Common/dataset_balancer/nodes.py`, `PluginPackage/Common/dataset_builder/nodes.py`, `PluginPackage/Common/dataset_versioner/nodes.py`, `PluginPackage/Common/deployment_packager/nodes.py`, `PluginPackage/Common/edge_optimizer/nodes.py`, `PluginPackage/Common/embedding_generator/nodes.py`, `PluginPackage/Common/evaluator/nodes.py`, `PluginPackage/Common/experiment_tracker/nodes.py`, `PluginPackage/Common/multimodal_fusion/nodes.py`, `PluginPackage/Common/realtime_inference/nodes.py`, `PluginPackage/Common/trainer/nodes.py` |

## Group-Specific Focus Areas

These are the extra checks to apply on top of the standard 10 dimensions, per group:

**Group 1 — IR Core:**
- Does `load_ir()` reject malformed JSON gracefully or panic?
- Does `migrate.py` handle unknown version numbers without data loss?
- Is `MappingProxyType` config immutability enforced everywhere it matters?
- Does `yaml_shim.py` handle missing required YAML fields without silent defaults?

**Group 2 — Node Base:**
- Does `Node.process()` contract enforce input/output types at runtime or only at build time?
- Does `retry.py` correctly handle non-retryable exceptions vs retryable ones?
- Does `observers.py` handle observer exceptions without killing the node?
- Does `compat.py` handle Union types, None types, and subclass relationships correctly in all edge cases?

**Group 3 — Registry & Discovery:**
- Does `registry.py` handle concurrent register/unregister safely?
- Does `discovery.py` handle import errors in scanned modules without aborting the whole scan?
- Does `catalogue.py` stay consistent if a node is registered after catalogue is built?
- Does `registry_runtime.py` handle the case where the registry is not yet initialized?

**Group 4 — Plugin Ecosystem:**
- Does `installer.py` handle pip failures, partial installs, and network errors?
- Does `loader.py` handle plugins with syntax errors or missing `__init__.py`?
- Does `manager.py` handle concurrent plugin load/unload safely?
- Does `store.py` handle corrupted state files?
- Does `manifest.py` validate all required fields or silently accept incomplete manifests?

**Group 5 — Planner:**
- Does `_topological_sort()` correctly detect all cycle types (self-loops, 2-node cycles, long cycles)?
- Does `_build()` handle nodes with zero input ports or zero output ports?
- Does `PipelineGraph` handle duplicate node IDs in the IR?
- Does wave computation produce correct results for diamond-shaped DAGs?
- Does config instantiation handle missing required config fields?

**Group 6 — Execution Runtime:**
- Does `orchestrator.py` correctly propagate exceptions from node execution to the caller?
- Does `executor.py` handle the case where one wave node fails — are other wave nodes cancelled?
- Does `node_executor.py` correctly handle nodes that return None from `process()`?
- Does `runtime_backend.py` handle the case where no backend is registered?
- Does `conditions.py` handle malformed condition expressions without crashing the pipeline?
- Does `events.py` handle event source failures without blocking execution?

**Group 7 — Observability & Storage:**
- Does `checkpoint.py` handle partial writes (disk full, process killed mid-write)?
- Does `artifact_store.py` handle hash collisions or corrupted artifact files?
- Does `run_journal.py` handle concurrent writes from parallel wave execution?
- Does `pipeline_cache.py` handle cache key collisions between different graphs?
- Does `provenance.py` handle missing parent run IDs gracefully?
- Does `logger.py` handle log write failures without crashing the pipeline?

**Group 8 — Platform Infra:**
- Does `config.py` handle missing env vars with clear errors vs silent defaults?
- Does `validation.py` cover all IR fields or only a subset?
- Does `webhook.py` handle network failures, timeouts, and non-2xx responses?
- Does `utils/hash.py` produce stable hashes across Python versions and platforms?

**Group 9 — SDK & CLI:**
- Does `sdk.py` correctly surface errors from the execution layer to the caller?
- Does `Pipeline.validate()` catch all the same errors that runtime would catch?
- Does the CLI handle malformed JSON graph files with clear error messages?
- Does the CLI handle keyboard interrupt (Ctrl+C) during a run cleanly?
- Does `cmd_artifacts_replay` correctly handle missing run IDs?

**Group 10 — API:**
- Do streaming endpoints correctly flush and close on error?
- Do all endpoints validate request bodies before touching the execution layer?
- Does the API handle concurrent requests to the same run ID safely?
- Are all 4xx vs 5xx status codes used correctly?
- Does auth middleware correctly reject malformed tokens vs missing tokens?

**Group 11 — MCP:**
- Does each handler correctly validate its input arguments before calling core?
- Does `optimization.py` handle graphs with no parallelism (linear chains)?
- Does `run_control.py` handler handle the case where a run has already completed?
- Does `auth.py` handle token expiry and rotation?
- Does `tool_registry.py` handle duplicate tool registration?

**Group 12 — Domain & Models:**
- Does `ingestion.py` handle corrupted audio files without crashing?
- Does `quality_checker.py` handle edge cases: silence-only audio, clipped audio, mono vs stereo?
- Do all `PortDataType` subclasses correctly implement serialization round-trips?
- Does `audio_artifact_serializer.py` handle all supported audio formats?

**Groups 13–15 — Audio Plugins:**
- Does `process()` validate its inputs before passing to the ML library?
- Does `setup()` handle missing model files or failed downloads gracefully?
- Does the node handle empty audio (zero samples) without crashing?
- Does the node handle very short audio (< minimum frame size) correctly?
- Does the node release GPU/CPU resources if `process()` raises?
- Are all config fields validated before `setup()` is called?

**Group 16 — Common Plugins:**
- Does `trainer/nodes.py` handle training failures (NaN loss, OOM) without corrupting state?
- Does `dataset_builder/nodes.py` handle empty datasets?
- Does `evaluator/nodes.py` handle the case where predictions and labels have different lengths?
- Does `realtime_inference/nodes.py` handle stream interruption?
- Does `experiment_tracker/nodes.py` handle backend unavailability?
