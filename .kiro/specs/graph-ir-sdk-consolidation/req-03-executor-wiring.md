# req-03 — Executor Wiring

## Introduction

This document defines requirements for wiring the DAG executor (`run_pipeline()` in `app/core/pipeline.py`) to consume `GraphIR` objects natively, replacing the current YAML-file-path-based entry point as the primary execution path.

The existing `PipelineGraph`, `NodeExecutor`, `NodeSpec`, `EdgeSpec`, and `PipelineConfig` data structures are preserved and extended. The NDJSON event streaming contract must remain fully compatible.

---

## Glossary

See [requirements.md](requirements.md) for the full glossary. Terms used here:

- **DAG_Executor**, **PipelineGraph**, **IR**, **GraphIR**, **IRNode**, **IREdge**, **PipelineConfig**, **NodeSpec**, **EdgeSpec**, **PipelineLogger**, **RunManager**, **YAML_Shim**

---

## Requirements

### Requirement 3.1 — IR-Native Executor Entry Point

**User Story:** As a platform developer, I want the executor to accept a `GraphIR` object directly, so that the execution path does not require a file on disk.

#### Acceptance Criteria

1. THE `DAG_Executor` SHALL expose a new function `run_pipeline_ir(graph: GraphIR, logger=None, use_cache=True, checkpoint=False, streaming=False, observer=None, run_manager=None) -> dict[str, Any]` in `app/core/pipeline.py`.
2. THE `run_pipeline_ir` function SHALL accept a `GraphIR` object as its first argument and SHALL NOT require a file path.
3. THE `run_pipeline_ir` function SHALL convert the `GraphIR` to a `PipelineConfig` internally using a new `_ir_to_pipeline_config(graph: GraphIR) -> PipelineConfig` helper.
4. THE `run_pipeline_ir` function SHALL support all keyword arguments currently supported by `run_pipeline()`: `logger`, `use_cache`, `checkpoint`, `streaming`, `observer`, `run_manager`.
5. THE `run_pipeline_ir` function SHALL return the outputs dict of the final node in topological order, identical to the current `run_pipeline()` return contract.

---

### Requirement 3.2 — IR to PipelineConfig Conversion

**User Story:** As a platform developer, I want a clean conversion from `GraphIR` to `PipelineConfig`, so that the existing `PipelineGraph` and `NodeExecutor` machinery can be reused without modification.

#### Acceptance Criteria

1. THE `_ir_to_pipeline_config` helper SHALL convert `GraphIR.metadata.seed` to `PipelineConfig.seed`.
2. THE `_ir_to_pipeline_config` helper SHALL convert each `IRNode` to a `NodeSpec` with matching `node_id`, `node_type`, and `config` fields.
3. THE `_ir_to_pipeline_config` helper SHALL convert each `IREdge` to an `EdgeSpec` with matching `src_id`, `src_port`, `dst_id`, and `dst_port` fields.
4. WHEN `_ir_to_pipeline_config` is called with a valid `GraphIR`, THE resulting `PipelineConfig` SHALL produce the same execution order as the equivalent YAML-parsed `PipelineConfig` for the same graph structure.

---

### Requirement 3.3 — Legacy YAML Executor Entry Point Preserved

**User Story:** As a platform developer, I want the existing `run_pipeline(config_path, ...)` function to remain callable, so that any code that has not yet migrated to the IR path continues to work.

#### Acceptance Criteria

1. THE existing `run_pipeline(config_path: str, ...)` function SHALL remain in `app/core/pipeline.py` with its current signature.
2. WHEN `run_pipeline(config_path)` is called with a YAML file path, THE `DAG_Executor` SHALL parse the YAML, convert it to a `GraphIR` via the `YAML_Shim`, and then call `run_pipeline_ir(graph, ...)` internally.
3. THE `run_pipeline` function SHALL emit a `DeprecationWarning` with the message: `"run_pipeline() with a YAML config path is deprecated. Use run_pipeline_ir() with a GraphIR object, or Pipeline.run() via the SDK."`.
4. THE `run_pipeline` function SHALL NOT emit the `DeprecationWarning` when called from within the `YAML_Shim` itself (to avoid double-warning).

