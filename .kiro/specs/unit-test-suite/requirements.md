# Requirements Document

## Introduction

This document specifies requirements for a brand-new `unit_test/` folder at the project root of the Graphyn platform (`/home/meritech/Desktop/newAudio3`). The existing `tests/` folder is outdated and references deleted built-in nodes; it must not be used as a reference. The new suite must cover the fully-migrated plugin architecture: all 29 plugin nodes now live exclusively in `PluginPackage/Audio/` (18 plugins) and `PluginPackage/Common/` (11 plugins). No test may reference deleted built-in node types (`clean`, `normalize`, `split`, `segment`, `augment`, etc.).

The suite is runnable with a single command: `venv/bin/pytest unit_test/`

## Glossary

- **Node**: A processing unit extending `app.core.nodes.base.Node` with typed ports, a Pydantic `Config`, and a `process()` method.
- **NodeRegistry**: Singleton mapping `node_type` strings to `Node` subclasses and `NodeMetadata`. Lives in `app/core/nodes/registry.py`.
- **AutoDiscovery**: Scans directories and registers `Node` / `PortDataType` subclasses into the registry. Lives in `app/core/nodes/discovery.py`.
- **PluginManager**: Single entry point for plugin lifecycle (install, uninstall, enable, disable). Lives in `app/core/plugins/manager.py`.
- **PluginLoader**: Validates manifests, checks compatibility/deps, imports entry points, registers node types. Lives in `app/core/plugins/loader.py`.
- **PluginManifest**: Pydantic model for `plugin.toml`. Lives in `app/core/plugins/manifest.py`.
- **GraphIR**: Versioned, validated, runtime-agnostic JSON pipeline representation. Lives in `app/core/ir/models.py`.
- **PipelineGraph**: Builds a validated DAG from a `PipelineConfig`, computes topological order and execution waves. Lives in `app/core/pipeline.py`.
- **PipelineCache**: Content-addressed cache for node outputs keyed by `(node_type, config, input_hash)`. Lives in `app/core/pipeline_cache.py`.
- **RunManager**: Manages run lifecycle, pause/resume/cancel, checkpoints, artifact registration, and provenance. Lives in `app/core/run_manager.py`.
- **PipelineLogger**: Emits structured JSON events for pipeline and node lifecycle. Lives in `app/core/logger.py`.
- **ArtifactCollection**: Wraps raw pipeline output dict with typed artifact access. Lives in `app/core/sdk.py`.
- **SISO node**: A node with exactly one input port named `"input"` and one output port named `"output"`, using the shorthand `process(self, data)` signature.
- **AudioSample**: Core data model for audio data. Lives in `app/models/audio_sample.py`.
- **FeatureArray**: Core data model for extracted features. Lives in `app/models/feature_array.py`.
- **PortDataType**: Base class for all inter-port data types. Lives in `app/core/nodes/ports.py`.
- **TypeCatalogue**: Maps fully-qualified type names to Python type objects. Lives in `app/core/nodes/catalogue.py`.
- **CompatibilityChecker**: Determines whether an output port type is compatible with an input port type. Lives in `app/core/nodes/compat.py`.
- **RetryPolicy**: Exponential back-off retry configuration for a node. Lives in `app/core/nodes/retry.py`.
- **IRNode**: Specification for a single node in the graph IR. Lives in `app/core/ir/models.py`.
- **IREdge**: A directed edge in the graph IR. Lives in `app/core/ir/models.py`.
- **MCP_Server**: The stdio-transport JSON-RPC server. Lives in `app/mcp/server.py`.
- **TestClient**: FastAPI's synchronous test client used for REST API tests.
- **Hypothesis**: Python property-based testing library used for generating arbitrary inputs.
- **Fixture_Plugin**: A minimal valid plugin created in a `tmp_path` directory for testing plugin lifecycle without touching production plugin directories.


## Linked Documents

| File | Contents |
|---|---|
| `requirements.md` (this file) | Requirements 1–16: infrastructure, node system, registry, IR, SDK, plugins, plugin nodes, API, MCP, CLI, integration, provenance, property-based |
| `requirements-per-file.md` | Requirements 17–25: isolated per-file unit tests for every source file in `app/` |

> **Rule:** Every source file in `app/` and `PluginPackage/` must have at least one corresponding test file in `unit_test/`. Requirements 17–25 define the per-file acceptance criteria.

---

## Requirements

### Requirement 1: Test Suite Infrastructure

**User Story:** As a developer, I want a self-contained `unit_test/` folder at the project root, so that I can run the entire test suite with `venv/bin/pytest unit_test/` without any dependency on the old `tests/` folder.

#### Acceptance Criteria

