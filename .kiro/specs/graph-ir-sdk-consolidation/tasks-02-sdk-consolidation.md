# Tasks 02 — SDK Consolidation (`app/core/sdk.py`)

## Scope

Rewrite the internals of `app/core/sdk.py` so that `PipelineNode` is backed by an `IRNode`
and `Pipeline` is backed by a `GraphIR`. The public constructor signatures, attribute names,
and existing method signatures (`run()`, `from_yaml()`, `to_yaml()`) are unchanged.
New methods `to_ir()`, `to_json()`, and `from_json()` are added.

**Design reference:** [design-02-sdk-consolidation.md](design-02-sdk-consolidation.md)
**Requirements:** Req 2.1 – 2.9 ([req-02-sdk-consolidation.md](req-02-sdk-consolidation.md))
**Depends on:** tasks-01 (IR package), tasks-04 partial (`yaml_shim.py` for `from_yaml`)

---

## Tasks

- [x] 6. Rewrite `PipelineNode` internals in `app/core/sdk.py`
  - [x] 6.1 Update `PipelineNode.__init__` to construct a backing `IRNode`
    - Keep existing `self.node_type` and `self.config` attributes unchanged
    - Keep existing `_validate()` call unchanged
    - After validation, construct `self._ir_node = IRNode(id=f"{node_type}_0", ...)` (Req 2.2.1)
    - Import `IRNode` from `app.core.ir.models` inside the method to avoid circular imports
    - _Requirements: 2.1.1, 2.1.2, 2.2.1_

  - [x] 6.2 Add `PipelineNode.to_ir_node(node_index: int) -> IRNode`
    - Return `IRNode(id=f"{self.node_type}_{node_index}", node_type=self.node_type, config=self.config)`
    - Called by `Pipeline._build_ir()` with the correct positional index
    - _Requirements: 2.2.2_

  - [x] 6.3 Update `PipelineNode.to_dict()` to derive from backing `IRNode`
    - Return `{"type": self._ir_node.node_type, "config": dict(self._ir_node.config)}`
    - _Requirements: 2.2.3_

- [x] 7. Rewrite `Pipeline` internals in `app/core/sdk.py`
  - [x] 7.1 Update `Pipeline.__init__` to accept `name` and `description` and build IR
    - Signature: `__init__(self, nodes, seed=42, name="pipeline", description="")`
    - Store `self.name` and `self.description` as new attributes
    - Call `self._graph_ir = self._build_ir()` at end of `__init__`
    - _Requirements: 2.4.1, 2.9.1_

  - [x] 7.2 Implement `Pipeline._build_ir() -> GraphIR`
    - Call `node.to_ir_node(i)` for each node to get `ir_nodes` list
    - Auto-chain linear edges: `IREdge(src_id=ir_nodes[i].id, src_port="output", dst_id=ir_nodes[i+1].id, dst_port="input")`
    - Construct `GraphIR(schema_version=CURRENT_IR_VERSION, metadata=IRMetadata(name=self.name, seed=self.seed, description=self.description), nodes=ir_nodes, edges=ir_edges)`
    - _Requirements: 2.4.1, 2.9.2, 2.9.3_

  - [x] 7.3 Add `Pipeline.to_ir() -> GraphIR`
    - Return `self._graph_ir`
    - _Requirements: 2.4.2_

  - [x] 7.4 Rewrite `Pipeline.run()` to use `run_pipeline_ir`
    - Accepts optional `logger=None, **kwargs` and forwards to `run_pipeline_ir`
    - No temporary YAML files created
    - _Requirements: 2.4.3, 2.9.4_

  - [x] 7.5 Add `Pipeline.to_json(path: str) -> None`
    - Call `dump_ir_to_file(self._graph_ir, path)`
    - _Requirements: 2.6.1, 2.6.2_

  - [x] 7.6 Add `Pipeline.from_json(path: str) -> Pipeline` (classmethod)
    - Call `load_ir_from_file(path)` — propagates `IRVersionError` (Req 2.5.3)
    - Reconstruct `PipelineNode` list from `graph.nodes`
    - Return `cls(nodes=nodes, seed=graph.metadata.seed, name=graph.metadata.name, description=graph.metadata.description)`
    - _Requirements: 2.5.1, 2.5.2, 2.5.3, 2.5.4_

  - [x] 7.7 Add `Pipeline._to_config_dict() -> dict` helper
    - Derive legacy YAML config dict from `self._graph_ir`
    - Returns `{"pipeline": {"seed": ..., "nodes": [{"type": ..., "config": ...}, ...]}}`
    - Used by `to_yaml()`
    - _Requirements: 2.7.2_

  - [x] 7.8 Update `Pipeline.to_yaml(path: str) -> None`
    - Derive YAML from `self._to_config_dict()` (not from a separate raw dict)
    - Does NOT emit `DeprecationWarning` (Req 2.7.3)
    - _Requirements: 2.7.1, 2.7.2, 2.7.3_

  - [x] 7.9 Update `Pipeline.from_yaml(path: str) -> Pipeline` (classmethod)
    - Call `load_yaml_with_deprecation(path)` from `app.core.ir.yaml_shim`
    - Reconstruct `PipelineNode` list from `graph.nodes`
    - Return `cls(nodes=nodes, seed=graph.metadata.seed, name=graph.metadata.name, description=graph.metadata.description)`
    - Emits `DeprecationWarning` via `load_yaml_with_deprecation` (Req 2.3.5, 4.2.4)
    - _Requirements: 2.3.5, 2.8.1, 2.8.2_

- [x] 8. Checkpoint — verify SDK backward compatibility
  - Run `venv/bin/python -c "from app.core.sdk import Pipeline, PipelineNode; print('OK')"` — must print `OK`
  - Run `venv/bin/pytest tests/ -x --tb=short -q` — all existing tests must pass
  - Verify `Pipeline([PipelineNode('clean', {})], seed=42).to_ir()` returns a `GraphIR`
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- The `_validate()` method in `PipelineNode` is unchanged — still uses `registry.get_class()` + `Config.model_validate()`
- `Pipeline.__init__` backward compatibility: `Pipeline(nodes, seed=42)` still works — `name` and `description` are optional kwargs
- `from_yaml` depends on `yaml_shim.py` being implemented (tasks-04 task 13); implement tasks-04 task 13 before task 7.9 if running sequentially
- Error handling table from design-02 must be preserved: `ValueError` for unknown node type, `ValueError` for invalid config, `FileNotFoundError` / `json.JSONDecodeError` / `pydantic.ValidationError` / `IRVersionError` for `from_json`
