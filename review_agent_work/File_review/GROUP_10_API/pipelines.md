# Functional Review — app/api/routers/pipelines.py

**Group:** 10 — API  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/api/routers/pipelines.py
FUNCTION:    run_pipeline_stream
CATEGORY:    Async Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Execute a pipeline and stream NDJSON log events as they occur. The queue is
bounded (maxsize=512) to "prevent memory leak on slow clients".

WHAT IT ACTUALLY DOES:
`queue.put(entry)` inside `PipelineLogger._emit` / `_emit_structured` is a
**blocking** call. When the queue is full (512 items) and the HTTP client is
reading slowly (or has disconnected), the pipeline thread blocks indefinitely
on `queue.put()`. The pipeline execution hangs — it cannot complete, cannot
time out, and the daemon thread is stuck.

THE BUG / RISK:
A slow or disconnected client causes the pipeline execution thread to block
forever on `queue.put()`. Because the thread is a daemon thread it will be
reaped when the process exits, but during the process lifetime it holds all
pipeline resources (GPU memory, file handles, etc.) and the run never
completes or fails cleanly. With enough concurrent slow clients, all pipeline
threads can be blocked simultaneously, starving the thread pool.

EVIDENCE:
`logger.py` line ~55: `self.queue.put(entry)` — no timeout, no `put_nowait`.
`pipelines.py` line ~107: `queue: Queue = Queue(maxsize=512)`.
`pipelines.py` line ~110: `pipeline.run(logger=logger)` — runs in the thread.

REPRODUCTION SCENARIO:
1. POST /pipelines/run with a multi-node pipeline.
2. Open the SSE stream but stop reading after the first few bytes.
3. The queue fills to 512; the pipeline thread blocks on `queue.put()`.
4. The run never emits "done" or "error"; the run_id is never marked complete.

IMPACT:
Resource leak (thread + pipeline resources held indefinitely). Silent hang —
no error is surfaced to the caller or the run journal.

FIX DIRECTION:
Use `queue.put(entry, timeout=5.0)` in `PipelineLogger._emit` / `_emit_structured`
and catch `queue.Full` to drop the event (with a warning) rather than blocking:
```python
try:
    self.queue.put(entry, timeout=5.0)
except queue.Full:
    _log.warning("Stream queue full — dropping event %s", entry.get("type"))
```

--------------------------------------------------------------------
FILE:        app/api/routers/pipelines.py
FUNCTION:    run_pipeline_stream
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Stream NDJSON log events and close the stream cleanly on completion or error.

WHAT IT ACTUALLY DOES:
The `stream()` generator yields items from the queue until it receives the
`None` sentinel. However, if the `_run()` thread raises an exception that is
NOT caught by the inner `except Exception` block (e.g. `BaseException`,
`KeyboardInterrupt`, `SystemExit`), the sentinel `queue.put(None)` in the
`finally` block is still executed — that part is safe. But if the generator
itself raises (e.g. a serialization error in `json.dumps(item)`), the
`StreamingResponse` will close the connection mid-stream with no error event
sent to the client. The client receives a truncated NDJSON stream with no
`{"type": "error"}` line.

THE BUG / RISK:
`json.dumps(item)` can raise `TypeError` if any value in the log entry is not
JSON-serializable (e.g. a numpy array, a custom object). This silently
truncates the stream — the client sees an incomplete response with no error
indication.

EVIDENCE:
`pipelines.py` line ~122: `yield json.dumps(item) + "\n"` — no try/except.

REPRODUCTION SCENARIO:
A node logs an entry containing a non-serializable value (e.g. a numpy int64).
`json.dumps` raises `TypeError`. The generator exits without yielding an error
event. The client's NDJSON parser sees a truncated stream.

IMPACT:
Silent truncation of the event stream. Client cannot distinguish "pipeline
completed" from "stream crashed mid-way".

FIX DIRECTION:
```python
def stream():
    while True:
        item = queue.get()
        if item is None:
            break
        try:
            yield json.dumps(item) + "\n"
        except (TypeError, ValueError) as exc:
            yield json.dumps({"type": "error", "message": f"Serialization error: {exc}"}) + "\n"
            break
```

