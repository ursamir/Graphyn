# Requirements Document

## Introduction

AudioBuilder is evolving from a pipeline-based audio dataset preparation tool into a **general-purpose pipeline/workflow engine**. This feature covers two tightly coupled changes:

1. **Node Directory Restructuring** — move all node implementation files out of `app/core/nodes/` into category subfolders (e.g. `app/core/nodes/audio/`, `app/core/nodes/ml/`), while keeping framework/infrastructure files (`base.py`, `registry.py`, `discovery.py`, etc.) in `app/core/nodes/` (or a dedicated `app/core/nodes/core/` subfolder).

2. **Core Philosophy Rebranding** — rename, redescribe, and extend the system so it presents itself as a domain-agnostic workflow engine capable of handling audio processing, ML training/inference, webhooks, web browsing, email dispatch, and any other pipeline workload — not just audio datasets.

The two changes are interdependent: the restructuring creates the physical category layout that the rebranding requires, and the rebranding defines what categories and abstractions must exist.

---

## Glossary

- **Engine**: The renamed system — a general-purpose pipeline/workflow engine (formerly "AudioBuilder").
- **Node**: A self-contained processing unit with typed ports, a Pydantic `Config`, and a `process()` method. Extends `app.core.nodes.base.Node`.
- **Node_Implementation**: A concrete `Node` subclass that performs domain work (e.g. `CleanNode`, `AugmentNode`).
- **Framework_File**: An infrastructure file that defines the node system itself — `base.py`, `registry.py`, `discovery.py`, `catalogue.py`, `compat.py`, `errors.py`, `ports.py`, `config.py`, `metadata.py`, `observers.py`, `retry.py`. These are NOT node implementations.
- **Category_Folder**: A subdirectory of `app/core/nodes/` that groups Node_Implementations by domain (e.g. `audio/`, `ml/`, `io/`, `utility/`).
- **AutoDiscovery**: The class in `discovery.py` that scans directories for `Node` and `PortDataType` subclasses and registers them in the `NodeRegistry`.
- **NodeRegistry**: The singleton that maps `node_type` strings to `Node` subclasses and `NodeMetadata`.
- **PortDataType**: The Pydantic `BaseModel` base class for all data types that flow between node ports.
- **AudioSample**: The existing `PortDataType` subclass for audio clips. Remains valid; becomes one of many possible domain types.
- **Pipeline**: A DAG of connected nodes executed by `run_pipeline()` in `app/core/pipeline.py`.
- **Backward_Compatibility**: The guarantee that existing YAML pipeline configs, SDK calls, and API requests continue to work without modification after this change.
- **Steering_File**: A `.kiro/steering/*.md` file that documents the system for AI-assisted development.

---

## Requirements

### Requirement 1: Separate Framework Files from Node Implementations

**User Story:** As a developer extending the system, I want framework/infrastructure files to be clearly separated from node implementation files, so that I can navigate the codebase without confusing "what the system is built on" with "what the system does."

#### Acceptance Criteria

1. THE Engine SHALL keep all Framework_Files (`base.py`, `registry.py`, `discovery.py`, `catalogue.py`, `compat.py`, `errors.py`, `ports.py`, `config.py`, `metadata.py`, `observers.py`, `retry.py`) in `app/core/nodes/` (the package root), NOT inside any Category_Folder.
2. THE Engine SHALL move all Node_Implementation files out of `app/core/nodes/` into Category_Folders under `app/core/nodes/`.
3. WHEN a developer lists `app/core/nodes/`, THE Engine SHALL present only Framework_Files, `__init__.py`, and Category_Folder subdirectories — no Node_Implementation `.py` files at the package root level.
4. THE Engine SHALL preserve `app/core/nodes/__init__.py` at the package root so that `from app.core.nodes import registry` continues to work.

---

### Requirement 2: Define and Populate Category Folders

**User Story:** As a developer browsing node implementations, I want nodes grouped into meaningful domain categories, so that I can find the right node quickly and understand what domain each node belongs to.

#### Acceptance Criteria

1. THE Engine SHALL create the following Category_Folders under `app/core/nodes/` at the time of this restructuring:
   - `audio/` — all existing audio-specific Node_Implementations (input, clean, augment, process, compress, compose, segment, split, stratified_split, spectrogram, noise_mix, export nodes, mic_input, file_input, file_export, hf_export, tfrecord_export) plus the six absorbed audio nodes from examples/plugins (background_noise_generator, command_validator, duration_filter, speaker_embedder, degradation_pipeline, noise)
   - `ml/` — the ten ML nodes absorbed from `examples/06_speech_commands_e2e/plugins/` (feature_extractor, dataset_builder, model_builder, model_trainer, model_evaluator, tflite_exporter, inference, confusion_matrix_plot, training_curves_plot, feature_visualizer)
