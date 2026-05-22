# Tasks 06 — Property-Based Tests (`tests/test_graph_ir_properties.py`)

## Scope

Implement all 9 Hypothesis property-based tests defined in design-06. Each property
is a separate sub-task. The complete test file is created in one parent task, with
each property as a sub-task. All tests use `max_examples=100` (minimum).

**Design reference:** [design-06-correctness-properties.md](design-06-correctness-properties.md)
**Requirements:** Req 1.8.8, 1.2.5, 2.6.3, 2.5.4, 4.1.2, 4.1.3, 3.2.4, 1.7.3, 5.1.1, 5.5.1, 3.1.5, 1.10.3, 1.10.2, 1.4.3, 1.9.2, 1.5.2, 1.9.1
**Depends on:** All previous task groups (tasks-01 through tasks-05)

---

## Tasks

- [x] 25. Create `tests/test_graph_ir_properties.py` with Hypothesis strategies
  - Created the test file with module docstring, imports, and all Hypothesis strategies:
    - `_node_id_strategy` — alphanumeric + `_-`, 1–20 chars
    - `_node_type_strategy` — nodes that accept empty config (clean, trim, normalize, etc.)
    - `_config_strategy` — small dicts with primitive values
    - `_ir_metadata_strategy` — builds `IRMetadata` with valid fields
    - `_build_graph_ir_strategy(max_nodes)` — composite strategy building valid `GraphIR`
      with consistent node IDs in edges (unique IDs, linear edge chain)
    - `_graph_ir_strategy = _build_graph_ir_strategy()` — top-level strategy
  - Hypothesis profile registered at module level (max_examples=100, suppress too_slow)
  - _Requirements: (all properties below)_

  - [x]* 25.1 Implement Property 1: IR Round-Trip
    - Assert `load_ir(dump_ir(graph)) == graph`
    - Tag: `# Feature: graph-ir-sdk-consolidation, Property 1: load_ir(dump_ir(g)) == g`
    - **Validates: Requirements 1.8.8, 1.2.5** ✓ PASSING

  - [x]* 25.2 Implement Property 2: SDK Round-Trip
    - Construct `Pipeline`, call `to_json(tmp_path)`, load with `from_json(tmp_path)`
    - Assert `loaded.seed == pipeline.seed`, same node count, same `node_type` and `config` per node
    - Tag: `# Feature: graph-ir-sdk-consolidation, Property 2: Pipeline.from_json(p.to_json()) == p`
    - **Validates: Requirements 2.6.3, 2.5.4** ✓ PASSING

  - [x]* 25.3 Implement Property 3: YAML Shim Equivalence
    - Assert same seed, same node count, same node types, same edge count, same port names
    - Tag: `# Feature: graph-ir-sdk-consolidation, Property 3: yaml_config_to_ir produces structurally equivalent graph`
    - **Validates: Requirements 4.1.2, 4.1.3, 3.2.4** ✓ PASSING

  - [x]* 25.4 Implement Property 4: Version Rejection
    - Assert `load_ir(data)` raises `IRVersionError` for incompatible major version
    - Tag: `# Feature: graph-ir-sdk-consolidation, Property 4: load_ir raises IRVersionError for incompatible major version`
    - **Validates: Requirements 1.7.3** ✓ PASSING

  - [x]* 25.5 Implement Property 5: Capability Defaults
    - Assert all seven capability fields equal their specified defaults
    - Tag: `# Feature: graph-ir-sdk-consolidation, Property 5: NodeMetadata without capability fields has correct defaults`
    - **Validates: Requirements 5.1.1, 5.5.1** ✓ PASSING

  - [x]* 25.6 Implement Property 6: Executor Equivalence
    - Assert same node types, same seed, same edge count (structural equivalence)
    - Tag: `# Feature: graph-ir-sdk-consolidation, Property 6: run_pipeline_ir produces same output as direct PipelineGraph execution`
    - **Validates: Requirements 3.1.5, 3.2.4** ✓ PASSING

  - [x]* 25.7 Implement Property 7: Deterministic Replay
    - Call `_ir_to_pipeline_config(graph)` twice, assert identical results
    - Tag: `# Feature: graph-ir-sdk-consolidation, Property 7: Same GraphIR + same seed produces same PipelineConfig`
    - **Validates: Requirements 1.10.3, 1.10.2** ✓ PASSING

  - [x]* 25.8 Implement Property 8: Node ID Uniqueness Enforcement
    - Assert `GraphIR(...)` raises `pydantic.ValidationError` for duplicate node ids
    - Tag: `# Feature: graph-ir-sdk-consolidation, Property 8: GraphIR raises ValidationError for duplicate node ids`
    - **Validates: Requirements 1.4.3, 1.9.2** ✓ PASSING

  - [x]* 25.9 Implement Property 9: Edge Reference Integrity Enforcement
    - Assert `load_ir(data)` raises `pydantic.ValidationError` for edges with unknown node ids
    - Tag: `# Feature: graph-ir-sdk-consolidation, Property 9: load_ir raises ValidationError for edges with unknown node ids`
    - **Validates: Requirements 1.5.2, 1.9.1** ✓ PASSING

- [x] 26. Checkpoint — run all property-based tests
  - `venv/bin/pytest tests/test_graph_ir_properties.py -v --tb=short` — 9 passed
  - `venv/bin/pytest tests/ -x --tb=short -q` — 421 passed, 0 failures
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- All property tests are marked optional (`*`) — they validate correctness but are not required for MVP
- The `_build_graph_ir_strategy` composite strategy ensures edge `src_id`/`dst_id` always reference valid node IDs — this is required for Properties 1, 7, 9
- `_node_type_strategy` uses only nodes that accept empty config to avoid validation errors in Property 2
- Property 6 (Executor Equivalence) tests structural equivalence only — not full execution (avoids real I/O)
- Property 7 (Deterministic Replay) tests `_ir_to_pipeline_config` determinism — full execution determinism depends on node implementations
- `filterwarnings` in `pytest.ini` ignores `DeprecationWarning` from YAML shim in tests (Req 4.9.2)
