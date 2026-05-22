# Implementation Plan: Graph IR + SDK Consolidation (Phase 1)

## Overview

This is the master task document for Phase 1 of the platform evolution roadmap.
Tasks are split across six sub-documents matching the design sub-documents.
Each sub-document is self-contained and references the relevant design and requirements files.

---

## Sub-Document Index

| Sub-Document | Scope | Key Files | Requirements |
|---|---|---|---|
| [tasks-01-graph-ir.md](tasks-01-graph-ir.md) | Create `app/core/ir/` package: models, loader, errors | `app/core/ir/__init__.py`, `models.py`, `loader.py` | Req 1.1 – 1.11 |
| [tasks-02-sdk-consolidation.md](tasks-02-sdk-consolidation.md) | Rewrite `app/core/sdk.py` internals (IR-backed) | `app/core/sdk.py` | Req 2.1 – 2.9 |
| [tasks-03-executor-wiring.md](tasks-03-executor-wiring.md) | Add `run_pipeline_ir()`, `_ir_to_pipeline_config()`, `RunManager.save_graph_ir()` | `app/core/pipeline.py`, `app/core/run_manager.py` | Req 3.1 – 3.8 |
| [tasks-04-yaml-compat.md](tasks-04-yaml-compat.md) | YAML shim, migration utility, CLI and API updates | `app/core/ir/yaml_shim.py`, `app/core/ir/migrate.py`, `app/cli/main.py`, `app/api/routers/pipelines.py` | Req 4.1 – 4.9 |
| [tasks-05-node-capability-metadata.md](tasks-05-node-capability-metadata.md) | `NodeMetadata` capability fields, API response update | `app/core/nodes/metadata.py`, `app/api/routers/nodes.py` | Req 5.1 – 5.5 |
| [tasks-06-property-tests.md](tasks-06-property-tests.md) | All 9 Hypothesis property-based tests | `tests/test_graph_ir_properties.py` | All |

---

## Execution Order

The task groups have the following dependency chain. Groups that can run in parallel are noted.

```
tasks-01 (IR models + loader)
    │
    ├──► tasks-02 (SDK rewrite)          ─┐
    │                                      │
    ├──► tasks-03 (executor wiring)       ─┤── tasks-04 (YAML shim + CLI + API)
    │                                      │
    └──► tasks-05 (capability metadata)  ─┘
              (parallel with tasks-02/03)
                        │
                        └──► tasks-06 (property tests)
                                  (depends on all above)
```

**Step-by-step order:**

1. **tasks-01** — IR models and loader. No dependencies. Foundation for everything.
2. **tasks-04 task 14** — `yaml_shim.py` (`yaml_config_to_ir`, `load_yaml_with_deprecation`). Depends on tasks-01. Needed by tasks-02 (`from_yaml`) and tasks-03 (shim).
3. **tasks-02** — SDK rewrite. Depends on tasks-01 and tasks-04 task 14.
4. **tasks-03** — Executor wiring. Depends on tasks-01 and tasks-04 task 14.
5. **tasks-05** — Capability metadata. Depends on tasks-01. Can run in parallel with tasks-02/03.
6. **tasks-04 tasks 15–19** — Migration utility, CLI updates, API updates. Depends on tasks-01, tasks-03.
7. **tasks-06** — Property tests. Depends on all above.

---

## Task Summary

### tasks-01: Graph IR Package

- [x] 1. Create `app/core/ir/` package skeleton
- [x] 2. Implement `app/core/ir/models.py` — IR Pydantic models
  - [x] 2.1 Implement `IRCapabilityMetadata` model
  - [x] 2.2 Implement `IRMetadata` model
  - [x] 2.3 Implement `IRNode` model
  - [x] 2.4 Implement `IREdge` model
  - [x] 2.5 Implement `IRParameter` model
  - [x] 2.6 Implement `GraphIR` model with graph-level validation
  - [x]* 2.7 Write unit tests for IR models