2. THE Engine SHALL NOT create `io/` or `utility/` Category_Folders at this time; those folders SHALL be created only when the first node of that type is added in a future change.
3. WHEN a Category_Folder is created, THE Engine SHALL include an `__init__.py` file in that folder so it is a valid Python package.
4. THE Engine SHALL NOT create a `core/` subfolder for Framework_Files; Framework_Files remain directly in `app/core/nodes/`.

---

### Requirement 3: AutoDiscovery Supports Recursive Category Scanning

**User Story:** As a developer adding a new node to a category subfolder, I want AutoDiscovery to find and register it automatically without any manual registration step, so that the zero-configuration discovery model is preserved.

#### Acceptance Criteria

1. WHEN `AutoDiscovery.run()` is called with `nodes_dir="app/core/nodes"`, THE AutoDiscovery SHALL recursively scan all Category_Folders under `nodes_dir` in addition to the root directory.
2. THE AutoDiscovery SHALL skip Framework_Files by name (the existing `_EXCLUDED_FILES` set) regardless of which directory they appear in.
3. THE AutoDiscovery SHALL skip `__init__.py` files in Category_Folders.
4. WHEN a Node_Implementation file is found in a Category_Folder, THE AutoDiscovery SHALL import it using the correct package path (e.g. `app.core.nodes.audio.clean`) so that relative imports within the file resolve correctly.
5. THE AutoDiscovery SHALL preserve existing behaviour for the `plugins_dir` scan (flat directory, no recursion required).
6. IF two Node_Implementation files in different Category_Folders define the same `node_type` string, THEN THE AutoDiscovery SHALL raise `DuplicateNodeTypeError` immediately.

---

### Requirement 4: Backward-Compatible Import Paths

**User Story:** As a developer with existing code that imports node classes directly, I want my imports to continue working after the restructuring, so that I do not need to update every import site immediately.

#### Acceptance Criteria

1. THE Engine SHALL add shim modules at the old flat paths (e.g. `app/core/nodes/clean.py`) that re-export the moved classes and emit a `DeprecationWarning` via `warnings.warn(..., DeprecationWarning, stacklevel=2)` when imported, so that existing import statements of the form `from app.core.nodes.clean import CleanNode` continue to resolve without `ImportError`.
2. THE shim modules SHALL be temporary; they are not permanent aliases and SHALL be removed in a future breaking-change release.
3. THE Engine SHALL NOT break any existing import in `app/core/pipeline.py`, `app/core/validation.py`, `app/core/sdk.py`, `app/cli/main.py`, or `app/api/routers/`.
4. WHEN a developer uses the new canonical import path (e.g. `from app.core.nodes.audio.clean import CleanNode`), THE Engine SHALL resolve it correctly without any deprecation warning.
5. THE Engine SHALL document both the legacy (deprecated) and canonical import paths in the updated `NODE_SYSTEM.md`.

---

### Requirement 5: NodeRegistry and NodeMetadata Remain Unchanged

**User Story:** As a developer using the registry API, I want `node_type` strings, `NodeMetadata`, and all registry methods to remain identical after the restructuring, so that pipeline YAML files and API responses are unaffected.

#### Acceptance Criteria

1. THE NodeRegistry SHALL register all nodes under the same `node_type` strings as before the restructuring (e.g. `"clean"`, `"augment"`, `"stratified_split"`).
2. THE NodeRegistry SHALL return identical `NodeMetadata` objects (same `node_type`, `label`, `description`, `category`, `version`, `tags`, `input_ports`, `output_ports`) for every node after the restructuring.
3. WHEN `registry.list_nodes()` is called, THE NodeRegistry SHALL return the same set of node metadata entries as before the restructuring.
4. THE Engine SHALL NOT change any `node_type` string, `NodeMetadata.category` value, or port definition as part of this restructuring.

---

### Requirement 6: Existing Pipeline YAML Configs Remain Valid

**User Story:** As a user with saved pipeline YAML files, I want my pipelines to run without modification after the restructuring, so that I do not lose any existing work.

#### Acceptance Criteria