1. THE Test_Suite SHALL be located at `unit_test/` in the project root and contain a `conftest.py` that sets up shared fixtures: a `function`-scoped `fresh_registry` fixture that creates a new `NodeRegistry` instance and tears it down after each test; a `tmp_plugin_dir` fixture backed by `tmp_path` for plugin installation (the real `plugins/` directory SHALL NOT be modified by any test); and a `make_audio_sample` factory fixture that returns synthetic `AudioSample` objects with configurable `sample_rate` and `data` length.
2. THE Test_Suite SHALL be runnable with `venv/bin/pytest unit_test/` and produce a pass/fail result without hanging.
3. THE Test_Suite SHALL NOT import from or reference the old `tests/` folder.
4. THE Test_Suite SHALL NOT reference deleted built-in node types (`clean`, `normalize`, `split`, `segment`, `augment`, `input`, `export`, `model_trainer`, `model_evaluator`, `tflite_exporter`, `inference`).
5. WHEN a test requires a plugin node type, THE Test_Suite SHALL install the plugin via `PluginManager.install(source, plugins_dir=tmp_plugin_dir)` — where `tmp_plugin_dir` is the `tmp_path`-backed fixture — before asserting on the node type, and SHALL discard the temporary directory after the test completes.
6. THE Test_Suite SHALL apply thread patches via a `function`-scoped autouse fixture in `conftest.py` that uses `unittest.mock.patch` to replace `concurrent.futures.ThreadPoolExecutor.submit` and `threading.Thread.start` with no-op callables returning `None` in any test that creates pipeline, stream, run-manager, or execution objects — to prevent hangs.
7. THE Test_Suite SHALL use `pytest-hypothesis` (Hypothesis library) for all property-based tests.
8. THE Test_Suite SHALL be organized into subdirectories: `unit_test/core/`, `unit_test/api/`, `unit_test/mcp/`, `unit_test/cli/`, `unit_test/plugins/audio/`, `unit_test/plugins/common/`.
9. EACH source file in `app/` SHALL have a corresponding test file in `unit_test/` following the naming convention `test_<module_name>.py` (e.g. `app/core/conditions.py` → `unit_test/core/test_conditions.py`).
10. EACH plugin in `PluginPackage/Audio/` and `PluginPackage/Common/` SHALL have a corresponding test file in `unit_test/plugins/audio/` or `unit_test/plugins/common/`.


### Requirement 2: Node Base System

**User Story:** As a platform developer, I want comprehensive tests for the node base system, so that I can be confident that `Node`, `NodeConfig`, `RetryPolicy`, `CompatibilityChecker`, and port descriptors behave correctly for all valid and invalid inputs.

#### Acceptance Criteria

1. WHEN a `Node` subclass declares a SISO `process(self, data)` method, THE Node_Base SHALL wrap it so that `process({"input": data})` returns `{"output": result}` (SISO wrapper invariant).
2. FOR ALL valid `NodeConfig` subclass instances, THE Node_Base SHALL accept construction from a dict via `Config.model_validate(dict)` and round-trip back to an equivalent dict via `model_dump()` (round-trip property).
3. FOR ALL `NodeConfig` subclasses, WHEN a dict containing an unknown field is passed to `Config.model_validate()`, THE Node_Base SHALL raise `pydantic.ValidationError` (extra-field rejection property).
4. FOR ALL valid `RetryPolicy` instances with `backoff_multiplier >= 1.0` and `backoff_seconds >= 0` and any `max_attempts >= 1`, THE RetryPolicy SHALL produce a non-decreasing sequence of wait times across all retry attempts (monotonicity property applies regardless of max_attempts).
5. THE CompatibilityChecker SHALL return `True` for `are_compatible(T, T)` for any non-None type `T` (reflexivity property).
6. WHEN `are_compatible(output_type, input_type)` returns `False`, THE CompatibilityChecker SHALL raise `NodeTypeError` when `check_connection()` is called with those port types (consistency property).
7. THE Node_Base SHALL call lifecycle hooks in the order `setup → on_start → process → on_end` for a successful execution, and `on_error` when `process()` raises (lifecycle ordering invariant).
8. WHEN `Node._is_siso()` returns `True`, THE Node_Base SHALL expose `input_type` and `output_type` properties without raising `AttributeError`.
9. IF a `Node` subclass has no `metadata` ClassVar, THEN THE AutoDiscovery SHALL raise `NodeMetadataError` when attempting to register it.


### Requirement 3: Registry and Discovery

**User Story:** As a platform developer, I want tests for `NodeRegistry`, `AutoDiscovery`, and `TypeCatalogue`, so that I can be confident that node registration, lookup, and type resolution are correct and that duplicate registrations are properly rejected.

#### Acceptance Criteria

1. WHEN `NodeRegistry.register(node_type, cls, meta)` is called on a `fresh_registry` instance, THE NodeRegistry SHALL make `node_type in registry` return `True` and `get_class(node_type)` return `cls` (registration invariant).
2. WHEN `NodeRegistry.unregister(node_type)` is called on a `fresh_registry` instance, THE NodeRegistry SHALL make `node_type in registry` return `False` (unregistration invariant).
3. WHEN `NodeRegistry.unregister()` is called for a node_type that is not registered, THE NodeRegistry SHALL complete without raising any exception (no-op idempotence).
4. WHEN `NodeRegistry.get_class()` is called for an unregistered node_type, THE NodeRegistry SHALL raise `NodeNotFoundError`.
5. THE NodeRegistry.to_json() output SHALL round-trip through `NodeRegistry.from_json()` and produce an equivalent list of `NodeMetadata` objects (serialization round-trip property).
6. WHEN `TypeCatalogue.register(cls)` is called and then `TypeCatalogue.resolve(fqn(cls))` is called, THE TypeCatalogue SHALL return the same class (round-trip property).
7. WHEN `TypeCatalogue.register(cls)` is called twice for the same class, THE TypeCatalogue SHALL raise `DuplicatePortTypeError` on the second call.
8. WHEN `AutoDiscovery` scans a directory containing a valid `Node` subclass with a `metadata` ClassVar, THE AutoDiscovery SHALL register that node_type in the `fresh_registry` instance passed to it.
9. WHEN `AutoDiscovery` encounters two different `Node` subclasses resolving to the same `node_type`, THE AutoDiscovery SHALL raise `DuplicateNodeTypeError`.
10. THE `_pascal_to_snake` function SHALL strip the `_node` suffix and convert PascalCase to snake_case correctly for all node class names used in the plugin package (e.g. `AudioConditionerNode` → `audio_conditioner`, `AlignmentNode` → `alignment_node`).


