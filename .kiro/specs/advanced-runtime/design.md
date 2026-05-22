# Design Document — Advanced Runtime (Phase 3)

## Overview

Phase 3 extends the execution runtime with six capabilities: parallel execution, async-native runtime, resumability, partial execution, conditional branching, and event-driven execution. All capabilities are additive — existing call sites require no changes.

The design principle is **opt-in extension**: every new capability is gated behind a new keyword argument to `run_pipeline_ir()` that defaults to the current behavior.

---

## Architecture

### Component Map

```
run_pipeline_ir()          ← sync entry point (preserved, delegates to async)
  └─ run_pipeline_ir_async()   ← NEW async entry point
       ├─ ParallelExecutor      ← NEW (app/core/executor.py)
       │    └─ execution_waves  ← NEW property on PipelineGraph
       ├─ ResumeLoader          ← NEW (inline in pipeline.py)
       ├─ PartialExecutor       ← NEW (inline in pipeline.py)
       ├─ ConditionEvaluator    ← NEW (app/core/conditions.py)
       ├─ EventLoop             ← NEW (app/core/events.py)
       └─ RuntimeController     ← NEW (RunManager methods)
```

### Execution Flow (all modes combined)

```
run_pipeline_ir_async(graph, parallel=True, resume_run_id=X,
                      include_nodes=[...], event_driven=True)
│
├─ 1. Validate graph (load_ir)
├─ 2. Resolve active_nodes (partial execution filter)
├─ 3. Load resume state (skip completed nodes, load checkpoints)
├─ 4. Build PipelineGraph → compute execution_waves
├─ 5. Register active run (RunManager)
│
├─ [event_driven=False] Sequential/Parallel execution loop:
│    for wave in execution_waves:
│      logger.wave_start(...)
│      run.wait_if_paused()          ← pause/cancel check
│      if run.is_cancelled: break
│      await gather(*[_run_node(nid) for nid in wave])
│      logger.wave_end(...)
│
└─ [event_driven=True] Event loop:
     for each trigger_node:
       asyncio.create_task(_handle_source(node_id, source))
     await gather(all source tasks)
```

---

## Key Design Decisions

### 1. `asyncio.run()` wrapper preserved

`run_pipeline_ir()` remains synchronous and calls `asyncio.run(run_pipeline_ir_async(...))`. This preserves all existing call sites (CLI, SDK, tests) without modification. The async function is the implementation; the sync function is the compatibility shim.

### 2. Thread pool for sync nodes in parallel mode

Sync nodes (`node.is_streaming = False`) are wrapped in `loop.run_in_executor(ThreadPoolExecutor)` when running in parallel mode. This avoids blocking the event loop while maintaining compatibility with nodes that use blocking I/O (soundfile, librosa, etc.).

### 3. `execution_waves` computed at graph construction time

Wave computation is O(N+E) and done once in `PipelineGraph.__init__`. The result is cached as `_waves`. The existing `execution_order` property becomes `list(chain(*self._waves))` — identical output, no behavior change.

### 4. Checkpoint format unchanged for resume

The existing `_write_checkpoint()` format (WAV files + `manifest.json`) is reused for resume. `resume_state.json` is a new lightweight file that lists completed node IDs. The checkpoint loader (`_load_checkpoint()`) is the inverse of `_write_checkpoint()`.

### 5. Condition evaluation uses restricted `eval()`

A full expression parser would be complex. A restricted `eval()` with AST whitelisting provides safety without the overhead of a custom parser. The whitelist allows: comparisons, boolean ops, subscript access (`output["key"]`), and `len()`. No imports, no attribute access on arbitrary objects, no function calls except `len`.

### 6. Schema version `"1.1"` is backward compatible

The IR loader already checks major version only for compatibility. Minor version `1` → `1` is always compatible. `"1.0"` documents load as `"1.1"` with `condition=None` and `event_trigger=None` on all nodes/edges. No migration needed.

