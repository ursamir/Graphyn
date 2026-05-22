# Implementation Plan: Node Restructure and Rebrand

## Overview

This implementation restructures `app/core/nodes/` into category subfolders (`audio/`, `ml/`), absorbs 16 example/plugin nodes as built-in nodes, introduces new ML model types in `app/models/`, and rebrands the system as a general-purpose pipeline engine. The implementation follows a 7-phase sequential approach to minimize risk, with each phase leaving the system in a working state.

## Tasks

- [x] 1. Phase 1: Create `app/models/` additions
  - [x] 1.1 Create `app/models/data_sample.py` with `DataSample` class
    - Define `DataSample(PortDataType)` with fields: `id: str = ""`, `source: str = ""`, `metadata: dict[str, Any] = {}`
    - Ensure constructable without arguments
    - _Requirements: 7.1, 7.2_
  
  - [x] 1.2 Create `app/models/feature_array.py` with `FeatureArray` class
    - Migrate from `examples/06_speech_commands_e2e/plugins/data_types.py`
    - Preserve field definitions, validators, and `model_config` exactly
    - Update imports to use absolute paths (`from app.core.nodes.ports import PortDataType`)
    - Do NOT add `from __future__ import annotations`
    - _Requirements: 14.1, 14.2, 14.3_
  
  - [x] 1.3 Create `app/models/model_artifact.py` with `ModelArtifact` class
    - Migrate from `examples/06_speech_commands_e2e/plugins/data_types.py`
    - Preserve all field definitions and validators
    - Update imports to absolute paths
    - _Requirements: 14.1, 14.2_
  
  - [x] 1.4 Create `app/models/tflite_artifact.py` with `TFLiteArtifact` class
    - Migrate from `examples/06_speech_commands_e2e/plugins/data_types.py`
    - Preserve quantisation validator
    - Update imports to absolute paths
    - _Requirements: 14.1, 14.2_
  
  - [x] 1.5 Create `app/models/prediction_result.py` with `PredictionResult` class
    - Migrate from `examples/06_speech_commands_e2e/plugins/data_types.py`
    - Preserve all field definitions
    - Update imports to absolute paths
    - _Requirements: 14.1, 14.2_
  
  - [x] 1.6 Update `app/models/__init__.py` to re-export all six types
    - Import and re-export: `AudioSample`, `DataSample`, `FeatureArray`, `ModelArtifact`, `TFLiteArtifact`, `PredictionResult`
    - Update `__all__` list
    - _Requirements: 14.6_

- [x] 2. Phase 2: Update AutoDiscovery for recursive scanning
  - [x] 2.1 Update `app/core/nodes/discovery.py` to add recursive Category_Folder scanning
    - Modify `run()` method to scan one level of subdirectories (Category_Folders)
    - Identify Category_Folders as subdirectories containing `__init__.py`
    - Scan each Category_Folder with correct package prefix (e.g., `app.core.nodes.audio`)
    - Preserve existing flat-directory scan for `plugins_dir`
    - _Requirements: 3.1, 3.2, 3.3, 3.4_
  
  - [x] 2.2 Add `models_dir` parameter to `AutoDiscovery.run()`
    - Add optional `models_dir` parameter
    - Scan `models_dir` for `PortDataType` subclasses when provided
    - Use package prefix `app.models` for model scanning
    - _Requirements: 3.1, 11.1_
  
  - [x] 2.3 Update `app/core/nodes/__init__.py` to pass `models_dir` to AutoDiscovery
    - Define `_models_dir` pointing to `app/models/`
    - Pass `models_dir=_models_dir` to `AutoDiscovery.run()`
    - _Requirements: 11.1, 11.3_

