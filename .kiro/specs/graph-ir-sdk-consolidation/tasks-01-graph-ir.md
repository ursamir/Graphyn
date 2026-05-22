# Tasks 01 — Graph IR Package (`app/core/ir/`)

## Scope

Create the `app/core/ir/` package from scratch: Pydantic models, loader/dumper functions,
version validation, and error types. This is the foundation for all other task groups.

**Design reference:** [design-01-graph-ir.md](design-01-graph-ir.md)
**Requirements:** Req 1.1 – 1.11 ([req-01-graph-ir.md](req-01-graph-ir.md))

---

## Tasks

- [x] 1. Create `app/core/ir/` package skeleton
  - Create `app/core/ir/__init__.py` with all public re-exports as specified in design-01
  - Create empty placeholder files `models.py` and `loader.py` (content added in tasks 2–3)
  - Verify `from app.core.ir import GraphIR` resolves without error after task 2 is complete
  - _Requirements: 1.1.1, 1.1.2_

- [x] 2. Implement `app/core/ir/models.py` — IR Pydantic models
  - [x] 2.1 Implement `IRCapabilityMetadata` model
    - `frozen=True`, seven `bool` fields with defaults as specified in design-01
    - _Requirements: 5.1.1, 5.2.1_

  - [x] 2.2 Implement `IRMetadata` model
    - `frozen=True`, fields: `name: str`, `seed: int`, `description: str = ""`,
      `created_at: str | None = None`, `tags: list[str] = []`
    - `@field_validator("name")` enforces non-empty string
    - _Requirements: 1.3.1, 1.3.2, 1.3.3_

  - [x] 2.3 Implement `IRNode` model
    - `frozen=True`, fields: `id: str`, `node_type: str`, `config: dict[str, Any] = {}`,
      `label: str | None = None`, `capability_metadata: IRCapabilityMetadata | None = None`
    - `@field_validator("id")` enforces `^[A-Za-z0-9_-]+$` regex (Req 1.4.4)
    - `@field_validator("node_type")` enforces non-empty string
    - _Requirements: 1.4.1, 1.4.2, 1.4.4_

  - [x] 2.4 Implement `IREdge` model
    - `frozen=True`, fields: `src_id`, `src_port`, `dst_id`, `dst_port` (all `str`)
    - _Requirements: 1.5.1_

  - [x] 2.5 Implement `IRParameter` model
    - `frozen=True`, fields: `type: str`, `default: Any`, `description: str = ""`
    - _Requirements: 1.6.1_

  - [x] 2.6 Implement `GraphIR` model with graph-level validation
    - `frozen=True`, fields: `schema_version: str`, `metadata: IRMetadata`,
      `nodes: list[IRNode]`, `edges: list[IREdge] = []`,
      `parameters: dict[str, IRParameter] = {}`
    - `@field_validator("schema_version")` enforces `"<major>.<minor>"` format
    - `@model_validator(mode="after")` named `_validate_graph`:
      - Checks for duplicate node IDs → raises `ValueError` mentioning the duplicate id
        (Req 1.4.3, 1.9.2)
      - Checks all edge `src_id` and `dst_id` exist in node id set → raises `ValueError`
        mentioning the unknown id (Req 1.5.2, 1.9.1)
    - _Requirements: 1.2.1, 1.2.2, 1.4.3, 1.5.2, 1.9.1, 1.9.2_

  - [x]* 2.7 Write unit tests for IR models
    - Test `IRNode` id regex validation (valid and invalid ids)
    - Test `GraphIR` duplicate node id raises `pydantic.ValidationError`
    - Test `GraphIR` unknown edge node id raises `pydantic.ValidationError`
    - Test `IRMetadata` empty name raises `pydantic.ValidationError`
    - Test `GraphIR` with zero nodes and zero edges is valid
    - _Requirements: 1.4.3, 1.4.4, 1.5.2, 1.9.1, 1.9.2_