1. WHEN `run_pipeline()` is called with a YAML config that was valid before the restructuring, THE Engine SHALL execute it successfully without any changes to the YAML file.
2. THE Engine SHALL NOT change the YAML schema, node type keys, or config field names as part of this restructuring.
3. WHEN `validate_pipeline()` is called with a previously valid YAML config, THE Engine SHALL return the same validation result as before the restructuring.

---

### Requirement 7: Introduce a Generic `DataSample` Base Type

**User Story:** As a developer building non-audio pipelines, I want a domain-agnostic base data type that I can subclass for any domain (text, images, tabular data, HTTP responses, etc.), so that the node system is not structurally tied to audio.

#### Acceptance Criteria

1. THE Engine SHALL introduce a `DataSample` class in `app/models/data_sample.py` that extends `PortDataType` and provides a minimal, domain-agnostic schema: `id: str`, `source: str`, `metadata: dict[str, Any]`. The `id` and `source` fields SHALL have empty-string defaults so that `DataSample()` is constructable without arguments.
2. THE `AudioSample` class SHALL remain in `app/models/audio_sample.py` and SHALL continue to extend `PortDataType` directly (not `DataSample`), preserving full backward compatibility.
3. THE Engine SHALL register `DataSample` in `TypeCatalogue` via AutoDiscovery, alongside `AudioSample`.
4. WHEN a developer subclasses `DataSample` for a new domain (e.g. `TextSample`, `ImageSample`), THE AutoDiscovery SHALL register the subclass in `TypeCatalogue` automatically.
5. THE `DataSample` class SHALL be documented in `docs/NODE_SYSTEM.md` as the recommended base for new domain types.

---

### Requirement 8: Rebrand Product Identity and Documentation

**User Story:** As a user or developer reading the documentation, I want the system to present itself as a general-purpose pipeline/workflow engine, so that I understand it can handle any kind of pipeline — not just audio datasets.

#### Acceptance Criteria

1. THE Engine SHALL update `docs/ARCHITECTURE.md` to describe the system as a general-purpose pipeline/workflow engine, replacing all "audio dataset preparation tool" framing.
2. THE Engine SHALL update `docs/README.md` to reflect the new identity, listing example use cases beyond audio (ML training pipelines, webhook chains, data transformation, etc.).
3. THE Engine SHALL update `docs/NODE_SYSTEM.md` to describe `AudioSample` as one example domain type rather than "the primary data type."
4. THE Engine SHALL update the `.kiro/steering/project-overview.md` steering file to reflect the new identity, updated file map (with Category_Folders), and updated Key Concepts.
5. THE Engine SHALL update the `.kiro/steering/node-catalogue.md` steering file to reflect the new Category_Folder layout and list nodes under their category subfolder paths.
6. THE Engine SHALL update the `.kiro/steering/node-registry.md` steering file to document the recursive scanning behaviour of AutoDiscovery.
7. THE Engine SHALL update the `.kiro/steering/data-models.md` steering file to document `DataSample` alongside `AudioSample`.
8. WHEN any steering file is updated, THE Engine SHALL preserve all existing accurate content and only modify sections that are directly affected by this feature.

---

### Requirement 9: Plugin System Continues to Work

**User Story:** As a plugin author, I want my existing plugins to continue loading and registering without modification after the restructuring, so that I do not need to update plugin code.

#### Acceptance Criteria

1. WHEN `AutoDiscovery` scans the `plugins_dir`, THE AutoDiscovery SHALL continue to use the existing flat-directory scan (no recursion required for plugins).
2. THE Engine SHALL NOT change the plugin authoring contract: a plugin file in `plugins/` that defines a `Node` subclass with a `metadata: ClassVar[NodeMetadata]` SHALL be registered automatically.
3. WHEN `plugins/noise_node.py` has been removed (because `NoiseNode` is now a built-in in `app/core/nodes/audio/`), THE AutoDiscovery SHALL register `NoiseNode` from its new canonical location and the `plugins/` directory SHALL contain no duplicate definition.

---

### Requirement 10: Test Suite Passes After Restructuring

**User Story:** As a developer, I want the full test suite to pass after the restructuring and rebranding, so that I have confidence no regressions were introduced.

#### Acceptance Criteria