- [x] 3. Checkpoint - Verify AutoDiscovery changes
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Phase 3: Create audio category folder and move existing audio nodes
  - [x] 4.1 Create `app/core/nodes/audio/__init__.py`
    - Create empty package with docstring: "Audio domain node implementations."
    - _Requirements: 2.3_
  
  - [x] 4.2 Move existing audio node files to `app/core/nodes/audio/`
    - Move 17 files: `augment.py`, `clean.py`, `compose.py`, `compress.py`, `export.py`, `file_export.py`, `file_input.py`, `hf_export.py`, `input.py`, `mic_input.py`, `noise_mix.py`, `process.py`, `segment.py`, `spectrogram.py`, `split.py`, `stratified_split.py`, `tfrecord_export.py`
    - No import changes needed (already use absolute imports)
    - _Requirements: 1.2, 2.1_
  
  - [x] 4.3 Absorb `examples/01_wake_word/plugins/background_noise_generator.py` into `app/core/nodes/audio/`
    - Move file to `app/core/nodes/audio/background_noise_generator.py`
    - Update imports to use absolute paths (`from app.core.nodes.base import Node`, `from app.models.audio_sample import AudioSample`)
    - Preserve `node_type="background_noise_generator"` exactly
    - _Requirements: 13.1, 13.5_
  
  - [x] 4.4 Absorb `examples/02_speech_commands/plugins/command_validator.py` into `app/core/nodes/audio/`
    - Move to `app/core/nodes/audio/command_validator.py`
    - Update imports to absolute paths
    - Preserve `node_type="command_validator"`
    - _Requirements: 13.1, 13.5_
  
  - [x] 4.5 Absorb `examples/03_environmental_sounds/plugins/duration_filter.py` into `app/core/nodes/audio/`
    - Move to `app/core/nodes/audio/duration_filter.py`
    - Update imports to absolute paths
    - Preserve `node_type="duration_filter"`
    - _Requirements: 13.1, 13.5_
  
  - [x] 4.6 Absorb `examples/04_speaker_verification/plugins/speaker_embedder.py` into `app/core/nodes/audio/`
    - Move to `app/core/nodes/audio/speaker_embedder.py`
    - Update imports to absolute paths
    - Preserve `node_type="speaker_embedder"`
    - _Requirements: 13.1, 13.5_
  
  - [x] 4.7 Absorb `examples/05_speech_enhancement/plugins/degradation_pipeline.py` into `app/core/nodes/audio/`
    - Move to `app/core/nodes/audio/degradation_pipeline.py`
    - Update imports to absolute paths
    - Preserve `node_type="degradation_pipeline"`
    - _Requirements: 13.1, 13.5_
  
  - [x] 4.8 Absorb `plugins/noise_node.py` into `app/core/nodes/audio/noise.py`
    - Move to `app/core/nodes/audio/noise.py` (rename file)
    - Update imports to absolute paths
    - Preserve class name `NoiseNode` and `node_type="noise"`
    - _Requirements: 13.1, 13.5_
  
  - [x] 4.9 Create backward-compatibility shim files for all 17 moved audio nodes
    - Create shim at each old path (e.g., `app/core/nodes/augment.py`)
    - Each shim: emit `DeprecationWarning` with `stacklevel=2`, re-export all classes from new location
    - Shims for: `augment.py`, `clean.py`, `compose.py`, `compress.py`, `export.py`, `file_export.py`, `file_input.py`, `hf_export.py`, `input.py`, `mic_input.py`, `noise_mix.py`, `process.py`, `segment.py`, `spectrogram.py`, `split.py`, `stratified_split.py`, `tfrecord_export.py`
    - _Requirements: 4.1, 4.2, 4.4_

