# Functional Review — app/mcp/handlers/execution.py

**Group:** 11 — MCP
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/mcp/handlers/execution.py
FUNCTION:    execute_pipeline_handler
CATEGORY:    Silent Failure Risk
SEVERITY:    CRITICAL
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Execute a pipeline asynchronously; return run_id within 500ms. Execution
proceeds in a background thread. Use inspect_run to retrieve results.

WHAT IT ACTUALLY DOES:
Submits `_get_backend().execute(graph, ...)` to `_PIPELINE_EXECUTOR` via
`_PIPELINE_EXECUTOR.submit(...)`. The `Future` returned by `submit()` is
discarded — it is never stored, never awaited, and never checked for
exceptions.

THE BUG / RISK:
If the background execution raises an exception (e.g. node failure,
OOM, import error in a plugin), the exception is stored in the discarded
`Future` and silently swallowed. The caller receives `{"run_id": ...,
"status": "started"}` and then polls `inspect_run` — but if the
`RunManager` was not passed to `run_pipeline_ir` correctly, or if
`run_pipeline_ir` raises before writing `meta.json`, the run directory
may never be updated to `"failed"` status. The caller sees `"running"`
forever.

More critically: `_get_backend().execute(...)` is called with
`run_manager=run_manager`, but `run_manager` is created in the handler
thread and passed to the background thread. If `run_pipeline_ir` raises
an unhandled exception before calling `run_manager.mark_failed()`, the
run stays in `"running"` status permanently.

EVIDENCE:
Lines ~72–78:
```python
_PIPELINE_EXECUTOR.submit(
    _get_backend().execute,
    graph,
    use_cache=use_cache,
    streaming=streaming,
    run_manager=run_manager,
)
# Future is discarded — no .add_done_callback(), no result check
```

REPRODUCTION SCENARIO:
1. Submit a graph with a node that raises `RuntimeError` in `process()`.
2. `run_pipeline_ir` calls `run_manager.mark_failed(str(exc))` — this
   works IF the orchestrator catches the exception. But if the orchestrator
   itself raises (e.g. a bug in wave building), `mark_failed` is never
   called.
3. `inspect_run` returns `{"status": "running"}` indefinitely.

IMPACT:
Silent wrong result: caller believes run is in progress when it has
actually crashed. No way to detect the failure without a timeout.
Data loss: run artifacts are never written.

FIX DIRECTION:
Add a done callback to log unhandled executor exceptions:
```python
def _on_done(fut):
    exc = fut.exception()
    if exc:
        log.error("Background pipeline execution failed for run %s: %s",
                  run_manager.run_id, exc, exc_info=exc)
        try:
            run_manager.mark_failed(str(exc))
        except Exception:
            pass

future = _PIPELINE_EXECUTOR.submit(
    _get_backend().execute, graph,
    use_cache=use_cache, streaming=streaming, run_manager=run_manager,
)
future.add_done_callback(_on_done)
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/handlers/execution.py
FUNCTION:    execute_pipeline_handler
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate the graph (Step 1) and return `{"valid": False, "errors": [...]}` on
validation failure.

WHAT IT ACTUALLY DOES:
Returns `{"valid": False, "errors": [str(exc)]}` when `load_ir` raises.
This is inconsistent with the error contract defined in `mcp-server.md`,
which specifies `{"error": True, "error_type": "ir_validation_error", ...}`.
All other handlers that call `load_ir` return the standard error envelope.
`execute_pipeline_handler` returns a different shape: `{"valid": False, ...}`
instead of `{"error": True, "error_type": "ir_validation_error", ...}`.

THE BUG / RISK:
Contract mismatch: callers that check `result.get("error")` to detect
failures will not detect this error. Callers that check `result.get("valid")`
will detect it, but this is inconsistent with every other handler in the
MCP layer.

EVIDENCE:
Lines ~63–65:
```python
except Exception as exc:
    return {"valid": False, "errors": [str(exc)]}
```
Compare with `validate_graph_handler` which also returns `{"valid": False, ...}` —
but `execute_pipeline_handler` is an execution tool, not a validation tool.
The error shape should match the MCP error contract.

REPRODUCTION SCENARIO:
Send `execute_pipeline` with a malformed graph. Response is
`{"valid": False, "errors": [...]}`. A client checking `response.get("error")`
gets `None` (falsy) and incorrectly treats this as a success.

IMPACT:
Client-side silent failure: error detection logic that checks `"error"` key
misses this failure mode.

FIX DIRECTION:
```python
except Exception as exc:
    return {
        "error": True,
        "error_type": "ir_validation_error",
        "message": str(exc),
    }
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/handlers/execution.py
FUNCTION:    execute_pipeline_handler
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Allocate a RunManager to get run_id immediately, then submit execution.

WHAT IT ACTUALLY DOES:
Creates `RunManager()` which immediately creates the run directory and
writes an initial `meta.json` with `"status": "running"`. If `load_ir`
fails (Step 1), the function returns early with a validation error — but
the `RunManager` has already been constructed and the run directory already
exists on disk with `"status": "running"`.

Wait — actually looking at the code order: Step 1 (load_ir) happens BEFORE
Step 2 (RunManager construction). So if `load_ir` fails, `RunManager` is
never created. This is correct.

However, if `_PIPELINE_EXECUTOR.submit(...)` raises (e.g. the executor has
been shut down), `RunManager` has already been created and the run directory
exists with `"status": "running"`, but no background task was submitted.
The run will stay in `"running"` status forever.

THE BUG / RISK:
If `_PIPELINE_EXECUTOR` is shut down (e.g. during process shutdown) and
`submit()` raises `RuntimeError: cannot schedule new futures after shutdown`,
the `RunManager` is created but no execution is submitted. The run directory
exists with `"status": "running"` permanently.

EVIDENCE:
Lines ~67–78: `RunManager()` is created at line ~67, then `submit()` at
line ~72. If `submit()` raises, `RunManager` is orphaned.

REPRODUCTION SCENARIO:
Call `execute_pipeline_handler` during process shutdown when the executor
is being torn down.

IMPACT:
Orphaned run directory with permanent `"running"` status. Low probability
in production but possible during graceful shutdown.

FIX DIRECTION:
Wrap the submit in try/except and call `run_manager.mark_failed()` on error:
```python
try:
    future = _PIPELINE_EXECUTOR.submit(...)
    future.add_done_callback(_on_done)
except Exception as exc:
    run_manager.mark_failed(str(exc))
    return {"error": True, "error_type": "execution_error", "message": str(exc)}
```
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | CRITICAL |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | UNSAFE |
| State Safety | UNSAFE |
| Resource Safety | SAFE |
| Test Hostile | PARTIAL |
| Top Risk | Discarded Future from `_PIPELINE_EXECUTOR.submit()` — background execution exceptions are silently swallowed; run stays in "running" status forever if the orchestrator crashes before calling `mark_failed`. |
