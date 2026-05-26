# Functional Review — app/core/artifact_store.py

**Group:** 7 — Observability & Storage  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/artifact_store.py
FUNCTION:    ArtifactStore.cleanup
CATEGORY:    Silent Failure Risk
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Delete artifact directories older than `older_than_days`. Removes the
artifact directory and updates all secondary indexes.

WHAT IT ACTUALLY DOES:
The loop body has a structural bug: the `bytes_freed` accumulation and
`shutil.rmtree` call are OUTSIDE the `try/except` block that parses the
record. This means every directory that has a `record.json` (regardless of
age) gets its bytes counted and gets deleted — even entries that are NOT
older than the cutoff.

THE BUG / RISK:
The `continue` statement inside the `try` block skips entries that are NOT
older than the cutoff. But the `shutil.rmtree` and `bytes_freed` accumulation
are at the same indentation level as the `try/except` block — they execute
for EVERY entry that has a `record.json`, including entries where the `try`
block raised an exception (which also does not `continue`). Entries that fail
to parse are silently deleted.

EVIDENCE:
```python
for entry in list(self.base.iterdir()):
    if not entry.is_dir() or entry.name in ("by_run", "by_name"):
        continue
    record_path = entry / "record.json"
    if not record_path.exists():
        continue
    try:
        record_data = json.loads(record_path.read_text(encoding="utf-8"))
        record = ArtifactRecord.model_validate(record_data)
        ...
        if created >= cutoff:
            continue          # ← skips rmtree for non-expired entries
        hashes_to_remove.append(record.content_hash)
        deleted_ids.append(record.artifact_id)
    except Exception:
        pass                  # ← does NOT continue; falls through to rmtree

    for f in entry.rglob("*"):   # ← executes for ALL entries that didn't continue
        if f.is_file():
            bytes_freed += f.stat().st_size
    shutil.rmtree(str(entry), ignore_errors=True)   # ← deletes ALL entries
    entries_deleted += 1
```

The `continue` inside the `try` block only skips entries where `created >=
cutoff`. For entries where the `try` block raises (corrupt record.json), the
`except: pass` falls through to `shutil.rmtree`. For entries where `created
< cutoff`, the `hashes_to_remove.append` runs and then falls through to
`shutil.rmtree` — this is correct. But for entries where `created >= cutoff`,
the `continue` skips `shutil.rmtree` — this is also correct.

Wait — re-reading: the `continue` IS inside the `try` block and DOES skip
the `shutil.rmtree`. The bug is specifically for the `except Exception: pass`
path: entries with corrupt `record.json` are deleted without being added to
`hashes_to_remove` or `deleted_ids`, so their content-hash index entries and
secondary index entries are NOT cleaned up. The index becomes stale.

REPRODUCTION SCENARIO:
An artifact directory has a corrupt `record.json` (e.g. truncated by a prior
crash). `cleanup()` deletes the directory but does not remove the
content-hash index entry. The index now points to a non-existent directory.
A future `register()` call for the same content hash finds the index entry,
tries to load `record.json` from the non-existent directory, logs a warning,
and re-registers — creating a duplicate entry with a new artifact_id.

IMPACT:
Index corruption — stale content-hash entries pointing to deleted directories.
Causes duplicate artifact registration for the same content on the next run.

FIX DIRECTION:
Add `continue` in the `except` block to skip deletion of unparseable entries,
or move `shutil.rmtree` inside the `try` block after the cutoff check:
```python
try:
    ...
    if created >= cutoff:
        continue
    hashes_to_remove.append(record.content_hash)
    deleted_ids.append(record.artifact_id)
    for f in entry.rglob("*"):
        if f.is_file():
            bytes_freed += f.stat().st_size
    shutil.rmtree(str(entry), ignore_errors=True)
    entries_deleted += 1
except Exception:
    pass  # skip unparseable entries — do NOT delete them
```

--------------------------------------------------------------------
FILE:        app/core/artifact_store.py
FUNCTION:    ArtifactStore.register
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Register a node output as an artifact. Serializes data BEFORE acquiring the
lock to minimize lock hold time (ARCH-6 fix).

WHAT IT ACTUALLY DOES:
Serializes data to a temp directory before acquiring the lock. If
`_serialize_data` raises `ArtifactSerializationError`, the temp directory
`tmp_artifact_dir` is NOT cleaned up — it is left on disk.

THE BUG / RISK:
The `try/except ArtifactSerializationError: raise` block does not clean up
`tmp_artifact_dir` before re-raising. Every failed serialization leaves a
`_tmp_{uuid}/` directory in `self.base`.

EVIDENCE:
```python
tmp_artifact_dir = self.base / f"_tmp_{tmp_artifact_id}"
tmp_data_dir = tmp_artifact_dir / "data"
try:
    self._serialize_data(artifact_type, data, tmp_data_dir)
except ArtifactSerializationError:
    raise   # ← tmp_artifact_dir is NOT cleaned up
```

REPRODUCTION SCENARIO:
A node produces a corrupt audio artifact. `handler.serialize()` raises.
`ArtifactSerializationError` is re-raised. `tmp_artifact_dir` remains on disk.
After 1000 failed registrations, the artifacts directory contains 1000
`_tmp_*/` directories.

IMPACT:
Disk space leak. No data corruption.

FIX DIRECTION:
```python
try:
    self._serialize_data(artifact_type, data, tmp_data_dir)
except ArtifactSerializationError:
    import shutil as _shutil
    _shutil.rmtree(str(tmp_artifact_dir), ignore_errors=True)
    raise
```