- [x] 5. Phase 4: Create ML category folder and absorb ML nodes
  - [x] 5.1 Create `app/core/nodes/ml/__init__.py`
    - Create empty package with docstring: "ML training, inference, and model-management node implementations."
    - _Requirements: 2.3_
  
  - [x] 5.2 Absorb `examples/06_speech_commands_e2e/plugins/feature_extractor.py` into `app/core/nodes/ml/`
    - Move to `app/core/nodes/ml/feature_extractor.py`
    - Replace `_load_data_types()` pattern with `from app.models.feature_array import FeatureArray`
    - Remove `import importlib.util`, `_DATA_TYPES_PATH`, `_load_data_types()`, and `self._dt = _load_data_types()` in `setup()`
    - Preserve `node_type="feature_extractor"`
    - _Requirements: 13.2, 13.3, 13.5_
  
  - [x] 5.3 Absorb `examples/06_speech_commands_e2e/plugins/dataset_builder.py` into `app/core/nodes/ml/`
    - Move to `app/core/nodes/ml/dataset_builder.py`
    - Replace lazy-loading with `from app.models.feature_array import FeatureArray`
    - Remove importlib pattern
    - Preserve `node_type="dataset_builder"`
    - _Requirements: 13.2, 13.3, 13.5_
  
  - [x] 5.4 Absorb `examples/06_speech_commands_e2e/plugins/model_builder.py` into `app/core/nodes/ml/`
    - Move to `app/core/nodes/ml/model_builder.py`
    - No model imports needed (uses `dict` and `object` ports)
    - Remove importlib pattern if present
    - Preserve `node_type="model_builder"`
    - _Requirements: 13.2, 13.5_
  
  - [x] 5.5 Absorb `examples/06_speech_commands_e2e/plugins/model_trainer.py` into `app/core/nodes/ml/`
    - Move to `app/core/nodes/ml/model_trainer.py`
    - Replace lazy-loading with `from app.models.model_artifact import ModelArtifact`
    - Remove importlib pattern
    - Preserve `node_type="model_trainer"`
    - _Requirements: 13.2, 13.3, 13.5_
  
  - [x] 5.6 Absorb `examples/06_speech_commands_e2e/plugins/model_evaluator.py` into `app/core/nodes/ml/`
    - Move to `app/core/nodes/ml/model_evaluator.py`
    - Replace lazy-loading with `from app.models.model_artifact import ModelArtifact`
    - Remove importlib pattern
    - Preserve `node_type="model_evaluator"`
    - _Requirements: 13.2, 13.3, 13.5_
  
  - [x] 5.7 Absorb `examples/06_speech_commands_e2e/plugins/tflite_exporter.py` into `app/core/nodes/ml/`
    - Move to `app/core/nodes/ml/tflite_exporter.py`
    - Replace lazy-loading with `from app.models.model_artifact import ModelArtifact` and `from app.models.tflite_artifact import TFLiteArtifact`
    - Remove importlib pattern
    - Preserve `node_type="tflite_exporter"`
    - _Requirements: 13.2, 13.3, 13.5_
  
  - [x] 5.8 Absorb `examples/06_speech_commands_e2e/plugins/inference_node.py` into `app/core/nodes/ml/`
    - Move to `app/core/nodes/ml/inference_node.py`
    - Replace lazy-loading with `from app.models.feature_array import FeatureArray` and `from app.models.prediction_result import PredictionResult`
    - Remove importlib pattern
    - Preserve `node_type="inference"`
    - _Requirements: 13.2, 13.3, 13.5_
  
  - [x] 5.9 Absorb `examples/06_speech_commands_e2e/plugins/confusion_matrix_node.py` into `app/core/nodes/ml/`
    - Move to `app/core/nodes/ml/confusion_matrix_node.py`
    - Replace lazy-loading with `from app.models.model_artifact import ModelArtifact` (pass-through)
    - Remove importlib pattern
    - Preserve `node_type="confusion_matrix_plot"`
    - _Requirements: 13.2, 13.3, 13.5_
  
  - [x] 5.10 Absorb `examples/06_speech_commands_e2e/plugins/training_curves_node.py` into `app/core/nodes/ml/`
    - Move to `app/core/nodes/ml/training_curves_node.py`
    - Replace lazy-loading with `from app.models.model_artifact import ModelArtifact` (pass-through)
    - Remove importlib pattern
    - Preserve `node_type="training_curves_plot"`
    - _Requirements: 13.2, 13.3, 13.5_
  
  - [x] 5.11 Absorb `examples/06_speech_commands_e2e/plugins/feature_visualizer.py` into `app/core/nodes/ml/`
    - Move to `app/core/nodes/ml/feature_visualizer.py`
    - Replace lazy-loading with `from app.models.feature_array import FeatureArray`
    - Remove importlib pattern
    - Preserve `node_type="feature_visualizer"`
    - _Requirements: 13.2, 13.3, 13.5_

- [x] 6. Phase 5: Clean up source files
  - [x] 6.1 Delete absorbed plugin source files
    - Delete `examples/01_wake_word/plugins/background_noise_generator.py`
    - Delete `examples/02_speech_commands/plugins/command_validator.py`
    - Delete `examples/03_environmental_sounds/plugins/duration_filter.py`
    - Delete `examples/04_speaker_verification/plugins/speaker_embedder.py`
    - Delete `examples/05_speech_enhancement/plugins/degradation_pipeline.py`
    - Delete `plugins/noise_node.py`
    - _Requirements: 13.4_
  
  - [x] 6.2 Delete all example 06 plugin files
    - Delete all files in `examples/06_speech_commands_e2e/plugins/`: `feature_extractor.py`, `dataset_builder.py`, `model_builder.py`, `model_trainer.py`, `model_evaluator.py`, `tflite_exporter.py`, `inference_node.py`, `confusion_matrix_node.py`, `training_curves_node.py`, `feature_visualizer.py`, `data_types.py`, `__init__.py`
    - _Requirements: 13.4, 14.5_