### 7. Active run registry is process-local

`_ACTIVE_RUNS` is a module-level dict. This is sufficient for single-process deployments (the current architecture). Multi-process deployments (Phase 5+) would require a distributed state store, but that is out of scope for Phase 3.

### 8. `watchfiles` is an optional dependency

`FileWatcherSource` imports `watchfiles` lazily. If not installed, it falls back to a polling implementation using `asyncio.sleep(1)` + directory scanning. This avoids adding a hard dependency for a feature that may not be used.

---

## IR Schema Changes

### `IREdge` (schema version `"1.1"`)

```python
class IREdge(BaseModel):
    src_id: str
    src_port: str
    dst_id: str
    dst_port: str
    condition: str | None = None   # Phase 3 addition
```

### `IRNode` (schema version `"1.1"`)

```python
class IRNode(BaseModel):
    id: str
    node_type: str
    config: dict[str, Any] = {}
    label: str | None = None
    capability_metadata: IRCapabilityMetadata | None = None
    event_trigger: dict | None = None   # Phase 3 addition
```

Both additions use `None` defaults — fully backward compatible.

---

## New Files

| File | Purpose |
|---|---|
| `app/core/executor.py` | `ParallelExecutor` — wave-based async execution engine |
| `app/core/conditions.py` | `evaluate_condition()`, `ConditionEvaluationError`, AST whitelist |
| `app/core/events.py` | `EventSource` ABC, `FileWatcherSource`, `TimerSource`, `QueueSource` |
| `app/api/routers/run_control.py` | REST endpoints: pause/resume/cancel |
| `app/mcp/handlers/run_control.py` | MCP tools: pause_run/resume_run/cancel_run |
| `tests/test_parallel_executor.py` | Parallel execution tests |
| `tests/test_async_runtime.py` | Async runtime equivalence tests |
| `tests/test_resumability.py` | Resume path tests |
| `tests/test_partial_execution.py` | Partial execution tests |
| `tests/test_conditional_branching.py` | Condition evaluation tests |
| `tests/test_event_driven.py` | Event-driven execution tests (QueueSource) |
| `tests/test_runtime_control.py` | Pause/resume/cancel tests |

---

## Modified Files

| File | Changes |
|---|---|
| `app/core/pipeline.py` | `run_pipeline_ir_async()`, extended `run_pipeline_ir()` signature, `PipelineGraph.execution_waves`, `ResumeError` |
| `app/core/ir/models.py` | `IREdge.condition`, `IRNode.event_trigger` |
| `app/core/ir/loader.py` | Accept `"1.1"`, bump `SUPPORTED_MINOR_MAX` |
| `app/core/run_manager.py` | `pause()`, `resume()`, `cancel()`, `wait_if_paused()`, `update_resume_state()`, `init_resume_state()`, `load_resume_state()`, `find_latest_checkpoint()`, `mark_cancelled()`, active run registry |
| `app/core/logger.py` | `wave_start()`, `wave_end()`, `node_skip()`, `event_received()`, `pipeline_paused()`, `pipeline_resumed()`, `pipeline_cancelled()` |
| `app/core/sdk.py` | `Pipeline.run()` passes through new kwargs |
| `app/cli/main.py` | New flags: `--parallel`, `--resume`, `--include-nodes`, `--exclude-nodes`, `--event-driven` |
| `app/api/main.py` | Register `run_control` router |
| `app/mcp/tool_registry.py` | Register `pause_run`, `resume_run`, `cancel_run` |

---

## Non-Regression Strategy

All new parameters default to `False` / `None`. The existing 787 tests call `run_pipeline_ir()` without new arguments → they exercise the unchanged sequential path. New tests cover only the new paths.

The `asyncio.run()` wrapper in `run_pipeline_ir()` is the only structural change to the existing sync path — it was already using `asyncio.run()` internally for streaming nodes, so this is not a new dependency.
