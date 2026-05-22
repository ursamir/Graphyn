# Requirements Document — Advanced Runtime (Phase 3)

## Introduction

This document captures the requirements for **Phase 3** of the six-phase platform evolution roadmap.

Phase 3 extends the execution runtime with advanced execution modes that operate directly on the `GraphIR` contract established in Phase 1. The current `run_pipeline_ir()` function executes nodes strictly sequentially in a single thread. Phase 3 introduces:

- **Parallel execution** — independent nodes in the same topological wave execute concurrently
- **Async runtime** — a native `asyncio`-based executor replaces the `asyncio.run()` bridge
- **Resumability** — a failed or interrupted run can be resumed from the last successful checkpoint
- **Partial execution** — a subgraph of nodes can be executed without running the full pipeline
- **Conditional branching** — edges can carry boolean conditions that gate data flow at runtime
- **Event-driven execution** — nodes can be triggered by external events rather than data-push topology

Phase 3 builds directly on the Phase 1 and Phase 2 foundations:
- `GraphIR` / `IRNode` / `IREdge` (canonical graph contract — extended minimally for conditions)
- `run_pipeline_ir()` (preserved and extended; not replaced)
- `NodeExecutor` (extended with async-native execution)
- `PipelineGraph` (extended with parallel tier computation)
- `RunManager` (extended with resume state persistence)
- `PipelineLogger` (extended with new event types)
- MCP execution tool (Phase 2) delegates to the same `run_pipeline_ir()` — gains all Phase 3 modes automatically

All 787 existing tests must not regress. All current public APIs (`Pipeline`, `PipelineNode`, CLI commands, REST endpoints, MCP tools) must remain fully functional throughout this phase.

---

## Sub-Document Index

| Sub-Document | Description |
|---|---|
| [req-01-parallel-async.md](req-01-parallel-async.md) | Parallel tier execution and async-native runtime |
| [req-02-resumability.md](req-02-resumability.md) | Run resumability from checkpoint state |
| [req-03-partial-execution.md](req-03-partial-execution.md) | Subgraph / partial pipeline execution |
| [req-04-conditional-branching.md](req-04-conditional-branching.md) | Conditional edges and branching logic |
| [req-05-event-driven.md](req-05-event-driven.md) | Event-driven node triggering |
| [req-06-runtime-api.md](req-06-runtime-api.md) | Runtime control API (pause, cancel, status) |

---

## Glossary

- **Execution_Wave** — A set of nodes that have no data dependencies on each other and can execute concurrently. Computed from the topological sort of the DAG.
- **Parallel_Executor** — The component that schedules and runs nodes within an Execution_Wave concurrently using `asyncio` tasks or a thread pool.
- **Async_Runtime** — The `asyncio`-native execution path that replaces the `asyncio.run()` bridge in the current `run_pipeline_ir()`.
- **Resume_State** — A persisted record of which nodes completed successfully in a prior run, stored at `workspace/runs/<run_id>/resume_state.json`.
- **Checkpoint** — The per-node output snapshot written to `workspace/runs/<run_id>/checkpoints/<node_id>/`. Already exists in Phase 1; Phase 3 makes it readable for resume.
- **Partial_Execution** — Executing only a named subset of nodes from a `GraphIR`, with upstream outputs sourced from checkpoints or provided directly.
- **Subgraph** — The induced subgraph of a `GraphIR` containing only the requested nodes and the edges between them.
- **Conditional_Edge** — An `IREdge` carrying a `condition` field. The edge transmits data only when the condition evaluates to `true` at runtime.
- **Condition_Expression** — A string expression evaluated against the upstream node's output to produce a boolean gate value.
- **Event_Source** — An external trigger (file system event, timer, queue message) that initiates execution of one or more nodes.
- **Event_Trigger** — An `IRNode` configuration field that binds a node to an Event_Source, causing it to execute when the event fires.
- **Runtime_Controller** — The component that exposes pause, resume, and cancel operations on a running pipeline.
- **Run_Status** — The current lifecycle state of a run: `running`, `paused`, `completed`, `failed`, `cancelled`, `resuming`.
- **GraphIR** — The canonical graph intermediate representation defined in `app/core/ir/models.py`. Extended minimally in Phase 3 for conditional edges.
- **IREdge** — Extended in Phase 3 with an optional `condition` field.
- **run_pipeline_ir** — The primary execution entry point. Extended in Phase 3 with new keyword arguments; existing call sites remain valid.
- **PipelineGraph** — Extended in Phase 3 to compute parallel execution waves.
- **NodeExecutor** — Extended in Phase 3 with async-native execution.
- **RunManager** — Extended in Phase 3 with resume state persistence and run control.
- **PipelineLogger** — Extended in Phase 3 with new event types for parallel, resume, partial, conditional, and event-driven execution.
- **SDK** — `app/core/sdk.py`. `Pipeline.run()` gains new keyword arguments mirroring `run_pipeline_ir()`.
- **CLI** — `app/cli/main.py`. New flags added to `audiobuilder run` for Phase 3 modes.
- **REST_API** — `app/api/routers/runs.py`. New endpoints for run control and resume.
- **MCP_Execution_Tool** — Phase 2 MCP tool. Gains Phase 3 modes via `run_pipeline_ir()` delegation.