- [x] 3. Implement `app/core/ir/loader.py` — serialization and version validation
  - [x] 3.1 Define constants and error types
  - [x] 3.2 Implement `_check_version()`
  - [x] 3.3 Implement `load_ir()`
  - [x] 3.4 Implement `load_ir_from_file()`
  - [x] 3.5 Implement `dump_ir()`
  - [x] 3.6 Implement `dump_ir_to_file()`
  - [x]* 3.7 Write unit tests for loader
- [x] 4. Update `app/core/ir/__init__.py` with complete re-exports
- [x] 5. Checkpoint — verify IR package in isolation

### tasks-02: SDK Consolidation

- [x] 6. Rewrite `PipelineNode` internals in `app/core/sdk.py`
  - [x] 6.1 Update `PipelineNode.__init__` to construct a backing `IRNode`
  - [x] 6.2 Add `PipelineNode.to_ir_node()`
  - [x] 6.3 Update `PipelineNode.to_dict()`
- [x] 7. Rewrite `Pipeline` internals in `app/core/sdk.py`
  - [x] 7.1 Update `Pipeline.__init__` to accept `name` and `description` and build IR
  - [x] 7.2 Implement `Pipeline._build_ir()`
  - [x] 7.3 Add `Pipeline.to_ir()`
  - [x] 7.4 Rewrite `Pipeline.run()` to use `run_pipeline_ir`
  - [x] 7.5 Add `Pipeline.to_json()`
  - [x] 7.6 Add `Pipeline.from_json()`
  - [x] 7.7 Add `Pipeline._to_config_dict()`
  - [x] 7.8 Update `Pipeline.to_yaml()`
  - [x] 7.9 Update `Pipeline.from_yaml()`
- [x] 8. Checkpoint — verify SDK backward compatibility

### tasks-03: Executor Wiring

- [x] 9. Add `_ir_to_pipeline_config()` to `app/core/pipeline.py`
- [x] 10. Add `run_pipeline_ir()` to `app/core/pipeline.py`
  - [x] 10.1 Implement function signature and docstring
  - [x] 10.2 Implement RunManager setup and IR storage
  - [x] 10.3 Implement IR → PipelineConfig conversion and graph build
  - [x] 10.4 Implement execution loop
  - [x] 10.5 Verify NDJSON event stream is identical to existing `run_pipeline()`
- [x] 11. Demote `run_pipeline()` to a deprecation shim
- [x] 12. Add `save_graph_ir()` to `app/core/run_manager.py`
- [x] 13. Checkpoint — verify executor wiring

### tasks-04: YAML Compatibility, CLI, and API

- [x] 14. Create `app/core/ir/yaml_shim.py`
  - [x] 14.1 Implement `yaml_config_to_ir()`
  - [x] 14.2 Implement `load_yaml_with_deprecation()`
  - [x]* 14.3 Write unit tests for YAML shim
- [x] 15. Create `app/core/ir/migrate.py`
  - [x]* 15.1 Write unit test for migration utility
- [x] 16. Add `migrate` subcommand to `app/cli/main.py`
  - [x] 16.1 Implement `cmd_migrate()`
  - [x] 16.2 Register `migrate` parser in `build_parser()`
- [x] 17. Update `run` subcommand to support `--graph`
  - [x] 17.1 Extract `_make_stdout_logger()` helper
  - [x] 17.2 Add `--graph` argument; make `--config` optional
  - [x] 17.3 Implement `--graph` execution path in `cmd_run`
- [x] 18. Update `validate` subcommand to support `--graph`
- [x] 19. Update `app/api/routers/pipelines.py` to accept IR JSON
  - [x] 19.1 Add `IRPipelinePayload` model
  - [x] 19.2 Update `POST /pipelines/run`
  - [x] 19.3 Update `POST /pipelines/validate`
  - [x] 19.4 Update `POST /pipelines/run-async`
  - [x]* 19.5 Write unit tests for updated API endpoints
