# Functional Review — app/core/executor.py

**Group:** 6 — Execution Runtime  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/executor.py
FUNCTION:    ParallelExecutor.run_wave
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Execute all nodes in a wave concurrently; re-raise the first exception found
after all tasks have been awaited (Req 1.4).

WHAT IT ACTUALLY DOES:
`asyncio.gather(*tasks, return_exceptions=True)` waits for ALL tasks to
complete (or fail) before any exception is re-raised. This means that if
node A in a wave fails immediately, nodes B and C in the same wave continue
running to completion before the exception is surfaced to the orchestrator.
For long-running nodes (e.g., model inference), this can add significant
latency to failure detection.

THE BUG / RISK:
The docstring says "If any task raises an exception, the first exception is
re-raised after all tasks have been awaited (no cancellation of already-running
tasks)." This is accurate but the consequence is not documented: a single fast
failure in a wave does not cancel the remaining slow nodes. In a wave with one
fast-failing node and one slow node (e.g., 30-second inference), the pipeline
waits the full 30 seconds before reporting the failure.

EVIDENCE:
```python
results = await asyncio.gather(*tasks, return_exceptions=True)
# ↑ waits for ALL tasks regardless of failures

for result in results:
    if isinstance(result, BaseException):
        raise result
```

REPRODUCTION SCENARIO:
Wave with two nodes: NodeA raises immediately, NodeB takes 30 seconds.
The orchestrator waits 30 seconds before seeing the NodeA exception.

IMPACT:
Slow failure detection in parallel mode. Not a correctness bug but a
significant operational issue for long-running pipelines.

FIX DIRECTION:
Document the behavior explicitly. If fast-fail is desired, use
`asyncio.gather` without `return_exceptions=True` (which cancels remaining
tasks on first failure), or implement a custom gather with cancellation.

--------------------------------------------------------------------
FILE:        app/core/executor.py
FUNCTION:    ParallelExecutor._run_node
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Assemble inputs from upstream outputs; reads from `node_outputs` are safe
because wave isolation guarantees prior-wave outputs are fully settled.

WHAT IT ACTUALLY DOES:
The comment correctly notes that reads of `node_outputs[src_id]` are safe
(prior-wave data). However, the write `node_outputs[node_id] = outputs` is
also performed without a lock. While a single `dict.__setitem__` is GIL-safe
in CPython, this is not guaranteed by the Python language spec and will break
under alternative implementations (PyPy, Jython, GraalPy) or if the dict is
replaced with a non-GIL-safe mapping.

More critically: `node_outputs[node_id]` is written by `_run_node` and then
immediately read by the `_write_checkpoint` call and the artifact registration
loop in the same coroutine — but other coroutines in the same wave could
theoretically read `node_outputs[node_id]` before the write completes if the
event loop yields between the assignment and the checkpoint write. In practice
this cannot happen because asyncio is single-threaded and there is no `await`
between the assignment and the reads, but the code relies on this implicit
guarantee without documenting it.

THE BUG / RISK:
The correctness argument depends on CPython's GIL and asyncio's single-threaded
cooperative scheduling. Neither is documented as a requirement. A future
refactor that adds an `await` between `node_outputs[node_id] = outputs` and
the checkpoint write could introduce a race.

EVIDENCE:
```python
node_outputs[node_id] = outputs   # write

# No await between here and:
if checkpoint:
    _write_checkpoint(run_base_path, node_id, node_outputs[node_id], ...)
```

REPRODUCTION SCENARIO:
Not currently reproducible in CPython. Latent risk under alternative runtimes
or future refactors.

IMPACT:
Latent correctness risk. Low immediate impact.

FIX DIRECTION:
Document the invariant explicitly: "No `await` may be inserted between
`node_outputs[node_id] = outputs` and any subsequent read of
`node_outputs[node_id]` in this coroutine."

--------------------------------------------------------------------
FILE:        app/core/executor.py
FUNCTION:    ParallelExecutor._run_node
CATEGORY:    Silent Failure
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Assemble inputs from upstream outputs for each node in the wave.

WHAT IT ACTUALLY DOES:
When a `ConditionEvaluationError` is raised during condition evaluation,
the code catches it and sets `passes = False`, silently treating a broken
condition expression as a "condition not met" result. This means a malformed
condition string (syntax error, disallowed construct) causes the input port
to receive `None` silently, rather than failing the pipeline with a clear error.

THE BUG / RISK:
```python
try:
    passes = evaluate_condition(condition, src_outputs)
except ConditionEvaluationError:
    passes = False   # ← silent: broken condition = condition not met
```
A typo in a condition expression (e.g., `"output['scor'] > 0.5"` where the
key is `"score"`) silently routes `None` to the downstream node instead of
failing with a clear error. The sequential path in `orchestrator.py` correctly
re-raises `ConditionEvaluationError` — the parallel path silently swallows it.

EVIDENCE:
```python
except ConditionEvaluationError:
    passes = False
    continue
```
Compare with orchestrator.py sequential path:
```python
except ConditionEvaluationError as exc:
    logger.node_error(node_type, idx, exc)
    run.save_logs(logger.logs)
    run.mark_failed(str(exc))
    deregister_active_run(run.run_id)
    raise
```

