# Tasks 04 — YAML Compatibility Shim, Migration Utility, CLI and API Updates

## Scope

Create `app/core/ir/yaml_shim.py` and `app/core/ir/migrate.py`, then update
`app/cli/main.py` and `app/api/routers/pipelines.py` to support IR JSON as the
canonical input format while keeping YAML working via a deprecated path.

**Design reference:** [design-04-yaml-compat.md](design-04-yaml-compat.md)
**Requirements:** Req 4.1 – 4.9 ([req-04-yaml-compat.md](req-04-yaml-compat.md))
**Depends on:** tasks-01 (IR package), tasks-03 (`run_pipeline_ir`)

---

## Tasks

- [x] 14. Create `app/core/ir/yaml_shim.py`
  - [x] 14.1 Implement `yaml_config_to_ir(raw: dict) -> GraphIR`
    - Extract `seed`, `name`, `raw_nodes` from `raw["pipeline"]`
    - Build `IRNode` list: `id = n.get("id") or f"{node_type}_{i}"` (Req 4.1.5)
    - If `pipeline.edges` present: parse explicit-edge format (both list format
      `{"from": [id, port], "to": [id, port]}` and dict format `{"src_id": ..., ...}`)
    - If no `edges` key: auto-chain `output → input` (legacy linear format, Req 4.1.3)
    - Set `schema_version=CURRENT_IR_VERSION` (Req 4.1.7)
    - Set `metadata.name` from `pipeline.name` if present (Req 4.1.8)
    - No `DeprecationWarning` emitted here — pure conversion function
    - _Requirements: 4.1.1, 4.1.2, 4.1.3, 4.1.4, 4.1.5, 4.1.6, 4.1.7, 4.1.8_

  - [x] 14.2 Implement `load_yaml_with_deprecation(path: str) -> GraphIR`
    - Read YAML file with `yaml.safe_load()`
    - Emit `DeprecationWarning` with message:
      `"YAML pipeline configs are deprecated. Loading: {path}. Run 'audiobuilder migrate --config {path}' to convert to IR JSON."`
      with `stacklevel=2` (Req 4.2.2, 4.2.3)
    - Call `yaml_config_to_ir(raw)` and return result
    - _Requirements: 4.2.1, 4.2.2, 4.2.3, 4.2.4_

  - [x]* 14.3 Write unit tests for YAML shim
    - `test_yaml_shim_linear_format` — linear YAML → correct auto-chained edges
    - `test_yaml_shim_explicit_edge_format` — explicit-edge YAML → correct edges
    - `test_yaml_shim_named_pipeline` — `pipeline.name` preserved in `IRMetadata.name`
    - `test_yaml_shim_id_derivation` — node id derived as `f"{type}_{index}"` when no `id` field
    - `test_load_yaml_with_deprecation_emits_warning` — `DeprecationWarning` emitted
    - _Requirements: 4.1.2, 4.1.3, 4.1.5, 4.1.8, 4.2.2_

- [x] 15. Create `app/core/ir/migrate.py`
  - Implement `migrate_yaml_to_ir_file(yaml_path: str, output_path: str | None = None) -> str`
  - Derive output path when `None`: replace `.yaml`/`.yml` extension with `.graph.json` (Req 4.4.3)
  - Read YAML, call `yaml_config_to_ir(raw)`, call `dump_ir_to_file(graph, output_path)`
  - Return the output path string (Req 4.4.2)
  - No `DeprecationWarning` emitted (Req 4.4.5)
  - _Requirements: 4.4.1, 4.4.2, 4.4.3, 4.4.4, 4.4.5_

  - [x]* 15.1 Write unit test for migration utility
    - `test_migrate_yaml_to_ir_file` — writes valid IR JSON, returns correct path
    - `test_migrate_yaml_to_ir_file_custom_output` — respects explicit `output_path`
    - _Requirements: 4.4.2, 4.4.3_

- [x] 16. Add `migrate` subcommand to `app/cli/main.py`
  - [x] 16.1 Implement `cmd_migrate(args)` function
    - Validate YAML file exists; print error and `sys.exit(1)` if not (Req 4.3.5)
    - Validate YAML syntax; print parse error and `sys.exit(1)` if invalid (Req 4.3.6)
    - Call `migrate_yaml_to_ir_file(yaml_path, output_path)`
    - Print `"✓ Migrated {yaml_path} → {result_path}"` on success
    - Print error and `sys.exit(1)` on failure
    - _Requirements: 4.3.1, 4.3.2, 4.3.3, 4.3.4, 4.3.5, 4.3.6_

  - [x] 16.2 Register `migrate` parser in `build_parser()`
    - Add `migrate` subparser with `--config PATH` (required) and `--output PATH` (optional)
    - Set `migrate_parser.set_defaults(func=cmd_migrate)`
    - _Requirements: 4.3.1_

