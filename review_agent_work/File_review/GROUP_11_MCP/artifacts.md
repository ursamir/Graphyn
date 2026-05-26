# Functional Review — app/mcp/handlers/artifacts.py

**Group:** 11 — MCP
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/mcp/handlers/artifacts.py
FUNCTION:    inspect_run_handler (list all runs path)
CATEGORY:    Performance
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
List all runs ordered newest-first by `created_at`.

WHAT IT ACTUALLY DOES:
Iterates over all subdirectories in `_RUNS_DIR`, reads `meta.json` for
each, builds a list, then sorts by `created_at`. This is O(n) filesystem
reads where n is the total number of runs. With thousands of runs, this
becomes slow.

More importantly: `_RUNS_DIR.iterdir()` returns entries in filesystem
order (undefined on most filesystems). The sort is correct, but the
`created_at` field is an ISO 8601 string. String comparison of ISO 8601
timestamps is lexicographically correct only if the timezone offset is
consistent (all UTC `Z` or all `+00:00`). If some runs have `+00:00` and
others have `Z`, the sort order is wrong.

THE BUG / RISK:
Silent wrong sort order: if `created_at` timestamps mix `Z` and `+00:00`
suffixes (both are valid ISO 8601 UTC representations), string comparison
produces incorrect ordering. `"2026-01-01T00:00:00Z"` sorts AFTER
`"2026-01-01T00:00:00+00:00"` lexicographically because `"Z"` > `"+"`.

EVIDENCE:
Lines ~100–103:
```python
runs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
```
`RunManager.__init__` writes:
```python
"created_at": datetime.now(timezone.utc).isoformat()
```
`datetime.isoformat()` with `timezone.utc` produces `"+00:00"` suffix in
Python 3.11+ but `"+00:00"` in all versions. However, if any run was
created by a different code path that uses `"Z"` suffix, the sort breaks.

REPRODUCTION SCENARIO:
Run A: `created_at = "2026-05-26T10:00:00+00:00"` (newer)
Run B: `created_at = "2026-05-26T09:00:00Z"` (older)
String sort: `"Z"` > `"+"`, so B sorts before A → wrong order.

IMPACT:
Wrong sort order in `list_runs` response. Callers that rely on the first
entry being the most recent run get the wrong run.

FIX DIRECTION:
Parse timestamps before sorting:
```python
from datetime import datetime, timezone
def _parse_ts(ts):
    if not ts:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
runs.sort(key=lambda r: _parse_ts(r.get("created_at")), reverse=True)
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/handlers/artifacts.py
FUNCTION:    inspect_run_handler (checkpoints path)
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return list of node IDs that have a checkpoint directory (Req 5.7).

WHAT IT ACTUALLY DOES:
Strips the `"node_"` prefix from directory names:
```python
node_ids = [
    d.name.replace("node_", "")
    for d in checkpoints_dir.iterdir()
    if d.is_dir() and d.name.startswith("node_")
]
```
This assumes checkpoint directories are named `node_{node_id}`. If a
node_id itself contains `"node_"` (e.g. `"node_audio_classifier"`), the
result would be `"audio_classifier"` — which is correct. But if a
node_id is `"node_1"`, the directory is `"node_node_1"` and the result
is `"node_1"` — also correct.

However, the `node_id` checkpoint manifest path is constructed as:
```python
checkpoint_dir = run_dir / "checkpoints" / f"node_{node_id}"
```
So the round-trip is: store as `node_{node_id}`, retrieve by stripping
`node_` prefix. This is consistent.

THE BUG / RISK:
The `replace("node_", "")` call replaces ALL occurrences of `"node_"`,
not just the prefix. For a directory named `"node_audio_node_1"`, the
result would be `"audio_1"` instead of `"audio_node_1"`. This is a
silent wrong result.

EVIDENCE:
Line ~175:
```python
d.name.replace("node_", "")
```
`str.replace` replaces all occurrences, not just the first.

REPRODUCTION SCENARIO:
Node ID is `"audio_node_1"`. Checkpoint dir is `"node_audio_node_1"`.
`"node_audio_node_1".replace("node_", "")` → `"audio_1"` (wrong).
Should be `"audio_node_1"`.

IMPACT:
Wrong node_id returned in checkpoints list. Subsequent `inspect_run` with
`node_id="audio_1"` would fail with `checkpoint_not_found`.

FIX DIRECTION:
```python
d.name[len("node_"):]  # strip prefix only, not all occurrences
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        app/mcp/handlers/artifacts.py
FUNCTION:    inspect_run_handler
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Handle all dispatch modes; never raise unhandled exceptions (Req 5.11).

WHAT IT ACTUALLY DOES:
The dispatch is evaluated in this order: `status_only` → `logs` → `graph`
→ `checkpoints` → `node_id` → default (meta.json). If multiple flags are
set simultaneously (e.g. `logs=True` AND `graph=True`), only the first
matching branch executes. The caller gets logs but not the graph, with no
indication that the `graph` flag was ignored.

THE BUG / RISK:
Silent flag suppression: if a caller sets both `logs=True` and `graph=True`,
only logs are returned. The `graph` flag is silently ignored. The caller
has no way to know the graph was not returned.

EVIDENCE:
The dispatch is a chain of `if arguments.get("logs"):` ... `if arguments.get("graph"):` ...
Only the first matching branch returns.

REPRODUCTION SCENARIO:
Call `inspect_run` with `{"run_id": "abc", "logs": true, "graph": true}`.
Response: `{"logs": [...]}`. The graph is silently not returned.

IMPACT:
Caller gets partial data without knowing it. Low impact — the schema
implies single-mode dispatch, but this is not enforced or documented.

FIX DIRECTION:
Document in the schema that flags are mutually exclusive, or return an
error if multiple flags are set simultaneously.
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 2 |
| Error Handling | COMPLETE |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `str.replace("node_", "")` strips all occurrences of the prefix, not just the leading one — node IDs containing "node_" in their name are silently mangled in the checkpoints list. |