- [x] 20. Checkpoint — verify YAML compat and CLI/API updates

### tasks-05: Node Capability Metadata

- [x] 21. Extend `NodeMetadata` with capability fields
  - [x]* 21.1 Write unit tests for `NodeMetadata` capability fields
- [x] 22. Update `_node_response()` in `app/api/routers/nodes.py`
  - [x]* 22.1 Write unit test for capability metadata in API response
- [x] 23. Add `_resolve_capability()` helper to `app/core/pipeline.py`
- [x] 24. Checkpoint — verify capability metadata

### tasks-06: Property-Based Tests

- [x] 25. Create `tests/test_graph_ir_properties.py` with Hypothesis strategies
  - [x]* 25.1 Property 1: IR Round-Trip — `load_ir(dump_ir(g)) == g`
  - [x]* 25.2 Property 2: SDK Round-Trip — `Pipeline.from_json(p.to_json()) == p`
  - [x]* 25.3 Property 3: YAML Shim Equivalence
  - [x]* 25.4 Property 4: Version Rejection
  - [x]* 25.5 Property 5: Capability Defaults
  - [x]* 25.6 Property 6: Executor Equivalence
  - [x]* 25.7 Property 7: Deterministic Replay
  - [x]* 25.8 Property 8: Node ID Uniqueness Enforcement
  - [x]* 25.9 Property 9: Edge Reference Integrity Enforcement
- [x] 26. Checkpoint — run all property-based tests

---

## Acceptance Gate

All of the following criteria have been satisfied. Phase 1 is complete.

### Regression

- [x] All existing tests pass — zero regressions — **421 passed, 0 failures**
  ```bash
  venv/bin/pytest tests/ -x --tb=short -q
  ```

### Property Tests

- [x] All 9 property-based tests pass with 100+ iterations each — **9 passed**
  ```bash
  venv/bin/pytest tests/test_graph_ir_properties.py -v --tb=short
  ```

### IR Round-Trip

- [x] `load_ir(dump_ir(g)) == g` for any valid `GraphIR` (Property 1) ✓

### SDK Round-Trip

- [x] `Pipeline.from_json(p.to_json()) == p` (Property 2) ✓

### YAML Backward Compatibility

- [x] All existing YAML examples execute successfully via `audiobuilder run --config` ✓
  ```bash
  audiobuilder run --config examples/01_wake_word/pipeline.yaml
  audiobuilder run --config examples/02_speech_commands/pipeline.yaml
  ```

### Migration Utility

- [x] `audiobuilder migrate --config <yaml>` produces valid IR JSON ✓
  ```bash
  audiobuilder migrate --config examples/01_wake_word/pipeline.yaml
  # → examples/01_wake_word/pipeline.graph.json
  ```

### IR JSON Execution

- [x] `audiobuilder run --graph <json>` executes successfully ✓
  ```bash
  audiobuilder run --graph examples/01_wake_word/pipeline.graph.json
  ```

### Capability Metadata API

- [x] `GET /api/v1/nodes` response includes `capability_metadata` for all nodes ✓
  ```bash
  curl http://localhost:8001/api/v1/nodes | python -m json.tool | grep capability_metadata
  ```

### Run Directory

- [x] `graph.json` is written to the run directory on every execution ✓
  ```bash
  ls workspace/runs/<run_id>/graph.json
  ```

---

## Notes

- Tasks marked with `*` are optional — all were implemented
- Each task group ends with a checkpoint that runs the full test suite
- All checkpoints use: `venv/bin/pytest tests/ -x --tb=short -q`
- `DeprecationWarning` from the YAML shim is not treated as an error in the test suite
- Post-implementation review fixed 3 gaps: Req 2.9.1 (CLI uses Pipeline.run()), Req 4.2.5 (run_pipeline shim calls load_yaml_with_deprecation), Req 4.6.4 (validate --config uses YAML shim)
