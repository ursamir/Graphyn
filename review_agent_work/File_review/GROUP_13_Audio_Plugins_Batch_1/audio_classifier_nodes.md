# Functional Review — PluginPackage/Audio/audio_classifier/nodes.py

**Group:** 13 — Audio Plugins Batch 1  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_classifier/nodes.py
FUNCTION:    AudioClassifierNode.process
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Classify each item in the input list and return a list of PredictionResult.

WHAT IT ACTUALLY DOES:
Iterates over `inputs` (the raw argument). If `inputs` is `None` or not iterable
(e.g. the port delivers a single AudioSample instead of a list), the `for item in inputs`
loop raises `TypeError: 'NoneType' object is not iterable` or `TypeError: argument of
type 'AudioSample' is not iterable` with no guard.

THE BUG / RISK:
No None-guard or type-check before iterating. A None input crashes with an unhandled
TypeError rather than a clean, descriptive error.

EVIDENCE:
```python
# line ~107
def process(self, inputs: list) -> list[PredictionResult]:
    ...
    for item in inputs:   # no None check
```

REPRODUCTION SCENARIO:
Pass `inputs=None` (e.g. upstream node returns None from its port).

IMPACT:
Crash with opaque TypeError; no indication of which node or port failed.

FIX DIRECTION:
```python
if not inputs:
    return []
```
Add at the top of `process()` after the `_resolved_backend` guard.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_classifier/nodes.py
FUNCTION:    AudioClassifierNode.process
CATEGORY:    Silent Failure
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return classification results for every input item.

WHAT IT ACTUALLY DOES:
Unknown input types are silently skipped with a `log.warning` and `continue`.
The caller receives a shorter list than the input list with no indication of
how many items were dropped.

EVIDENCE:
```python
# lines ~120-122
else:
    log.warning("AudioClassifierNode: unknown input type %s — skipping", type(item))
    continue
```

REPRODUCTION SCENARIO:
Pass a list containing a `str` or `dict` (wrong type). The result list is shorter
than the input list; the caller has no way to detect the mismatch.

IMPACT:
Silent data loss — downstream nodes receive fewer results than expected, potentially
causing index mismatches or incorrect training labels.

FIX DIRECTION:
Raise `TypeError` instead of silently skipping, or return a sentinel
`PredictionResult` with an error flag so the caller can detect the failure.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_classifier/nodes.py
FUNCTION:    AudioClassifierNode._classify_audio
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Extract log-mel features and classify an AudioSample.

WHAT IT ACTUALLY DOES:
Calls `librosa.power_to_db(mel, ref=np.max)`. When `mel` is all-zeros (silent audio),
`np.max(mel)` is 0.0, causing `librosa.power_to_db` to compute `10*log10(0/0)` which
produces `-inf` or `nan` values in `features`. These are then fed to the TFLite/PyTorch
model, producing garbage probabilities silently.

EVIDENCE:
```python
# lines ~155-156
mel = librosa.feature.melspectrogram(y=y, sr=sr, n_fft=512, hop_length=160, n_mels=40)
features = librosa.power_to_db(mel, ref=np.max).astype(np.float32)
```

REPRODUCTION SCENARIO:
Pass an AudioSample with `data = np.zeros(16000)` (one second of silence).

IMPACT:
Silent wrong result — model receives NaN/inf features and produces meaningless
probabilities without any error.