### Requirement 4: Graph IR and Pipeline Execution

**User Story:** As a platform developer, I want tests for the Graph IR models, pipeline DAG construction, topological sort, and the `NodeExecutor` lifecycle, so that I can be confident that pipelines are built and executed correctly.

#### Acceptance Criteria

1. FOR ALL valid `GraphIR` objects, THE IR_Loader SHALL produce an equivalent `GraphIR` when `load_ir(dump_ir(graph))` is called (IR round-trip property).
2. WHEN a `GraphIR` is constructed with two `IRNode` objects sharing the same `id`, THE GraphIR SHALL raise `ValueError` during construction (duplicate node ID rejection).
3. WHEN a `GraphIR` is constructed with an `IREdge` referencing a non-existent `src_id` or `dst_id`, THE GraphIR SHALL raise `ValueError` during construction (edge reference integrity).
4. WHEN `IRNode` is constructed with an `id` containing characters outside `[A-Za-z0-9_-]`, THE IRNode SHALL raise `ValueError` (ID format validation).
5. FOR ALL valid acyclic `PipelineGraph` instances, THE PipelineGraph SHALL produce an `execution_order` where every node appears exactly once (completeness invariant).
6. FOR ALL valid acyclic `PipelineGraph` instances, THE PipelineGraph SHALL produce an `execution_order` where for every edge `(A → B)`, node `A` appears before node `B` (topological ordering invariant).
7. WHEN `PipelineGraph` is constructed with a graph containing a cycle, THE PipelineGraph SHALL raise `PipelineGraphError` (cycle detection).
8. WHEN `NodeExecutor.execute()` is called and `process()` raises on the first attempt but succeeds on the second, THE NodeExecutor SHALL return the successful result when `RetryPolicy.max_attempts >= 2` (retry correctness).
9. THE `validate_pipeline()` function SHALL return a list of validated node dicts for a valid pipeline config dict, and raise `ValueError` for configs with unknown node types or invalid node configs.
10. WHEN `Pipeline.from_json(path)` is called on a file written by `Pipeline.to_json(path)`, THE Pipeline SHALL produce a pipeline with the same nodes, edges, and seed (JSON round-trip property).


### Requirement 5: SDK, Cache, Logger, and RunManager

**User Story:** As a platform developer, I want tests for the Python SDK (`Pipeline`, `PipelineNode`, `ArtifactCollection`), `PipelineCache`, `PipelineLogger`, and `RunManager`, so that I can be confident that the developer-facing API and backend services behave correctly.

#### Acceptance Criteria

1. WHEN `PipelineNode` is constructed with an unknown `node_type`, THE PipelineNode SHALL raise `ValueError` listing available types.
2. WHEN `PipelineNode` is constructed with a `config` dict containing an invalid field for that node type, THE PipelineNode SHALL raise `ValueError`.
3. THE `PipelineCache.key()` function SHALL return the same string for identical `(node_type, config, input_hash)` inputs on repeated calls (determinism property).
4. FOR ALL JSON-serializable output dicts, THE PipelineCache SHALL produce an equivalent dict when `load(key)` is called after `save(key, outputs)` (cache round-trip property).
5. WHEN `PipelineCache.clear()` is called, THE PipelineCache SHALL return a dict with `entries_deleted >= 0` and `bytes_freed >= 0`, and subsequent `has(key)` calls SHALL return `False` for all previously cached keys (clear idempotence).
6. WHEN `PipelineLogger.pipeline_start(N)` is called, THE PipelineLogger SHALL append an entry with `type="pipeline_start"` and `total_nodes=N` to `self.logs`.
7. WHEN `PipelineLogger.node_end()` is called, THE PipelineLogger SHALL append an entry with `type="node_end"` to `self.logs`.
8. WHEN `RunManager.pause()` is called, THE RunManager SHALL set `is_paused` to `True`; WHEN `RunManager.resume()` is called, THE RunManager SHALL set `is_paused` to `False` (state machine invariant).
9. WHEN `RunManager.cancel()` is called, THE RunManager SHALL set `is_cancelled` to `True` regardless of prior pause/resume state (cancel idempotence property).
10. WHEN `ArtifactCollection.__getitem__(key)` is called with a key present in the raw output dict, THE ArtifactCollection SHALL return the same value as the raw dict (backward-compatibility invariant).
11. THE `Pipeline.subscribe()` method SHALL return an unsubscribe callable; WHEN the unsubscribe callable is called, THE Pipeline SHALL stop forwarding events to that callback.