- [x] 17. Update `run` subcommand in `app/cli/main.py` to support `--graph`
  - [x] 17.1 Extract `StdoutLogger` inner class to `_make_stdout_logger(base_class)` helper
    - Avoids code duplication between `--graph` and `--config` paths
    - _Requirements: 4.5.1_

  - [x] 17.2 Add `--graph PATH` argument to `run` parser; make `--config` optional
    - Change `--config` from `required=True` to `required=False, default=None`
    - Add `--graph` with `required=False, default=None`
    - _Requirements: 4.5.2, 4.5.3_

  - [x] 17.3 Implement `--graph` execution path in `cmd_run`
    - Validate mutual exclusivity: both `--graph` and `--config` → error + exit 1 (Req 4.5.5)
    - Neither provided → error + exit 1 (Req 4.5.6)
    - `--graph` path: `Pipeline.from_json(graph_path)` → `pipeline.run(logger=logger)` (Req 2.9.1)
    - `--config` path: `Pipeline.from_yaml(config_path)` → `pipeline.run(logger=logger)` (Req 2.9.1)
    - Seed override: reconstruct `GraphIR` with new `IRMetadata(seed=args.seed, ...)` (Req 4.5.7)
    - _Requirements: 4.5.3, 4.5.4, 4.5.5, 4.5.6, 4.5.7_

- [x] 18. Update `validate` subcommand in `app/cli/main.py` to support `--graph`
  - Add `--graph PATH` argument; make `--config` optional
  - `--graph` path: `load_ir_from_file(graph_path)` → print node list → exit 0; catch `IRVersionError` → exit 1 (Req 4.6.3, 4.6.6)
  - `--config` path: `load_yaml_with_deprecation(config_path)` → validate node types via registry → print node list (Req 4.6.4)
  - _Requirements: 4.6.1, 4.6.2, 4.6.3, 4.6.4, 4.6.6_

- [x] 19. Update `app/api/routers/pipelines.py` to accept IR JSON
  - [x] 19.1 Add `IRPipelinePayload` Pydantic model
    - Fields: `schema_version: str`, `metadata: dict`, `nodes: list[dict]`,
      `edges: list[dict] = []`, `parameters: dict = {}`
    - _Requirements: 4.7.5_

  - [x] 19.2 Update `POST /pipelines/run` to accept both YAML and IR JSON
    - Change signature to `payload: dict = Body(...)` to accept both formats
    - Detect format: `"schema_version" in payload` → IR JSON path (Req 4.7.5)
    - IR path: `load_ir(payload)` → `run_pipeline_ir(graph, logger=logger)` (Req 4.7.1, 4.7.3)
    - YAML path: `yaml_config_to_ir(yaml.safe_load(payload["yaml"]))` → `run_pipeline_ir(graph, logger=logger)` (Req 4.7.2, 4.7.4)
    - YAML path adds `X-Deprecation-Warning` response header (Req 4.7.4)
    - _Requirements: 4.7.1, 4.7.2, 4.7.3, 4.7.4, 4.7.5_

  - [x] 19.3 Update `POST /pipelines/validate` to accept both YAML and IR JSON
    - Detect format via `"schema_version" in payload`
    - IR path: `load_ir(payload)` → `{"valid": True, "node_count": len(graph.nodes)}` (Req 4.8.1, 4.8.3)
    - IR validation failure → HTTP 422 with `{"valid": False, "error": str(exc)}` (Req 4.8.4)
    - YAML path: existing behavior + `X-Deprecation-Warning` header (Req 4.8.2, 4.8.5)
    - _Requirements: 4.8.1, 4.8.2, 4.8.3, 4.8.4, 4.8.5_

  - [x] 19.4 Update `POST /pipelines/run-async` to accept both YAML and IR JSON
    - Same format detection as `/run`
    - IR path delegates to `run_pipeline_ir(graph, ...)`
    - YAML path converts via `yaml_config_to_ir()` then delegates to `run_pipeline_ir()`
    - _Requirements: 4.7.1, 4.7.2_

  - [x]* 19.5 Write unit tests for updated API endpoints
    - `test_pipeline_from_yaml_deprecation_warning` — `DeprecationWarning` emitted on YAML load
    - `test_api_run_ir_json` — POST `/run` with IR JSON body executes successfully
    - `test_api_run_yaml_deprecation_header` — POST `/run` with YAML returns `X-Deprecation-Warning` header
    - `test_api_validate_ir_json` — POST `/validate` with IR JSON returns `{"valid": true}`
    - _Requirements: 4.7.3, 4.7.4, 4.8.3, 4.8.5_

- [x] 20. Checkpoint — verify YAML compat and CLI/API updates
  - Run `venv/bin/pytest tests/ -x --tb=short -q` — all existing tests must pass
  - Verify `audiobuilder migrate --help` shows `--config` and `--output` options
  - Verify `audiobuilder run --help` shows both `--config` and `--graph` options
  - Verify `audiobuilder validate --help` shows both `--config` and `--graph` options
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- `yaml_config_to_ir()` is a pure conversion function — no warnings, no file I/O
- `load_yaml_with_deprecation()` is the only function that emits `DeprecationWarning` for YAML files
- `migrate_yaml_to_ir_file()` does NOT emit `DeprecationWarning` — it is the migration tool itself
- Existing YAML examples in `examples/` continue to work via `--config` (Req 4.9.1)
- `DeprecationWarning` from YAML shim must NOT be treated as an error in the test suite (Req 4.9.2)
- The `run-async` endpoint preserves the existing `RunManager` pre-creation pattern for known `run_id`