- [x] 3. Implement `app/core/ir/loader.py` — serialization and version validation
  - [x] 3.1 Define constants and error types
    - `CURRENT_IR_VERSION: str = "1.0"`
    - `class IRVersionError(ValueError)` — raised on incompatible major version (Req 1.7.3)
    - `class IRValidationError(ValueError)` — raised on structural validation failure (Req 1.9.3)
    - _Requirements: 1.7.1, 1.7.3, 1.9.3_

  - [x] 3.2 Implement `_check_version(schema_version: str) -> None`
    - Parse `doc_major, doc_minor` from `schema_version`
    - Parse `cur_major, cur_minor` from `CURRENT_IR_VERSION`
    - Raise `IRVersionError` if `doc_major != cur_major` (Req 1.7.3)
    - Emit `UserWarning` if `doc_minor > cur_minor` (Req 1.7.4)
    - _Requirements: 1.7.2, 1.7.3, 1.7.4_

  - [x] 3.3 Implement `load_ir(data: dict) -> GraphIR`
    - Call `GraphIR.model_validate(data)` — raises `pydantic.ValidationError` on failure
    - Call `_check_version(graph.schema_version)` — raises `IRVersionError` on mismatch
    - Return validated `GraphIR`
    - _Requirements: 1.8.1, 1.8.7_

  - [x] 3.4 Implement `load_ir_from_file(path: str) -> GraphIR`
    - Raise `FileNotFoundError` if file does not exist (Req 1.8.5)
    - Call `json.load()` — raises `json.JSONDecodeError` on invalid JSON (Req 1.8.6)
    - Delegate to `load_ir(data)`
    - _Requirements: 1.8.2, 1.8.5, 1.8.6_

  - [x] 3.5 Implement `dump_ir(graph: GraphIR) -> dict`
    - Return `graph.model_dump(mode="json")`
    - _Requirements: 1.8.3_

  - [x] 3.6 Implement `dump_ir_to_file(graph: GraphIR, path: str) -> None`
    - Write with `json.dump(..., indent=2, ensure_ascii=False)` + trailing newline
    - _Requirements: 1.8.4_

  - [x]* 3.7 Write unit tests for loader
    - `test_load_ir_file_not_found` — `FileNotFoundError` on missing file
    - `test_load_ir_invalid_json` — `json.JSONDecodeError` on bad JSON
    - `test_load_ir_schema_mismatch` — `pydantic.ValidationError` on wrong schema
    - `test_version_rejection_major` — `IRVersionError` when major differs
    - `test_version_warning_minor` — `UserWarning` when minor is higher
    - `test_round_trip_file` — `load_ir_from_file(dump_ir_to_file(g))` equals `g`
    - _Requirements: 1.7.3, 1.7.4, 1.8.5, 1.8.6, 1.8.7, 1.8.8_

- [x] 4. Update `app/core/ir/__init__.py` with complete re-exports
  - Re-export all public symbols from `models.py` and `loader.py` as listed in design-01
  - Verify `from app.core.ir import GraphIR, IRNode, IREdge, IRMetadata, IRParameter,
    IRCapabilityMetadata, CURRENT_IR_VERSION, IRVersionError, IRValidationError,
    load_ir, load_ir_from_file, dump_ir, dump_ir_to_file` all resolve
  - _Requirements: 1.1.3, 5.2.5_

- [x] 5. Checkpoint — verify IR package in isolation
  - Run `venv/bin/python -c "from app.core.ir import GraphIR, load_ir, dump_ir; print('OK')"` — must print `OK`
  - Run `venv/bin/pytest tests/ -x --tb=short -q` — all existing tests must pass (zero regressions)
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- `models.py` and `loader.py` must NOT import from `app/core/pipeline.py`,
  `app/core/nodes/`, or `app/core/sdk.py` — the IR is runtime-agnostic (Req 1.11.3)
- All IR models use `ConfigDict(frozen=True)` — enables `==` comparison for round-trip tests
- `IRParameter.default` is typed `Any` — constrain to JSON primitives in practice