FIX DIRECTION:
```python
ref_val = max(np.max(mel), 1e-10)
features = librosa.power_to_db(mel, ref=ref_val).astype(np.float32)
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_classifier/nodes.py
FUNCTION:    AudioClassifierNode._tflite_classify
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Load the TFLite model once and reuse it across calls.

WHAT IT ACTUALLY DOES:
`self._model_obj` is shared across all calls. The TFLite `Interpreter` is NOT
thread-safe — concurrent calls to `set_tensor` / `invoke` / `get_tensor` on the
same interpreter instance will corrupt results or crash.

EVIDENCE:
```python
# lines ~228-229
self._model_obj.set_tensor(inp_detail["index"], inp)
self._model_obj.invoke()
```
`self._model_obj` is a single shared `tflite.Interpreter` instance.

REPRODUCTION SCENARIO:
Two pipeline waves call `process()` concurrently on the same node instance.

IMPACT:
Data corruption or crash in concurrent execution; wrong classification results
returned silently.

FIX DIRECTION:
Create a new `Interpreter` per call, or use a threading.Lock around
`set_tensor` / `invoke` / `get_tensor`.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_classifier/nodes.py
FUNCTION:    AudioClassifierNode._tflite_classify
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Reshape features to match the model's expected input shape.

WHAT IT ACTUALLY DOES:
Adds a batch dimension and a channel dimension unconditionally:
`features[np.newaxis, ..., np.newaxis]`. If the model expects a flat 1-D input
or a 2-D input without a channel axis, this produces a shape mismatch that raises
a cryptic TFLite error rather than a clear message.

EVIDENCE:
```python
inp = features[np.newaxis, ..., np.newaxis].astype(inp_detail["dtype"])
```

REPRODUCTION SCENARIO:
Use a TFLite model that expects shape `[1, 40*T]` (flat) instead of `[1, 40, T, 1]`.

IMPACT:
Crash with opaque TFLite shape error; no guidance on what shape was expected.

FIX DIRECTION:
Compare `features.shape` against `inp_detail["shape"]` and reshape explicitly,
raising a clear `ValueError` if incompatible.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_classifier/nodes.py
FUNCTION:    AudioClassifierNode._yamnet_classify
CATEGORY:    Resource Leak
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Load YAMNet once and reuse it.

WHAT IT ACTUALLY DOES:
`self._model_obj` is loaded lazily inside `_yamnet_classify`. If `setup()` is
called but `process()` is never called, no model is loaded (fine). However, if
`process()` raises after model load, the TF session/graph is never explicitly
released. More critically, `self._model_obj` is a TF Hub module held on the
instance — if the node is garbage-collected without explicit cleanup, TF resources
may not be released promptly.

EVIDENCE:
No `teardown()` / `__del__` method defined. `self._model_obj` holds a TF Hub
SavedModel.

REPRODUCTION SCENARIO:
Load YAMNet in a long-running server; repeatedly create/destroy node instances.

IMPACT:
Gradual GPU/CPU memory accumulation; eventual OOM in long-running deployments.

FIX DIRECTION:
Implement `teardown()` to set `self._model_obj = None` and call
`tf.keras.backend.clear_session()` if TF is loaded.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_classifier/nodes.py
FUNCTION:    AudioClassifierNode._load_yamnet_labels
CATEGORY:    Error Handling
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Load YAMNet class names from disk cache, network, or fallback.

WHAT IT ACTUALLY DOES:
The disk-cache validation checks `len(classes) == 521` but the CSV parsing
uses `csv.DictReader` which requires a `display_name` column. If the cached
file is corrupted (missing column header), `row["display_name"]` raises
`KeyError` which is caught by the bare `except Exception: pass` block,
silently falling through to the network fetch. This is acceptable behavior
but the silent swallow of `KeyError` vs `OSError` is indistinguishable.

More critically: if the network fetch succeeds but returns a CSV with fewer
than 521 rows (e.g. partial download), the function returns a short list.
`process()` then uses `labels[top_indices[0]]` without bounds-checking,
which can raise `IndexError`.

EVIDENCE:
```python
# line ~175
predicted_label = labels[top_indices[0]] if labels else f"class_{top_indices[0]}"
```
The guard `if labels` is True even for a 10-element list; `top_indices[0]`
can be 520 (YAMNet class 520), causing `IndexError`.

REPRODUCTION SCENARIO:
Network returns a truncated CSV (e.g. 100 classes). `top_indices[0]` = 300.
`labels[300]` → `IndexError`.

IMPACT:
Crash during inference when network delivers a partial label file.

FIX DIRECTION:
```python
predicted_label = labels[top_indices[0]] if top_indices[0] < len(labels) else f"class_{top_indices[0]}"
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_classifier/nodes.py
FUNCTION:    AudioClassifierNode.setup
CATEGORY:    Testability
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Initialize the node without loading any model.

WHAT IT ACTUALLY DOES:
`setup()` does not validate `config.top_k > 0`, `config.sample_rate > 0`, or
that `config.backend` is one of the allowed values. Invalid configs are only
discovered at `process()` time, deep inside backend-specific code.

EVIDENCE:
`Config` class has no `@validator` or `model_validator` for these fields.

REPRODUCTION SCENARIO:
Set `top_k=0` — `process()` calls `np.argsort(probs)[::-1][:0]` returning an
empty array, then `top_indices[0]` raises `IndexError`.

IMPACT:
Crash at inference time with a confusing traceback rather than a clear config
validation error at setup time.

FIX DIRECTION:
Add Pydantic validators:
```python
@validator("top_k")
def top_k_positive(cls, v):
    if v < 1: raise ValueError("top_k must be >= 1")
    return v
```

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
| Test Hostile | PARTIAL |
| Top Risk | TFLite Interpreter shared across concurrent calls causes data corruption or crash |
