# Functional Review — app/api/routers/artifacts.py

**Group:** 10 — API  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/api/routers/artifacts.py
FUNCTION:    replay_artifact / _do_replay (inner)
CATEGORY:    Resource Leak
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Trigger an asynchronous replay of the run that produced artifact_id. Uses a
`ThreadPoolExecutor(max_workers=1)` so "concurrent replay requests queue
silently — only one replay runs at a time."

WHAT IT ACTUALLY DOES:
`_replay_executor` is a module-level `ThreadPoolExecutor(max_workers=1)`.
When a replay is already running and a second request arrives, `executor.submit()`
queues the task internally. The queue is unbounded — there is no limit on how
many replays can be queued. With enough concurrent requests, the executor's
internal queue grows without bound, holding references to `Pipeline` objects,
`RunManager` objects, and `GraphIR` objects in memory.

THE BUG / RISK:
The executor's internal task queue is unbounded. Under load (e.g. a client
retrying replay requests), memory grows without bound. The comment says
"only one replay runs at a time" but does not mention that the queue is
unbounded.

EVIDENCE:
`artifacts.py` line ~30: `_replay_executor = ThreadPoolExecutor(max_workers=1)`
`artifacts.py` line ~120: `_replay_executor.submit(_do_replay)` — no queue size limit.

REPRODUCTION SCENARIO:
Send 1,000 concurrent POST /artifacts/{id}/replay requests. All 1,000 tasks
are queued in the executor. Memory grows proportionally to the number of queued
`Pipeline` + `GraphIR` objects.

IMPACT:
Memory exhaustion under load. Silent — no 429 or 503 returned to the caller.

FIX DIRECTION:
Use a `BoundedSemaphore` or check queue depth before submitting:
```python
from concurrent.futures import Future
_replay_futures: list[Future] = []
# Before submit: prune completed futures and check depth
pending = [f for f in _replay_futures if not f.done()]
if len(pending) >= MAX_QUEUED_REPLAYS:
    raise HTTPException(status_code=429, detail="Too many replay requests queued")
```
Or switch to a `Queue(maxsize=N)` + worker thread pattern.

--------------------------------------------------------------------
FILE:        app/api/routers/artifacts.py
FUNCTION:    replay_artifact / _do_replay (inner)
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Submit replay via Pipeline.run_with_manager() and mark the run failed on
exception.

WHAT IT ACTUALLY DOES:
`_do_replay()` catches `Exception` and calls `new_run_mgr.mark_failed(str(exc))`.
However, there is no call to `deregister_active_run(new_run_id)` in a `finally`
block. If the orchestrator registers the run during execution (via
`register_active_run`), it may or may not deregister it on completion. If it
does not, the run stays in the active registry indefinitely after the replay
completes, causing stale entries (same issue as in pipelines.py run_pipeline_async).

Additionally, if `new_run_mgr.mark_failed()` itself raises (e.g. disk full
when writing the failure status), the exception is silently swallowed by the
executor — `Future.result()` is never called, so the exception is never
surfaced anywhere.

EVIDENCE:
`artifacts.py` lines ~108–115:
```python
def _do_replay():
    try:
        ...
        replay_pipeline.run(run_manager=new_run_mgr)
    except Exception as exc:
        new_run_mgr.mark_failed(str(exc))
```
No `finally` block. No `deregister_active_run`.

REPRODUCTION SCENARIO:
Start a replay. After it completes, `GET /runs/{new_run_id}/status` shows
"completed". `POST /runs/{new_run_id}/cancel` may return 200 on a completed run
(stale registry entry).

IMPACT:
Stale active run entries. Exceptions from `mark_failed()` are silently lost.

FIX DIRECTION:
```python
def _do_replay():
    try:
        replay_pipeline.run(run_manager=new_run_mgr)
    except Exception as exc:
        try:
            new_run_mgr.mark_failed(str(exc))
        except Exception:
            pass
    finally:
        from app.core.run_control import deregister_active_run
        deregister_active_run(new_run_mgr.run_id)
```

--------------------------------------------------------------------
FILE:        app/api/routers/artifacts.py
FUNCTION:    replay_artifact
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Load graph.json for the original run and replay it.

WHAT IT ACTUALLY DOES:
`artifact_record.run_id` is used directly to construct the graph path:
`_runs_dir() / original_run_id / "graph.json"`. There is no validation that
`original_run_id` is a safe path component. If `ArtifactStore` stores a
`run_id` that contains path traversal characters (e.g. `"../../../etc/passwd"`),
the path construction would escape the runs directory.

THE BUG / RISK:
`original_run_id` comes from the artifact store (trusted internal data), but
if the store is ever populated with untrusted data (e.g. via a compromised
artifact import), the path construction is unsafe. The `_run_dir()` helper in
`runs.py` has a path traversal guard, but `replay_artifact` does NOT use
`_run_dir()` — it constructs the path directly.

EVIDENCE:
`artifacts.py` lines ~96–99:
```python
graph_path = _runs_dir() / original_run_id / "graph.json"
if not graph_path.exists():
    raise HTTPException(...)
```
No path traversal check on `original_run_id`.

REPRODUCTION SCENARIO:
If an artifact record has `run_id = "../../../etc/passwd"`, then
`graph_path = runs_dir / "../../../etc/passwd" / "graph.json"` — path traversal.

IMPACT:
Path traversal if artifact store data is ever untrusted. Low probability in
normal operation but a latent security risk.

FIX DIRECTION:
```python
graph_path = (_runs_dir() / original_run_id / "graph.json").resolve()
if not graph_path.is_relative_to(_runs_dir().resolve()):
    raise HTTPException(status_code=422, detail="Invalid run_id in artifact record")
```

--------------------------------------------------------------------
FILE:        app/api/routers/artifacts.py
FUNCTION:    list_artifacts
CATEGORY:    Performance
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return all artifacts matching the provided filters, sorted by created_at descending.

WHAT IT ACTUALLY DOES:
Delegates entirely to `ArtifactStore().list(...)`. The sorting claim ("sorted
by created_at descending") is in the docstring but the actual sort order
depends entirely on `ArtifactStore.list()` — this router does not sort the
results itself. If `ArtifactStore.list()` returns unsorted results, the
docstring is wrong.

EVIDENCE:
`artifacts.py` lines ~50–54: `records = store.list(...); return [r.model_dump(...) for r in records]`
No sort applied in this function.

REPRODUCTION SCENARIO:
If `ArtifactStore.list()` returns results in insertion order, the response is
not sorted by `created_at`. The docstring contract is violated silently.

IMPACT:
Silent contract mismatch. Clients expecting sorted results get unsorted results.

FIX DIRECTION:
Either sort explicitly here or remove the "sorted by created_at descending"
claim from the docstring and rely on ArtifactStore's documented sort order.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | UNSAFE |
| State Safety | SAFE |
| Resource Safety | UNSAFE |
| Test Hostile | PARTIAL |
| Top Risk | Unbounded executor task queue allows memory exhaustion under concurrent replay requests, with no backpressure or 429 response to callers. |
