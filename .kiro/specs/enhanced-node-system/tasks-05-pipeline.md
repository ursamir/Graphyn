# Tasks 05 — Pipeline DAG Executor, Serialisation, Schema Export

← [Back to tasks.md](tasks.md)

---

## Tasks

- [x] 32. Add DAG data structures to `app/core/pipeline.py`: `NodeSpec`, `EdgeSpec`, `PipelineConfig`
  - Add `@dataclass NodeSpec` with fields: `node_id: str`, `node_type: str`, `config: dict`
  - Add `@dataclass EdgeSpec` with fields: `src_id`, `src_port`, `dst_id`, `dst_port`
  - Add `@dataclass PipelineConfig` with fields: `seed: int`, `nodes: list[NodeSpec]`, `edges: list[EdgeSpec]`
  - Add `_parse_pipeline_config(raw: dict) -> PipelineConfig` supporting both new explicit-edge format and legacy linear format (auto-chain `output → input`)
  - _Requirements: R10.3, R11.1_
  - _Design: design-04-serialisation.md § 3.1, § 3.5_

- [x] 33. Implement `PipelineGraph` in `app/core/pipeline.py`
  - Implement `PipelineGraph.__init__(config, observer)` calling `_build()`
  - Implement `_build()`: instantiate nodes from `NodeSpec` list using `node_registry.get_class`, validate all edges via `CompatibilityChecker.check_connection`, compute topological order
  - Implement `_topological_sort()` using Kahn's algorithm; raise `PipelineGraphError` on cycle detection
  - Implement `get_node(node_id)` and `execution_order` property
  - _Requirements: R2D.10–R2D.11, R10.3_
  - _Design: design-04-serialisation.md § 3.2_

- [x] 34. Rewrite `run_pipeline` in `app/core/pipeline.py` as DAG executor
  - Replace the existing linear list executor with the DAG-based `run_pipeline` function
  - Parse YAML config via `_parse_pipeline_config`; build `PipelineGraph`
  - Setup all `NodeExecutor` instances before execution loop
  - Build `incoming` edge lookup dict; assemble `inputs` dict for each node from upstream outputs
  - Handle `"multi"` cardinality ports (collect into list)
  - Fill unconnected optional ports with `None`
  - Support `streaming=True` path via `_collect_stream` async helper
  - Support `checkpoint=True` path (adapt existing `_write_checkpoint` to new node_id-based naming)
  - Teardown all executors after execution; save run artifacts via `RunManager`
  - Preserve backward compatibility: legacy linear YAML configs (no `edges` key) auto-chain via `_parse_pipeline_config`
  - _Requirements: R5.2–R5.3, R7.2–R7.3, R9.6, R10.3_
  - _Design: design-04-serialisation.md § 3.3, § 3.4_

- [x]* 35. Write unit tests for pipeline DAG (`tests/test_pipeline_dag.py`)
  - Test `_parse_pipeline_config` with explicit edge format → correct `EdgeSpec` list
  - Test `_parse_pipeline_config` with legacy linear format → auto-chained edges
  - Test `PipelineGraph` cycle detection: construct cyclic graph → `PipelineGraphError`
  - Test `PipelineGraph` unknown node reference in edge → `PipelineGraphError`
  - Test `PipelineGraph` incompatible port types → `NodeTypeError`
  - Test `run_pipeline` with a minimal 2-node pipeline (mock nodes) → correct output
  - _Requirements: R10.3_

- [x]* 36. Write integration tests for full pipeline execution (`tests/test_pipeline_integration.py`)
  - Test full pipeline execution: load an existing YAML config from `workspace/configs/templates/`, run `run_pipeline`, verify output structure (dict with `"output"` key containing a list)
  - Test legacy linear format backward compatibility: existing YAML configs run without modification after migration
  - Test plugin discovery: place a minimal node file in `plugins/`, verify it appears in `registry` after import
  - _Requirements: R3.5, R10.3_
  - _Design: design-04-serialisation.md § 5 Integration Tests_

- [x] 37. Checkpoint — pipeline DAG executor complete
  - Ensure all tests pass, ask the user if questions arise.
