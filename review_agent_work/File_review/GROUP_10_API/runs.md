# Functional Review — app/api/routers/runs.py

**Group:** 10 — API  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/api/routers/runs.py
FUNCTION:    list_runs
CATEGORY:    Performance
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return a summary list of pipeline runs, newest first, with pagination.
Default: first 50 runs.

WHAT IT ACTUALLY DOES:
`runs_root.iterdir()` reads ALL run directories, loads ALL `meta.json` files
into memory, sorts the entire list, then slices `[offset: offset + limit]`.
For a workspace with thousands of runs, this reads and parses every meta.json
on every request — O(n) disk reads and O(n log n) sort for every paginated
request.

THE BUG / RISK:
With 10,000 runs, every call to `GET /runs?limit=50` reads 10,000 files from
disk. This is an unbounded O(n) operation that grows with the number of runs.
There is no index, no caching, and no early termination.

EVIDENCE:
`runs.py` lines ~52–65: full `iterdir()` scan, full sort, then slice.

REPRODUCTION SCENARIO:
Accumulate 5,000 runs. `GET /runs?limit=50` takes several seconds and reads
5,000 files. Concurrent requests multiply the disk I/O.

IMPACT:
API latency degrades linearly with run count. Under load, this can cause
request timeouts and high disk I/O.

FIX DIRECTION:
Short-term: sort by directory mtime (OS-level, no file reads) and only read
meta.json for the sliced entries. Long-term: maintain a run index file.
```python
entries = sorted(
    (e for e in runs_root.iterdir() if e.is_dir()),
    key=lambda e: e.stat().st_mtime,
    reverse=True,
)[offset: offset + limit]
runs = []
for entry in entries:
    meta_path = entry / "meta.json"
    if meta_path.exists():
        try:
            runs.append(json.loads(meta_path.read_text()))
        except Exception:
            continue
return runs
```

--------------------------------------------------------------------
FILE:        app/api/routers/runs.py
FUNCTION:    _run_dir
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate run_id is alphanumeric (hyphens allowed) and that the resolved path
stays within the runs root.

WHAT IT ACTUALLY DOES:
The validation is `run_id.replace("-", "").isalnum()`. This accepts run IDs
that are ALL hyphens (e.g. `"---"`), because `"---".replace("-", "")` is `""`
which is falsy — but the check is `not run_id.replace("-", "")` which catches
the empty-after-strip case. Wait — the condition is:
```python
if not run_id.replace("-", "").isalnum() or not run_id.replace("-", ""):
```
`"---".replace("-", "")` → `""` → `not ""` → `True` → raises 400. ✓

However, `run_id` itself could be an empty string `""`:
`"".replace("-", "")` → `""` → `not ""` → `True` → raises 400. ✓

