# Implementation Plan: Examples Plugin Migration

## Overview

Migrate all 21 examples one at a time, replacing old built-in node types with plugin-based node types. Each task covers one example completely before moving to the next.

## Notes

- Work sequentially — complete one example fully before starting the next
- For each `.graph.json`: update `node_type`, node `id` fields, and edge `src_id`/`dst_id` references
- For each Python file: replace `PipelineNode`/`IRNode` calls and add a plugin install block
- See `design.md` for the full node type mapping table

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2"] },
    { "id": 2, "tasks": ["3"] },
    { "id": 3, "tasks": ["4"] },
    { "id": 4, "tasks": ["5"] },
    { "id": 5, "tasks": ["6"] },
    { "id": 6, "tasks": ["7"] },
    { "id": 7, "tasks": ["8"] },
    { "id": 8, "tasks": ["9"] },
    { "id": 9, "tasks": ["10"] },
    { "id": 10, "tasks": ["11"] },
    { "id": 11, "tasks": ["12"] },
    { "id": 12, "tasks": ["13"] },
    { "id": 13, "tasks": ["14"] },
    { "id": 14, "tasks": ["15"] },
    { "id": 15, "tasks": ["16"] },
    { "id": 16, "tasks": ["17"] },
    { "id": 17, "tasks": ["18"] },
    { "id": 18, "tasks": ["19"] },
    { "id": 19, "tasks": ["20"] },
    { "id": 20, "tasks": ["21"] },
    { "id": 21, "tasks": ["22"] }
  ]
}
```

## Tasks

- [x] 1. Migrate example 01 — Wake Word
  - [x] 1.1 Migrate `examples/01_wake_word/pipeline.graph.json`
    - Replace `file_input` → `dataset_ingest` (add `source_type: "filesystem"`), update id `file_input_0` → `dataset_ingest_0`
    - Replace `clean` → `audio_conditioner`, update id
    - Replace `trim` → `segmenter` (`threshold_db` → `silence_threshold_db`, add `mode: "silence"`), update id
    - Consolidate `augment` + `speed_perturb` + `noise_mix` → single `augmentation_pipeline` node with `augmentations` list
    - Replace `split` → `dataset_builder` (`train`/`val` → `split_ratios` dict, add `test: 0.15`), update id
    - Replace `file_export` → `dataset_versioner` (`output` → `output_dir`, `version` → `version_tag`), update id
    - Update all edge `src_id`/`dst_id` to match new node ids
  - [x] 1.2 Migrate `examples/01_wake_word/run_sdk.py`
    - Add plugin install block at top (after imports): install `dataset_ingest`, `audio_conditioner`, `segmenter`, `augmentation_pipeline`, `dataset_builder`, `dataset_versioner`
    - Replace `PipelineNode("file_input", ...)` → `PipelineNode("dataset_ingest", ...)`
    - Replace `PipelineNode("clean", ...)` → `PipelineNode("audio_conditioner", ...)`
    - Replace `PipelineNode("trim", ...)` → `PipelineNode("segmenter", ...)`
    - Consolidate `PipelineNode("augment", ...)` + `PipelineNode("speed_perturb", ...)` + `PipelineNode("noise_mix", ...)` → single `PipelineNode("augmentation_pipeline", {"augmentations": [...], "copies_per_sample": 2})`
    - Replace `PipelineNode("split", ...)` → `PipelineNode("dataset_builder", {"split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15}})`
    - Replace `PipelineNode("file_export", ...)` → `PipelineNode("dataset_versioner", ...)`

- [x] 2. Migrate example 02 — Speech Commands
  - [x] 2.1 Migrate `examples/02_speech_commands/pipeline.graph.json`
    - Replace `file_input` → `dataset_ingest`, `clean` → `audio_conditioner`, `trim` → `segmenter`
    - Replace `silence_detector` → `audio_quality_gate` (`threshold_db` → `min_snr_db`, add `policy: "drop"`)
    - Replace `command_validator` → `audio_quality_gate` (`max_duration` → `max_duration_s`)
    - Consolidate `pitch_shift` + `time_stretch` → `augmentation_pipeline`
    - Replace `duplicate` → `dataset_balancer` (add `strategy: "oversample"`)
    - Replace `split` → `dataset_builder`, `file_export` → `dataset_versioner`
    - Update all node ids and edge references
  - [x] 2.2 Migrate `examples/02_speech_commands/run_sdk.py`
    - Add plugin install block
    - Replace all `PipelineNode(...)` calls per mapping

- [x] 3. Migrate example 03 — Environmental Sounds
  - [x] 3.1 Migrate `examples/03_environmental_sounds/pipeline.graph.json`
    - Replace `file_input` → `dataset_ingest`, `clean` → `audio_conditioner`
    - Replace `normalize` → `audio_conditioner` (`method` → `normalize_method`)
    - Replace `duration_filter` → `audio_quality_gate` (`min/max_duration` → `min/max_duration_s`)
    - Consolidate `augment` + `pitch_shift` → `augmentation_pipeline`
    - Replace `split` → `dataset_builder`, `file_export` → `dataset_versioner`
    - Update all node ids and edge references
  - [x] 3.2 Migrate `examples/03_environmental_sounds/run_sdk.py`
    - Add plugin install block
    - Replace all `PipelineNode(...)` calls per mapping

- [x] 4. Migrate example 04 — Speaker Verification
  - [x] 4.1 Migrate `examples/04_speaker_verification/pipeline.graph.json`
    - Replace `file_input` → `dataset_ingest`, `clean` → `audio_conditioner`, `trim` → `segmenter`
    - Replace `normalize` → `audio_conditioner` (`method` → `normalize_method`)
    - Replace `speaker_embedder` → `audio_annotator` (structural: `annotation_mode: "auto"`, `auto_rules: [{label_field: "speaker_id", method: "embedding_cluster"}]`)
    - Replace `split` → `dataset_builder`, `file_export` → `dataset_versioner`
    - Update all node ids and edge references
  - [x] 4.2 Migrate `examples/04_speaker_verification/run_sdk.py`
    - Add plugin install block
    - Replace all `PipelineNode(...)` calls per mapping

- [x] 5. Migrate example 05 — Speech Enhancement
  - [x] 5.1 Migrate `examples/05_speech_enhancement/pipeline.graph.json`
    - Replace `file_input` → `dataset_ingest`, `clean` → `audio_conditioner`, `trim` → `segmenter`
    - Replace `compression` → `audio_conditioner` (`threshold_db` → `compress_threshold_db`, `ratio` → `compress_ratio`, add `compress: true`)
    - Replace `fade` → `audio_conditioner` (absorbed into defaults)
    - Replace `degradation_pipeline` → `augmentation_pipeline` (codec aspect) + `environment_simulator` (room aspect if room params present)
    - Replace `split` → `dataset_builder`, `file_export` → `dataset_versioner`
    - Update all node ids and edge references
  - [x] 5.2 Migrate `examples/05_speech_enhancement/run_sdk.py`
    - Add plugin install block
    - Replace all `PipelineNode(...)` calls per mapping

- [x] 6. Migrate example 06 — Speech Commands E2E
  - [x] 6.1 Migrate `examples/06_speech_commands_e2e/pipeline_preprocess.graph.json`
    - Same pattern as example 02 (file_input, clean, trim, silence_detector, command_validator, pitch_shift, time_stretch, duplicate, split, file_export)
    - Update all node ids and edge references
  - [x] 6.2 Migrate `examples/06_speech_commands_e2e/pipeline_train_ml.graph.json`
    - Replace `file_input` → `dataset_ingest`
    - Replace `feature_extractor` → `feature_frontend`
    - Replace `model_builder` → `trainer`, `model_trainer` → `trainer`
    - Replace `model_evaluator` → `evaluator`
    - Replace `tflite_exporter` → `edge_optimizer` (add `backend: "tflite"`)
    - Update all node ids and edge references
  - [x] 6.3 Migrate `examples/06_speech_commands_e2e/pipeline_infer.graph.json`
    - Replace `file_input` → `dataset_ingest`, `clean` → `audio_conditioner`, `trim` → `segmenter`
    - Replace `feature_extractor` → `feature_frontend`
    - Replace `inference` → `realtime_inference`
    - Update all node ids and edge references
  - [x] 6.4 Migrate `examples/06_speech_commands_e2e/run_train.py`
    - Add plugin install block
    - Replace all `PipelineNode(...)` calls per mapping
  - [x] 6.5 Migrate `examples/06_speech_commands_e2e/run_infer.py`
    - Add plugin install block
    - Replace all `PipelineNode(...)` calls per mapping

- [x] 7. Migrate example 07 — MCP Agent Pipeline
  - [x] 7.1 Migrate `examples/07_mcp_agent_pipeline/agent.py`
    - Replace all `node_type` string literals in `_TASK_PLANS` dict and fallback plan
    - Update any `if node["node_type"] == "file_input"` / `"file_export"` checks
    - Add plugin install block

- [x] 8. Migrate example 08 — REST API Streaming
  - [x] 8.1 Check `examples/08_rest_api_streaming/` for old node type references and migrate any found

- [x] 9. Migrate example 09 — Parallel Execution
  - [x] 9.1 Migrate `examples/09_parallel_execution/pipeline.graph.json`
    - Replace all old node types across all 4 parallel branches (yes/no/up/down)
    - Update all node ids and edge references; preserve fan-out topology
  - [x] 9.2 Migrate `examples/09_parallel_execution/parallel_pipeline.py`
    - Replace all `IRNode(node_type=...)` calls per mapping
    - Add plugin install block

- [x] 10. Migrate example 10 — Resumable Pipeline
  - [x] 10.1 Check `examples/10_resumable_pipeline/` for old node type references and migrate any found
    - Preserve checkpoint/resume behavior

- [x] 11. Migrate example 11 — Artifact Lineage
  - [x] 11.1 Check `examples/11_artifact_lineage/` for old node type references and migrate any found

- [x] 12. Migrate example 12 — Conditional Branching
  - [x] 12.1 Migrate `examples/12_conditional_branching/pipeline.graph.json`
    - Replace `file_input`, `trim`, `silence_detector`, `split`, `file_export`, `augment` → plugin equivalents
    - Update all node ids and edge references; preserve `IREdge.condition` fields
  - [x] 12.2 Migrate `examples/12_conditional_branching/conditional_pipeline.py`
    - Replace all `IRNode(node_type=...)` calls per mapping
    - Update hardcoded node ID strings to match new node types
    - Add plugin install block

- [x] 13. Migrate example 13 — CSV Data Processing
  - [x] 13.1 Check `examples/13_csv_data_processing/` for old node type references and migrate any found

- [x] 14. Migrate example 14 — Plugin Manifest
  - [x] 14.1 Check `examples/14_plugin_manifest/` for old node type references and migrate any found

- [x] 15. Migrate example 15 — Event-Driven Pipeline
  - [x] 15.1 Migrate `examples/15_event_driven_pipeline/event_driven_demo.py`
    - Replace `IRNode(node_type="file_input")`, `"clean"`, `"trim"` → plugin equivalents
    - Update hardcoded node ID strings in `IREdge` calls
    - Preserve `event_driven=True`, `FileWatcherSource`, `TimerSource`
    - Add plugin install block

- [x] 16. Migrate example 16 — Deterministic Replay
  - [x] 16.1 Migrate `examples/16_deterministic_replay/replay_demo.py`
    - Replace all `PipelineNode(...)` calls per mapping
    - Update any `node["node_type"] == "file_export"` checks
    - Add plugin install block

- [x] 17. Migrate example 17 — Partial Execution
  - [x] 17.1 Migrate `examples/17_partial_execution/partial_demo.py`
    - Replace all `PipelineNode(...)` calls per mapping
    - Update `include_nodes`/`exclude_nodes` string values to match new node ids
    - Add plugin install block

- [x] 18. Migrate example 18 — Pipeline Composition
  - [x] 18.1 Migrate `examples/18_pipeline_composition/preprocessing.graph.json`
    - Replace `file_input`, `clean`, `trim`, `silence_detector` → plugin equivalents; update ids and edges
  - [x] 18.2 Migrate `examples/18_pipeline_composition/augmentation.graph.json`
    - Consolidate `augment` + `pitch_shift` → `augmentation_pipeline`; replace `split` → `dataset_builder`, `file_export` → `dataset_versioner`; update ids and edges
  - [x] 18.3 Migrate `examples/18_pipeline_composition/composed.graph.json`
    - Replace all 8 old node types → plugin equivalents; update ids and edges
  - [x] 18.4 Migrate `examples/18_pipeline_composition/composition_demo.py`
    - Replace all `PipelineNode(...)` calls in `build_preprocessing_pipeline()` and `build_augmentation_pipeline()`
    - Add plugin install block

- [x] 19. Migrate example 19 — Capability Scheduling
  - [x] 19.1 Check `examples/19_capability_scheduling/` for old node type references and migrate any found

- [x] 20. Migrate example 20 — Retry / Fault Tolerance
  - [x] 20.1 Check `examples/20_retry_fault_tolerance/` for old node type references and migrate any found

- [x] 21. Migrate example 21 — Runtime Control API
  - [x] 21.1 Check `examples/21_runtime_control_api/` for old node type references and migrate any found

- [x] 22. Final validation and README updates
  - [x] 22.1 Update `examples/README.md` — replace all old node type names with plugin equivalents
  - [x] 22.2 Update per-example README files that reference old node types (07, 15, others)
  - [x] 22.3 Scan all files under `examples/` for any remaining old node type strings and fix any found