- [x] 7. Checkpoint - Verify all nodes are discovered
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Phase 6: Update tests
  - [x] 8.1 Write property test: AutoDiscovery finds all nodes after restructuring
    - **Property 1: AutoDiscovery finds all nodes after restructuring**
    - **Validates: Requirements 3.1, 3.6, 13.6**
    - Verify `len(registry) >= original_count + 16`
    - Verify all pre-existing `node_type` strings present
    - Verify all 16 absorbed node types present
  
  - [x] 8.2 Write property test: Shim imports emit DeprecationWarning
    - **Property 2: Shim imports emit DeprecationWarning**
    - **Validates: Requirements 4.1, 4.2**
    - Test that importing from old path emits `DeprecationWarning`
    - Verify warning message contains new canonical path
  
  - [x] 8.3 Write property test: Canonical imports do not emit DeprecationWarning
    - **Property 3: Canonical imports do not emit DeprecationWarning**
    - **Validates: Requirements 4.4**
    - Test that importing from new path emits no deprecation warnings
  
  - [x] 8.4 Write property test: node_type strings preserved after absorption
    - **Property 4: node_type strings are preserved after absorption**
    - **Validates: Requirements 5.1, 13.5**
    - Verify each absorbed node's `node_type` matches original exactly
  
  - [x] 8.5 Write property test: ML model types registered in TypeCatalogue
    - **Property 5: ML model types are registered in TypeCatalogue**
    - **Validates: Requirements 14.4**
    - Verify all 6 types registered: `AudioSample`, `DataSample`, `FeatureArray`, `ModelArtifact`, `TFLiteArtifact`, `PredictionResult`
  
  - [x] 8.6 Write property test: DataSample constructable without arguments
    - **Property 6: DataSample is constructable without arguments**
    - **Validates: Requirements 7.1**
    - Test `DataSample()` succeeds with default values
  
  - [x] 8.7 Write property test: No DuplicateNodeTypeError on startup
    - **Property 7: No DuplicateNodeTypeError on startup**
    - **Validates: Requirements 3.6**
    - Verify `AutoDiscovery.run()` completes without raising `DuplicateNodeTypeError`
  
  - [x] 8.8 Write property test: Existing pipeline YAML configs remain valid
    - **Property 8: Existing pipeline YAML configs remain valid**
    - **Validates: Requirements 6.1, 6.3**
    - Test each example YAML config validates successfully
  
  - [x] 8.9 Write property test: app/models/__init__.py re-exports all six types
    - **Property 9: app/models/__init__.py re-exports all six types**
    - **Validates: Requirements 14.6**
    - Test all 6 types importable from `app.models`
  
  - [x] 8.10 Update any test files using old import paths
    - Search for imports from `app.core.nodes.{node_file}` in test files
    - Update to use canonical paths or rely on shims
    - _Requirements: 10.2_

- [x] 9. Phase 7: Update documentation and steering files
  - [x] 9.1 Update `docs/ARCHITECTURE.md`
    - Rebrand as general-purpose pipeline/workflow engine
    - Update file map to show Category_Folders
    - Remove "audio dataset preparation tool" framing
    - _Requirements: 8.1_
  
  - [x] 9.2 Update `docs/README.md`
    - Reflect new identity as domain-agnostic workflow engine
    - List example use cases beyond audio (ML training, webhooks, data transformation)
    - _Requirements: 8.2_
  
  - [x] 9.3 Update `docs/NODE_SYSTEM.md`
    - Document new Category_Folder layout (`audio/`, `ml/`)
    - Document `DataSample` as domain-agnostic base type
    - Document ML types: `FeatureArray`, `ModelArtifact`, `TFLiteArtifact`, `PredictionResult`
    - Describe `AudioSample` as one example domain type
    - Document shim deprecation pattern and timeline
    - Document mapping between `NodeMetadata.category` and Category_Folders
    - _Requirements: 8.3, 8.5, 12.4_
  
  - [x] 9.4 Update `.kiro/steering/project-overview.md`
    - Update file map to show Category_Folders
    - Update Key Concepts to reflect domain-agnostic identity
    - Update node implementations row to reference `audio/` and `ml/` subfolders
    - _Requirements: 8.4_
  
  - [x] 9.5 Update `.kiro/steering/node-catalogue.md`
    - Update all node file paths to show category subfolder paths
    - Add 16 absorbed nodes to the catalogue with their new paths
    - Group nodes by category folder
    - _Requirements: 8.5_
  
  - [x] 9.6 Update `.kiro/steering/node-registry.md`
    - Document recursive Category_Folder scanning behaviour
    - Document `models_dir` parameter in `AutoDiscovery.run()`
    - Update AutoDiscovery flow diagram to show recursive scan
    - _Requirements: 8.6_
  
  - [x] 9.7 Update `.kiro/steering/data-models.md`
    - Add `DataSample` documentation with schema and usage
    - Add ML type documentation: `FeatureArray`, `ModelArtifact`, `TFLiteArtifact`, `PredictionResult`
    - Update `app/models/__init__.py` re-exports section
    - _Requirements: 8.7_