REPRODUCTION SCENARIO:
Parallel pipeline with a malformed condition expression on an edge. Sequential
mode fails with a clear error; parallel mode silently passes `None` to the
downstream node.

IMPACT:
Silent wrong result — parallel and sequential modes behave differently for
the same malformed condition. Debugging is extremely difficult.

FIX DIRECTION:
Re-raise `ConditionEvaluationError` in the parallel path, consistent with
the sequential path:
```python
except ConditionEvaluationError:
    raise   # let run_wave catch it and re-raise to orchestrator
```

--------------------------------------------------------------------
FILE:        app/core/executor.py
FUNCTION:    ParallelExecutor._run_node
CATEGORY:    Resource Leak
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Execute a single node; emit `node_start` / `node_end` / `node_error` events.

WHAT IT ACTUALLY DOES:
`logger.node_start()` is called before the cache check and execution. If an
exception is raised during execution, `logger.node_error()` is called in the
`except` block and the exception is re-raised. However, `logger.node_end()` is
NOT called when an exception occurs — it is only called on the happy path at
the bottom of the function. This means the logger sees `node_start` without a
matching `node_end` for failed nodes.

THE BUG / RISK:
Any logging/metrics system that tracks open node spans (start without end)
will accumulate unmatched starts for every failed node in parallel mode.

EVIDENCE:
```python
logger.node_start(node_type, idx, total_nodes=total_nodes)
# ...
try:
    outputs = await loop.run_in_executor(pool, exec_.execute, inputs)
except Exception as exc:
    logger.node_error(node_type, idx, exc)
    raise   # ← node_end never called

# ...
logger.node_end(...)   # ← only reached on success
```

REPRODUCTION SCENARIO:
Any node failure in parallel mode. `node_start` is logged, `node_error` is
logged, but `node_end` is never logged.

IMPACT:
Unmatched log spans. Metrics dashboards show nodes as "in progress" forever.

FIX DIRECTION:
```python
try:
    ...
except Exception as exc:
    logger.node_error(node_type, idx, exc)
    raise
finally:
    logger.node_end(node_type, idx, time.time() - node_start_time, output_count=0)
```
Or call `node_end` in the `except` block before re-raising.

--------------------------------------------------------------------
FILE:        app/core/executor.py
FUNCTION:    ParallelExecutor._run_node
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Assemble inputs from upstream outputs.

WHAT IT ACTUALLY DOES:
`upstream_outputs = node_outputs[src_id]` is accessed without checking whether
`src_id` is in `node_outputs`. In a correctly constructed wave, all upstream
nodes (prior waves) will have their outputs in `node_outputs`. However, if a
prior-wave node was skipped (e.g., due to a false condition setting
`node_outputs[node_id] = {}`), the key exists but the value is `{}`. If a
prior-wave node was excluded from partial execution and its passthrough was
not populated (a bug in the orchestrator), `node_outputs[src_id]` would raise
`KeyError`.

THE BUG / RISK:
`node_outputs[src_id]` raises `KeyError` if `src_id` is not in `node_outputs`.
The parallel path has no guard for this case, unlike the sequential path which
uses `node_outputs.get(src_id, {})` in some places.

EVIDENCE:
```python
upstream_outputs = node_outputs[src_id]   # KeyError if src_id missing
value = upstream_outputs.get(src_port)
```

REPRODUCTION SCENARIO:
A wave node whose upstream node was excluded from partial execution and whose
passthrough was not populated in `node_outputs`.

IMPACT:
`KeyError` crash in parallel mode for certain partial execution configurations.

FIX DIRECTION:
```python
upstream_outputs = node_outputs.get(src_id, {})
```

--------------------------------------------------------------------
FILE:        app/core/executor.py
FUNCTION:    ParallelExecutor.shutdown
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Shut down the shared thread pool. Call once after all waves complete.

WHAT IT ACTUALLY DOES:
`shutdown()` sets `self._pool = None` after calling `shutdown(wait=True)`.
If `shutdown()` is called concurrently from two threads (unlikely but possible
if the orchestrator is used from multiple threads), there is a TOCTOU race:
both threads check `self._pool is not None`, both call `shutdown()`, and the
second call raises `RuntimeError: cannot schedule new futures after shutdown`.

THE BUG / RISK:
`shutdown()` is not thread-safe. The check-then-act on `self._pool` is not
atomic.

EVIDENCE:
```python
def shutdown(self) -> None:
    if self._pool is not None:       # ← check
        self._pool.shutdown(wait=True)  # ← act (not atomic with check)
        self._pool = None
```

REPRODUCTION SCENARIO:
Two threads both call `par_exec.shutdown()` simultaneously.

IMPACT:
`RuntimeError` on double-shutdown. Low risk given current single-threaded
orchestrator usage.

FIX DIRECTION:
Use a lock or `threading.Lock` around the check-and-act.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | SAFE |
| State Safety | UNSAFE |
| Resource Safety | UNSAFE |
| Test Hostile | NO |
| Top Risk | `ConditionEvaluationError` is silently swallowed in the parallel path (treated as `passes=False`), causing malformed condition expressions to silently route `None` to downstream nodes instead of failing the pipeline — behavior is inconsistent with the sequential path |