---

## Current Architecture (Preserved — Must Not Regress)

| Component | Location | Phase 3 Role |
|---|---|---|
| `GraphIR`, `IRNode`, `IREdge` | `app/core/ir/models.py` | Extended: `IREdge` gains optional `condition` field |
| `run_pipeline_ir()` | `app/core/pipeline.py` | Extended: new kwargs; existing signature preserved |
| `PipelineGraph` | `app/core/pipeline.py` | Extended: parallel wave computation added |
| `NodeExecutor` | `app/core/pipeline.py` | Extended: async-native path added |
| `PipelineLogger` | `app/core/logger.py` | Extended: new event types added |
| `RunManager` | `app/core/run_manager.py` | Extended: resume state + run control |
| `PipelineCache` | `app/core/pipeline_cache.py` | Preserved; used by resume path |
| `Pipeline`, `PipelineNode` | `app/core/sdk.py` | Extended: new `run()` kwargs |
| CLI (`audiobuilder run`) | `app/cli/main.py` | Extended: new flags |
| REST API | `app/api/routers/runs.py` | Extended: new endpoints |
| MCP Execution Tool | `app/mcp/handlers/execution.py` | Gains Phase 3 modes automatically |
| 787 passing tests | `tests/` | Must not regress |

---

## Requirements

### Requirement 1: Parallel Execution

**User Story:** As a pipeline author, I want independent nodes to execute concurrently, so that pipelines with parallel branches complete faster without requiring any changes to the graph definition.

#### Acceptance Criteria

