# Tasks 03 — Executor Wiring (`app/core/pipeline.py`, `app/core/run_manager.py`)

## Scope

Add `run_pipeline_ir()` as the primary execution entry point, add `_ir_to_pipeline_config()`
as a pure conversion helper, demote `run_pipeline()` to a deprecation shim, and extend
`RunManager` with `save_graph_ir()`. The existing `PipelineGraph`, `NodeExecutor`,
`NodeSpec`, `EdgeSpec`, and `PipelineConfig` data structures are preserved unchanged.

**Design reference:** [design-03-executor-wiring.md](design-03-executor-wiring.md)
**Requirements:** Req 3.1 – 3.8 ([req-03-executor-wiring.md](req-03-executor-wiring.md))
**Depends on:** tasks-01 (IR package), tasks-04 partial (`yaml_config_to_ir` for shim)

---

## Tasks

- [x] 9. Add `_ir_to_pipeline_config()` to `app/core/pipeline.py`
  - Pure conversion function: `GraphIR` → `PipelineConfig` (no side effects, no I/O)
  - Map each `IRNode` → `NodeSpec(node_id=ir_node.id, node_type=ir_node.node_type, config=dict(ir_node.config))`
  - Map each `IREdge` → `EdgeSpec(src_id, src_port, dst_id, dst_port)`
  - Return `PipelineConfig(seed=graph.metadata.seed, nodes=nodes, edges=edges)`
  - Import `GraphIR` inside the function body to avoid circular imports at module level
  - _Requirements: 3.2.1, 3.2.2, 3.2.3, 3.2.4_

- [x] 10. Add `run_pipeline_ir()` to `app/core/pipeline.py`
  - [x] 10.1 Implement function signature and docstring
    - Signature matches `run_pipeline()` but first arg is `graph: "GraphIR"` instead of `config_path: str`
    - All other kwargs (`logger`, `use_cache`, `checkpoint`, `streaming`, `observer`, `run_manager`) preserved
    - _Requirements: 3.1.1, 3.1.2_

  - [x] 10.2 Implement RunManager setup and IR storage
    - Create `RunManager()` if `run_manager` is `None`
    - Call `run.save_graph_ir(dump_ir(graph))` immediately after RunManager is ready
    - Import `dump_ir` from `app.core.ir.loader` inside the function
    - _Requirements: 3.6.1, 3.6.2_

  - [x] 10.3 Implement IR → PipelineConfig conversion and graph build
    - Call `_ir_to_pipeline_config(graph)` to get `pipeline_cfg`
    - Construct `PipelineGraph(pipeline_cfg, observer=observer)`
    - _Requirements: 3.2.4, 3.4.1_

  - [x] 10.4 Implement execution loop (copy from existing `run_pipeline`, replace YAML loading)
    - Setup all `NodeExecutor` instances
    - Build `incoming` edge lookup dict
    - Execute nodes in topological order with cache, checkpoint, and streaming support
    - Teardown all executors
    - Call `run.save_logs()` and `run.save_metadata()` at end
    - Return `node_outputs[last_id]`
    - _Requirements: 3.1.3, 3.1.4, 3.5.1, 3.7.1, 3.8.1_

  - [x] 10.5 Verify NDJSON event stream is identical to existing `run_pipeline()`
    - Same `logger.pipeline_start()`, `logger.node_start()`, `logger.node_end()`,
      `logger.node_error()`, `logger.summary()` call sequence
    - Same event field names and values
    - _Requirements: 3.5.1, 3.5.2, 3.5.3_

- [x] 11. Demote `run_pipeline()` to a deprecation shim in `app/core/pipeline.py`
  - Emit `DeprecationWarning` at the top of the function body (Req 3.3.1)
  - Call `load_yaml_with_deprecation(config_path)` to get `GraphIR` (Req 4.2.5)
  - Read raw YAML separately and call `run_manager.save_config(yaml_str)` (Req 3.6.3)
  - Delegate to `run_pipeline_ir(graph, ...)` with all kwargs forwarded
  - _Requirements: 3.3.1, 3.3.2, 3.3.3, 3.3.4, 3.6.3_

- [x] 12. Add `save_graph_ir()` to `app/core/run_manager.py`
  - Method signature: `def save_graph_ir(self, graph_data: dict) -> None`
  - Write to `{self.base_path}/graph.json` with `json.dump(..., indent=2, ensure_ascii=False)` + trailing newline
  - _Requirements: 3.6.1, 3.6.2_

- [x] 13. Checkpoint — verify executor wiring
  - Run `venv/bin/pytest tests/ -x --tb=short -q` — all existing tests must pass
  - Verify `run_pipeline_ir` is importable: `venv/bin/python -c "from app.core.pipeline import run_pipeline_ir, _ir_to_pipeline_config; print('OK')"`
  - Verify `save_graph_ir` is importable: `venv/bin/python -c "from app.core.run_manager import RunManager; r = RunManager(); print(hasattr(r, 'save_graph_ir'))"`
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- `run_pipeline_ir()` is the new canonical entry point — all other entry points (CLI, API, SDK) delegate here
- `run_pipeline()` shim calls `load_yaml_with_deprecation()` (Req 4.2.5) — emits two DeprecationWarnings (one for the deprecated function, one for the deprecated YAML format) — both intentional
- Cache key derivation is unchanged: `cache.key(node_type, node_cfg_dict, cache.input_hash(input_list))` — same dict passes through IR (Req 3.7.1)
- Checkpoint directory structure is unchanged: `{run_dir}/checkpoints/node_{node_id}/` (Req 3.8.1)
- Run directory after Phase 1: `meta.json`, `logs.json`, `graph.json` (always), `config.yaml` (only via YAML path)