### Requirement 6: Plugin Ecosystem

**User Story:** As a platform developer, I want tests for `PluginManifest`, `PluginManager`, `PluginLoader`, and `PluginStore`, so that I can be confident that the plugin install/uninstall/enable/disable lifecycle is correct and that manifest validation rejects malformed manifests.

#### Acceptance Criteria

1. FOR ALL valid manifest dicts (valid slug name, PEP 440 version, non-empty entry_points ending in `.py`), THE PluginManifest SHALL construct without raising any exception (valid manifest acceptance property).
2. WHEN a manifest dict contains a `name` that does not match `^[a-z][a-z0-9_-]*$`, THE PluginManifest SHALL raise `PluginManifestError` (slug validation property).
3. WHEN a manifest dict contains a `version` that is not a valid PEP 440 version string, THE PluginManifest SHALL raise `PluginManifestError`.
4. WHEN a manifest dict contains an `entry_points` list where any item does not end with `.py`, THE PluginManifest SHALL raise `PluginManifestError`.
5. WHEN `PluginManager.install(source, plugins_dir=tmp_plugin_dir)` is called with a valid `Fixture_Plugin` directory created under `tmp_path`, THE PluginManager SHALL register the plugin's node types in the `fresh_registry` and persist a `PluginRecord` with `enabled=True` inside `tmp_plugin_dir`; the real `plugins/` directory SHALL NOT be modified.
6. WHEN `PluginManager.install(source, plugins_dir=tmp_plugin_dir)` is called twice for the same plugin without `upgrade=True`, THE PluginManager SHALL raise `PluginAlreadyInstalledError` on the second call.
7. WHEN `PluginManager.uninstall(name, plugins_dir=tmp_plugin_dir)` is called after a successful install, THE PluginManager SHALL remove the plugin's node types from the registry and delete the `PluginRecord` from `tmp_plugin_dir`.
8. WHEN `PluginManager.disable(name, plugins_dir=tmp_plugin_dir)` is called, THE PluginManager SHALL unload the plugin's node types from the registry and update the `PluginRecord` with `enabled=False`.
9. WHEN `PluginManager.enable(name, plugins_dir=tmp_plugin_dir)` is called on a disabled plugin, THE PluginManager SHALL reload the plugin's node types into the registry and update the `PluginRecord` with `enabled=True`.
10. WHEN `PluginManager.uninstall(name, plugins_dir=tmp_plugin_dir)` is called for a plugin that is not installed, THE PluginManager SHALL raise `PluginNotFoundError`.
11. WHEN `PluginManager.load_enabled_plugins()` is called and one plugin fails to load, THE PluginManager SHALL log a WARNING and continue loading remaining plugins without raising an exception (fault isolation invariant).


### Requirement 7: Audio Plugin Node Registration

**User Story:** As a plugin developer, I want tests that verify all 18 Audio plugins register their node types correctly after installation, so that I can be confident the plugin package is complete and functional.

#### Acceptance Criteria

1. WHEN `PluginManager.install("PluginPackage/Audio/audio_conditioner/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"audio_conditioner"` in the registry.
2. WHEN `PluginManager.install("PluginPackage/Audio/feature_frontend/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"feature_frontend"` in the registry.
3. WHEN `PluginManager.install("PluginPackage/Audio/dataset_ingest/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"dataset_ingest"` in the registry.
4. WHEN `PluginManager.install("PluginPackage/Audio/stream_ingest/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"stream_ingest"` in the registry.
5. WHEN `PluginManager.install("PluginPackage/Audio/audio_quality_gate/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"audio_quality_gate"` in the registry.
6. WHEN `PluginManager.install("PluginPackage/Audio/segmenter/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"segmenter"` in the registry.
7. WHEN `PluginManager.install("PluginPackage/Audio/audio_annotator/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"audio_annotator"` in the registry.
8. WHEN `PluginManager.install("PluginPackage/Audio/alignment_node/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"alignment_node"` in the registry.
9. WHEN `PluginManager.install("PluginPackage/Audio/speech_enhancer/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"speech_enhancer"` in the registry.
10. WHEN `PluginManager.install("PluginPackage/Audio/speaker_separator/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"speaker_separator"` in the registry.
11. WHEN `PluginManager.install("PluginPackage/Audio/environment_simulator/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"environment_simulator"` in the registry.
12. WHEN `PluginManager.install("PluginPackage/Audio/augmentation_pipeline/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"augmentation_pipeline"` in the registry.
13. WHEN `PluginManager.install("PluginPackage/Audio/audio_event_detector/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"audio_event_detector"` in the registry.
14. WHEN `PluginManager.install("PluginPackage/Audio/audio_classifier/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"audio_classifier"` in the registry.
15. WHEN `PluginManager.install("PluginPackage/Audio/speech_synthesizer/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"speech_synthesizer"` in the registry.
16. WHEN `PluginManager.install("PluginPackage/Audio/voice_converter/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"voice_converter"` in the registry.
17. WHEN `PluginManager.install("PluginPackage/Audio/audio_generator/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"audio_generator"` in the registry.
18. WHEN `PluginManager.install("PluginPackage/Audio/stream_processor/", plugins_dir=tmp_plugin_dir)` is called on a `fresh_registry`, THE PluginManager SHALL register `"stream_processor"` in the registry.
19. WHEN all 18 Audio plugins are installed into a single `module`-scoped `tmp_plugin_dir` fixture shared across criteria 1–18, THE NodeRegistry SHALL contain at least 18 Audio plugin node types with correct `NodeMetadata` (label, category, version, capability fields); additional plugins beyond the core 18 are permitted.