1. THE Parallel_Executor SHALL compute Execution_Waves from the `PipelineGraph` topological order, where each wave contains all nodes whose upstream dependencies are satisfied by the completion of all prior waves.
2. WITHIN a single Execution_Wave, THE Parallel_Executor SHALL execute all nodes concurrently using `asyncio` tasks (for async-capable nodes) or a `ThreadPoolExecutor` (for sync nodes), with a configurable `max_workers` parameter (default: `min(32, os.cpu_count() + 4)`).
3. THE Parallel_Executor SHALL NOT execute a node until all nodes in prior waves have completed successfully.
4. IF any node in a wave raises an exception, THE Parallel_Executor SHALL cancel all remaining tasks in that wave, call `teardown()` on all nodes in the wave, emit a `node_error` event for the failing node, and propagate the exception to terminate the run.
5. WHEN `run_pipeline_ir()` is called with `parallel=True` (new keyword argument, default `False`), THE Parallel_Executor SHALL be used; WHEN `parallel=False` (default), the existing sequential execution path SHALL be used unchanged.
6. THE Parallel_Executor SHALL emit `wave_start` and `wave_end` events via `PipelineLogger` at the beginning and end of each wave, containing `wave_index` (int) and `node_ids` (list of strings) fields.
7. FOR ALL pipelines with no parallel branches (linear chains), the Parallel_Executor SHALL produce outputs identical to the sequential executor for the same `GraphIR` and seed (determinism property).
8. THE Parallel_Executor SHALL respect the `cacheable` flag in `IRCapabilityMetadata`: nodes with `cacheable=False` SHALL NOT have their outputs stored in `PipelineCache` even when `use_cache=True`.
9. THE `PipelineGraph` SHALL expose a `execution_waves` property returning `list[list[str]]` — a list of waves, each wave being a list of node IDs — computed once at graph construction time.
10. THE Parallel_Executor SHALL pass the correct assembled inputs to each node in a wave, sourcing values from the `node_outputs` dict populated by prior waves.

---

### Requirement 2: Async-Native Runtime

**User Story:** As a platform developer, I want the execution runtime to be natively async, so that streaming nodes, I/O-bound nodes, and future async integrations do not require the `asyncio.run()` bridge that currently blocks the event loop.

#### Acceptance Criteria

1. THE Async_Runtime SHALL provide an `async def run_pipeline_ir_async()` function in `app/core/pipeline.py` with the same signature as `run_pipeline_ir()` plus an `event_loop` optional parameter, that executes the pipeline natively within an existing event loop.
2. THE `run_pipeline_ir()` synchronous function SHALL remain the primary entry point and SHALL delegate to `run_pipeline_ir_async()` via `asyncio.run()` when called from synchronous contexts, preserving full backward compatibility.
3. THE Async_Runtime SHALL execute streaming nodes (where `node.is_streaming` is `True`) via `NodeExecutor.execute_stream()` natively without wrapping in `asyncio.run()`.
4. THE Async_Runtime SHALL execute non-streaming nodes via `asyncio.get_event_loop().run_in_executor()` with a `ThreadPoolExecutor` to avoid blocking the event loop.
5. WHEN `run_pipeline_ir_async()` is awaited from within an existing `asyncio` event loop (e.g., from the MCP server or a FastAPI endpoint), it SHALL execute without creating a nested event loop.
6. THE Async_Runtime SHALL preserve all existing event emission (`pipeline_start`, `node_start`, `node_end`, `node_error`, `done`, `error`) with identical field schemas.
7. FOR ALL pipelines, `run_pipeline_ir_async()` SHALL produce outputs identical to `run_pipeline_ir()` for the same `GraphIR` and seed (equivalence property).

---

### Requirement 3: Resumability

**User Story:** As a pipeline operator, I want to resume a failed or interrupted pipeline run from the last successful checkpoint, so that long-running pipelines do not need to re-execute completed nodes after a failure.

#### Acceptance Criteria

