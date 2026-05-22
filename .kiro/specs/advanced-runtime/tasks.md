# Tasks — Advanced Runtime (Phase 3)

## Task Groups

- **Group A** — IR Schema Extensions (foundation, no dependencies)
- **Group B** — Async Runtime + Parallel Execution (depends on A)
- **Group C** — Resumability (depends on B)
- **Group D** — Partial Execution (depends on B)
- **Group E** — Conditional Branching (depends on A, B)
- **Group F** — Event-Driven Execution (depends on B)
- **Group G** — Runtime Control API (depends on B)
- **Group H** — SDK / CLI / API wiring (depends on B, C, D, E, F, G)
- **Group I** — Tests (depends on all implementation groups)

---

- [x] 1. Extend `IREdge` with optional `condition` field and bump IR schema to `"1.1"`
  - Add `condition: str | None = None` to `IREdge` in `app/core/ir/models.py`
  - Add `event_trigger: dict | None = None` to `IRNode` in `app/core/ir/models.py`
  - Update `app/core/ir/loader.py`: set `SUPPORTED_MINOR_MAX = 1`, accept `"1.0"` as `"1.1"` (treat missing `condition`/`event_trigger` as `None`)
  - Verify all 787 existing tests still pass after schema change
  - Update `pipeline-execution.md` steering file: note `"1.1"` schema version and new fields

- [x] 2. Add `execution_waves` property to `PipelineGraph`
  - Implement level-based BFS wave computation in `PipelineGraph` in `app/core/pipeline.py`
  - Expose `execution_waves: list[list[str]]` property (computed once at `_build()` time, cached as `self._waves`)
  - Update `execution_order` property to return `list(itertools.chain(*self._waves))` (identical output)
  - Verify all 787 existing tests still pass

- [x] 3. Implement `run_pipeline_ir_async()` — async-native execution entry point
  - Add `async def run_pipeline_ir_async(graph, logger, use_cache, checkpoint, streaming, parallel, observer, run_manager, max_workers, resume_run_id, include_nodes, exclude_nodes, input_overrides, event_driven, event_loop)` to `app/core/pipeline.py`
  - Move the core execution logic from `run_pipeline_ir()` into `run_pipeline_ir_async()`
  - Update `run_pipeline_ir()` to delegate: `return asyncio.run(run_pipeline_ir_async(...))`
  - Ensure all existing call sites (no new args) produce identical outputs
  - Verify all 787 existing tests still pass

- [x] 4. Implement `ParallelExecutor` in `app/core/executor.py`
  - Create `app/core/executor.py` with `ParallelExecutor` class
  - `ParallelExecutor.run_wave(wave, node_outputs, ...)` executes all nodes in a wave concurrently using `asyncio.gather` + `ThreadPoolExecutor` for sync nodes
  - Emit `wave_start` / `wave_end` events via `PipelineLogger`
  - Add `wave_start()` and `wave_end()` methods to `PipelineLogger` in `app/core/logger.py`
  - Wire `parallel=True` path in `run_pipeline_ir_async()` to use `ParallelExecutor`
  - Respect `cacheable=False` flag: skip cache save for non-cacheable nodes
  - Verify all 787 existing tests still pass (parallel=False default)

- [x] 5. Implement `ResumeError` and resumability in `RunManager` and executor
  - Define `class ResumeError(RuntimeError)` in `app/core/pipeline.py`
  - Add `init_resume_state(graph_hash)`, `update_resume_state(node_id)`, `load_resume_state(run_id)` to `RunManager` in `app/core/run_manager.py`
  - Add `node_skip(node_id, node_type, reason)` to `PipelineLogger` in `app/core/logger.py`
  - Implement resume path in `run_pipeline_ir_async()`: load prior `resume_state.json`, skip completed nodes, load checkpoint outputs
  - Write `resumed_from`, `skipped_nodes`, `executed_nodes` to `meta.json` on resume
  - Verify all 787 existing tests still pass

- [x] 6. Implement partial execution (`include_nodes` / `exclude_nodes` / `input_overrides`)
  - Add `find_latest_checkpoint(node_id)` to `RunManager` in `app/core/run_manager.py`
  - Implement partial execution logic in `run_pipeline_ir_async()`: resolve `active_nodes`, validate IDs, raise `ValueError` on mutual exclusion or unknown IDs
  - Extend `PipelineLogger.pipeline_start()` with optional `partial` and `included_nodes` kwargs
  - Write `partial_execution`, `included_nodes`/`excluded_nodes` to `meta.json`
  - Verify all 787 existing tests still pass

- [x] 7. Implement conditional branching in `app/core/conditions.py` and executor
  - Create `app/core/conditions.py` with `evaluate_condition(expression, output)`, `ConditionEvaluationError`, and `_validate_ast()` AST whitelist
  - Integrate condition evaluation in `run_pipeline_ir_async()` execution loop: evaluate `IREdge.condition` before transmitting data; emit `node_skip` with `reason="condition_false"` when a required port receives `None` from a false condition
  - Verify all 787 existing tests still pass (condition=None default)

- [x] 8. Implement `EventSource` and event-driven execution in `app/core/events.py`
  - Create `app/core/events.py` with `EventSource` ABC, `FileWatcherSource`, `TimerSource`, `QueueSource`, and `create_event_source()` factory
  - Implement event-driven execution path in `run_pipeline_ir_async()`: bind trigger nodes to sources, run indefinitely until cancelled, emit `event_received` events
  - Add `event_received()` to `PipelineLogger` in `app/core/logger.py`
  - Write `event_driven: true` and `trigger_count` to `meta.json`
  - Verify all 787 existing tests still pass

