# Functional Review — app/models/tensor_batch.py

**Group:** 12 — Domain & Models  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/models/tensor_batch.py
FUNCTION:    TensorBatch.batch_size (property)
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return the number of samples in the batch (`data.shape[0]`).

WHAT IT ACTUALLY DOES:
Returns `self.data.shape[0] if self.data.ndim > 0 else 0`. For a 0-D array (scalar), `ndim == 0` and `batch_size` returns 0 — correct. For a 1-D array of shape `(0,)` (the default from `_coerce_float32` when `data=None`), `ndim == 1 > 0` and `shape[0] == 0` — returns 0, correct.

However, if `data` is a 1-D array of shape `(N,)` where N > 0 (e.g., a flat feature vector passed by mistake), `batch_size` returns `N` — treating each element as a separate sample. This is a contract mismatch: the docstring says `data` has shape `[batch_size, *feature_dims]`, implying at least 2 dimensions for non-trivial batches. A 1-D array is ambiguous.

EVIDENCE:
Lines ~55–57:
```python
@property
def batch_size(self) -> int:
    return self.data.shape[0] if self.data.ndim > 0 else 0
```
No validation that `data.ndim >= 2` for non-empty batches.

REPRODUCTION SCENARIO:
```python
tb = TensorBatch(data=np.array([1.0, 2.0, 3.0]))  # 1-D, shape (3,)
tb.batch_size  # returns 3 — but this is not a batch of 3 samples
```

IMPACT:
Silent wrong result — downstream nodes that use `batch_size` to iterate over samples will iterate over individual float values instead of feature vectors.

FIX DIRECTION:
Add a validator that warns (or raises) when `data.ndim == 1` and `data.shape[0] > 0`:
```python
if v.ndim == 1 and v.shape[0] > 0:
    # Reshape to (N, 1) or raise ValueError
    raise ValueError("TensorBatch.data must be 2-D or higher for non-empty batches")
```

--------------------------------------------------------------------
FILE:        app/models/tensor_batch.py
FUNCTION:    TensorBatch.model_post_init
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Ensure data is always a float32 array even when using default.

WHAT IT ACTUALLY DOES:
Same dead-code pattern as `FeatureArray.model_post_init` — `_coerce_float32` already converts `None` to `np.zeros((0,))`, so `model_post_init`'s `if self.data is None` check can never be true after normal construction.

EVIDENCE:
Lines ~60–62:
```python
def model_post_init(self, __context: Any) -> None:
    if self.data is None:
        object.__setattr__(self, "data", np.zeros((0,), dtype=np.float32))
```

IMPACT:
None — dead code.

FIX DIRECTION:
Remove or add a comment explaining it is a safety net for `model_construct()`.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 1 |
| Error Handling | COMPLETE |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `batch_size` returns `N` for a 1-D array of shape `(N,)`, silently treating a flat feature vector as a batch of N scalar samples. |