- [x] 10. Final checkpoint - Verify complete system
  - Run full test suite with `venv/bin/pytest`
  - Verify all 9 correctness properties pass
  - Verify example YAML pipelines validate successfully
  - Ensure all tests pass, ask the user if questions arise.

## Phase 8: Remove Shims and Fix All Imports

- [x] 11. Fix all imports from old shim paths
  - [x] 11.1 Update `app/core/nodes/test_process.py` to import from canonical path
    - Changed `from app.core.nodes.process import ...` → `from app.core.nodes.audio.process import ...`
    - Fixed all `node.process([s])` calls to use SISO dict convention `node.process({"input": [s]})`
  - [x] 11.2 Update `tests/test_migration.py` to import from canonical paths
    - Updated all `from app.core.nodes.clean import ...` → `from app.core.nodes.audio.clean import ...`
    - Updated all `from app.core.nodes.augment import ...` → `from app.core.nodes.audio.augment import ...`
    - Updated all `from app.core.nodes.split import ...` → `from app.core.nodes.audio.split import ...`
    - Updated all `from app.core.nodes.stratified_split import ...` → `from app.core.nodes.audio.stratified_split import ...`
    - Updated all `from app.core.nodes.input import ...` → `from app.core.nodes.audio.input import ...`
    - Updated all `from app.core.nodes.mic_input import ...` → `from app.core.nodes.audio.mic_input import ...`
    - Updated all `from app.core.nodes.export import ...` → `from app.core.nodes.audio.export import ...`
    - Updated all `from app.core.nodes.compress import ...` → `from app.core.nodes.audio.compress import ...`
    - Updated all `from app.core.nodes.segment import ...` → `from app.core.nodes.audio.segment import ...`
    - Updated all `from app.core.nodes.spectrogram import ...` → `from app.core.nodes.audio.spectrogram import ...`
    - Updated all `from app.core.nodes.process import ...` → `from app.core.nodes.audio.process import ...`
    - Updated all `from app.core.nodes.compose import ...` → `from app.core.nodes.audio.compose import ...`
    - Updated `test_registry_get_class_works` to use class name/module check instead of `is` identity

- [x] 12. Update `tests/test_node_restructure.py` — remove Property 2 shim tests
  - Removed `TestProperty2ShimImportsEmitDeprecationWarning` class entirely (shims no longer exist)
  - Updated module docstring to reflect removal of Property 2

- [x] 13. Delete all 17 shim files
  - Deleted: `augment.py`, `clean.py`, `compose.py`, `compress.py`, `export.py`, `file_export.py`,
    `file_input.py`, `hf_export.py`, `input.py`, `mic_input.py`, `noise_mix.py`, `process.py`,
    `segment.py`, `spectrogram.py`, `split.py`, `stratified_split.py`, `tfrecord_export.py`
  - Note: `test_process.py` was NOT deleted (it is a test file, not a shim)

- [x] 14. Create `pytest.ini` to fix test collection
  - Added `testpaths = tests app/core/nodes` to resolve module naming conflict

- [x] 15. Run full test suite — verify 441 tests pass
  - `venv/bin/pytest` → 441 passed, 5 warnings

- [x] 16. Update steering files
  - [x] 16.1 Update `node-catalogue.md` — remove shim references
  - [x] 16.2 Update `node-registry.md` — remove shim documentation

## Notes

- Tasks marked with `*` are optional property-based tests and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at phase boundaries
- Property tests validate universal correctness properties from the design document
- All Python commands use `venv/bin/python` and `venv/bin/pytest`
- Shim files are temporary and will be removed in a future breaking-change release
- The restructuring preserves all `node_type` strings and `NodeMetadata` for backward compatibility
- Example YAML configs continue to work without modification
