# Functional Review — app/core/orchestrator.py

**Group:** 6 — Execution Runtime  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/orchestrator.py
FUNCTION:    run_pipeline_ir_async
CATEGORY:    Resource Leak
SEVERITY:    CRITICAL
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Coordinate execution of validated DAGs; always teardown executors and
deregister the active run on completion or failure.

WHAT IT ACTUALLY DOES:
In the sequential execution path, if an exception is raised during node
execution, the code calls `run.mark_failed()` and `deregister_active_run()`
and re-raises — but it does NOT call `exec_.teardown()` for any executor.
The `for exec_ in executors.values(): exec_.teardown()` block at the bottom
of the function is only reached on the happy path.

THE BUG / RISK:
Any exception in the sequential path (node failure, condition evaluation error,
cache error) causes all `NodeExecutor` instances to leak without teardown.
Nodes that hold open file handles, GPU memory, model weights, or network
connections will not release them.

EVIDENCE:
```python
# Sequential path exception handler (~line 270):
except Exception as exc:
    logger.node_error(node_type, idx, exc)
    run.save_logs(logger.logs)
    run.mark_failed(str(exc))
    deregister_active_run(run.run_id)
    raise
# ↑ No teardown of executors before raise

# Happy path teardown (~line 370):
for exec_ in executors.values():
    exec_.teardown()   # ← only reached on success
```

REPRODUCTION SCENARIO:
Any node that raises during `process()` in sequential mode. The node's
`teardown()` is never called, leaking whatever resources `setup()` acquired.

IMPACT:
Resource leak — GPU memory, file handles, model weights, network connections
held open for the lifetime of the process. In long-running services this
accumulates across runs.

FIX DIRECTION:
Wrap the sequential execution loop in a `try/finally`:
```python
try:
    for idx, node_id in enumerate(graph_obj.execution_order):
        ...
except Exception as exc:
    ...
    raise
finally:
    for exec_ in executors.values():
        exec_.teardown()
```

--------------------------------------------------------------------
FILE:        app/core/orchestrator.py
FUNCTION:    run_pipeline_ir_async
CATEGORY:    Resource Leak
SEVERITY:    CRITICAL
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Always deregister the active run and teardown executors.

WHAT IT ACTUALLY DOES:
In the parallel execution path, when `par_exec.run_wave()` raises, the code
calls `run.mark_failed()` and `deregister_active_run()` and re-raises — but
it does NOT call `par_exec.shutdown()` (the thread pool is never shut down)
and does NOT call `exec_.teardown()` for any executor.

THE BUG / RISK:
A wave failure in parallel mode leaks the `ThreadPoolExecutor` (threads remain
alive) and all node executors (resources not released). `par_exec.shutdown()`
is only called on the happy path after the wave loop completes.

EVIDENCE:
```python
# Parallel path exception handler (~line 185):
except Exception as exc:
    run.save_logs(logger.logs)
    run.mark_failed(str(exc))
    deregister_active_run(run.run_id)
    raise
# ↑ par_exec.shutdown() and executor teardowns are missing

# Happy path (~line 195):
par_exec.shutdown()   # ← only reached if all waves succeed
```

REPRODUCTION SCENARIO:
Any node failure in parallel mode. The `ThreadPoolExecutor` and all node
resources are leaked.

IMPACT:
Thread pool leak — threads remain alive indefinitely. In a long-running API
server, repeated pipeline failures accumulate leaked thread pools, eventually
exhausting OS thread limits.

FIX DIRECTION:
```python
try:
    for wave_idx, wave in enumerate(graph_obj.execution_waves):
        ...
        await par_exec.run_wave(...)
        ...
except Exception as exc:
    run.save_logs(logger.logs)
    run.mark_failed(str(exc))
    deregister_active_run(run.run_id)
    raise
finally:
    par_exec.shutdown()
    for exec_ in executors.values():
        exec_.teardown()
```

--------------------------------------------------------------------
FILE:        app/core/orchestrator.py
FUNCTION:    run_pipeline_ir_async
CATEGORY:    Resource Leak
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Setup all executors before execution begins, teardown after.