1. WHEN `run_pipeline_ir()` is called with `checkpoint=True`, THE RunManager SHALL write a `resume_state.json` file to `workspace/runs/<run_id>/` after each node completes successfully, containing the list of completed node IDs and the run ID.
2. THE `resume_state.json` file SHALL have the schema: `{"run_id": "<str>", "completed_nodes": ["<node_id>", ...], "schema_version": "1.0"}`.
3. WHEN `run_pipeline_ir()` is called with `resume_run_id="<prior_run_id>"`, THE Parallel_Executor SHALL skip all nodes whose IDs appear in the prior run's `resume_state.json` and load their outputs from the prior run's checkpoint directory instead of re-executing them.
4. IF `resume_run_id` references a run directory that does not exist, THEN `run_pipeline_ir()` SHALL raise a `ResumeError` with a message identifying the missing run ID.
5. IF `resume_run_id` references a run whose `resume_state.json` is absent or malformed, THEN `run_pipeline_ir()` SHALL raise a `ResumeError` with a descriptive message.
6. IF a node listed in `resume_state.json` does not have a corresponding checkpoint directory, THEN `run_pipeline_ir()` SHALL log a WARNING and re-execute that node rather than raising an error.
7. WHEN resuming, THE RunManager SHALL create a new run directory with a new `run_id` and write a `meta.json` field `resumed_from: "<prior_run_id>"` to record the provenance.
8. THE `ResumeError` class SHALL be defined in `app/core/pipeline.py` and SHALL be a subclass of `RuntimeError`.
9. WHEN a node is skipped due to resume, THE PipelineLogger SHALL emit a `node_skip` event containing `node_id` (string), `node_type` (string), `reason` (string `"resumed_from_checkpoint"`), and `timestamp` fields.
10. FOR ALL resumed runs, the final output of the pipeline SHALL be identical to a full re-execution of the same `GraphIR` with the same seed, provided no node implementations have changed (resume correctness property).

---

### Requirement 4: Partial Execution

**User Story:** As a pipeline developer, I want to execute only a named subset of nodes from a pipeline graph, so that I can test, debug, or re-run individual stages without executing the full pipeline.

#### Acceptance Criteria

1. WHEN `run_pipeline_ir()` is called with `include_nodes=["<node_id>", ...]`, THE executor SHALL execute only the nodes in the `include_nodes` list, in topological order, sourcing inputs for nodes with no upstream node in the subset from checkpoints or from an `input_overrides` dict.
2. WHEN `run_pipeline_ir()` is called with `exclude_nodes=["<node_id>", ...]`, THE executor SHALL execute all nodes except those in the `exclude_nodes` list, sourcing inputs for nodes whose upstream was excluded from checkpoints or `input_overrides`.
3. IF `include_nodes` and `exclude_nodes` are both provided, THEN `run_pipeline_ir()` SHALL raise a `ValueError` with the message `"include_nodes and exclude_nodes are mutually exclusive"`.
4. WHEN `run_pipeline_ir()` is called with `input_overrides={"<node_id>": {"<port>": <value>}}`, THE executor SHALL use the provided values as the inputs for the specified node, bypassing upstream execution for those ports.
5. IF a node ID in `include_nodes` or `exclude_nodes` does not exist in the `GraphIR`, THEN `run_pipeline_ir()` SHALL raise a `ValueError` identifying the unknown node ID.
6. THE partial execution path SHALL emit the same event types as full execution (`pipeline_start`, `node_start`, `node_end`, `node_error`, `done`, `error`) with a `partial: true` field added to the `pipeline_start` event.
7. THE partial execution path SHALL write a `meta.json` field `partial_execution: true` and `included_nodes: [...]` (or `excluded_nodes: [...]`) to record which nodes were executed.
8. FOR ALL partial executions where `include_nodes` contains all nodes in the graph, the output SHALL be identical to a full execution of the same `GraphIR` (completeness property).

---

### Requirement 5: Conditional Branching

**User Story:** As a pipeline author, I want to define edges with boolean conditions so that data flows only along branches where the condition is satisfied, enabling dynamic routing without requiring separate graph definitions.

#### Acceptance Criteria