--------------------------------------------------------------------
FILE:        app/api/routers/pipelines.py
FUNCTION:    run_pipeline_async
CATEGORY:    Silent Failure Risk
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Start a pipeline run in a background thread and return the run_id immediately.
The docstring says it "delegates to Pipeline.run_with_manager()".

WHAT IT ACTUALLY DOES:
The `_run()` thread calls `pipeline.run(run_manager=run_mgr)`. If the run
succeeds, `run_mgr` is updated internally by the execution layer. If it fails,
`run_mgr.mark_failed(str(exc))` is called. However, there is no call to
`register_active_run(run_mgr)` before the thread starts. This means:
1. The run is not registered in `run_control`, so `POST /runs/{run_id}/pause`,
   `/resume`, and `/cancel` will all return 404 immediately.
2. The run IS created in the run journal (RunManager constructor does this),
   so `GET /runs/{run_id}` will work — but control endpoints won't.

THE BUG / RISK:
Async runs started via `/run-async` cannot be paused, resumed, or cancelled
via the run-control API because the RunManager is never registered with
`register_active_run()`. The run-control endpoints return 404 for all valid
async run IDs.

EVIDENCE:
`pipelines.py` lines ~148–165: `run_mgr = RunManager(); run_id = run_mgr.run_id`
then `threading.Thread(target=_run, daemon=True).start()`.
No call to `register_active_run(run_mgr)`.
Compare with `app/core/sdk.py` `_execute()` which also does not call
`register_active_run` — that registration happens inside the orchestrator.
The question is whether the orchestrator registers it when called via
`pipeline.run(run_manager=run_mgr)`. If it does, this is not a bug; if it
doesn't, the run is uncontrollable.

REPRODUCTION SCENARIO:
1. POST /pipelines/run-async → get run_id.
2. POST /runs/{run_id}/pause → 404 "run_not_active".

IMPACT:
Run control (pause/resume/cancel) silently does nothing for async runs started
via this endpoint. Users believe they can control the run but cannot.

FIX DIRECTION:
Verify that the orchestrator calls `register_active_run` during execution. If
not, add it explicitly before starting the thread:
```python
from app.core.run_control import register_active_run
register_active_run(run_mgr)
threading.Thread(target=_run, daemon=True).start()
```

--------------------------------------------------------------------
FILE:        app/api/routers/pipelines.py
FUNCTION:    run_pipeline_async / _run (inner)
CATEGORY:    Resource Leak
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Run the pipeline in a background thread; mark it failed on exception.

WHAT IT ACTUALLY DOES:
The `_run()` function catches `Exception` and calls `run_mgr.mark_failed()`.
However, there is no `finally` block to call `deregister_active_run(run_id)`.
If the orchestrator registers the run (see finding above), it may or may not
deregister it on completion. If it does not, the run stays in the active
registry indefinitely after completion, causing `get_active_run()` to return
a stale RunManager for a completed run.

EVIDENCE:
`pipelines.py` lines ~158–163:
```python
def _run():
    try:
        pipeline.run(run_manager=run_mgr)
    except Exception as exc:
        run_mgr.mark_failed(str(exc))
```
No `finally: deregister_active_run(run_id)`.

REPRODUCTION SCENARIO:
Start an async run. After it completes, call `GET /runs/{run_id}/status` →
shows "completed". Call `POST /runs/{run_id}/cancel` → may return 200 "cancelled"
on a run that has already finished (stale registry entry).

IMPACT:
Stale run entries in the active registry. Control signals sent to completed
runs. Memory leak proportional to number of completed async runs.

FIX DIRECTION:
```python
def _run():
    try:
        pipeline.run(run_manager=run_mgr)
    except Exception as exc:
        run_mgr.mark_failed(str(exc))
    finally:
        from app.core.run_control import deregister_active_run
        deregister_active_run(run_mgr.run_id)
```

--------------------------------------------------------------------
FILE:        app/api/routers/pipelines.py
FUNCTION:    _build_pipeline_from_payload
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Build a Pipeline from either IR JSON or YAML payload.

