# Functional Review — app/api/routers/run_control.py

**Group:** 10 — API  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/api/routers/run_control.py
FUNCTION:    pause_run / resume_run / cancel_run
CATEGORY:    Async Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Pause, resume, or cancel an active pipeline run. The handlers are declared
`async def`.

WHAT IT ACTUALLY DOES:
`get_active_run(run_id)` acquires `_ACTIVE_RUNS_LOCK` (a `threading.Lock`)
inside an `async def` handler. `threading.Lock.acquire()` is a blocking call.
When the lock is contended (e.g. another thread is registering or deregistering
a run), the async handler blocks the event loop thread until the lock is
released.

THE BUG / RISK:
Blocking a `threading.Lock` inside an `async def` function blocks the entire
uvicorn event loop for the duration of the lock hold. Under concurrent
pause/resume/cancel requests, this can cause all async handlers to stall.
The lock hold time is very short (dict lookup), so the practical impact is
low — but it is technically an async correctness violation.

EVIDENCE:
`run_control.py` lines ~35–44: `async def pause_run` calls `get_active_run(run_id)`.
`app/core/run_control.py` line ~90: `with _ACTIVE_RUNS_LOCK: run = _ACTIVE_RUNS.get(run_id)`.

REPRODUCTION SCENARIO:
Under high concurrency (many simultaneous pause/resume/cancel requests), the
event loop stalls briefly on each lock acquisition. Not observable in normal
use but violates async correctness.

IMPACT:
Event loop stall under high concurrency. Low practical impact given the short
lock hold time, but a correctness violation.

FIX DIRECTION:
Either convert the handlers to `def` (sync, FastAPI runs them in a thread pool
automatically) or use `asyncio.Lock` in `run_control.py` and `await` it.
Simplest fix: change `async def` to `def` for these three handlers since they
do no async I/O:
```python
def pause_run(run_id: str):
    ...
```

--------------------------------------------------------------------
FILE:        app/api/routers/run_control.py
FUNCTION:    pause_run / resume_run / cancel_run
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Pause/resume/cancel an active run. Returns `{"run_id": ..., "status": "paused/running/cancelled"}`.

WHAT IT ACTUALLY DOES:
`run.pause()`, `run.resume()`, and `run.cancel()` are called without any
exception handling. If these methods raise (e.g. the RunManager's internal
state is inconsistent, or a Redis publish fails in the Redis backend), the
exception propagates as an unhandled 500 with a raw Python traceback.

THE BUG / RISK:
No try/except around `run.pause()` / `run.resume()` / `run.cancel()`. Any
exception from these methods returns a raw 500 instead of a structured error
response.

EVIDENCE:
`run_control.py` lines ~40–43:
```python
run = get_active_run(run_id)
if run is None: raise HTTPException(...)
run.pause()
return {"run_id": run_id, "status": "paused"}
```
No exception handling around `run.pause()`.

REPRODUCTION SCENARIO:
If `run.pause()` raises `RuntimeError` (e.g. run is in an invalid state),
the client receives a 500 with a Python traceback instead of a structured
error response.

IMPACT:
Unhandled 500 with raw traceback exposed to API clients. Potential information
disclosure.

FIX DIRECTION:
```python
try:
    run.pause()
except Exception as exc:
    raise HTTPException(status_code=500, detail=f"Failed to pause run: {exc}")
return {"run_id": run_id, "status": "paused"}
```

--------------------------------------------------------------------
FILE:        app/api/routers/run_control.py
FUNCTION:    resume_run
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Resume a paused pipeline run. Returns `{"run_id": ..., "status": "running"}`.

WHAT IT ACTUALLY DOES:
`get_active_run(run_id)` returns `None` if the run is not in the active
registry. This covers three cases: (a) run never existed, (b) run completed,
(c) run is active on another worker. All three return 404 "run_not_active".

For case (b) — a completed run — the 404 is correct. But for case (a) — a
run_id that never existed — the error detail says "run_not_active" rather than
"run_not_found". The caller cannot distinguish "this run completed" from "this
run never existed".

EVIDENCE:
`run_control.py` lines ~47–51:
```python
run = get_active_run(run_id)
if run is None:
    raise HTTPException(status_code=404, detail={"error": "run_not_active", "run_id": run_id})
```
Same response for all three cases.

REPRODUCTION SCENARIO:
`POST /runs/nonexistent-id/resume` → 404 `{"error": "run_not_active"}`.
`POST /runs/completed-run-id/resume` → 404 `{"error": "run_not_active"}`.
Caller cannot distinguish the two cases.

IMPACT:
Minor UX issue. Clients cannot distinguish "run completed" from "run never
existed". No functional bug.

FIX DIRECTION:
Cross-check with the run journal to distinguish the cases:
```python
if run is None:
    # Check if run ever existed
    from app.core.run_journal import RunManager
    # If run_id exists in journal but not active → "run_not_active"
    # If run_id not in journal → 404 "run_not_found"
    raise HTTPException(status_code=404, detail={"error": "run_not_active", "run_id": run_id})
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 0 |
| Error Handling | PARTIAL |
| Async Safety | UNSAFE |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | Blocking threading.Lock acquisition inside async def handlers stalls the event loop under concurrent control requests. |
