# Functional Review — app/core/run_journal.py

**Group:** 7 — Observability & Storage  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/run_journal.py
FUNCTION:    RunManager.__init__
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Creates the run directory on construction and writes an initial meta.json.

WHAT IT ACTUALLY DOES:
Truncates `run_id` to 16 hex characters:
```python
self.run_id = str(uuid.uuid4()).replace("-", "")[:16]
```
A UUID4 hex string is 32 characters (128 bits). Truncating to 16 characters
gives 64 bits of entropy. With the birthday paradox, a collision is expected
after approximately 2^32 ≈ 4 billion runs. In a high-throughput system
generating thousands of runs per day, this is reachable in ~11,000 years —
but in a system generating millions of runs per day (e.g. automated testing),
a collision is expected after ~4 million runs.

THE BUG / RISK:
Two concurrent runs with the same `run_id` will attempt to create the same
directory. `os.makedirs(self.base_path, exist_ok=True)` will succeed for
both. Both will write to the same `meta.json`, `resume_state.json`, etc.
The second write will overwrite the first. Run data is silently corrupted.

EVIDENCE:
```python
self.run_id = str(uuid.uuid4()).replace("-", "")[:16]
self.base_path = os.path.join(base_dir, self.run_id)
...
os.makedirs(self.base_path, exist_ok=True)
self._write_meta({...})
```

REPRODUCTION SCENARIO:
Generate 2^32 runs. With high probability, two runs share the same 16-char
prefix. Both write to the same directory. The second run's `meta.json`
overwrites the first's.

IMPACT:
Silent data corruption — run metadata, logs, and artifacts from one run
overwrite another. In practice, very low probability but non-zero.

FIX DIRECTION:
Use the full 32-character UUID4 hex string:
```python
self.run_id = str(uuid.uuid4()).replace("-", "")
```

--------------------------------------------------------------------
FILE:        app/core/run_journal.py
FUNCTION:    RunManager.update_resume_state
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Update `resume_state.json` by appending `node_id` to `completed_nodes`.
Thread-safe via `_meta_lock`.

WHAT IT ACTUALLY DOES:
Reads `resume_state.json`, appends `node_id`, then writes back with a plain
`open()` + `json.dump()` (no atomic rename). If the process is killed between
the `open()` and the `json.dump()` completing, `resume_state.json` is left
truncated or empty.

THE BUG / RISK:
A truncated `resume_state.json` causes `load_resume_state()` to raise
`ResumeError` on the next resume attempt. The run cannot be resumed.

EVIDENCE:
```python
with open(path, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2)
```
No atomic rename. Compare with `_write_meta_unlocked` which uses `os.replace`.

REPRODUCTION SCENARIO:
SIGKILL during `json.dump()` for a large `completed_nodes` list.
`resume_state.json` is truncated. Next resume attempt raises `ResumeError`.

IMPACT:
Resume capability lost for the affected run. No other data corruption.

FIX DIRECTION:
Use atomic rename, consistent with `_write_meta_unlocked`:
```python
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2)
os.replace(tmp, path)
```

--------------------------------------------------------------------
FILE:        app/core/run_journal.py
FUNCTION:    RunManager.save_logs
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Write logs to `logs.json`.

WHAT IT ACTUALLY DOES:
Calls `json.dump(list(logs), ...)`. If `logs` is a `deque` of structured
event dicts (as produced by `PipelineLogger`), and any event dict contains
a non-JSON-serializable value (e.g. a numpy array in a `metadata` field),
`json.dump` raises `TypeError`. The exception propagates uncaught to the
caller.

THE BUG / RISK:
`save_logs` is called from the orchestrator's finally block. An uncaught
`TypeError` here would mask the original pipeline exception and replace it
with a confusing serialization error.

EVIDENCE:
```python
def save_logs(self, logs) -> None:
    path = os.path.join(self.base_path, "logs.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(logs), f, indent=2)
```
No `default=str` fallback, no try/except.

REPRODUCTION SCENARIO:
A node emits a structured log event with a numpy array in the payload.
`save_logs` raises `TypeError: Object of type ndarray is not JSON serializable`.
The orchestrator's finally block propagates this instead of the original
pipeline error.

IMPACT:
Misleading error message — the user sees a JSON serialization error instead
of the actual pipeline failure. Logs are not saved.

FIX DIRECTION:
```python
json.dump(list(logs), f, indent=2, default=str)
```