--------------------------------------------------------------------
FILE:        app/core/artifact_store.py
FUNCTION:    ArtifactStore.register
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Deduplicate artifacts by content hash. Returns existing record if
content_hash already exists.

WHAT IT ACTUALLY DOES:
When deduplication finds an existing record, it returns a NEW `ArtifactRecord`
constructed from the existing record's fields but with the CURRENT call's
`node_id`, `node_type`, and `run_id`. The `created_at` field is taken from
the existing record (correct for deduplication). However, the `metadata` and
`name` fields use the current call's values if provided, otherwise fall back
to the existing record's values.

THE BUG / RISK:
The deduplicated record is returned with the current `run_id` and `node_id`,
but the `data_path` points to the ORIGINAL artifact's data directory. If the
original artifact is later deleted by `cleanup()`, the deduplicated record's
`data_path` becomes a dangling reference. The caller has no way to know that
the data was shared.

More critically: the deduplicated record is NOT written to disk. Only the
in-memory return value has the current `run_id`. The `by_run` index IS updated
(G3-09 fix), but there is no `record.json` for the deduplicated artifact_id
with the current run's metadata. If the caller later calls `get(artifact_id)`,
they get the ORIGINAL record (with the original `run_id`, `node_id`), not the
deduplicated one.

EVIDENCE:
```python
return ArtifactRecord(
    artifact_id=existing.artifact_id,
    ...
    run_id=run_id,          # ← current run
    node_id=node_id,        # ← current node
    ...
    data_path=existing.data_path,  # ← original data path
)
# ← no record.json written for this deduplicated view
```

REPRODUCTION SCENARIO:
Run A produces artifact X (content_hash H). Run B produces the same content.
`register()` returns a record with `run_id=B` but `artifact_id=X`. Caller
stores `artifact_id=X`. Later calls `store.get(X)` — gets the record with
`run_id=A`. The caller's `run_id=B` association is only in the `by_run` index,
not in the record itself.

IMPACT:
Contract mismatch — the returned record does not match what `get()` returns
for the same `artifact_id`. Callers that rely on `record.run_id` from the
return value of `register()` get a different value than from `get()`.

FIX DIRECTION:
Document clearly that the returned record from a deduplicated `register()` is
a view with the current run context, and that `get()` returns the canonical
record. Alternatively, write a per-run record file for deduplicated artifacts.

--------------------------------------------------------------------
FILE:        app/core/artifact_store.py
FUNCTION:    ArtifactStore._by_name_path
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Sanitize artifact name for use as a filename. Prevents "." and ".." from
being used as filenames.

WHAT IT ACTUALLY DOES:
Sanitizes the name by replacing non-alphanumeric characters with `_` and
stripping leading dots. However, the sanitization can produce collisions:
two different names that differ only in special characters will map to the
same filename. For example, `"my-model"` and `"my_model"` both map to
`"my_model.json"`.

THE BUG / RISK:
Two artifacts with names `"my-model"` and `"my_model"` share the same
`by_name` index file. `get_versions("my-model")` returns artifacts for both
names. `get_versions("my_model")` also returns artifacts for both names.

EVIDENCE:
```python
safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)[:128]
```
`"-"` is in the allowed set, so `"my-model"` → `"my-model"` and
`"my_model"` → `"my_model"` — these are different. But `"my model"` →
`"my_model"` and `"my_model"` → `"my_model"` — collision.

REPRODUCTION SCENARIO:
Register artifact with name `"my model"` (space). Register artifact with name
`"my_model"`. Both map to `by_name/my_model.json`. `get_versions("my model")`
returns both artifacts.

IMPACT:
Silent wrong result — `get_versions` returns artifacts for a different name.

FIX DIRECTION:
Store the original name in the index file alongside the artifact_id, and
filter by exact name match in `_load_by_name`. Or use a hash of the original
name as the filename.

--------------------------------------------------------------------
FILE:        app/core/artifact_store.py
FUNCTION:    ArtifactStore.list (slow path)
CATEGORY:    Performance
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return all registered artifacts, optionally filtered. Uses secondary index
for run_id-only queries.

WHAT IT ACTUALLY DOES:
For queries with `node_type` or `artifact_type` filters, performs a full
directory scan. With 100,000 artifacts, this reads 100,000 `record.json`
files. No lock is held during the scan, so concurrent `register()` calls
may add new entries mid-scan.

THE BUG / RISK:
The scan is not atomic. A concurrent `register()` call may add a new artifact
between the `iterdir()` call and the end of the loop. The new artifact may or
may not appear in the results depending on filesystem ordering. This is a
TOCTOU issue but not a correctness bug for most use cases.

EVIDENCE:
```python
for entry in self.base.iterdir():
    ...
```
No lock held during iteration.

REPRODUCTION SCENARIO:
Two concurrent calls: `list(artifact_type="audio_samples")` and
`register(...)`. The new artifact may or may not appear in the list results.

IMPACT:
Non-deterministic list results under concurrent load. No data corruption.

FIX DIRECTION:
Document that `list()` is not atomic under concurrent writes. For
production use, add a secondary index for `artifact_type` similar to `by_run`.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | UNSAFE |
| Resource Safety | UNSAFE |
| Test Hostile | NO |
| Top Risk | `cleanup()` deletes artifact directories for entries with corrupt `record.json` without removing their index entries, leaving the content-hash index pointing to non-existent directories and causing duplicate registration on the next run. |
