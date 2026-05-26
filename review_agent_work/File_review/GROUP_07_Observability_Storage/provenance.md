# Functional Review — app/core/provenance.py

**Group:** 7 — Observability & Storage  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/provenance.py
FUNCTION:    ProvenanceStore.record
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Write `{artifact_id}.json` and append `artifact_id` to
`by_run/{run_id}.json`. Thread-safe via `threading.Lock()`.

WHAT IT ACTUALLY DOES:
Writes `{artifact_id}.json` with `record_path.write_text(...)` (atomic on
most POSIX filesystems for small files, but NOT guaranteed). Then writes
`by_run/{run_id}.json` with `by_run_path.write_text(...)` (also not atomic).
Then writes `by_graph_hash/{graph_hash}.json` with `by_hash_path.write_text(...)`.

None of these writes use atomic rename (`write_text` is not atomic — it
opens, writes, and closes, and a crash mid-write leaves a truncated file).

THE BUG / RISK:
If the process is killed between writing `{artifact_id}.json` and writing
`by_run/{run_id}.json`, the provenance record exists but is not indexed by
run. `find_by_run()` will not return this artifact. The artifact appears
orphaned from its run.

If the process is killed during `by_run_path.write_text(...)`, the
`by_run/{run_id}.json` file is left truncated. `find_by_run()` raises a
JSON parse error, catches it, and returns `[]` — all provenance for that
run is lost from the index.

EVIDENCE:
```python
record_path.write_text(
    json.dumps(prov.model_dump(mode="json"), indent=2), encoding="utf-8"
)
# ← crash here: record exists but not in by_run index

by_run_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
# ← crash here: by_run index is truncated
```

REPRODUCTION SCENARIO:
SIGKILL after `record_path.write_text` but before `by_run_path.write_text`.
`find_by_run(run_id)` returns `[]`. The artifact's provenance record exists
on disk but is unreachable via the run index.

IMPACT:
Provenance records become unreachable via `find_by_run()`. `get_provenance_summary()`
returns an empty `provenance_records` list for the affected run. Lineage
queries still work via `get_lineage(artifact_id)` since the individual
record file exists.

FIX DIRECTION:
Use atomic rename for all three writes:
```python
tmp = record_path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(prov.model_dump(mode="json"), indent=2), encoding="utf-8")
tmp.replace(record_path)
```
Apply the same pattern to `by_run_path` and `by_hash_path`.

--------------------------------------------------------------------
FILE:        app/core/provenance.py
FUNCTION:    ProvenanceStore.find_reproducible
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return all ProvenanceRecords whose `graph_hash` matches. Uses the
`by_graph_hash/` secondary index when available, falling back to a full scan.

WHAT IT ACTUALLY DOES:
In the fast path (index file exists), if reading the index file raises an
exception, `artifact_ids` is set to `None` (via `# type: ignore[assignment]`).
The code then falls through to the slow path (full directory scan). However,
the slow path is OUTSIDE the `else` branch of the `try/except` — it is
reached only when `by_hash_path.exists()` is False. When the index file
exists but is corrupt, the `except` sets `artifact_ids = None` and the
`else` branch (which returns the fast-path results) is NOT executed. But
the slow path is also NOT reached because it is outside the `if
by_hash_path.exists():` block.

THE BUG / RISK:
When the `by_graph_hash` index file exists but is corrupt, the function
returns `[]` (the initial value of `records`) without performing the slow
path scan. The docstring says it "falls back to a full scan" on index
failure, but the code does not.

EVIDENCE:
```python
if by_hash_path.exists():
    try:
        artifact_ids = json.loads(...)
        ...
    except Exception as exc:
        logger.warning(...)
        artifact_ids = None  # type: ignore[assignment]
    else:
        records = [...]
        return records   # ← only reached if no exception

# Slow path: full directory scan (for legacy records without index)
records = []
for entry in self.base.iterdir():   # ← only reached if by_hash_path does NOT exist
    ...
```

When `by_hash_path.exists()` is True and the `try` raises, the `else` is
skipped and execution falls through to the slow path. Wait — re-reading:
the slow path IS outside the `if by_hash_path.exists():` block, so it IS
reached when the `try` raises. Let me re-read more carefully.

```python
if by_hash_path.exists():
    try:
        artifact_ids = ...
        if not isinstance(artifact_ids, list):
            artifact_ids = []
    except Exception as exc:
        logger.warning(...)
        artifact_ids = None
    else:
        records = [...]
        return records   # ← returns here on success

# Slow path — reached when by_hash_path does NOT exist OR when try raised
records = []
for entry in self.base.iterdir():
    ...
```