WHAT IT ACTUALLY DOES:
All executors are set up in a loop before execution starts. If `exec_.setup()`
raises for any node (e.g., model file missing, GPU OOM), the exception
propagates immediately — but all executors that were already set up are never
torn down, and `deregister_active_run()` is never called.

THE BUG / RISK:
The setup loop has no error handling. A failure in `setup()` for node N leaves
nodes 0..N-1 set up but never torn down, and the run is never deregistered
from the active run registry.

EVIDENCE:
```python
# Setup loop (~line 130):
for node_id in graph_obj.execution_order:
    exec_ = NodeExecutor(graph_obj.get_node(node_id), run_id=run_id)
    exec_.setup()   # ← if this raises, prior executors leak
    executors[node_id] = exec_
# No try/except around this loop
```

REPRODUCTION SCENARIO:
First node sets up fine (loads a large model). Second node's `setup()` raises
(model file missing). First node's resources are never released.

IMPACT:
Resource leak on setup failure. Run remains registered as active indefinitely.

FIX DIRECTION:
```python
try:
    for node_id in graph_obj.execution_order:
        exec_ = NodeExecutor(graph_obj.get_node(node_id), run_id=run_id)
        exec_.setup()
        executors[node_id] = exec_
except Exception:
    for exec_ in executors.values():
        exec_.teardown()
    deregister_active_run(run.run_id)
    raise
```

--------------------------------------------------------------------
FILE:        app/core/orchestrator.py
FUNCTION:    run_pipeline_ir_async
CATEGORY:    Silent Failure
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the outputs of the final node in topological order.

WHAT IT ACTUALLY DOES:
`graph_obj.execution_order[-1]` is used to find the last node. If
`execution_order` is empty (a graph with zero nodes passes validation), this
raises `IndexError`. More importantly, if the last node was skipped (excluded
from partial execution, or skipped due to a false condition), `node_outputs`
will not contain its key, and `node_outputs.get(last_id, {})` silently returns
`{}` — the caller has no way to distinguish "pipeline succeeded with empty
output" from "last node was skipped."

THE BUG / RISK:
Silent empty-dict return when the last node is skipped. No warning is logged.
The caller (SDK, API, MCP) receives `{}` and may treat it as a successful
empty result.

EVIDENCE:
```python
last_id = graph_obj.execution_order[-1]
deregister_active_run(run.run_id)
return node_outputs.get(last_id, {})   # silent {} if last node skipped
```

REPRODUCTION SCENARIO:
Call with `exclude_nodes=[last_node_id]`. The pipeline runs, the last node is
excluded, and `{}` is returned with no indication that the intended output node
was skipped.

IMPACT:
Silent wrong result — downstream consumers receive empty output and may
silently produce incorrect results.

FIX DIRECTION:
Log a warning when `last_id not in node_outputs`:
```python
if last_id not in node_outputs:
    log.warning("Last node '%s' produced no outputs (skipped or excluded).", last_id)
return node_outputs.get(last_id, {})
```

--------------------------------------------------------------------
FILE:        app/core/orchestrator.py
FUNCTION:    run_pipeline_ir_async (event-driven path)
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Handle event-driven execution; deregister the active run and teardown executors
on completion.

WHAT IT ACTUALLY DOES:
In `_handle_source`, when a node raises during `exec_obj.execute(exec_inputs)`,
the code calls `logger.node_error()` and `break`s out of the inner loop — but
does NOT call `run.mark_failed()`, does NOT call `deregister_active_run()`,
and does NOT teardown executors. The outer `asyncio.gather` continues running
other source handlers. The run remains registered as active indefinitely.

THE BUG / RISK:
A node failure in event-driven mode leaves the run in an indeterminate state:
not marked failed, not deregistered, executors not torn down. The `finally`
block in the outer `try` only calls `deregister_active_run()` after
`asyncio.gather` completes — but `gather` uses `return_exceptions=True`, so
it always completes even if tasks raise. However, the `_handle_source` task
catches the exception internally (via `break`) and returns normally, so
`gather` never sees the exception.

