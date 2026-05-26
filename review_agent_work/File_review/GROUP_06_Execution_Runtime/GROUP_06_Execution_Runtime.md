# Group Review Index — Group 6: Execution Runtime

**Files reviewed:** 6  
**Total findings:** 26 (CRITICAL: 2 | HIGH: 12 | MEDIUM: 10 | LOW: 4)  
**Date:** 2026-05-26

---

## File Summaries

| File | Overall Risk | Silent Failures | Top Risk |
|---|---|---|---|
| `orchestrator.md` | CRITICAL | 2 | Sequential and parallel paths do not teardown executors or shut down the thread pool on failure — resource leak accumulates across runs |
| `executor.md` | HIGH | 1 | `ConditionEvaluationError` silently swallowed in parallel path — malformed conditions route `None` to downstream nodes instead of failing the pipeline |
| `node_executor.md` | HIGH | 2 | `process()` returning `None` bypasses `on_error()`, skips retry, and raises a misleading `AttributeError` with no observer notification |
| `events.md` | HIGH | 2 | `FileWatcherSource` silently stops yielding events when the watched directory becomes inaccessible — pipeline continues running without processing events |
| `conditions.md` | MEDIUM | 0 | Python 3.8 incompatibility — `ast.Index` not in whitelist causes all subscript condition expressions to be rejected |
| `runtime_backend.md` | MEDIUM | 0 | `LocalPythonBackend.execute()` raises `RuntimeError` from async contexts — backend abstraction is bypassed by all async callers |

---

## Priority Findings (CRITICAL and HIGH only)

**[CRITICAL] orchestrator.md — `run_pipeline_ir_async` (sequential path) — Node executors are never torn down on sequential execution failure; GPU memory, file handles, and model weights leak for every failed run**

**[CRITICAL] orchestrator.md — `run_pipeline_ir_async` (parallel path) — `ThreadPoolExecutor` and all node executors are never shut down or torn down on wave failure; threads accumulate indefinitely in a long-running service**

**[HIGH] orchestrator.md — `run_pipeline_ir_async` (setup loop) — If any `NodeExecutor.setup()` raises, all previously set-up executors leak and the run is never deregistered from the active run registry**

**[HIGH] orchestrator.md — `run_pipeline_ir_async` (return value) — Last node skipped due to partial execution or false condition silently returns `{}` with no warning — caller cannot distinguish success from skip**

**[HIGH] orchestrator.md — `run_pipeline_ir_async` (event-driven path) — Node failure inside `_handle_source` does not mark the run as failed, does not deregister the run, and does not teardown executors**

**[HIGH] orchestrator.md — `run_pipeline_ir_async` (event-driven path) — `EventSource.close()` called twice on every source in the cancellation path — double-close latent bug for non-idempotent sources**

**[HIGH] executor.md — `ParallelExecutor._run_node` — `ConditionEvaluationError` silently treated as `passes=False` in parallel path; sequential path correctly re-raises — inconsistent behavior for malformed conditions**

**[HIGH] executor.md — `ParallelExecutor.run_wave` — All wave nodes continue running after first failure (no cancellation); slow nodes add full execution time to failure latency**

**[HIGH] executor.md — `ParallelExecutor._run_node` — `logger.node_end()` never called for failed nodes — unmatched `node_start` events accumulate in metrics/tracing systems**

**[HIGH] executor.md — `ParallelExecutor._run_node` — `node_outputs[src_id]` accessed without `.get()` guard — `KeyError` crash for certain partial execution configurations in parallel mode**

**[HIGH] node_executor.md — `NodeExecutor.execute` — `process()` returning `None` raises `AttributeError` outside the `try/except`, bypassing `on_error()` and retry — observer never notified**

**[HIGH] node_executor.md — `NodeExecutor.execute` — Post-process bookkeeping (`_last_output_counts` assignment) is outside the `try/except` wrapping `process()` — any exception there bypasses `on_error()` and retry**

**[HIGH] events.md — `FileWatcherSource.watch` — Non-`ImportError` exceptions from `watchfiles` backend (directory deleted, permission denied) propagate uncaught and are silently discarded by `asyncio.gather`**

**[HIGH] events.md — `FileWatcherSource.watch` — Non-existent path causes silent infinite loop in polling mode (`OSError` swallowed) or uncaught exception in `watchfiles` mode**

---

## Most Dangerous File

`orchestrator.md` — The orchestrator's sequential and parallel execution paths both fail to teardown node executors and (in parallel mode) the thread pool when an exception occurs, causing resource leaks (GPU memory, file handles, model weights, OS threads) that accumulate across every failed pipeline run in a long-running service. Combined with the setup-loop leak and the event-driven run-registry leak, the orchestrator has three independent resource leak paths that will degrade a production service over time.
