# Functional Review — PluginPackage/Common/evaluator/nodes.py

**Group:** 16 — Common Plugins  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Common/evaluator/nodes.py
FUNCTION:    EvaluatorNode.process
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Evaluate the model and save metrics/plots."

WHAT IT ACTUALLY DOES:
Accesses `dataset.X_test` and `dataset.y_test` directly without checking if
they are None or empty. If the test split is empty (e.g., a dataset built with
`split_ratios={"train": 0.9, "val": 0.1, "test": 0.0}`), `X_test` is a
zero-row array and `y_test` is also zero-length. Then:

1. `model.predict(X_test, verbose=0)` on a zero-row array returns a zero-row
   prediction array — this is fine for Keras.
2. `np.mean(y_pred == y_test)` on empty arrays returns `nan` (numpy mean of
   empty slice).
3. `precision_recall_fscore_support(y_test, y_pred, ...)` on empty arrays
   raises `ValueError: Found input variables with inconsistent numbers of samples`
   or returns all-zero metrics with a `UndefinedMetricWarning`.
4. `confusion_matrix(y_test, y_pred, ...)` on empty arrays returns a zero matrix.

The `nan` test accuracy is then written to `metrics.json` without any warning.

THE BUG / RISK:
Empty test set produces `nan` test accuracy in `metrics.json` silently. The
`precision_recall_fscore_support` call may raise or return zeros with a warning
that is not surfaced to the user.

EVIDENCE:
```python
X_test = dataset.X_test          # may be shape (0, T, F, 1)
y_test = np.asarray(dataset.y_test, dtype=np.int64)  # may be shape (0,)
y_pred_probs = model.predict(X_test, verbose=0)       # shape (0, n_classes)
y_pred = np.argmax(y_pred_probs, axis=1)              # shape (0,)
test_acc = float(np.mean(y_pred == y_test))           # nan
```

REPRODUCTION SCENARIO:
```python
dataset.X_test = np.zeros((0, 101, 40, 1), dtype=np.float32)
dataset.y_test = np.zeros((0,), dtype=np.int32)
node.process({"model_artifact": artifact, "dataset": dataset})
# metrics.json: {"test_accuracy": NaN, ...}
```

IMPACT:
Silent wrong result: `NaN` accuracy written to metrics.json. Downstream
experiment tracking logs `NaN` without error.

FIX DIRECTION:
```python
if len(X_test) == 0:
    log.warning("EvaluatorNode: test set is empty — skipping evaluation")
    return {"output": ModelArtifact(
        model_path=artifact.model_path,
        labels=labels,
        history=artifact.history,
        metrics={"error": "empty test set"},
    )}
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/evaluator/nodes.py
FUNCTION:    EvaluatorNode.process
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Evaluate the model on the held-out test set."

WHAT IT ACTUALLY DOES:
Computes `per_class` metrics using `labels[i]` for `i in range(n_classes)`.
`n_classes = len(labels)`. However, `y_pred_probs` has shape `(N, K)` where
`K` is the number of output neurons in the model. If `K != n_classes` (e.g.,
the model was trained on a different dataset than the one being evaluated),
`np.argmax(y_pred_probs, axis=1)` returns indices up to `K-1`, but
`precision_recall_fscore_support(..., labels=list(range(n_classes)))` uses
`n_classes` from the label list. This mismatch produces wrong metrics silently.

THE BUG / RISK:
Model output dimension mismatch with label count produces wrong per-class
metrics without any error or warning.

EVIDENCE:
```python
n_classes = len(labels)   # from artifact.labels or dataset.labels
y_pred_probs = model.predict(X_test, verbose=0)  # shape (N, K) — K may != n_classes
y_pred = np.argmax(y_pred_probs, axis=1)         # indices 0..K-1
prec, rec, f1, _ = precision_recall_fscore_support(
    y_test, y_pred,
    labels=list(range(n_classes)),   # uses n_classes, not K
    ...
)
```

REPRODUCTION SCENARIO:
Pass a model with 10 output classes but a dataset with 8 labels. `n_classes=8`,
`K=10`. `y_pred` may contain indices 8 or 9, which are not in `labels=range(8)`.
`precision_recall_fscore_support` treats them as unknown classes and returns
wrong metrics.

IMPACT:
Silent wrong result. Metrics appear valid but are computed on mismatched classes.

FIX DIRECTION:
```python
K = y_pred_probs.shape[1]
if K != n_classes:
    raise ValueError(
        f"EvaluatorNode: model output dimension {K} != n_classes {n_classes}. "
        "Ensure the model and dataset are compatible."
    )
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/evaluator/nodes.py
FUNCTION:    EvaluatorNode._load_model
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Load a model from the artifact. Supports Keras and PyTorch formats."