EVIDENCE:
```python
# Inside _handle_source:
try:
    exec_outputs = exec_obj.execute(exec_inputs)
    node_outputs[exec_node_id] = exec_outputs
except Exception as exc:
    logger.node_error(exec_node_type, exec_idx, exc)
    break   # ← run not marked failed, not deregistered
```

REPRODUCTION SCENARIO:
Event-driven pipeline where a triggered node raises. The run stays "active"
forever, blocking any run-count limits or cleanup logic.

IMPACT:
Run registry leak. Run is never marked failed. Resources not released.

FIX DIRECTION:
In the `except` block inside `_handle_source`, call `run.mark_failed(str(exc))`
and set a shared cancellation flag so other source handlers stop.

--------------------------------------------------------------------
FILE:        app/core/orchestrator.py
FUNCTION:    run_pipeline_ir_async (event-driven path)
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Run event-driven execution; sources are closed in the `finally` block.

WHAT IT ACTUALLY DOES:
The `finally` block closes sources again after they were already closed by
`_cancel_watcher`. `EventSource.close()` is called twice: once by
`_cancel_watcher` when `run.is_cancelled` becomes true, and again in the
`finally` block. For `FileWatcherSource`, `close()` sets the stop event and
sleeps 0.3s — calling it twice is harmless but wasteful. For future sources
with non-idempotent `close()` (e.g., closing a network connection), this is
a double-close bug.

THE BUG / RISK:
`close()` is called twice on every source in the cancellation path. The
`EventSource` ABC does not document that `close()` must be idempotent.

EVIDENCE:
```python
async def _cancel_watcher() -> None:
    while not run.is_cancelled:
        await asyncio.sleep(0.2)
    for src in sources.values():
        await src.close()   # ← first close

# ...
finally:
    for src in sources.values():
        await src.close()   # ← second close (always)
    deregister_active_run(run.run_id)
```

REPRODUCTION SCENARIO:
Cancel a running event-driven pipeline. Both `_cancel_watcher` and the
`finally` block call `close()` on each source.

IMPACT:
Double-close on event sources. Safe for current implementations but a latent
bug for any future source with non-idempotent close semantics.

FIX DIRECTION:
Track which sources have been closed, or make `_cancel_watcher` not close
sources (let the `finally` block own all cleanup).

--------------------------------------------------------------------
FILE:        app/core/orchestrator.py
FUNCTION:    run_pipeline_ir_async
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Handle partial execution with `include_nodes` / `exclude_nodes`.

WHAT IT ACTUALLY DOES:
When a node is excluded from partial execution, its outputs are assembled from
upstream outputs and stored as a passthrough dict. However, if an excluded node
has NO incoming edges (it is a source node), `incoming[node_id]` is empty, so
`passthrough` is `{}`. Downstream nodes that depend on this excluded source
node will receive `None` for all their inputs from it — but no warning is
logged and no error is raised.

THE BUG / RISK:
Excluding a source node silently propagates `None` to all its downstream
consumers. The downstream nodes may fail with confusing errors, or silently
produce wrong results if their input ports are optional.

EVIDENCE:
```python
passthrough: dict[str, Any] = {}
for src_id, src_port, dst_port in incoming[node_id]:
    upstream = node_outputs.get(src_id, {})
    value = upstream.get(src_port)
    passthrough[dst_port] = value
node_outputs[node_id] = passthrough
# If incoming[node_id] is empty, passthrough = {} — no warning
```

REPRODUCTION SCENARIO:
`exclude_nodes=["source_node_id"]` where `source_node_id` has no incoming
edges. All downstream nodes receive `None` for inputs from the excluded source.

IMPACT:
Silent wrong result or confusing downstream failure.

FIX DIRECTION:
Log a warning when an excluded node has no incoming edges and downstream nodes
depend on it.

--------------------------------------------------------------------
FILE:        app/core/orchestrator.py
FUNCTION:    run_pipeline_ir_async
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Skip a node when a required input port receives `None` due to a false condition.