### Requirement 8: Common Plugin Node Registration

**User Story:** As a plugin developer, I want tests that verify all 11 Common plugins register their node types correctly after installation, so that I can be confident the cross-domain plugin package is complete and functional.

#### Acceptance Criteria

1. WHEN `PluginManager.install("PluginPackage/Common/dataset_builder/")` is called, THE PluginManager SHALL register `"dataset_builder"` in the registry.
2. WHEN `PluginManager.install("PluginPackage/Common/trainer/")` is called, THE PluginManager SHALL register `"trainer"` in the registry.
3. WHEN `PluginManager.install("PluginPackage/Common/evaluator/")` is called, THE PluginManager SHALL register `"evaluator"` in the registry.
4. WHEN `PluginManager.install("PluginPackage/Common/edge_optimizer/")` is called, THE PluginManager SHALL register `"edge_optimizer"` in the registry.
5. WHEN `PluginManager.install("PluginPackage/Common/realtime_inference/")` is called, THE PluginManager SHALL register `"realtime_inference"` in the registry.
6. WHEN `PluginManager.install("PluginPackage/Common/dataset_balancer/")` is called, THE PluginManager SHALL register `"dataset_balancer"` in the registry.
7. WHEN `PluginManager.install("PluginPackage/Common/dataset_versioner/")` is called, THE PluginManager SHALL register `"dataset_versioner"` in the registry.
8. WHEN `PluginManager.install("PluginPackage/Common/experiment_tracker/")` is called, THE PluginManager SHALL register `"experiment_tracker"` in the registry.
9. WHEN `PluginManager.install("PluginPackage/Common/deployment_packager/")` is called, THE PluginManager SHALL register `"deployment_packager"` in the registry.
10. WHEN `PluginManager.install("PluginPackage/Common/embedding_generator/")` is called, THE PluginManager SHALL register `"embedding_generator"` in the registry.
11. WHEN `PluginManager.install("PluginPackage/Common/multimodal_fusion/")` is called, THE PluginManager SHALL register `"multimodal_fusion"` in the registry.
12. WHEN all 11 Common plugins are installed, THE NodeRegistry SHALL contain exactly 11 Common plugin node types (counting only Common plugins) with correct `NodeMetadata` (label, category, version, capability fields); registration SHALL be rejected if metadata is invalid.


### Requirement 9: Audio Plugin Node Correctness

**User Story:** As a plugin developer, I want property-based and unit tests for the core Audio plugin nodes, so that I can be confident that conditioning, feature extraction, segmentation, augmentation, and quality gating produce correct outputs for arbitrary valid inputs.

#### Acceptance Criteria

1. FOR ALL valid `AudioSample` inputs with non-zero data, WHEN `AudioConditionerNode` processes them with `target_sample_rate=R`, THE AudioConditionerNode SHALL produce output samples where `sample_rate == R` (sample rate invariant property).
2. FOR ALL valid `AudioSample` inputs, WHEN `AudioConditionerNode` processes them with `mono=True`, THE AudioConditionerNode SHALL produce output samples where `data.ndim == 1` (mono invariant property).
3. FOR ALL valid `AudioSample` inputs with non-zero data, WHEN `AudioConditionerNode` processes them with `normalize=True` and `normalize_method="peak"` and `limiter=True`, THE AudioConditionerNode SHALL produce output samples where `max(abs(data)) <= 1.0 + 1e-5` to account for floating-point precision in audio processing (clipping protection invariant property).
4. WHEN `AudioConditionerNode` processes a list of N samples with `skip_clipped=False`, THE AudioConditionerNode SHALL produce at most N output samples (output count invariant).
5. WHEN `AudioConditionerNode` processes a sample with `compress=True`, THE AudioConditionerNode SHALL add `"conditioning"` key to `sample.metadata` containing `"compress": True` (metadata propagation invariant).
6. FOR ALL valid `AudioSample` inputs with sufficient length, WHEN `FeatureFrontendNode` processes them with `feature_type="mfcc"` and `n_mfcc=N`, THE FeatureFrontendNode SHALL produce `FeatureArray` objects where `data.shape[1] == N` (MFCC dimension invariant property).
7. FOR ALL valid `AudioSample` inputs with sufficient length, WHEN `FeatureFrontendNode` processes them with `feature_type="zcr"`, THE FeatureFrontendNode SHALL produce `FeatureArray` objects where `data.shape[0] == 1` (ZCR shape invariant property).
8. FOR ALL valid `AudioSample` inputs with duration > `segment_length_s`, WHEN `SegmenterNode` processes them with `mode="fixed"` and `segment_length_s=L`, THE SegmenterNode SHALL produce output segments where each segment has `metadata["start"]` and `metadata["end"]` keys (segment metadata invariant property).
9. WHEN `SegmenterNode` processes a sample in `mode="fixed"`, THE SegmenterNode SHALL produce output segments where `metadata["parent"]` equals the original sample's path (parent reference invariant).
10. WHEN `AugmentationPipelineNode` processes N input samples with at least one augmentation enabled, THE AugmentationPipelineNode SHALL produce at least N output samples (augmentation count lower bound invariant).
11. WHEN `AudioQualityGateNode` processes a clipped sample (max amplitude > 1.0) with `rejection_policy="skip"`, THE AudioQualityGateNode SHALL place the sample in the `"rejected"` output port and not in the `"output"` port (rejection routing invariant).
12. WHEN `AudioQualityGateNode` processes a sample that passes all quality checks, THE AudioQualityGateNode SHALL set `metadata["quality_passed"] = True` on the output sample (quality metadata invariant).


