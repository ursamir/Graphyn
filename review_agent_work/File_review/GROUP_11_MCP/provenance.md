# Functional Review — app/mcp/handlers/provenance.py

**Group:** 11 — MCP
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/mcp/handlers/provenance.py
FUNCTION:    replay_run_handler
CATEGORY:    Silent Failure Risk
SEVERITY:    CRITICAL
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Replay a previous run from its stored graph.json. Returns a new run_id
immediately. Execution proceeds asynchronously.

WHAT IT ACTUALLY DOES:
Submits `_get_backend().execute(graph, run_manager=new_run_manager)` to
`_REPLAY_EXECUTOR` via `_REPLAY_EXECUTOR.submit(...)`. The `Future`
returned by `submit()` is discarded — never stored, never checked for
exceptions.

This is the same critical bug as in `execution.py`: if the background
execution raises an exception (e.g. node failure, OOM, plugin error),
the exception is stored in the discarded `Future` and silently swallowed.
The caller receives `{"run_id": ..., "status": "started"}` and the run
stays in `"running"` status forever if the orchestrator crashes before
calling `mark_failed`.

THE BUG / RISK:
Discarded Future: background execution exceptions are silently swallowed.
Run stays in `"running"` status permanently if the orchestrator crashes
before calling `run_manager.mark_failed()`.

EVIDENCE:
Lines ~130–131:
```python
_REPLAY_EXECUTOR.submit(_get_backend().execute, graph, run_manager=new_run_manager)
return {"run_id": new_run_manager.run_id, "status": "started"}
```
The `Future` from `submit()` is not stored or checked.

REPRODUCTION SCENARIO:
Replay a run whose graph references a node type that has been unregistered
since the original run. `run_pipeline_ir` raises `KeyError` in the planner.
The orchestrator may not catch this before `mark_failed` is called.
`inspect_run` returns `{"status": "running"}` indefinitely.

IMPACT:
Silent wrong result: caller believes replay is in progress when it has
crashed. No way to detect the failure without a timeout.

FIX DIRECTION:
```python
def _on_replay_done(fut, run_manager=new_run_manager):
    exc = fut.exception()
    if exc:
        log.error("Replay execution failed for run %s: %s",
                  run_manager.run_id, exc, exc_info=exc)
        try:
            run_manager.mark_failed(str(exc))
        except Exception:
            pass

future = _REPLAY_EXECUTOR.submit(
    _get_backend().execute, graph, run_manager=new_run_manager
)
future.add_done_callback(_on_replay_done)
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/handlers/provenance.py
FUNCTION:    replay_run_handler
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Load the graph from `workspace/runs/{run_id}/graph.json` and execute it.

WHAT IT ACTUALLY DOES:
Creates `new_run_manager = RunManager()` which immediately creates a new
run directory and writes `meta.json` with `"status": "running"`. If
`_REPLAY_EXECUTOR.submit()` raises (e.g. executor shut down), the
`RunManager` is orphaned with permanent `"running"` status.

Additionally, `replay_run_handler` does NOT call
`new_run_manager.save_graph_ir(...)` before submitting to the executor.
The `graph_hash` is therefore `""` for the entire replay run. This means:
- Provenance records for the replay run have `graph_hash = ""`
- Cache lookups that use `graph_hash` will not match the original run's
  cache entries (different hash)

THE BUG / RISK:
Missing `save_graph_ir` call: the replay run's `graph_hash` is always `""`
because `new_run_manager.save_graph_ir()` is never called. This breaks
provenance tracking and cache reuse for replay runs.

EVIDENCE:
Lines ~120–131: `new_run_manager = RunManager()` is created, then
`_REPLAY_EXECUTOR.submit(...)` is called. There is no
`new_run_manager.save_graph_ir(...)` call between them.

Compare with `execute_pipeline_handler` — it also does not call
`save_graph_ir` directly (the orchestrator does this). So this may be
intentional — the orchestrator calls `save_graph_ir` internally. Need
to verify.

Looking at `run_journal.py`: `save_graph_ir` is called by the orchestrator
via `run_manager.save_graph_ir(dump_ir(graph))`. So the orchestrator
handles this. The `graph_hash` will be set correctly once the orchestrator
runs. This is NOT a bug — it's the same pattern as `execute_pipeline_handler`.

REVISED ASSESSMENT: The `save_graph_ir` concern is not a bug. The
`RunManager` orphan on executor shutdown is the real issue (same as
execution.py).

THE BUG / RISK (revised):
If `_REPLAY_EXECUTOR.submit()` raises, `new_run_manager` is orphaned with
permanent `"running"` status. Low probability but possible during shutdown.

EVIDENCE:
Lines ~128–131: `new_run_manager = RunManager()` created before `submit()`.

REPRODUCTION SCENARIO:
Call `replay_run_handler` during process shutdown when executor is torn down.

IMPACT:
Orphaned run directory with permanent `"running"` status.

FIX DIRECTION:
```python
try:
    future = _REPLAY_EXECUTOR.submit(...)
    future.add_done_callback(_on_replay_done)