Actually the slow path IS reached when the `try` raises (since `else` is
skipped and there's no `return` in the `except`). So the fallback DOES work.

The actual bug: when `artifact_ids = None` is set in the `except` block,
the slow path iterates `self.base.iterdir()` which includes the
`by_run/` and `by_graph_hash/` subdirectories. The slow path filters by
`entry.is_file() and entry.suffix == ".json"`, so subdirectories are
skipped. But `by_graph_hash/` contains `.json` files — these are index
files, not provenance records. `ProvenanceRecord.model_validate()` will
fail on them (they are lists, not dicts), and the `except` logs a warning
and skips them. This is safe but produces spurious warnings.

EVIDENCE (actual bug):
```python
for entry in self.base.iterdir():
    if not entry.is_file() or entry.suffix != ".json":
        continue   # ← skips by_run/ and by_graph_hash/ directories
    try:
        data = json.loads(entry.read_text(encoding="utf-8"))
        record = ProvenanceRecord.model_validate(data)   # ← fails for index files
```
The slow path only iterates `self.base` (the provenance root), not
subdirectories. Index files are in `by_run/` and `by_graph_hash/`
subdirectories, which are directories, not files. So `entry.is_file()`
filters them out. This is actually safe.

The real issue: the slow path does NOT scan `by_run/` or `by_graph_hash/`
subdirectories. It only scans the root `provenance/` directory for
`{artifact_id}.json` files. This is correct.

Revised assessment: the fallback logic is correct. The `artifact_ids = None`
assignment is misleading but harmless since the slow path doesn't use it.

SEVERITY DOWNGRADE: This is a LOW severity code clarity issue, not a bug.

THE ACTUAL BUG: The `artifact_ids = None` assignment in the `except` block
is dead code — the slow path doesn't use `artifact_ids`. This is confusing
and could mislead future maintainers into thinking the slow path uses it.

IMPACT:
Code clarity issue. No functional bug.

FIX DIRECTION:
Remove `artifact_ids = None` from the `except` block. Add a comment
explaining that the slow path is reached by falling through.

--------------------------------------------------------------------
FILE:        app/core/provenance.py
FUNCTION:    ProvenanceStore.get_lineage
CATEGORY:    Performance
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the full upstream lineage tree rooted at `artifact_id`. Uses
path-aware recursion to detect cycles.

WHAT IT ACTUALLY DOES:
Recursively reads `{artifact_id}.json` for each input artifact. For a deep
lineage tree with N nodes, this performs N file reads. Each file read is
synchronous and holds `self._lock` is NOT held during reads (reads are
outside the lock). This is correct for concurrency but means the lineage
tree is not a consistent snapshot — a concurrent `record()` call may add
new provenance records mid-traversal.

THE BUG / RISK:
For a lineage tree with 1000 nodes (e.g. a long audio processing pipeline
with many intermediate artifacts), `get_lineage()` performs 1000 synchronous
file reads. With 1ms per read, this takes 1 second. The function is called
from the API layer (provenance endpoint) and blocks the event loop if called
from an async context.

EVIDENCE:
```python
def _build_lineage_node(self, artifact_id: str, ancestors: frozenset) -> dict:
    ...
    record_path = self.base / f"{artifact_id}.json"
    ...
    data = json.loads(record_path.read_text(encoding="utf-8"))
    ...
    inputs = [
        self._build_lineage_node(input_id, new_ancestors)
        for input_id in prov.input_artifact_ids
    ]
```
Recursive, synchronous, no depth limit.

REPRODUCTION SCENARIO:
A pipeline with 500 nodes, each producing one artifact. `get_lineage()` on
the final artifact reads 500 files recursively. Called from an async API
handler, this blocks the event loop for ~500ms.

IMPACT:
API latency spike for deep lineage trees. No data corruption.

FIX DIRECTION:
Add a `max_depth` parameter with a default of 100. Log a warning when the
limit is reached. For the API layer, run `get_lineage()` in a thread pool
executor.

--------------------------------------------------------------------
FILE:        app/core/provenance.py
FUNCTION:    ProvenanceStore.record
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Record provenance for an artifact. Idempotent — no duplicates in by_run index.

WHAT IT ACTUALLY DOES:
When `graph_hash` is an empty string (e.g. `RunManager._graph_hash` before
`save_graph_ir()` is called), the `if graph_hash:` check skips writing the
`by_graph_hash` index. This is correct behavior. However, `find_reproducible("")`
would then perform a full scan and return all records with `graph_hash == ""`
— potentially a large number of records from runs where `save_graph_ir` was
never called.

THE BUG / RISK:
`find_reproducible("")` returns all provenance records with an empty
`graph_hash`. This is a valid query but could return a very large result set
if many runs failed before `save_graph_ir` was called.

EVIDENCE:
```python
if graph_hash:
    ...
    by_hash_path.write_text(...)
```
Empty `graph_hash` skips index write. `find_reproducible("")` falls through
to full scan (no index file for `""`).

REPRODUCTION SCENARIO:
1000 runs that failed before `save_graph_ir` was called. Each has
`graph_hash = ""`. `find_reproducible("")` scans all 1000 provenance files.

IMPACT:
Performance issue for `find_reproducible("")`. No data corruption.

FIX DIRECTION:
Document that `find_reproducible("")` is not a supported query. Add a guard:
```python
if not graph_hash:
    return []
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 0 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | UNSAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `record()` writes three files non-atomically — a crash between writes leaves the `by_run` index truncated, causing `find_by_run()` to return `[]` for the affected run and making all provenance for that run unreachable via the run index. |