--------------------------------------------------------------------
FILE:        app/core/run_journal.py
FUNCTION:    RunManager.init_resume_state
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Write `resume_state.json` with initial state.

WHAT IT ACTUALLY DOES:
Writes `resume_state.json` with a plain `open()` + `json.dump()` (no atomic
rename, no lock). This is inconsistent with `_write_meta_unlocked` which uses
`os.replace`. If the process is killed during the write, `resume_state.json`
is left truncated.

THE BUG / RISK:
A truncated `resume_state.json` from `init_resume_state` causes
`load_resume_state` to raise `ResumeError`. The run cannot be resumed even
though no nodes have completed yet.

EVIDENCE:
```python
def init_resume_state(self, graph_hash: str) -> None:
    ...
    path = os.path.join(self.base_path, "resume_state.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
```
No atomic rename, no lock.

REPRODUCTION SCENARIO:
SIGKILL during `init_resume_state`. `resume_state.json` is truncated.
Resume attempt raises `ResumeError`.

IMPACT:
Resume capability lost for the affected run if killed during initialization.

FIX DIRECTION:
Use atomic rename and acquire `_meta_lock`:
```python
with self._meta_lock:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)
```

--------------------------------------------------------------------
FILE:        app/core/run_journal.py
FUNCTION:    RunManager.register_artifact
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Register a node output as an artifact and record its provenance.

WHAT IT ACTUALLY DOES:
Calls `self._get_artifact_store().register(...)` then
`self._get_provenance_store().record(...)`. If `provenance_store.record()`
raises (e.g. disk full, permission error), the artifact IS registered in
`ArtifactStore` but its provenance is NOT recorded. The artifact exists
without lineage.

THE BUG / RISK:
Partial state: artifact registered, provenance missing. The artifact appears
in `list()` results but `get_lineage()` returns `{"error": "no_provenance_record"}`.
The caller receives the `ArtifactRecord` and assumes provenance was recorded.

EVIDENCE:
```python
record = self._get_artifact_store().register(...)   # ← succeeds

_input_ids = input_artifact_ids or []
if record.artifact_id not in _input_ids:
    self._get_provenance_store().record(...)   # ← may raise; artifact already registered
```
No rollback of the artifact registration if provenance recording fails.

REPRODUCTION SCENARIO:
Disk full after artifact data is written but before provenance JSON is written.
`provenance_store.record()` raises `OSError`. `register_artifact` propagates
the exception. The artifact is in `ArtifactStore` but has no provenance.

IMPACT:
Partial state — artifact without provenance. `get_lineage()` returns error
nodes for this artifact. No data loss.

FIX DIRECTION:
Wrap the provenance call in try/except and log a warning rather than
propagating, since the artifact itself was successfully registered:
```python
try:
    self._get_provenance_store().record(...)
except Exception as exc:
    log.warning("Failed to record provenance for artifact %s: %s", record.artifact_id, exc)
```

--------------------------------------------------------------------
FILE:        app/core/run_journal.py
FUNCTION:    RunManager.save_graph_ir
CATEGORY:    Resource Leak
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Write `graph.json` and compute `self._graph_hash`.

WHAT IT ACTUALLY DOES:
Writes `graph.json` with a plain `open()` + `json.dump()` (no atomic rename).
If the process is killed during the write, `graph.json` is left truncated.

THE BUG / RISK:
A truncated `graph.json` cannot be loaded by `ir.loader`. If the run is
inspected after a crash, the graph cannot be reconstructed. This is a
diagnostic loss, not a runtime correctness issue.

EVIDENCE:
```python
with open(path, "w", encoding="utf-8") as f:
    json.dump(graph_data, f, indent=2, ensure_ascii=False)
    f.write("\n")
```
No atomic rename.

REPRODUCTION SCENARIO:
SIGKILL during `json.dump()` for a large graph. `graph.json` is truncated.
Post-mortem analysis cannot load the graph.

IMPACT:
Diagnostic loss — graph cannot be reconstructed from the run directory.
No runtime impact.

FIX DIRECTION:
Use atomic rename consistent with `_write_meta_unlocked`.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | UNSAFE |
| Resource Safety | UNSAFE |
| Test Hostile | PARTIAL |
| Top Risk | `update_resume_state` writes `resume_state.json` non-atomically — a crash mid-write permanently destroys resume capability for the affected run, with no recovery path. |