### Requirement 10: Common Plugin Node Correctness

**User Story:** As a plugin developer, I want unit tests for the core Common plugin nodes, so that I can be confident that dataset building, balancing, versioning, and embedding generation produce structurally correct outputs.

#### Acceptance Criteria

1. WHEN `DatasetBuilderNode` processes a `DatasetArtifact`-compatible input with N total samples and `split_ratios` summing to 1.0, THE DatasetBuilderNode SHALL produce a `DatasetArtifact` where `len(X_train) + len(X_val) + len(X_test) == N` (split size preservation invariant).
2. WHEN `DatasetBuilderNode` processes an input with `output_format="numpy"`, THE DatasetBuilderNode SHALL produce a `DatasetArtifact` where `X_train` is a numpy array (output format invariant).
3. WHEN `DatasetVersionerNode` processes the same `DatasetArtifact` twice, THE DatasetVersionerNode SHALL produce the same SHA-256 hash both times (determinism property).
4. WHEN `DatasetBalancerNode` processes a `DatasetArtifact` with `strategy="oversample"`, THE DatasetBalancerNode SHALL produce a `DatasetArtifact` where the training split has at least as many samples as the input (oversample size invariant).
5. WHEN `EmbeddingGeneratorNode` processes a list of `AudioSample` objects with a fixed `model` config, THE EmbeddingGeneratorNode SHALL produce `EmbeddingVector` objects where all embeddings have the same shape (embedding dimension consistency invariant).
6. WHEN `MultimodalFusionNode` processes inputs with `fusion_strategy="concat"` and audio embedding dimension A and text embedding dimension T, THE MultimodalFusionNode SHALL produce an output embedding (output existence invariant).
7. WHEN `ExperimentTrackerNode` processes a `ModelArtifact` input, THE ExperimentTrackerNode SHALL produce an `ExperimentArtifact` with a non-empty `run_id` field (artifact creation invariant).
8. WHEN `StreamProcessorNode` processes a list of `AudioSample` objects with `window_ms=W` and `hop_ms=H`, THE StreamProcessorNode SHALL produce output chunks where each chunk has duration approximately `W` milliseconds (window size invariant).


### Requirement 11: REST API Endpoints

**User Story:** As an API consumer, I want integration tests for all REST API routers using FastAPI's `TestClient`, so that I can be confident that the API returns correct status codes, response shapes, and error messages.

#### Acceptance Criteria

1. WHEN `GET /api/v1/nodes` is called, THE API SHALL return HTTP 200 with a JSON array where each element contains `node_type`, `label`, `category`, `capability_metadata`, `input_ports`, and `output_ports` fields.
2. WHEN `GET /api/v1/nodes/{node_type}` is called with a registered node type, THE API SHALL return HTTP 200 with a response containing a `capability_metadata` object with all 10 capability fields.
3. WHEN `GET /api/v1/nodes/{node_type}` is called with an unregistered node type, THE API SHALL return HTTP 404.
4. WHEN `POST /api/v1/nodes/{node_type}/validate-config` is called with a valid config body, THE API SHALL return HTTP 200 with `{"valid": true, "errors": {}}`.
5. WHEN `POST /api/v1/nodes/{node_type}/validate-config` is called with an invalid config body, THE API SHALL return HTTP 200 with `{"valid": false, "errors": {...}}` containing at least one error entry.
6. WHEN `POST /api/v1/pipelines/validate` is called with a valid IR JSON body containing `schema_version`, THE API SHALL return HTTP 200 with `{"valid": true}`.
7. WHEN `POST /api/v1/pipelines/validate` is called with an IR JSON body referencing an unknown node type, THE API SHALL return HTTP 200 with `{"valid": false, "error": "..."}`.
8. WHEN `GET /api/v1/system/health` is called, THE API SHALL return HTTP 200 with `{"status": "ok"}`.
9. WHEN `GET /api/v1/plugins` is called, THE API SHALL return HTTP 200 with a JSON array (empty or populated).
10. WHEN `POST /api/v1/plugins/install` is called with a valid local plugin source, THE API SHALL return HTTP 200 with a response containing `"status": "installed"` and the plugin `"name"`.
11. WHEN `DELETE /api/v1/plugins/{name}` is called for an installed plugin and the deletion succeeds, THE API SHALL return HTTP 200 with `{"name": ..., "status": "uninstalled"}`.
12. WHEN `DELETE /api/v1/plugins/{name}` is called for a plugin that is not installed, THE API SHALL return HTTP 404.
13. WHEN `GET /api/v1/types` is called, THE API SHALL return HTTP 200 with a JSON array of fully-qualified port data type name strings.
14. WHEN `GET /api/v1/runs` is called, THE API SHALL return HTTP 200 with a JSON array (empty or populated with run metadata objects).