WHAT IT ACTUALLY DOES:
The skip-node check re-evaluates conditions a second time (the condition was
already evaluated during input assembly). This double-evaluation is wasteful
and introduces a TOCTOU-style inconsistency: if `node_outputs[src_id]` were
mutable and changed between the two evaluations (not currently possible in
sequential mode, but possible in future parallel extensions), the skip
decision could differ from the input assembly decision.

THE BUG / RISK:
Conditions are evaluated twice per node per edge. In sequential mode this is
merely wasteful. In any future concurrent extension it is a correctness risk.

EVIDENCE:
```python
# First evaluation during input assembly (~line 240):
passes = evaluate_condition(condition, src_outputs)

# Second evaluation during skip check (~line 265):
if not evaluate_condition(condition, src_outputs):
    false_condition_ports.add(dst_port)
```

REPRODUCTION SCENARIO:
Any pipeline with conditional edges. Every node with a conditional input
evaluates the condition twice.

IMPACT:
Performance waste (low severity). Latent correctness risk in concurrent
extensions.

FIX DIRECTION:
Cache condition results from the input assembly phase and reuse them in the
skip check.

--------------------------------------------------------------------
FILE:        app/core/orchestrator.py
FUNCTION:    run_pipeline_ir_async
CATEGORY:    Performance
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Compute `_output_count` for logging.

WHAT IT ACTUALLY DOES:
The output count computation iterates over all output port values and breaks
on the first list it finds. This means the logged `output_count` is the length
of the first list-valued output port, not the total number of outputs. For
nodes with multiple list outputs, only the first is counted. For nodes with
no list outputs, `_output_count` is always 0 even if there are scalar outputs.

THE BUG / RISK:
`output_count` in logs is misleading — it is 0 for all scalar-output nodes
and reflects only the first list port for multi-list nodes.

EVIDENCE:
```python
_output_count = 0
for _v in node_outputs[node_id].values():
    if isinstance(_v, list):
        _output_count = len(_v)
        break   # ← stops at first list, ignores rest
```
(Same pattern repeated in parallel executor and event-driven path.)

REPRODUCTION SCENARIO:
Any node that returns scalar outputs (e.g., a classifier returning a label
string). `output_count` is always logged as 0.

IMPACT:
Misleading logs. Low functional impact but affects observability.

FIX DIRECTION:
```python
_output_count = sum(
    len(v) if isinstance(v, list) else (0 if v is None else 1)
    for v in node_outputs[node_id].values()
)
```

--------------------------------------------------------------------
FILE:        app/core/orchestrator.py
FUNCTION:    run_pipeline_ir_async
CATEGORY:    Testability
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Coordinate execution across all modes in a single async function.

WHAT IT ACTUALLY DOES:
`run_pipeline_ir_async` is ~400 lines with three deeply nested execution paths
(sequential, parallel, event-driven), each with their own teardown, logging,
and error handling logic. The function cannot be unit-tested without a full
`GraphIR`, `PipelineGraph`, `RunManager`, `PipelineLogger`, and `PipelineCache`
stack. There are no seams for injecting test doubles for individual paths.

THE BUG / RISK:
The function is effectively untestable at the unit level. Any regression in
one execution mode requires a full integration test to catch.

EVIDENCE:
Function body spans ~400 lines with 3 major branches, each with 5+ nested
levels of control flow.

REPRODUCTION SCENARIO:
Attempt to write a unit test for just the "resume from checkpoint" logic
without standing up a full RunManager and filesystem.

IMPACT:
Test coverage gap. Bugs in edge cases (resume, partial execution, event-driven
cancellation) are likely to go undetected.

FIX DIRECTION:
Extract each execution mode into a separate async function:
`_run_sequential()`, `_run_parallel()`, `_run_event_driven()`.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | CRITICAL |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | UNSAFE |
| State Safety | UNSAFE |
| Resource Safety | UNSAFE |
| Test Hostile | YES |
| Top Risk | Sequential and parallel execution paths do not teardown node executors or shut down the thread pool on failure, causing resource leaks (GPU memory, file handles, threads) that accumulate across runs in a long-running service |