WHAT IT ACTUALLY DOES:
For the YAML path, `payload.get("yaml", "")` returns `""` if the key is
missing. `yaml.safe_load("")` returns `None`. Then `yaml_config_to_ir(None)`
is called. Whether `yaml_config_to_ir` handles `None` gracefully depends on
its implementation. If it raises `AttributeError` or `TypeError` (e.g.
`None.get("pipeline")`), the exception propagates as a generic 422 with a
confusing message.

EVIDENCE:
`pipelines.py` line ~72: `yaml_str = payload.get("yaml", "")`
`pipelines.py` line ~74: `raw = yaml.safe_load(yaml_str)` → `None` for empty string
`pipelines.py` line ~75: `graph = yaml_config_to_ir(raw)` — `raw` may be `None`

REPRODUCTION SCENARIO:
`POST /pipelines/run` with body `{}` (no `schema_version`, no `yaml` key).
→ `yaml_str = ""`, `raw = None`, `yaml_config_to_ir(None)` raises with a
confusing traceback.

IMPACT:
Confusing 422 error message for a common mistake (empty body or missing yaml key).

FIX DIRECTION:
```python
if not raw:
    raise HTTPException(status_code=422, detail="Empty or missing YAML content")
```

--------------------------------------------------------------------
FILE:        app/api/routers/pipelines.py
FUNCTION:    validate_pipeline_config
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate a pipeline config without executing it. Returns `{"valid": True, "node_count": N}`
on success.

WHAT IT ACTUALLY DOES:
For the YAML path, on success it returns `JSONResponse(content={"valid": True})`
— without `node_count`. For the IR JSON path, it returns `{"valid": True, "node_count": len(graph.nodes)}`.
The response schema is inconsistent between the two paths.

EVIDENCE:
`pipelines.py` line ~93: IR path returns `{"valid": True, "node_count": len(graph.nodes)}`
`pipelines.py` line ~107: YAML path returns `JSONResponse(content={"valid": True})`

REPRODUCTION SCENARIO:
POST /pipelines/validate with `{"yaml": "pipeline:\n  nodes: []"}` → `{"valid": true}` (no node_count).
POST /pipelines/validate with `{"schema_version": "1.0", ...}` → `{"valid": true, "node_count": 0}`.

IMPACT:
API clients that always expect `node_count` in the response will fail on YAML
validation responses. Inconsistent contract.

FIX DIRECTION:
Add `node_count` to the YAML success response:
```python
return JSONResponse(
    content={"valid": True, "node_count": len(config.get("pipeline", {}).get("nodes", []))},
    headers=headers,
)
```

--------------------------------------------------------------------
FILE:        app/api/routers/pipelines.py
FUNCTION:    get_template
CATEGORY:    Error Handling
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the IR JSON content of a named template.

WHAT IT ACTUALLY DOES:
`path.read_text(encoding="utf-8")` followed by `_json.loads(...)` — if the
template file contains invalid JSON (e.g. was written with a partial write or
corrupted), `json.JSONDecodeError` propagates as an unhandled 500 with a
FastAPI default error body.

EVIDENCE:
`pipelines.py` line ~183: `return {"name": name, "graph": _json.loads(path.read_text(...))}`
No try/except around the JSON parse.

REPRODUCTION SCENARIO:
Write a template file with truncated JSON. GET /pipelines/templates/{name} →
500 Internal Server Error with a raw Python traceback in the response.

IMPACT:
Unhandled 500 instead of a clean 422/500 with a meaningful message.

FIX DIRECTION:
```python
try:
    return {"name": name, "graph": _json.loads(path.read_text(encoding="utf-8"))}
except json.JSONDecodeError as exc:
    raise HTTPException(status_code=500, detail=f"Template file is corrupted: {exc}")
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | UNSAFE |
| State Safety | SAFE |
| Resource Safety | UNSAFE |
| Test Hostile | PARTIAL |
| Top Risk | Bounded queue with blocking put() causes pipeline execution thread to hang indefinitely when the HTTP client is slow or disconnected. |