### Requirement 12: MCP Server Handlers

**User Story:** As an MCP client developer, I want tests for all MCP tool handlers, so that I can be confident that the handlers return correct structured JSON responses and proper error types for all dispatch paths.

#### Acceptance Criteria

1. WHEN `execute_pipeline_handler` is called with a valid `GraphIR` dict, THE execute_pipeline_handler SHALL return a dict containing `"run_id"` and `"status": "started"` within 500 ms; the test SHALL apply `unittest.mock.patch` to replace `concurrent.futures.ThreadPoolExecutor.submit` with a no-op callable returning `None` before invoking the handler, to prevent actual background execution.
2. WHEN `execute_pipeline_handler` is called with an invalid `GraphIR` dict (e.g. duplicate node IDs), THE execute_pipeline_handler SHALL return `{"valid": false, "errors": [...]}`.
3. WHEN the `list_nodes` handler is called with no arguments, THE list_nodes_handler SHALL return a list of all registered node metadata dicts.
4. WHEN the `list_nodes` handler is called with `{"category": "Preprocessing"}`, THE list_nodes_handler SHALL return only nodes whose `category` field equals `"Preprocessing"`.
5. WHEN the `list_nodes` handler is called with `{"capability_filter": {"invalid_key": true}}`, THE list_nodes_handler SHALL return `{"error_type": "invalid_filter_key"}`.
6. WHEN the `list_nodes` handler is called with `{"list_types": true}`, THE list_nodes_handler SHALL return `{"port_data_types": [...]}`.
7. WHEN the `validate_graph` handler is called with a valid IR JSON dict, THE validate_graph_handler SHALL return `{"valid": true}`.
8. WHEN the `validate_graph` handler is called with an invalid IR JSON dict, THE validate_graph_handler SHALL return `{"error_type": "ir_validation_error", ...}`.
9. WHEN the `pause_run` handler is called with a `run_id` that is not in the active run registry, THE pause_run_handler SHALL return `{"error_type": "run_not_active"}`.
10. WHEN the `inspect_run` handler is called with no `run_id` argument, THE inspect_run_handler SHALL return a dict containing a `"runs"` key with a list value.
11. WHEN the `get_graph_capability_summary` handler is called with a valid graph containing nodes with known capability metadata, THE get_graph_capability_summary_handler SHALL return a dict containing `any_requires_gpu`, `all_support_cpu`, `all_support_edge`, `all_deterministic`, and `any_batch_support` fields.
12. WHEN an MCP tool handler is called with a `_meta.auth_token` that does not match `GRAPHYN_API_TOKEN` (when the token is set), THE handler SHALL return `{"error_type": "unauthorized"}`.


### Requirement 13: CLI Commands

**User Story:** As a CLI user, I want tests for the `run`, `validate`, `migrate`, `list-nodes`, and `plugins` CLI commands using Click's test runner, so that I can be confident that the CLI produces correct output and exit codes.

#### Acceptance Criteria

1. WHEN the `list-nodes` CLI command is invoked, THE CLI SHALL exit with code 0, print a list of registered node types to stdout, and SHALL NOT print any error messages.
2. WHEN the `validate` CLI command is invoked with a path to a valid IR JSON file, THE CLI SHALL exit with code 0 and print a success message.
3. WHEN the `validate` CLI command is invoked with a path to an IR JSON file referencing an unknown node type, THE CLI SHALL exit with a non-zero code, print an error message, and SHALL NOT print any success message.
4. WHEN the `plugins` CLI command is invoked with the `list` subcommand, THE CLI SHALL exit with code 0 and print the list of installed plugins (empty or populated).
5. WHEN the `run` CLI command is invoked with a valid IR JSON graph argument, THE CLI SHALL exit with code 0 after pipeline execution completes (using a minimal single-node graph with a mocked node).
6. WHEN the `migrate` CLI command is invoked with a valid YAML pipeline file, THE CLI SHALL exit with code 0 and produce an IR JSON output file.


### Requirement 14: Pipeline Integration Tests

**User Story:** As a platform developer, I want end-to-end integration tests that run real multi-node pipelines using installed plugin nodes, so that I can be confident that the full execution path from `Pipeline.run()` through `NodeExecutor` to `ArtifactCollection` works correctly.

#### Acceptance Criteria

