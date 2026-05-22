# Requirements Document

## Introduction

The Graphyn platform has migrated its node system from built-in nodes (registered in `app/core/nodes/`) to plugin-based nodes (in `PluginPackage/`). All 21 examples under `examples/` still reference the old built-in node types and must be updated to use the new plugin node types directly.

This migration edits the example files in place — `.graph.json` pipeline files, Python runner/demo files, and README files — so that every example works with the plugin-based node system.

---

## Glossary

- **Old_Node**: A built-in node type being replaced. Full set: `file_input`, `clean`, `trim`, `augment`, `split`, `file_export`, `silence_detector`, `command_validator`, `pitch_shift`, `time_stretch`, `duplicate`, `normalize`, `duration_filter`, `speaker_embedder`, `compression`, `fade`, `degradation_pipeline`, `feature_extractor`, `model_builder`, `model_trainer`, `model_evaluator`, `tflite_exporter`, `inference`, `speed_perturb`, `noise_mix`.
- **Plugin_Node**: A node type from `PluginPackage/` registered via `PluginManager`. Replacements: `dataset_ingest`, `audio_conditioner`, `segmenter`, `augmentation_pipeline`, `dataset_builder`, `dataset_versioner`, `audio_quality_gate`, `feature_frontend`, `trainer`, `evaluator`, `edge_optimizer`, `realtime_inference`, `audio_annotator`, `dataset_balancer`, `environment_simulator`.
- **Graph_File**: A `.graph.json` file containing a serialized pipeline definition.
- **NodeRegistry**: Singleton populated at startup by `AutoDiscovery` mapping `node_type` strings to classes.
- **PluginManager**: Component in `app/core/plugins/manager.py` that loads plugins from `PluginPackage/`.

---

## Requirements

### Requirement 1: Node Type Mapping

**User Story:** As a developer, I want a clear mapping from every old node type to its plugin replacement so the migration is consistent.

#### Acceptance Criteria

1. Every Old_Node type SHALL have a documented Plugin_Node replacement with config key translations.
2. The mapping SHALL cover all 26 old node types found across the examples.
3. WHERE multiple old nodes consolidate into one plugin node (e.g. `augment` + `speed_perturb` + `noise_mix` → `augmentation_pipeline`), the consolidated config structure SHALL be documented.

---

### Requirement 2: Graph File Migration

**User Story:** As a developer running examples via the CLI, I want all `.graph.json` files to use Plugin_Node types so pipelines execute without errors.

#### Acceptance Criteria

1. WHEN a Graph_File is loaded, THE NodeRegistry SHALL resolve every `node_type` value to a registered Plugin_Node class.
2. All node `id` fields and edge `src_id`/`dst_id` references SHALL be updated to match the new node types.
3. WHEN `file_input` is replaced by `dataset_ingest`, THE config SHALL include `source_type: "filesystem"`.
4. WHEN `split` is replaced by `dataset_builder`, THE config SHALL use `split_ratios` with `train`, `val`, and `test` keys summing to 1.0.
5. WHEN multiple augmentation nodes are consolidated, THE resulting `augmentation_pipeline` node SHALL have an `augmentations` list preserving all augmentation parameters.

---

### Requirement 3: Python File Migration

**User Story:** As a developer running examples via the Python SDK, I want all `PipelineNode` and `IRNode` calls to use Plugin_Node types.

#### Acceptance Criteria

1. All `PipelineNode("old_type", ...)` calls SHALL be replaced with the corresponding Plugin_Node type and translated config.
2. All `IRNode(node_type="old_type", ...)` calls SHALL be replaced with the corresponding Plugin_Node type.
3. Each runner file SHALL include a plugin install block before pipeline construction that calls `PluginManager.install()` for each required plugin and `PluginManager.load_enabled_plugins()`.
4. String literals referencing old node types in plan dictionaries (e.g. `agent.py`) SHALL be replaced.

---

### Requirement 4: No Old Node Type References Remain

**User Story:** As a platform maintainer, I want a guarantee that no example file references any old node type after migration.

#### Acceptance Criteria

1. AFTER migration, no `.graph.json`, `.py`, or `.md` file under `examples/` SHALL contain any Old_Node type string.
2. IF any old node type reference is found, it SHALL be fixed before the migration is considered complete.

---

### Requirement 5: Example Semantics Preserved

**User Story:** As a developer learning from the examples, I want each migrated example to demonstrate the same platform feature as before.

#### Acceptance Criteria

1. THE migrated `examples/09_parallel_execution/` SHALL preserve the fan-out DAG topology.
2. THE migrated `examples/12_conditional_branching/` SHALL preserve `IREdge.condition` fields.
3. THE migrated `examples/10_resumable_pipeline/` SHALL preserve checkpoint/resume behavior.
4. THE migrated `examples/17_partial_execution/` SHALL have valid Plugin_Node IDs in `include_nodes`/`exclude_nodes`.
5. THE migrated `examples/15_event_driven_pipeline/` SHALL preserve `event_driven=True`, `FileWatcherSource`, and `TimerSource`.