1. WHEN `venv/bin/pytest` is run after the restructuring, THE Engine SHALL produce zero test failures attributable to import path changes, missing modules, or AutoDiscovery failures.
2. THE Engine SHALL update any test files that import node classes using the old flat paths to use either the new canonical paths or the backward-compatible re-exports.
3. WHEN `AutoDiscovery.run()` is called in the test environment, THE AutoDiscovery SHALL discover and register all nodes from their new Category_Folder locations.
4. THE Engine SHALL add at least one test that verifies AutoDiscovery correctly scans a Category_Folder and registers the nodes found within it.

---

### Requirement 11: `__init__.py` Discovery Entry Point Updated

**User Story:** As a developer importing `app.core.nodes`, I want the package `__init__.py` to correctly trigger AutoDiscovery across all Category_Folders, so that the singleton registry is fully populated on first import.

#### Acceptance Criteria

1. WHEN `app/core/nodes/__init__.py` is imported, THE Engine SHALL invoke `AutoDiscovery.run()` with the `nodes_dir` pointing to `app/core/nodes/`, and AutoDiscovery SHALL recursively find all nodes in Category_Folders.
2. THE Engine SHALL NOT require any manual listing of Category_Folders in `__init__.py`; new Category_Folders SHALL be discovered automatically by AutoDiscovery.
3. WHEN `from app.core.nodes import registry` is executed, THE registry SHALL contain all nodes from all Category_Folders.

---

### Requirement 12: Category Metadata Alignment

**User Story:** As a frontend developer rendering the node palette, I want `NodeMetadata.category` values to align with the physical Category_Folder names where practical, so that the UI grouping and the filesystem layout are consistent.

#### Acceptance Criteria

1. THE Engine SHALL define a mapping between `NodeMetadata.category` string values and Category_Folder names in the updated `docs/NODE_SYSTEM.md`.
2. WHERE a `NodeMetadata.category` value maps to a Category_Folder, THE Engine SHALL ensure the Node_Implementation file resides in that Category_Folder.
3. THE Engine SHALL NOT change existing `NodeMetadata.category` string values (e.g. `"Preprocessing"`, `"Augmentation"`, `"Splitting"`, `"Export"`) as part of this restructuring, to preserve Backward_Compatibility with API consumers.
4. THE Engine SHALL document in `docs/NODE_SYSTEM.md` that `NodeMetadata.category` is a display label (used by the UI) and is independent of the filesystem Category_Folder name.

---

### Requirement 13: Absorb Example Plugin Nodes into Built-in Categories

**User Story:** As a developer using the system, I want the nodes that were previously scattered across `examples/*/plugins/` and `plugins/` to be first-class built-in nodes, so that they are always available without any plugin directory configuration and use proper absolute imports.

#### Acceptance Criteria

1. THE Engine SHALL move the following six audio-domain nodes into `app/core/nodes/audio/`, rewriting all imports to use absolute package paths (`from app.core.nodes.*` and `from app.models.*`):
   - `BackgroundNoiseGeneratorNode` (`node_type: background_noise_generator`, category: Generation) — from `examples/01_wake_word/plugins/background_noise_generator.py`
   - `CommandValidatorNode` (`node_type: command_validator`, category: Validation) — from `examples/02_speech_commands/plugins/command_validator.py`
   - `DurationFilterNode` (`node_type: duration_filter`, category: Filtering) — from `examples/03_environmental_sounds/plugins/duration_filter.py`
   - `SpeakerEmbedderNode` (`node_type: speaker_embedder`, category: Annotation) — from `examples/04_speaker_verification/plugins/speaker_embedder.py`
   - `DegradationPipelineNode` (`node_type: degradation_pipeline`, category: Augmentation) — from `examples/05_speech_enhancement/plugins/degradation_pipeline.py`
   - `NoiseNode` (`node_type: noise`, category: Augmentation) — from `plugins/noise_node.py`