1. WHEN a two-node pipeline `[audio_conditioner → feature_frontend]` is executed via `Pipeline.run(use_cache=False)` with synthetic `AudioSample` inputs, THE Pipeline SHALL complete without raising an exception and return an `ArtifactCollection`.
2. WHEN a pipeline is executed with `use_cache=True` and then executed again with identical inputs, THE Pipeline SHALL return results from cache on the second execution (cache hit integration test).
3. WHEN a pipeline is executed with `checkpoint=True`, THE Pipeline SHALL write `resume_state.json` and per-node checkpoint directories under the run directory.
4. WHEN a pipeline containing a node that raises on first attempt is executed with a `RetryPolicy(max_attempts=2)`, THE Pipeline SHALL succeed on the second attempt and return a valid `ArtifactCollection`; WHILE no nodes fail, THE Pipeline SHALL succeed immediately without waiting for any retry delay.
5. WHEN a pipeline with a cycle in its edge definitions is constructed, THE Pipeline SHALL raise `PipelineGraphError` before execution begins.
6. WHEN `Pipeline.run()` is called with `parallel=True` on a pipeline with independent nodes, THE Pipeline SHALL complete without raising an exception and return an `ArtifactCollection`.
7. WHEN `Pipeline.subscribe(callback)` is called before `Pipeline.run()`, THE Pipeline SHALL invoke the callback with at least one event dict containing a `"type"` key during execution.


### Requirement 15: Provenance and Artifact Store

**User Story:** As a platform developer, I want tests for `ArtifactStore` and `ProvenanceStore`, so that I can be confident that artifact registration, content-addressing, and lineage tracking are correct.

#### Acceptance Criteria

1. WHEN `RunManager.register_artifact()` is called with a node output, THE RunManager SHALL return an `ArtifactRecord` with a non-empty `artifact_id` and the correct `node_type` and `artifact_type` fields.
2. WHEN `RunManager.register_artifact()` is called twice with identical data, THE RunManager SHALL return `ArtifactRecord` objects with the same `artifact_id` (content-addressing idempotence property).
3. WHEN `RunManager.get_provenance_summary()` is called after registering N artifacts, THE RunManager SHALL return a dict where `len(artifacts) == N`.
4. WHEN `ArtifactCollection.lineage(artifact_id)` is called for any artifact ID (registered or unknown), THE ArtifactCollection SHALL return a dict without raising an exception; WHEN no lineage exists for the given ID, THE ArtifactCollection SHALL return an empty dict or an error-node dict.
5. WHEN `RunManager.save_graph_ir(graph_data)` is called, THE RunManager SHALL atomically write a `graph.json` file to the run directory and set `_graph_hash` to a non-empty SHA-256 hex string; IF either the file write or hash computation fails, THE RunManager SHALL roll back all changes and raise an exception.


### Requirement 16: Property-Based Test Correctness Properties

**User Story:** As a platform developer, I want Hypothesis-driven property-based tests for the most critical correctness properties, so that I can discover edge cases that example-based tests would miss.

#### Acceptance Criteria

1. FOR ALL pairs of `(node_type: str, config: dict, input_hash: str)`, THE PipelineCache SHALL produce the same cache key when `PipelineCache.key()` is called multiple times (determinism property — Hypothesis generates arbitrary strings and dicts).
2. FOR ALL valid `GraphIR` objects constructable from Hypothesis-generated node lists and edge lists, THE IR_Loader SHALL satisfy `load_ir(dump_ir(graph)) == load_ir(dump_ir(load_ir(dump_ir(graph))))` (idempotent round-trip property).
3. FOR ALL valid `RetryPolicy` instances with `max_attempts >= 1`, `backoff_seconds >= 0`, and `backoff_multiplier >= 1.0`, THE RetryPolicy SHALL produce wait times where `wait_before_attempt(i+1) >= wait_before_attempt(i)` for all valid `i` (monotonicity property applies regardless of max_attempts — Hypothesis generates valid policy parameters).
4. FOR ALL `NodeConfig` subclass instances constructable from their declared fields, THE NodeConfig SHALL satisfy `Config.model_validate(instance.model_dump()) == instance` (config round-trip property — Hypothesis generates valid field values).
5. FOR ALL valid `PluginManifest` dicts with a name matching `^[a-z][a-z0-9_-]*$`, a valid PEP 440 version, and at least one `.py` entry point, THE PluginManifest SHALL construct without raising any exception (valid manifest acceptance property — Hypothesis generates valid manifest dicts).
6. FOR ALL `AudioSample` inputs with non-zero float32 data and `sample_rate > 0`, WHEN `AudioConditionerNode` processes them with `normalize=True`, `normalize_method="peak"`, and `limiter=True`, THE AudioConditionerNode SHALL produce output where `max(abs(data)) <= 1.0 + 1e-5` to account for floating-point precision in audio processing (normalization bound property — Hypothesis generates varied audio arrays).
7. FOR ALL valid acyclic directed graphs representable as `PipelineConfig` objects, THE PipelineGraph SHALL produce an `execution_order` where every node ID appears exactly once (completeness property — Hypothesis generates valid DAG structures).
8. FOR ALL `CompatibilityChecker.are_compatible(T, T)` calls with any non-None Python type `T`, THE CompatibilityChecker SHALL return `True` (reflexivity property — Hypothesis generates type objects from a strategy).