---

### Requirement 3.4 — PipelineGraph Compatibility

**User Story:** As a platform developer, I want `PipelineGraph` to continue working with `PipelineConfig` objects, so that the graph-building and topological-sort logic does not need to be rewritten.

#### Acceptance Criteria

1. THE `PipelineGraph` class SHALL continue to accept a `PipelineConfig` as its constructor argument.
2. THE `PipelineGraph` class SHALL NOT be modified to accept `GraphIR` directly — the conversion is handled by `_ir_to_pipeline_config`.
3. THE `PipelineGraph.execution_order` property SHALL continue to return node IDs in topological order.
4. THE `PipelineGraph` cycle detection SHALL continue to raise `PipelineGraphError` for graphs containing cycles.

---

### Requirement 3.5 — Event Streaming Compatibility

**User Story:** As a frontend developer and API consumer, I want the NDJSON event stream to remain unchanged, so that existing clients do not break.

#### Acceptance Criteria

1. THE `PipelineLogger` SHALL continue to emit the following event types with their existing field schemas: `pipeline_start`, `node_start`, `node_end`, `node_error`, `pipeline_summary`, `info`.
2. WHEN `run_pipeline_ir` is called, THE `PipelineLogger` SHALL emit events in the same sequence and with the same field names as the current `run_pipeline` implementation.
3. THE `pipeline_start` event SHALL include `total_nodes` as an integer field.
4. THE `node_start` event SHALL include `node_type`, `node_index`, and `total_nodes` fields.
5. THE `node_end` event SHALL include `node_type`, `node_index`, `duration_s`, and `output_count` fields.
6. THE `node_error` event SHALL include `node_type`, `node_index`, and `error_message` fields.
7. THE `pipeline_summary` event SHALL include `total_duration_s` and `total_samples_out` fields.

---

### Requirement 3.6 — RunManager Integration

**User Story:** As a platform developer, I want the `RunManager` to store the IR JSON alongside the run metadata, so that runs are reproducible from their stored artifacts.

#### Acceptance Criteria

1. WHEN `run_pipeline_ir` is called, THE `RunManager` SHALL store the serialized `GraphIR` JSON as part of the run record (in addition to the existing metadata and logs).
2. THE stored IR JSON SHALL be written to `{run_dir}/graph.json` within the run directory.
3. THE `RunManager.save_config()` method SHALL continue to work for YAML-path-based runs (backward compatibility).
4. WHEN `run_pipeline_ir` is called without a `run_manager` argument, THE `DAG_Executor` SHALL create a default `RunManager` instance as it does today.

---

### Requirement 3.7 — Caching Compatibility

**User Story:** As a platform developer, I want the pipeline cache to continue working after the executor is wired to IR, so that performance is not regressed.

#### Acceptance Criteria

1. THE `PipelineCache` SHALL continue to function when `run_pipeline_ir` is used.
2. THE cache key derivation SHALL use the same `node_type`, `node_config`, and `input_hash` inputs as the current implementation.
3. WHEN `use_cache=True` is passed to `run_pipeline_ir`, THE `DAG_Executor` SHALL apply the same cache-hit and cache-save logic as the current `run_pipeline` implementation.

---

### Requirement 3.8 — Checkpoint Compatibility

**User Story:** As a platform developer, I want per-node checkpoints to continue working after the executor is wired to IR, so that debugging and resumability capabilities are not regressed.

#### Acceptance Criteria

1. WHEN `checkpoint=True` is passed to `run_pipeline_ir`, THE `DAG_Executor` SHALL write per-node checkpoint directories using the existing `_write_checkpoint` helper.
2. THE checkpoint directory structure (`{run_dir}/checkpoints/node_{node_id}/`) SHALL remain unchanged.