2. THE Engine SHALL move the following ten ML-domain nodes into `app/core/nodes/ml/`, rewriting all imports to use absolute package paths:
   - `FeatureExtractorNode` (`node_type: feature_extractor`, category: Feature Extraction) — from `examples/06_speech_commands_e2e/plugins/feature_extractor.py`
   - `DatasetBuilderNode` (`node_type: dataset_builder`, category: ML) — from `examples/06_speech_commands_e2e/plugins/dataset_builder.py`
   - `ModelBuilderNode` (`node_type: model_builder`, category: ML) — from `examples/06_speech_commands_e2e/plugins/model_builder.py`
   - `ModelTrainerNode` (`node_type: model_trainer`, category: ML) — from `examples/06_speech_commands_e2e/plugins/model_trainer.py`
   - `ModelEvaluatorNode` (`node_type: model_evaluator`, category: ML) — from `examples/06_speech_commands_e2e/plugins/model_evaluator.py`
   - `TFLiteExporterNode` (`node_type: tflite_exporter`, category: Export) — from `examples/06_speech_commands_e2e/plugins/tflite_exporter.py`
   - `InferenceNode` (`node_type: inference`, category: Inference) — from `examples/06_speech_commands_e2e/plugins/inference_node.py`
   - `ConfusionMatrixNode` (`node_type: confusion_matrix_plot`, category: Visualization) — from `examples/06_speech_commands_e2e/plugins/confusion_matrix_node.py`
   - `TrainingCurvesNode` (`node_type: training_curves_plot`, category: Visualization) — from `examples/06_speech_commands_e2e/plugins/training_curves_node.py`
   - `FeatureVisualizerNode` (`node_type: feature_visualizer`, category: Visualization) — from `examples/06_speech_commands_e2e/plugins/feature_visualizer.py`
3. THE Engine SHALL replace all `importlib.util.spec_from_file_location` lazy-loading patterns used in the example 06 ML nodes (for loading `data_types.py`) with direct absolute imports from `app.models.*` (e.g. `from app.models.feature_array import FeatureArray`).
4. THE Engine SHALL remove the original plugin source files after absorption:
   - `examples/01_wake_word/plugins/background_noise_generator.py`
   - `examples/02_speech_commands/plugins/command_validator.py`
   - `examples/03_environmental_sounds/plugins/duration_filter.py`
   - `examples/04_speaker_verification/plugins/speaker_embedder.py`
   - `examples/05_speech_enhancement/plugins/degradation_pipeline.py`
   - `examples/06_speech_commands_e2e/plugins/feature_extractor.py`, `dataset_builder.py`, `model_builder.py`, `model_trainer.py`, `model_evaluator.py`, `tflite_exporter.py`, `inference_node.py`, `confusion_matrix_node.py`, `training_curves_node.py`, `feature_visualizer.py`, `data_types.py`
   - `plugins/noise_node.py`
5. THE Engine SHALL preserve all `node_type` string values exactly as they were in the original plugin files, so that existing YAML pipeline configs that reference these node types continue to work without modification.
6. WHEN `AutoDiscovery.run()` is called, THE AutoDiscovery SHALL discover and register all absorbed nodes from their new locations in `app/core/nodes/audio/` and `app/core/nodes/ml/` without any manual registration step.

---

### Requirement 14: Absorb ML Data Types into `app/models/`

**User Story:** As a developer building ML pipelines, I want the ML-specific data types (`FeatureArray`, `ModelArtifact`, `TFLiteArtifact`, `PredictionResult`) to live in `app/models/` as proper package modules, so that they are importable via clean absolute paths and registered in `TypeCatalogue` automatically.

#### Acceptance Criteria

1. THE Engine SHALL create the following four model files in `app/models/`, each containing exactly one `PortDataType` subclass migrated from `examples/06_speech_commands_e2e/plugins/data_types.py`:
   - `app/models/feature_array.py` — `FeatureArray`
   - `app/models/model_artifact.py` — `ModelArtifact`
   - `app/models/tflite_artifact.py` — `TFLiteArtifact`
   - `app/models/prediction_result.py` — `PredictionResult`
2. THE Engine SHALL preserve the field definitions, validators, and `model_config` of each migrated class exactly as they appear in the original `data_types.py`, with only the module-level import paths updated to use absolute imports.
3. THE Engine SHALL NOT add `from __future__ import annotations` to any of the four new model files, because Pydantic v2 `model_rebuild()` requires annotations to be evaluated eagerly when the module is loaded via standard import.
4. WHEN `AutoDiscovery` scans `app/models/` (or when the models are imported by the ML nodes), THE TypeCatalogue SHALL register all four types under their fully-qualified names (e.g. `app.models.feature_array.FeatureArray`).
5. THE Engine SHALL delete `examples/06_speech_commands_e2e/plugins/data_types.py` after all four model files have been created and all ML nodes have been updated to import from `app.models.*`.
6. THE Engine SHALL update `app/models/__init__.py` to re-export all six model types (`AudioSample`, `DataSample`, `FeatureArray`, `ModelArtifact`, `TFLiteArtifact`, `PredictionResult`) so that `from app.models import FeatureArray` works.
