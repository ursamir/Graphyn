# Tasks 01 — Foundation: Errors, Ports, Config, Node Base Class, Compat

← [Back to tasks.md](tasks.md)

---

## Tasks

- [x] 1. Add `hypothesis` and `pydantic` to `requirements.txt`
  - Add `hypothesis==6.112.2` (or latest stable) to `requirements.txt` if not present
  - Confirm `pydantic>=2.0` is listed (already a FastAPI transitive dep — add explicit pin)
  - Run `venv/bin/pip install -r requirements.txt` to verify installation
  - _Requirements: R6.3, R7, R11.2 (Hypothesis needed for property tests)_
  - _Design: design.md § File Layout_

- [x] 2. Create `app/core/nodes/errors.py` — custom exception hierarchy
  - Implement `NodeSystemError`, `NodeNotFoundError`, `DuplicateNodeTypeError`, `NodeMetadataError`, `NodeTypeError`, `PortTypeNotFoundError`, `DuplicatePortTypeError`, `PipelineGraphError` as specified
  - All exceptions inherit from `NodeSystemError(Exception)`
  - _Requirements: R2.11, R3.4, R3.9, R4.3, R13A.2, R13A.3_
  - _Design: design-01-node-contract.md § 7, design.md § Error Taxonomy_

- [x] 3. Create `app/core/nodes/ports.py` — `PortDataType`, `InputPort`, `OutputPort`
  - Implement `PortDataType(BaseModel)` with `arbitrary_types_allowed=True`
  - Implement `InputPort(BaseModel)` with fields: `name`, `data_type`, `cardinality`, `required`, `description`
  - Implement `OutputPort(BaseModel)` with fields: `name`, `data_type`, `description`
  - _Requirements: R2A.1–R2A.5, R9.1_
  - _Design: design-01-node-contract.md § 1_

- [x] 4. Create `app/core/nodes/config.py` — `NodeConfig` base class
  - Implement `NodeConfig(BaseModel)` with `extra="forbid"`, `frozen=False`, `populate_by_name=True`
  - _Requirements: R1.1–R1.6_
  - _Design: design-01-node-contract.md § 2_

- [x] 5. Create `app/core/nodes/retry.py` — `RetryPolicy`
  - Implement `RetryPolicy(BaseModel)` with `max_attempts`, `backoff_seconds`, `backoff_multiplier`
  - Add field validators: `max_attempts >= 1`, `backoff_seconds >= 0`, `backoff_multiplier >= 1.0`
  - Implement `wait_before_attempt(attempt_index: int) -> float` returning `backoff_seconds * (backoff_multiplier ** attempt_index)`
  - _Requirements: R6.1–R6.3_
  - _Design: design-03-runtime.md § 1_

- [x] 6. Create `app/core/nodes/compat.py` — `CompatibilityChecker` and `_type_to_schema`
  - Implement `are_compatible(output_type, input_type) -> bool` with all four rules (None/None, None/X, plain classes via `issubclass`, generic aliases via `get_origin`/`get_args`)
  - Implement `check_connection(src_node, src_port, dst_node, dst_port) -> None` raising `NodeTypeError` on mismatch or missing port
  - Implement `_type_to_schema(t) -> dict | None` helper for JSON Schema conversion
  - _Requirements: R2D.10–R2D.13, R2E.14_
  - _Design: design-01-node-contract.md § 4_

- [x] 7. Rewrite `app/core/nodes/base.py` — `Node` base class
  - Implement `Node(Generic[InputT, OutputT])` with all class-level declarations (`node_type`, `metadata`, `input_ports`, `output_ports`, `retry_policy`)
  - Implement `__init__(self, config, seed, observer)` with dict coercion via `Config.model_validate`
  - Implement `__init_subclass__` with `_maybe_wrap_siso` SISO wrapper installation
  - Implement `input_type` / `output_type` properties (SISO only, raise `AttributeError` otherwise)
  - Implement `_is_siso()`, `port_schemas()`, `is_streaming` class property
  - Implement all lifecycle hooks as no-ops: `setup`, `on_start`, `on_end`, `on_error`, `teardown`
  - Implement `process(self, inputs: dict) -> dict` raising `NotImplementedError`
  - Implement `process_stream` default wrapping `process` as single-item async generator
  - Implement `_maybe_wrap_siso` module-level helper
  - _Requirements: R1.1–R1.3, R2A.1, R2B.6–R2B.7, R2C.8–R2C.9, R2E.14, R5.1–R5.6, R6.1, R7.1–R7.4, R8.1, R9.1–R9.2_
  - _Design: design-01-node-contract.md § 3_

- [x]* 8. Write unit tests for foundation layer (`tests/test_foundation.py`)
  - Test `NodeConfig` dict coercion: valid dict → config instance; invalid dict → `ValidationError`
  - Test `CompatibilityChecker.are_compatible`: all four rule branches (None/None, None/X, plain classes, generic aliases)
  - Test `CompatibilityChecker.check_connection`: valid connection → no raise; wrong type → `NodeTypeError`; missing port → `NodeTypeError`
  - Test SISO wrapper: `process({"input": x})["output"]` equals direct transform result
  - Test `RetryPolicy.wait_before_attempt` formula for several `(backoff_seconds, backoff_multiplier, i)` triples
  - Test `Node.input_type` / `Node.output_type` on SISO node; `AttributeError` on non-SISO
  - _Requirements: R1.2, R1.4, R2B.6, R2D.10–R2D.11, R6.3_

- [x] 9. Checkpoint — foundation layer
  - Ensure all tests pass, ask the user if questions arise.
