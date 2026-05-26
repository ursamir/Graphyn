# Functional Review — PluginPackage/Common/dataset_builder/nodes.py

**Group:** 16 — Common Plugins  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Common/dataset_builder/nodes.py
FUNCTION:    DatasetBuilderNode.process
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Assemble features into a DatasetArtifact. Raises ValueError if split_ratios
don't sum to 1.0, or if metadata-split mode encounters an invalid split value."

WHAT IT ACTUALLY DOES:
In metadata-split mode, the code validates that every feature has a valid split
value. However, the validation loop raises `ValueError` for any feature whose
`_infer_split()` returns a value NOT in `valid_splits`. But `_infer_split()` can
return `None` (when no split metadata and no path match), and `None not in valid_splits`
is `True`, so the error fires. The problem is the guard condition:

```python
has_split_metadata = any(self._infer_split(f) in valid_splits for f in features)
```

If only SOME features have valid split metadata (e.g., a mixed batch where half
have `metadata["split"]` and half don't), `has_split_metadata` is `True`, and the
subsequent validation loop raises `ValueError` for the features without split info,
even though auto-split would have been the correct fallback.

THE BUG / RISK:
A mixed batch (some features with split metadata, some without) raises a confusing
`ValueError` instead of either (a) using metadata-split for those that have it and
auto-splitting the rest, or (b) falling back to auto-split entirely. The error
message says "invalid split value 'None'" which is misleading.

EVIDENCE:
```python
has_split_metadata = any(
    self._infer_split(f) in valid_splits for f in features
)
if has_split_metadata:
    for f in features:
        split = self._infer_split(f)
        if split not in valid_splits:   # None triggers this
            raise ValueError(
                f"DatasetBuilderNode: invalid split value '{split}' ..."
            )
```

REPRODUCTION SCENARIO:
```python
f1 = FeatureArray(...); f1.metadata["split"] = "train"
f2 = FeatureArray(...); f2.metadata = {}; f2.source_path = "/data/audio.wav"
node.process({"input": [f1, f2]})
# Raises: ValueError: invalid split value 'None' for sample '/data/audio.wav'
```

IMPACT:
Pipeline crash on any mixed-metadata batch. The error message is misleading.

FIX DIRECTION:
Either require ALL features to have valid split metadata when any do, or fall back
to auto-split for features without metadata. The simplest fix is to change the
guard to `all(...)` instead of `any(...)`:
```python
has_split_metadata = all(self._infer_split(f) in valid_splits for f in features)
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/dataset_builder/nodes.py
FUNCTION:    DatasetBuilderNode._infer_split
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Get split from metadata, or infer from source_path directory structure."

WHAT IT ACTUALLY DOES:
Accesses `f.source_path` directly without checking if it is None or empty.
If `source_path` is None, `f.source_path.replace(...)` raises `AttributeError`.
If `source_path` is an empty string, the path check silently returns None.

THE BUG / RISK:
`FeatureArray` objects created without a `source_path` (e.g., from in-memory
generation) will crash `_infer_split` with `AttributeError: 'NoneType' object
has no attribute 'replace'`.

EVIDENCE:
```python
path_lower = f.source_path.replace("\\", "/").lower()  # crashes if source_path is None
```

REPRODUCTION SCENARIO:
```python
f = FeatureArray(data=np.zeros((10, 40)), label="cat", source_path=None)
node._infer_split(f)  # AttributeError
```

IMPACT:
Crash on any FeatureArray without a source_path.

FIX DIRECTION:
```python
path_lower = (f.source_path or "").replace("\\", "/").lower()
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/dataset_builder/nodes.py
FUNCTION:    DatasetBuilderNode._to_arrays
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Stack features into [N, T, F, 1] X array and [N] y array."

WHAT IT ACTUALLY DOES:
When `fixed_length > 0`, all frames are padded/truncated to the same length.
When `fixed_length == 0`, frames are stacked with `np.stack(frames)` without
checking that all frames have the same shape. If different FeatureArray objects
have different time dimensions (T), `np.stack` raises a `ValueError: all input
arrays must have the same shape`.

THE BUG / RISK:
Variable-length audio features (different number of frames per sample) cause a
crash in `np.stack` with a confusing error message. The fix (set `fixed_length`)
is not obvious from the error.

EVIDENCE:
```python
frames.append(arr)   # arr may be (T1, F) for one sample, (T2, F) for another
X = np.stack(frames)  # ValueError if shapes differ
```

REPRODUCTION SCENARIO:
```python
f1 = FeatureArray(data=np.zeros((50, 40)), label="a", source_path="a.wav")
f2 = FeatureArray(data=np.zeros((80, 40)), label="b", source_path="b.wav")
node.process({"input": [f1, f2]})  # ValueError: all input arrays must have the same shape
```

IMPACT:
Crash with confusing error. User must know to set `fixed_length`.

FIX DIRECTION:
Add a pre-check and a clear error message:
```python
if fixed_length == 0:
    shapes = {arr.shape for arr in frames}
    if len(shapes) > 1:
        raise ValueError(
            f"DatasetBuilderNode: variable-length features detected {shapes}. "
            "Set fixed_length > 0 to enable padding/truncation."
        )
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/dataset_builder/nodes.py
FUNCTION:    DatasetBuilderNode.process
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Returns a DatasetArtifact with empty splits when `features` is empty.

WHAT IT ACTUALLY DOES:
Returns `DatasetArtifact(labels=[], input_shape=(), n_classes=0)` without
setting `X_train`, `X_val`, `X_test`, `y_train`, `y_val`, `y_test`. Downstream
nodes (TrainerNode, EvaluatorNode) access `dataset.X_train` directly and will
get `None` or raise `AttributeError` depending on the DatasetArtifact defaults.

THE BUG / RISK:
Empty-input path produces a partially-initialised DatasetArtifact. If
`DatasetArtifact` defaults these fields to `None`, TrainerNode's
`np.asarray(dataset.X_train, dtype=np.float32)` will raise `TypeError`.

EVIDENCE:
```python
if not features:
    return {"output": DatasetArtifact(
        labels=[],
        input_shape=(),
        n_classes=0,
    )}
```

REPRODUCTION SCENARIO:
```python
out = node.process({"input": []})
trainer.process({"model": model, "dataset": out["output"]})
# TypeError: float() argument must be a string or a number, not 'NoneType'
```

IMPACT:
Crash in downstream node with confusing error.

FIX DIRECTION:
Provide zero-length arrays explicitly:
```python
return {"output": DatasetArtifact(
    X_train=np.zeros((0,1,1,1), dtype=np.float32),
    y_train=np.zeros((0,), dtype=np.int32),
    X_val=np.zeros((0,1,1,1), dtype=np.float32),
    y_val=np.zeros((0,), dtype=np.int32),
    X_test=np.zeros((0,1,1,1), dtype=np.float32),
    y_test=np.zeros((0,), dtype=np.int32),
    labels=[], input_shape=(1,1,1), n_classes=0,
)}
```
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | Mixed-metadata batch (some features with split info, some without) triggers a misleading ValueError instead of falling back to auto-split |