- [x] 9. Implement Runtime Control API (`pause` / `resume` / `cancel`)
  - Add `pause()`, `resume()`, `cancel()`, `wait_if_paused()`, `is_paused`, `is_cancelled`, `mark_cancelled()`, `_write_meta_field()` to `RunManager` in `app/core/run_manager.py`
  - Add module-level `register_active_run()`, `get_active_run()`, `deregister_active_run()` to `app/core/run_manager.py`
  - Add pause/cancel check between nodes in `run_pipeline_ir_async()`
  - Add `pipeline_paused()`, `pipeline_resumed()`, `pipeline_cancelled()` to `PipelineLogger` in `app/core/logger.py`
  - Create `app/api/routers/run_control.py` with `POST /api/v1/runs/{run_id}/pause`, `/resume`, `/cancel`
  - Register `run_control` router in `app/api/main.py`
  - Create `app/mcp/handlers/run_control.py` with `pause_run`, `resume_run`, `cancel_run` MCP tools
  - Register new MCP tools in `app/mcp/tool_registry.py`
  - Update `api-endpoints.md` steering file with new run control endpoints
  - Update `mcp-server.md` steering file with new run control tools
  - Verify all 787 existing tests still pass

- [x] 10. Wire Phase 3 modes into SDK, CLI, and REST API
  - Update `Pipeline.run()` in `app/core/sdk.py` to accept and pass through: `parallel`, `resume_run_id`, `include_nodes`, `exclude_nodes`, `input_overrides`, `event_driven`, `max_workers`
  - Add CLI flags to `audiobuilder run` in `app/cli/main.py`: `--parallel` (flag), `--resume <run_id>` (option), `--include-nodes <id,...>` (option), `--exclude-nodes <id,...>` (option), `--event-driven` (flag)
  - Update `sdk-cli.md` steering file with new CLI flags
  - Verify all 787 existing tests still pass

- [x] 11. Write tests for parallel execution and async runtime
  - Create `tests/test_parallel_executor.py`:
    - Test that independent nodes in a wave execute concurrently (timing assertion)
    - Test that dependent nodes execute in correct order across waves
    - Test that a node failure in a wave cancels remaining wave tasks
    - Test that `parallel=True` produces identical outputs to `parallel=False` for linear pipelines (determinism property)
    - Test `execution_waves` property on `PipelineGraph` for various DAG shapes
  - Create `tests/test_async_runtime.py`:
    - Test that `run_pipeline_ir_async()` produces identical outputs to `run_pipeline_ir()` (equivalence property)
    - Test that `run_pipeline_ir_async()` can be awaited from within an existing event loop

- [x] 12. Write tests for resumability
  - Create `tests/test_resumability.py`:
    - Test that `resume_state.json` is written after each node when `checkpoint=True`
    - Test that a resumed run skips completed nodes and loads checkpoint outputs
    - Test that `ResumeError` is raised for missing run ID
    - Test that `ResumeError` is raised for missing `resume_state.json`
    - Test that a missing checkpoint for a completed node triggers re-execution (warning, not error)
    - Test that `meta.json` contains `resumed_from` field on resume
    - Test `node_skip` event is emitted for skipped nodes

- [x] 13. Write tests for partial execution
  - Create `tests/test_partial_execution.py`:
    - Test `include_nodes` executes only specified nodes
    - Test `exclude_nodes` skips specified nodes
    - Test `ValueError` raised when both `include_nodes` and `exclude_nodes` provided
    - Test `ValueError` raised for unknown node IDs
    - Test `input_overrides` injects values correctly
    - Test `pipeline_start` event contains `partial: true` and `included_nodes`
    - Test `meta.json` contains `partial_execution: true`
    - Test that `include_nodes` with all nodes produces identical output to full execution (completeness property)

- [x] 14. Write tests for conditional branching
  - Create `tests/test_conditional_branching.py`:
    - Test that a `True` condition transmits data normally
    - Test that a `False` condition sets destination port to `None`
    - Test that a `False` condition on a required port emits `node_skip` with `reason="condition_false"`
    - Test that a condition evaluation error emits `node_error` with `error_type="ConditionEvaluationError"`
    - Test that `condition=None` edges behave identically to Phase 1/2 (backward compatibility)
    - Test `evaluate_condition()` with comparison, boolean, and `len()` expressions
    - Test that unsafe expressions (imports, attribute access) raise `ConditionEvaluationError`
    - Test `"1.0"` IR documents load correctly as `"1.1"` with `condition=None`

- [x] 15. Write tests for event-driven execution and runtime control
  - Create `tests/test_event_driven.py`:
    - Test `QueueSource` fires and injects payload as node input
    - Test `TimerSource` fires at configured interval (short interval, 2 ticks)
    - Test `event_received` event is emitted on each trigger
    - Test `meta.json` contains `event_driven: true` and correct `trigger_count`
    - Test that cancelling an event-driven run stops the source watchers
  - Create `tests/test_runtime_control.py`:
    - Test `RunManager.pause()` sets status to `"paused"` in `meta.json`
    - Test `RunManager.resume()` sets status back to `"running"`
    - Test `RunManager.cancel()` sets status to `"cancelled"` and calls `teardown()` on all nodes
    - Test `get_active_run()` returns the active `RunManager` during execution
    - Test `get_active_run()` returns `None` after run completes
    - Test REST endpoints return 404 for inactive run IDs
    - Test `pipeline_paused`, `pipeline_resumed`, `pipeline_cancelled` events are emitted
