# Functional Review — app/mcp/handlers/run_control.py

**Group:** 11 — MCP
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/mcp/handlers/run_control.py
FUNCTION:    handle_pause_run / handle_resume_run / handle_cancel_run
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Thin delegation to `get_active_run(run_id).pause/resume/cancel()`.
Returns structured error if run is not active.

WHAT IT ACTUALLY DOES:
Calls `run.pause()`, `run.resume()`, or `run.cancel()` with no exception
handling. Looking at `RunManager.pause()`:
```python
def pause(self) -> None:
    self._pause_event.clear()
    self._write_meta_field("status", "paused")
```
`_write_meta_field` does file I/O (reads and writes `meta.json`). If the
filesystem is full, the run directory has been deleted, or there is a
permissions error, `_write_meta_field` raises an `OSError`. This exception
propagates out of `handle_pause_run` uncaught, through `handle_call_tool`'s
generic `except Exception` block in `server.py`, and is returned as a
generic `{"error": True, "error_type": "OSError", "message": "..."}`.

This is technically handled by the server's outer catch, but the handler
itself claims to return only `{"run_id": ..., "status": "paused"}` or
`{"error": True, "error_type": "run_not_active", ...}`. The OSError case
is undocumented and produces an inconsistent error shape.

THE BUG / RISK:
Undocumented exception path: `pause()`, `resume()`, and `cancel()` can
raise `OSError` from `_write_meta_field`. The handlers do not catch this,
so the error bubbles to the server's generic handler with `error_type:
"OSError"` — not a documented MCP error type.

Additionally, `handle_cancel_run` returns `{"status": "cancelled"}` but
`RunManager.cancel()` only sets the cancel event and unblocks the pause
event — it does NOT write `"cancelled"` to `meta.json`. The actual
`mark_cancelled()` call happens in the orchestrator's finally block.
So the response `{"status": "cancelled"}` is misleading: it means "cancel
signal sent", not "run has been cancelled". A caller that polls
`inspect_run` immediately after `cancel_run` may still see `"running"`.

EVIDENCE:
`run_control.py` lines ~47–50:
```python
run.cancel()
return {"run_id": run_id, "status": "cancelled"}
```
`RunManager.cancel()` in `run_journal.py`:
```python
def cancel(self) -> None:
    self._cancel_event.set()
    self._pause_event.set()  # unblock if paused
    # NOTE: does NOT call mark_cancelled() — that happens in orchestrator finally
```

REPRODUCTION SCENARIO:
1. Call `cancel_run` for an active run.
2. Immediately call `inspect_run` with `status_only: true`.
3. Response is `{"status": "running"}` — not `"cancelled"` — because the
   orchestrator hasn't reached its finally block yet.

IMPACT:
Contract mismatch: `cancel_run` response says `"cancelled"` but the run
is still executing. Callers that rely on this status for immediate
decision-making will get wrong data.

FIX DIRECTION:
Change the response to accurately reflect what happened:
```python
run.cancel()
return {"run_id": run_id, "status": "cancel_requested",
        "message": "Cancel signal sent. Run will stop after current node completes."}
```
Similarly for `pause_run`: `"pause_requested"` is more accurate than `"paused"`.
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/handlers/run_control.py
FUNCTION:    handle_pause_run / handle_resume_run / handle_cancel_run
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Handle the case where a run has already completed (group-specific focus area).

WHAT IT ACTUALLY DOES:
`get_active_run(run_id)` returns `None` for both "run never existed" and
"run has already completed and been deregistered". Both cases return the
same error: `{"error_type": "run_not_active", "message": "Run '...' is not active"}`.

This is correct behavior per the MCP error contract. However, the error
message does not distinguish between "run completed" and "run never existed",
which makes it harder for callers to understand why the operation failed.

THE BUG / RISK:
Ambiguous error message: a caller that tries to pause a completed run gets
the same error as one that provides a typo'd run_id. This is a UX issue,
not a correctness bug — the behavior is correct (can't pause a completed run).

EVIDENCE:
`run_control.py` lines ~43–45:
```python
if run is None:
    return {"error": True, "error_type": "run_not_active",
            "message": f"Run '{run_id}' is not active", "run_id": run_id}
```

REPRODUCTION SCENARIO:
Call `pause_run` with a run_id that completed 5 minutes ago. Response is
identical to calling with a completely unknown run_id.

IMPACT:
Caller cannot distinguish "run completed" from "run never existed". Low
impact — both cases mean the operation cannot proceed.

FIX DIRECTION:
Check the run directory to distinguish the two cases:
```python
from app.core.config import runs_dir as _runs_dir
run_dir = _runs_dir() / run_id
if run_dir.exists():
    msg = f"Run '{run_id}' has already completed or is not active in this process."
else:
    msg = f"Run '{run_id}' is not active and no run directory was found."
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/handlers/run_control.py
FUNCTION:    handle_pause_run / handle_resume_run / handle_cancel_run
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate `run_id` before calling `get_active_run`.

WHAT IT ACTUALLY DOES:
Uses `arguments.get("run_id", "")` — defaults to empty string `""` if
`run_id` is absent. `get_active_run("")` returns `None` (no run with
empty string ID), so the handler returns `run_not_active` for an empty
run_id. This is technically correct but the error message
`"Run '' is not active"` is confusing — it should say `"run_id is required"`.

THE BUG / RISK:
Misleading error message when `run_id` is missing from arguments. The
schema marks `run_id` as required, so this should not happen in practice,
but defensive handling would improve debuggability.

EVIDENCE:
Line ~43: `run_id = arguments.get("run_id", "")`

REPRODUCTION SCENARIO:
Call `pause_run` with `{}` (no `run_id`). Response: `{"error_type":
"run_not_active", "message": "Run '' is not active"}`.

IMPACT:
Confusing error message. No functional impact.

FIX DIRECTION:
```python
run_id = arguments.get("run_id", "")
if not run_id:
    return {"error": True, "error_type": "missing_argument",
            "message": "run_id is required"}
```
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `cancel_run` returns `{"status": "cancelled"}` but the run is still executing — the cancel signal has only been sent; `mark_cancelled()` happens asynchronously in the orchestrator's finally block. |