WHAT IT ACTUALLY DOES:
For PyTorch models, loads the state dict with `torch.load(model_path, map_location="cpu")`
and returns it. The caller then checks `is_pytorch_state_dict = isinstance(model, dict)`
and returns early with an error message in metrics. However, `torch.load` on a
TorchScript model (`.pt` file saved with `torch.jit.save`) returns a
`torch.jit.ScriptModule`, not a dict. The `isinstance(model, dict)` check is
False, so the code proceeds to call `model.predict(X_test, verbose=0)` on a
TorchScript module, which raises `AttributeError: 'RecursiveScriptModule' object
has no attribute 'predict'`.

THE BUG / RISK:
TorchScript models loaded via `torch.load` (not `torch.jit.load`) are not
detected as state dicts, and the subsequent `model.predict()` call crashes with
a confusing `AttributeError`.

EVIDENCE:
```python
state_dict = torch.load(model_path, map_location="cpu")
# If model_path is a TorchScript .pt file, state_dict is a ScriptModule
return state_dict

# In process():
is_pytorch_state_dict = isinstance(model, dict)  # False for ScriptModule
y_pred_probs = model.predict(X_test, verbose=0)  # AttributeError
```

REPRODUCTION SCENARIO:
Pass a TorchScript `.pt` model (saved with `torch.jit.save`). `torch.load`
returns a `ScriptModule`. `isinstance(model, dict)` is False. `model.predict()`
raises `AttributeError`.

IMPACT:
Crash with confusing error. No data loss.

FIX DIRECTION:
Try `torch.jit.load` first, then fall back to `torch.load`:
```python
try:
    model = torch.jit.load(model_path, map_location="cpu")
    model.eval()
    return model
except Exception:
    return torch.load(model_path, map_location="cpu")
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/evaluator/nodes.py
FUNCTION:    EvaluatorNode.teardown
CATEGORY:    Resource Leak
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Release model resources."

WHAT IT ACTUALLY DOES:
`teardown()` deletes `self._model` if it exists. However, `self._model` is only
set in `process()` as `self._model = model`. If `process()` raises before
reaching that line (e.g., during `_load_model`), `self._model` is never set,
and `teardown()` silently does nothing (the `hasattr` check prevents an error).
This is correct behavior. However, if `process()` raises AFTER setting
`self._model`, the model is held in memory until `teardown()` is called. If
`teardown()` is never called (e.g., the node is used outside the pipeline
lifecycle), the model is never released.

THE BUG / RISK:
Low risk in normal pipeline usage (teardown is called by the executor). Risk
exists when the node is used directly in tests or scripts without calling teardown.

EVIDENCE:
```python
def teardown(self) -> None:
    if hasattr(self, "_model"):
        del self._model
```

REPRODUCTION SCENARIO:
Use `EvaluatorNode` in a test without calling `teardown()`. Keras model stays
in memory for the test session duration.

IMPACT:
Memory not released in test/script usage. Low severity.

FIX DIRECTION:
Use a context manager or ensure teardown is called in tests.
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
| Resource Safety | UNSAFE |
| Test Hostile | PARTIAL |
| Top Risk | Empty test set produces NaN test_accuracy written to metrics.json without any warning or error |
