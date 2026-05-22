# Tasks 03 — Runtime: Observers, NodeExecutor, Lifecycle, Streaming

← [Back to tasks.md](tasks.md)

---

## Tasks

- [x] 17. Create `app/core/nodes/observers.py` — `NodeObserver`, `LoggingObserver`, `CompositeObserver`
  - Implement `NodeObserver` as an ABC with abstract methods: `on_node_start`, `on_node_end`, `on_node_error`
  - Implement `LoggingObserver` writing one structured JSON line per event to a `logging.Logger`
    - `on_node_start` → `{"event": "node_start", "node_type": ..., "run_id": ...}`
    - `on_node_end` → `{"event": "node_end", ..., "duration_s": ..., "input_counts": ..., "output_counts": ...}`
    - `on_node_error` → `{"event": "node_error", ..., "error": ..., "error_type": ...}`
  - Implement `CompositeObserver` fanning out all events to a list of child observers
  - _Requirements: R8.1–R8.5_
  - _Design: design-03-runtime.md § 2_

- [x] 18. Implement `NodeExecutor` in `app/core/pipeline.py` (runtime section)
  - Add `_count_port_items(port_data) -> int` helper
  - Implement `NodeExecutor.__init__(node, run_id)` storing node and run_id, `_setup_done = False`
  - Implement `NodeExecutor.setup()` calling `node.setup()` once (guarded by `_setup_done`)
  - Implement `NodeExecutor.teardown()` calling `node.teardown()`
  - Implement `NodeExecutor.execute(inputs) -> dict` with full lifecycle sequence:
    - Retry loop up to `policy.max_attempts` (or 1 if no policy)
    - Sleep `policy.wait_before_attempt(attempt - 1)` before each retry (not before first attempt)
    - Call `node.on_start()` → observer `on_node_start` → `node.process(inputs)` → `node.on_end()` → observer `on_node_end`
    - On exception: `node.on_error(exc)` → observer `on_node_error` → continue retry loop
    - After all attempts exhausted: call `on_error`, observer `on_node_error`, `teardown()`, re-raise
    - Log `INFO` on retry success
  - Implement `NodeExecutor.execute_stream(inputs)` as async generator calling `node.process_stream`
  - _Requirements: R5.1–R5.6, R6.1–R6.5, R7.1–R7.3, R8.1–R8.3_
  - _Design: design-03-runtime.md § 3_

- [x]* 19. Write unit tests for runtime layer (`tests/test_runtime.py`)
  - Test `NodeExecutor` lifecycle ordering: mock hooks, verify `setup → on_start → process → on_end → teardown` sequence
  - Test `NodeExecutor` retry: mock `process` to fail N times then succeed; verify retry count and final success
  - Test `NodeExecutor` all-attempts-exhausted: verify `on_error` called, `teardown` called, exception re-raised
  - Test `NodeExecutor` `on_start` raises: verify `on_error` called, `process` NOT called
  - Test `LoggingObserver` emits correct JSON structure for each event type
  - Test `CompositeObserver` fans out to all children
  - _Requirements: R5.3–R5.6, R6.3–R6.5, R8.3–R8.5_

- [x] 20. Checkpoint — runtime layer
  - Ensure all tests pass, ask the user if questions arise.