1. THE `IREdge` model SHALL be extended with an optional `condition` field of type `str | None` (default `None`), preserving full backward compatibility — all existing `IREdge` instances without a `condition` field SHALL behave identically to the current implementation.
2. WHEN an `IREdge` has a non-null `condition` field, THE executor SHALL evaluate the condition expression against the source node's output dict before transmitting data to the destination node.
3. THE condition expression language SHALL support: field access (`output["key"]`), comparison operators (`==`, `!=`, `<`, `>`, `<=`, `>=`), boolean operators (`and`, `or`, `not`), and `len()` calls — evaluated via Python's `ast.literal_eval`-safe subset using a restricted `eval()` with only the source node's output dict in scope.
4. IF a condition expression evaluates to `True`, THE executor SHALL transmit the source port's value to the destination port as normal.
5. IF a condition expression evaluates to `False`, THE executor SHALL NOT transmit data on that edge; the destination node's input port SHALL receive `None` for that port.
6. IF a condition expression raises an exception during evaluation, THE executor SHALL emit a `node_error` event for the destination node with `error_type: "ConditionEvaluationError"` and the exception message, and SHALL NOT execute the destination node.
7. WHEN a destination node receives `None` on a required input port due to a false condition, THE executor SHALL skip execution of that node and emit a `node_skip` event with `reason: "condition_false"`.
8. THE `GraphIR` schema version SHALL be bumped to `"1.1"` to reflect the `IREdge.condition` extension; the IR loader SHALL accept both `"1.0"` and `"1.1"` documents.
9. THE `IREdge.condition` field SHALL be included in `IREdge.model_json_schema()` output with a description string `"Optional boolean condition expression. Edge transmits data only when this evaluates to true."`.
10. FOR ALL `IREdge` instances where `condition` is `None`, the executor SHALL behave identically to the Phase 1/2 behavior (backward compatibility property).

---

### Requirement 6: Event-Driven Execution

**User Story:** As a pipeline operator, I want to bind pipeline nodes to external event sources so that pipelines can be triggered by file system changes, timers, or queue messages without polling.

#### Acceptance Criteria

1. THE platform SHALL provide an `EventSource` abstract base class in `app/core/events.py` with a single abstract method `async def watch() -> AsyncGenerator[dict, None]` that yields event payloads.
2. THE platform SHALL provide three built-in `EventSource` implementations: `FileWatcherSource` (watches a directory for new files using `watchfiles` or `watchdog`), `TimerSource` (fires at a configurable interval in seconds), and `QueueSource` (reads from an `asyncio.Queue`).
3. THE `IRNode` model SHALL be extended with an optional `event_trigger` field of type `dict | None` (default `None`) containing `source_type` (string) and `source_config` (dict) fields, preserving full backward compatibility.
4. WHEN `run_pipeline_ir()` is called with `event_driven=True`, THE Async_Runtime SHALL identify all nodes with a non-null `event_trigger` field and bind them to the corresponding `EventSource` instances.
5. WHEN an `EventSource` yields an event payload, THE Async_Runtime SHALL inject the payload as the `input` port value of the bound node and execute that node and all its downstream dependents.
6. WHEN `event_driven=True`, THE Async_Runtime SHALL run indefinitely until cancelled via `Runtime_Controller.cancel()` or until a `KeyboardInterrupt` is received.
7. THE PipelineLogger SHALL emit an `event_received` event when an `EventSource` fires, containing `source_type` (string), `node_id` (string), `payload_keys` (list of strings from the event payload dict), and `timestamp` fields.
8. IF an `EventSource` raises an exception during `watch()`, THE Async_Runtime SHALL log the error at ERROR level, emit an `error` event, and stop the event-driven run.
9. THE `FileWatcherSource` SHALL accept a `path` config key (directory to watch) and a `pattern` config key (glob pattern, default `"*"`), and SHALL yield `{"path": "<absolute_file_path>", "event": "created"|"modified"}` payloads.
10. THE `TimerSource` SHALL accept an `interval_s` config key (float, seconds between fires) and SHALL yield `{"tick": <int>, "timestamp": "<ISO 8601>"}` payloads.
11. FOR ALL event-driven runs, the `meta.json` SHALL include `event_driven: true` and `trigger_count: <int>` (number of events processed before the run ended).

---

### Requirement 7: Runtime Control API

**User Story:** As a pipeline operator, I want to pause, resume, and cancel a running pipeline programmatically, so that I can manage long-running executions without killing the process.

#### Acceptance Criteria

