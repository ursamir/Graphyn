# Functional Review — PluginPackage/Common/dataset_versioner/nodes.py

**Group:** 16 — Common Plugins  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Common/dataset_versioner/nodes.py
FUNCTION:    DatasetVersionerNode.process
CATEGORY:    Resource Leak
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Assign a version hash to a dataset for reproducibility and lineage tracking."

WHAT IT ACTUALLY DOES:
Calls `_write_manifest`, `_write_lineage`, and optionally `_write_snapshot`.
None of these are wrapped in try/except. If any write fails (disk full, permission
error), the function raises mid-way, leaving a partially-written `out_dir` on disk
(the directory was already created by `out_dir.mkdir(parents=True, exist_ok=True)`).
The returned `result` is never produced, but the partial directory remains.

THE BUG / RISK:
On a subsequent retry with the same `version_tag`, `out_dir.mkdir(..., exist_ok=True)`
succeeds silently, and the partial manifest/lineage from the failed run may be
overwritten or left in an inconsistent state. No cleanup occurs.

EVIDENCE:
```python
out_dir = Path(self.config.output_dir) / version
out_dir.mkdir(parents=True, exist_ok=True)   # created before any writes
manifest_path = out_dir / "manifest.csv"
self._write_manifest(dataset, manifest_path, dataset_hash)  # may fail
self._write_lineage(dataset, lineage_path, version, dataset_hash)  # may fail
```

REPRODUCTION SCENARIO:
Fill disk to capacity, then call `process()`. `out_dir` is created, then
`_write_manifest` raises `OSError: No space left on device`. The empty directory
persists.

IMPACT:
Partial output directory left on disk; no data loss but confusing state.

FIX DIRECTION:
Wrap writes in try/except and clean up on failure:
```python
try:
    self._write_manifest(...)
    self._write_lineage(...)
    if self.config.create_snapshot:
        self._write_snapshot(...)
except Exception:
    shutil.rmtree(out_dir, ignore_errors=True)
    raise
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/dataset_versioner/nodes.py
FUNCTION:    DatasetVersionerNode._write_manifest
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Write manifest CSV (id, label, split, hash) for all samples."

WHAT IT ACTUALLY DOES:
Iterates over `y_arr` and uses `labels[int(yi)]` to look up the label string.
If `yi` is out of range (e.g., `y_arr` contains a class index that exceeds
`len(labels) - 1`), it falls back to `str(yi)`. However, if `labels` is an
empty list and `y_arr` is non-empty, `int(yi) < len(labels)` is always False,
so every row gets a numeric string label instead of the actual class name.
This is a silent wrong result — the manifest is written without error.

THE BUG / RISK:
If `dataset.labels` is empty (e.g., a DatasetArtifact built from an empty
feature list that was later populated externally), the manifest contains
numeric strings instead of class names. No warning is emitted.

EVIDENCE:
```python
label = labels[int(yi)] if int(yi) < len(labels) else str(yi)
# If labels == [], every row gets str(yi) — silently wrong
```

REPRODUCTION SCENARIO:
```python
dataset.labels = []
dataset.y_train = np.array([0, 1, 2])
node._write_manifest(dataset, path, "abc123")
# manifest has labels "0", "1", "2" instead of class names
```

IMPACT:
Silent wrong result in manifest CSV. Lineage tracking is corrupted.

FIX DIRECTION:
```python
if not labels:
    log.warning("DatasetVersionerNode: labels list is empty — manifest will use numeric class indices")
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/dataset_versioner/nodes.py
FUNCTION:    DatasetVersionerNode.process
CATEGORY:    Type Safety
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Sets `result.version`, `result.content_hash`, `result.manifest_path` on the
deepcopy of the dataset.

WHAT IT ACTUALLY DOES:
Uses `setattr`-style assignment (`result.version = version`) on a deepcopy of
the input dataset. If the input is a Pydantic model with `model_config =
ConfigDict(frozen=True)` or similar, this raises `ValidationError` or
`TypeError: "Model" is immutable`. The code does not guard against this.

THE BUG / RISK:
If `DatasetArtifact` is a frozen Pydantic model, attribute assignment on the
deepcopy raises at runtime.

EVIDENCE:
```python
result = copy.deepcopy(dataset)
result.version = version           # raises if frozen Pydantic model
result.content_hash = dataset_hash
result.manifest_path = str(manifest_path)
```

REPRODUCTION SCENARIO:
Use a frozen DatasetArtifact → `TypeError: "DatasetArtifact" is immutable`.

IMPACT:
Crash at runtime if DatasetArtifact is frozen.

FIX DIRECTION:
Use `model_copy(update={...})` with a try/except fallback (same pattern used
in `DeploymentPackagerNode`).
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | UNSAFE |
| Test Hostile | NO |
| Top Risk | Partial output directory left on disk when any write fails mid-process, with no cleanup |
