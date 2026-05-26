# Functional Review — PluginPackage/Common/dataset_balancer/nodes.py

**Group:** 16 — Common Plugins  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Common/dataset_balancer/nodes.py
FUNCTION:    DatasetBalancerNode._flag_synthetic
CATEGORY:    Contract Mismatch
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Flag minority samples for augmentation by setting metadata on a copy."

WHAT IT ACTUALLY DOES:
Returns `(X, y)` — the original unmodified arrays — but the caller in `process()` then
calls `result.X_train = X_bal.astype(np.float32)` and `result.y_train = y_bal.astype(np.int32)`
on the deepcopy. However `_flag_synthetic` also does `result_dataset = copy.deepcopy(dataset)`
internally and sets `result_dataset.metadata["needs_augmentation"]`, but that internal copy
is **never returned** — it is discarded. The metadata mutation is lost.

THE BUG / RISK:
The `needs_augmentation` metadata written inside `_flag_synthetic` is set on a local
`result_dataset` that is never returned. The caller's `result = copy.deepcopy(dataset)` is
a separate object. The augmentation flags are silently dropped.

EVIDENCE:
```python
# _flag_synthetic (lines ~155-165):
result_dataset = copy.deepcopy(dataset)   # local copy — never returned
...
result_dataset.metadata.setdefault("needs_augmentation", {})
...
return X, y   # only arrays returned; result_dataset discarded

# process() (lines ~115-125):
elif strategy == "synthetic":
    X_bal, y_bal = self._flag_synthetic(X, y, dataset)
# then falls through to:
result = copy.deepcopy(dataset)           # separate copy — no augmentation flags
result.X_train = X_bal.astype(np.float32)
result.y_train = y_bal.astype(np.int32)
result.metadata = {**dataset.metadata, "balancer": {...}}  # overwrites metadata entirely
```

REPRODUCTION SCENARIO:
```python
node = DatasetBalancerNode(Config(strategy="synthetic"))
out = node.process(dataset)
assert "needs_augmentation" in out.metadata  # FAILS — key is absent
```

IMPACT:
Silent wrong result. Downstream nodes expecting `needs_augmentation` metadata will
find it absent and silently skip augmentation, producing an unbalanced dataset with
no error or warning.

FIX DIRECTION:
Return the augmentation flags from `_flag_synthetic` and merge them in `process()`:
```python
def _flag_synthetic(self, X, y, dataset) -> tuple:
    classes, counts = np.unique(y, return_counts=True)
    target = self.config.target_count or int(counts.max())
    aug_flags = {}
    for cls, cnt in zip(classes, counts):
        deficit = target - cnt
        if deficit > 0:
            aug_flags[int(cls)] = int(deficit)
    return X, y, aug_flags

# In process():
X_bal, y_bal, aug_flags = self._flag_synthetic(X, y, dataset)
result = copy.deepcopy(dataset)
result.X_train = X_bal.astype(np.float32)
result.y_train = y_bal.astype(np.int32)
result.metadata = {**dataset.metadata, "balancer": {...}, "needs_augmentation": aug_flags}
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/dataset_balancer/nodes.py
FUNCTION:    DatasetBalancerNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Balance dataset class distributions to prevent training bias."

WHAT IT ACTUALLY DOES:
Checks `if X is None or len(X) == 0` and returns unchanged. However it does not
check whether `y` is None or whether `X` and `y` have mismatched lengths.

THE BUG / RISK:
If `dataset.y_train` is None while `dataset.X_train` is non-empty, `np.unique(y, ...)`
raises `TypeError: argument of type 'NoneType' is not iterable`. If `len(X) != len(y)`,
numpy indexing in `_oversample`/`_undersample` will raise an IndexError with a confusing
traceback rather than a clear validation error.

EVIDENCE:
```python
X = dataset.X_train
y = dataset.y_train
if X is None or len(X) == 0:   # y is never checked
    ...
# _oversample:
idx = np.where(y == cls)[0]
chosen = rng.choice(idx, ...)
X_extra = X[chosen]            # IndexError if len(X) != len(y)
```

REPRODUCTION SCENARIO:
```python
dataset.X_train = np.zeros((10, 40))
dataset.y_train = None
node.process(dataset)  # TypeError in np.unique(None)
```

IMPACT:
Crash with confusing traceback instead of a clear validation error.

FIX DIRECTION:
```python
if X is None or y is None or len(X) == 0:
    log.warning("DatasetBalancerNode: empty training set — returning unchanged")
    return dataset
if len(X) != len(y):
    raise ValueError(f"DatasetBalancerNode: X_train length {len(X)} != y_train length {len(y)}")
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/dataset_balancer/nodes.py
FUNCTION:    DatasetBalancerNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validates `strategy` and raises `ValueError` for unknown values.

WHAT IT ACTUALLY DOES:
Does not validate `strategy` before the `if/elif` chain. The `balance_by` check
raises `NotImplementedError` for non-"class" values, but `strategy` is only
validated at the end of the chain. More importantly, `target_count` is never
validated — a negative value would cause `_oversample` to compute a negative
`deficit` and silently skip all oversampling, returning the original unbalanced data.

THE BUG / RISK:
`target_count = -1` causes `deficit = -1 - cnt < 0` for all classes, so the
oversample loop adds nothing. The result is the original unbalanced dataset
returned as if it were balanced, with no warning.

EVIDENCE:
```python
target = self.config.target_count or int(counts.max())
# If target_count = -1: target = -1 (truthy, so counts.max() not used)
deficit = target - cnt   # -1 - cnt < 0 always
if deficit <= 0:
    continue             # silently skips all classes
```

REPRODUCTION SCENARIO:
```python
node = DatasetBalancerNode(Config(strategy="oversample", target_count=-1))
out = node.process(dataset)
# out.X_train == dataset.X_train — no balancing done, no error raised
```

IMPACT:
Silent wrong result. Training proceeds on unbalanced data.

FIX DIRECTION:
```python
if self.config.target_count < 0:
    raise ValueError(f"DatasetBalancerNode: target_count must be >= 0, got {self.config.target_count}")
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/dataset_balancer/nodes.py
FUNCTION:    DatasetBalancerNode.process (weighted branch)
CATEGORY:    State Bug
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Returns a balanced DatasetArtifact with class weights in metadata.

WHAT IT ACTUALLY DOES:
The `weighted` branch does `dataset = copy.deepcopy(dataset)` (reassigning the
parameter), then sets `dataset.metadata["class_weights"]` and `dataset.X_train`.
It then returns early. This is correct in isolation, but the parameter reassignment
is confusing and differs from the pattern used by all other branches (which use
`result = copy.deepcopy(dataset)`). If the code is ever refactored, this asymmetry
is a maintenance hazard.

THE BUG / RISK:
Low risk currently, but the inconsistent pattern (reassigning `dataset` vs using
`result`) makes the code fragile under refactoring.

EVIDENCE:
```python
elif strategy == "weighted":
    X_bal, y_bal, weights = self._compute_weights(X, y)
    dataset = copy.deepcopy(dataset)   # reassigns parameter
    dataset.metadata["class_weights"] = weights.tolist()
    ...
    return dataset
```

REPRODUCTION SCENARIO:
N/A — current behavior is correct but inconsistent.

IMPACT:
Maintenance hazard; no current runtime impact.

FIX DIRECTION:
Use `result = copy.deepcopy(dataset)` consistently across all branches.
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `_flag_synthetic` discards its own metadata copy — `needs_augmentation` flags are silently lost on every synthetic-strategy run |