1. THE `RunManager` SHALL expose `pause()`, `resume()`, and `cancel()` methods that set a shared `asyncio.Event` or `threading.Event` checked by the executor between node executions.
2. WHEN `RunManager.pause()` is called on a running pipeline, THE executor SHALL complete the currently executing node(s), then suspend before starting the next wave or node, and update `meta.json` status to `"paused"`.
3. WHEN `RunManager.resume()` is called on a paused pipeline, THE executor SHALL continue from the suspension point and update `meta.json` status back to `"running"`.
4. WHEN `RunManager.cancel()` is called on a running or paused pipeline, THE executor SHALL stop after the current node(s) complete, call `teardown()` on all nodes, emit a `pipeline_cancelled` event, and update `meta.json` status to `"cancelled"`.
5. THE REST API SHALL expose `POST /api/v1/runs/{run_id}/pause`, `POST /api/v1/runs/{run_id}/resume`, and `POST /api/v1/runs/{run_id}/cancel` endpoints that delegate to the corresponding `RunManager` methods for the active run.
6. IF a `pause`, `resume`, or `cancel` request references a `run_id` that is not currently active (i.e., already completed, failed, or not found), THE REST API SHALL return HTTP 404 with a structured error body.
7. THE PipelineLogger SHALL emit `pipeline_paused` and `pipeline_resumed` events with `run_id` and `timestamp` fields when the pipeline transitions to/from paused state.
8. THE `pipeline_cancelled` event SHALL contain `run_id`, `nodes_completed` (int), `nodes_remaining` (int), and `timestamp` fields.
9. THE MCP server SHALL expose `pause_run`, `resume_run`, and `cancel_run` tools that accept a `run_id` argument and delegate to the REST API or `RunManager` directly.
10. FOR ALL active runs, `RunManager.cancel()` SHALL guarantee that `teardown()` is called on every node that had `setup()` called, regardless of the cancellation point (resource cleanup guarantee).

---

### Requirement 8: Backward Compatibility and Non-Regression

**User Story:** As a platform user, I want Phase 3 runtime extensions to have no impact on existing pipelines, APIs, and tests, so that current integrations continue to work without modification.

#### Acceptance Criteria

1. THE `run_pipeline_ir()` function signature SHALL remain backward compatible: all new parameters (`parallel`, `resume_run_id`, `include_nodes`, `exclude_nodes`, `input_overrides`, `event_driven`, `max_workers`) SHALL have default values that reproduce the current behavior.
2. WHEN `run_pipeline_ir()` is called with no new arguments, it SHALL execute identically to the Phase 1/2 implementation (sequential, no resume, no partial, no conditions, no events).
3. THE `IREdge` extension (adding `condition`) SHALL be backward compatible: existing `GraphIR` documents without `condition` fields SHALL load and execute without modification.
4. THE `IRNode` extension (adding `event_trigger`) SHALL be backward compatible: existing `GraphIR` documents without `event_trigger` fields SHALL load and execute without modification.
5. THE schema version bump to `"1.1"` SHALL be handled by the IR loader accepting both `"1.0"` and `"1.1"` documents; `"1.0"` documents SHALL be treated as `"1.1"` with all new fields set to their defaults.
6. IF the 787 existing tests are run after Phase 3 implementation with no changes to test source files or runner configuration, THEN all 787 tests SHALL pass.
7. THE MCP Execution Tool (Phase 2) SHALL gain Phase 3 modes automatically via `run_pipeline_ir()` delegation without any changes to `app/mcp/handlers/execution.py`.
8. THE `Pipeline.run()` SDK method SHALL accept all new `run_pipeline_ir()` keyword arguments and pass them through transparently.
9. THE CLI `audiobuilder run` command SHALL accept `--parallel`, `--resume <run_id>`, `--include-nodes <id,...>`, `--exclude-nodes <id,...>`, and `--event-driven` flags, all defaulting to the current behavior when omitted.
