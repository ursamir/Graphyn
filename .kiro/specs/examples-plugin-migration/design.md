# Design: Examples Plugin Migration

## Overview

Directly edit all example files to replace old built-in node types with plugin-based node types. No migration tooling — just file-by-file edits.

## Node Type Mapping

| Old | New | Key changes |
|---|---|---|
| `file_input` | `dataset_ingest` | add `source_type: "filesystem"` |
| `clean` | `audio_conditioner` | `sample_rate` preserved |
| `trim` | `segmenter` | `threshold_db` → `silence_threshold_db`, add `mode: "silence"` |
| `normalize` | `audio_conditioner` | `method` → `normalize_method` |
| `compression` | `audio_conditioner` | `threshold_db` → `compress_threshold_db`, `ratio` → `compress_ratio`, add `compress: true` |
| `fade` | `audio_conditioner` | absorbed into defaults |
| `augment` + `speed_perturb` + `pitch_shift` + `time_stretch` + `noise_mix` | `augmentation_pipeline` | consolidate into `augmentations` list |
| `silence_detector` | `audio_quality_gate` | `threshold_db` → `min_snr_db`, add `policy: "drop"` |
| `command_validator` | `audio_quality_gate` | `max_duration` → `max_duration_s` |
| `duration_filter` | `audio_quality_gate` | `min/max_duration` → `min/max_duration_s` |
| `duplicate` | `dataset_balancer` | add `strategy: "oversample"` |
| `speaker_embedder` | `audio_annotator` | structural: `annotation_mode: "auto"`, `auto_rules` |
| `degradation_pipeline` | `augmentation_pipeline` + `environment_simulator` | split codec/room aspects |
| `split` | `dataset_builder` | `train/val` → `split_ratios` dict, add `test` |
| `file_export` | `dataset_versioner` | `output` → `output_dir`, `version` → `version_tag` |
| `feature_extractor` | `feature_frontend` | direct rename |
| `model_builder` / `model_trainer` | `trainer` | direct rename |
| `model_evaluator` | `evaluator` | direct rename |
| `tflite_exporter` | `edge_optimizer` | add `backend: "tflite"` |
| `inference` | `realtime_inference` | direct rename |

## Architecture

This is a direct file-edit migration. There is no runtime component — the changes are made to the example files themselves. The platform's existing `PluginManager` and `NodeRegistry` handle loading at runtime once the files reference the correct plugin node types.

## Components and Interfaces

- **`.graph.json` files** — updated in place: `node_type` values, node `id` fields, edge `src_id`/`dst_id` references
- **Python runner/demo files** — updated in place: `PipelineNode`/`IRNode` calls replaced, plugin install block added
- **README files** — updated in place: old node type names replaced with plugin equivalents
- **`PluginManager`** (`app/core/plugins/manager.py`) — called in each runner to install and load plugins before pipeline construction
- **`NodeRegistry`** — populated by `PluginManager.load_enabled_plugins()` at runtime

## Data Models

No new data models. The existing `GraphIR`, `IRNode`, `IREdge`, and `PipelineNode` structures are unchanged — only the `node_type` string values and config keys within them are updated.

## Correctness Properties

### Property 1: Zero old node type references
After migration, no file under `examples/` contains any old node type string from the mapping table.
**Validates: Requirements 4.1, 4.2**

### Property 2: Split ratio conservation
For any migrated `dataset_builder` node, `split_ratios["train"] + split_ratios["val"] + split_ratios["test"] == 1.0`.
**Validates: Requirements 2.4**

### Property 3: Augmentation count preservation
For any consolidated `augmentation_pipeline` node, the `augmentations` list length equals the number of old augmentation nodes it replaced.
**Validates: Requirements 2.5**

## Error Handling

If a node type is not in the mapping table, it is left unchanged and flagged in the final validation scan.

## Testing Strategy

After all edits, run a grep scan across `examples/` for all old node type strings to confirm zero remaining references.

## Approach

1. Edit `.graph.json` files: replace `node_type` values, update node `id` fields, update edge `src_id`/`dst_id` references
2. Edit Python runner/demo files: replace `PipelineNode`/`IRNode` calls, add plugin install blocks
3. Edit README files: replace old node type names with plugin equivalents
4. Validate: scan for any remaining old node type references

## Plugin Install Block Pattern

```python
from app.core.plugins.manager import PluginManager

manager = PluginManager()
manager.install("PluginPackage/Audio/dataset_ingest/")
manager.install("PluginPackage/Audio/audio_conditioner/")
# ... install all required plugins ...
manager.load_enabled_plugins()

# Now construct pipeline
pipeline = Pipeline([...])
```