except Exception as exc:
    new_run_manager.mark_failed(str(exc))
    return {"error": True, "error_type": "replay_error", "message": str(exc)}
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/handlers/provenance.py
FUNCTION:    get_artifact_lineage_handler
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the full lineage tree for an artifact. Returns the lineage tree
dict or an error dict.

WHAT IT ACTUALLY DOES:
Calls `store.get_lineage(artifact_id)` and returns the result directly.
If `get_lineage` returns `None` (artifact not found in provenance store),
the handler returns `None` — which is then passed to `json.dumps(None)`
in `server.py`, producing the JSON string `"null"`. The caller receives
`"null"` as the tool result, which is not a structured error dict.

THE BUG / RISK:
Silent wrong result: if `ProvenanceStore.get_lineage()` returns `None`
for an unknown artifact_id (rather than raising), the handler returns
`None`, which serialises to `"null"`. The caller cannot distinguish
"lineage is null" from "artifact not found".

EVIDENCE:
Lines ~100–106:
```python
lineage = store.get_lineage(artifact_id)
return lineage  # could be None
```
No check for `lineage is None`.

REPRODUCTION SCENARIO:
Call `get_artifact_lineage` with an artifact_id that has no provenance
record. If `ProvenanceStore.get_lineage()` returns `None`, the response
is `null` (JSON null), not `{"error": True, "error_type": "artifact_not_found", ...}`.

IMPACT:
Caller cannot detect "artifact not found" — receives `null` instead of
a structured error. Silent wrong result.

FIX DIRECTION:
```python
lineage = store.get_lineage(artifact_id)
if lineage is None:
    return {
        "error": True,
        "error_type": "artifact_not_found",
        "message": f"No lineage found for artifact '{artifact_id}'",
    }
return lineage
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/handlers/provenance.py
FUNCTION:    list_artifacts_handler
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
List artifacts with optional filters. Returns `{"artifacts": [...], "count": N}`.

WHAT IT ACTUALLY DOES:
Calls `store.list(run_id=run_id, node_type=node_type, artifact_type=artifact_type)`.
If all three filters are `None` (no arguments provided), this returns ALL
artifacts in the store. With a large artifact store (thousands of records),
this could return a very large response.

THE BUG / RISK:
No pagination or limit: `list_artifacts` with no filters returns all
artifacts. With a large store, this produces a response that may exceed
MCP message size limits or cause memory pressure.

EVIDENCE:
Lines ~82–88: `store.list(run_id=None, node_type=None, artifact_type=None)`
— no limit parameter.

REPRODUCTION SCENARIO:
After 1000 pipeline runs with 10 artifacts each, `list_artifacts` with no
filters returns 10,000 artifact records in a single response.

IMPACT:
Memory pressure; potential MCP message size limit exceeded. Not a
correctness bug — results are always correct.

FIX DIRECTION:
Add a `limit` parameter to the schema and pass it to `store.list()`.
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
| Top Risk | Discarded Future from `_REPLAY_EXECUTOR.submit()` — background replay exceptions are silently swallowed; run stays in "running" status forever if the orchestrator crashes before calling `mark_failed`. |