The real edge case: `run_id` containing Unicode letters. `"rün123".replace("-","").isalnum()`
→ `True` (Python's `isalnum()` accepts Unicode letters). A run_id like `"rün123"`
passes validation but is unlikely to exist on disk. The path traversal guard
catches it anyway. Low severity but the validation is looser than documented
("alphanumeric" typically means ASCII only).

THE BUG / RISK:
Unicode run IDs pass the alphanumeric check. On case-insensitive filesystems
(macOS HFS+), `run_id = "RUN123"` and `run_id = "run123"` resolve to the same
directory. The path traversal guard does not catch this. Not a security issue
in practice (run IDs are generated internally), but the validation contract
is weaker than stated.

EVIDENCE:
`runs.py` line ~35: `if not run_id.replace("-", "").isalnum() or not run_id.replace("-", ""):`

REPRODUCTION SCENARIO:
`GET /runs/rün123` — passes validation, returns 404 (run not found). No crash,
but the validation contract says "alphanumeric" and this accepts Unicode.

IMPACT:
Low. No security impact due to the path traversal guard. Validation is slightly
weaker than documented.

FIX DIRECTION:
Use an explicit ASCII-only regex:
```python
import re
_RUN_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]*$')
if not _RUN_ID_RE.match(run_id):
    raise HTTPException(status_code=400, detail="Invalid run_id")
```

--------------------------------------------------------------------
FILE:        app/api/routers/runs.py
FUNCTION:    get_run_status
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the status of a specific run including progress_pct and current_node.

WHAT IT ACTUALLY DOES:
`progress_pct` computation: `completed / total * 100` where `total` falls back
to `completed` when `num_nodes` is missing or zero. This means if `num_nodes`
is not stored in meta.json (e.g. for older runs), `total = completed` and
`progress_pct` is always 100.0 regardless of actual progress. A run with 3
of 10 nodes completed would report 100% progress.

THE BUG / RISK:
When `num_nodes` is absent from meta.json, `progress_pct` silently returns
100.0 for any non-empty `node_stats` list. This is a silent wrong result —
the caller sees 100% progress for a run that is still executing.

EVIDENCE:
`runs.py` lines ~100–106:
```python
total = num_nodes if isinstance(num_nodes, int) and num_nodes > 0 else completed
progress_pct = round(completed / total * 100, 1)
```
When `num_nodes` is None: `total = completed`, `progress_pct = 100.0`.

REPRODUCTION SCENARIO:
A run with `num_nodes` not written to meta.json (e.g. older run format or
a run that failed before writing num_nodes). `GET /runs/{run_id}/status` →
`{"status": "running", "progress_pct": 100.0, "current_node": "SomeNode"}`.

IMPACT:
Silent wrong result. UI shows 100% progress for an in-progress run. Users
believe the run is complete when it is not.

FIX DIRECTION:
Return `null` for `progress_pct` when `num_nodes` is unknown:
```python
if node_stats and isinstance(node_stats, list) and isinstance(num_nodes, int) and num_nodes > 0:
    completed = len(node_stats)
    progress_pct = round(completed / num_nodes * 100, 1)
else:
    progress_pct = None
```

--------------------------------------------------------------------
FILE:        app/api/routers/runs.py
FUNCTION:    get_checkpoint_manifest
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the manifest.json content for a specific checkpoint node. Uses exact
match first, then prefix match for backward compat.

WHAT IT ACTUALLY DOES:
The prefix match iterates `checkpoints_dir.iterdir()` without sorting. If
multiple checkpoint directories share the same prefix (e.g. `AudioClassifier_0`
and `AudioClassifier_1`), the first match returned by `iterdir()` is
filesystem-order dependent (non-deterministic on most filesystems). The caller
gets whichever checkpoint the OS returns first.

EVIDENCE:
`runs.py` lines ~143–148:
```python
for entry in checkpoints_dir.iterdir():
    if entry.is_dir() and entry.name.startswith(node_id):
        checkpoint_dir = entry
        break
```
No sorting before iteration.

REPRODUCTION SCENARIO:
Two checkpoints: `AudioClassifier_0` and `AudioClassifier_1`. Request
`node_id="AudioClassifier"`. Returns whichever the OS lists first — could be
either one, non-deterministically.

IMPACT:
Non-deterministic checkpoint selection. Wrong checkpoint data returned silently.

FIX DIRECTION:
Sort before iterating:
```python
for entry in sorted(checkpoints_dir.iterdir()):
    if entry.is_dir() and entry.name.startswith(node_id):
        checkpoint_dir = entry
        break
```

--------------------------------------------------------------------
FILE:        app/api/routers/runs.py
FUNCTION:    list_run_artifacts / get_run_provenance
CATEGORY:    Testability
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return artifacts/provenance for a run by delegating to ArtifactStore and
ProvenanceStore.

WHAT IT ACTUALLY DOES:
Both functions instantiate `ArtifactStore()` and `ProvenanceStore()` directly
inside the function body (deferred imports). This makes unit testing impossible
without patching the constructors at the module level or using full integration
test setup.

EVIDENCE:
`runs.py` lines ~175–177: `from app.core.artifact_store import ArtifactStore; ArtifactStore()`
`runs.py` lines ~185–188: same pattern for ProvenanceStore.

REPRODUCTION SCENARIO:
Unit test for `list_run_artifacts` must mock `app.core.artifact_store.ArtifactStore`
at the module level, which is fragile and couples the test to the import path.

IMPACT:
Test hostile. No functional bug, but increases test complexity and fragility.

FIX DIRECTION:
Accept store instances as optional parameters (dependency injection) or use
FastAPI's `Depends()` mechanism for the stores.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | PARTIAL |
| Top Risk | get_run_status silently returns 100% progress when num_nodes is absent from meta.json, giving wrong progress data for in-progress runs. |
