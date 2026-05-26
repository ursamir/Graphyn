# Functional Review — PluginPackage/Audio/feature_frontend/nodes.py

**Group:** 14 — Audio Plugins Batch 2
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/feature_frontend/nodes.py
FUNCTION:    FeatureFrontendNode.process
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Extracts features from each AudioSample; resamples if sample_rate differs.

WHAT IT ACTUALLY DOES:
`y = sample.data.astype(np.float32)` — if `sample.data` is `None`, this raises
`AttributeError: 'NoneType' object has no attribute 'astype'`. If `sample.data`
is an empty array (zero samples), librosa feature extractors will either return
an empty feature matrix or raise an error deep in their STFT implementation.

Neither case is guarded against. The error propagates up from `process()` with
no domain-level message identifying which sample caused the failure.

THE BUG / RISK:
A single None or empty-data sample in the batch crashes the entire `process()`
call, losing all features for all samples in the batch.

EVIDENCE:
```python
for sample in samples:
    y = sample.data.astype(np.float32)  # AttributeError if data is None
    sr = sample.sample_rate
    if sr != self.config.sample_rate:
        y = librosa.resample(y=y, orig_sr=sr, target_sr=self.config.sample_rate)
```

REPRODUCTION SCENARIO:
samples = [AudioSample(data=None, sample_rate=16000, ...)]
node.process(samples) → AttributeError: 'NoneType' object has no attribute 'astype'

IMPACT:
Entire batch fails on a single bad sample; no partial results.

FIX DIRECTION:
```python
if sample.data is None or len(sample.data) == 0:
    log.warning("FeatureFrontendNode: skipping sample with empty data: %s", sample.path)
    continue
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/feature_frontend/nodes.py
FUNCTION:    FeatureFrontendNode.process
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Resamples audio to config.sample_rate if the input sample rate differs.

WHAT IT ACTUALLY DOES:
`librosa.resample(y=y, orig_sr=sr, target_sr=self.config.sample_rate)` — if
`sr` is 0 (e.g., AudioSample constructed with sample_rate=0 or sample_rate=None
which becomes 0 after int coercion), librosa raises a `ZeroDivisionError` or
`ValueError` deep in its resampling code. `sample.sample_rate` is not validated
before use.

THE BUG / RISK:
A sample with sample_rate=0 or sample_rate=None crashes with an opaque error.

EVIDENCE:
```python
sr = sample.sample_rate
if sr != self.config.sample_rate:
    y = librosa.resample(y=y, orig_sr=sr, target_sr=self.config.sample_rate)
    # sr=0 → ZeroDivisionError inside librosa
```

REPRODUCTION SCENARIO:
sample = AudioSample(data=np.zeros(1000, dtype=np.float32), sample_rate=0, ...)
node.process([sample]) → ZeroDivisionError or ValueError inside librosa

IMPACT:
Crash with opaque error; entire batch fails.

FIX DIRECTION:
```python
if not sr or sr <= 0:
    raise ValueError(
        f"FeatureFrontendNode: invalid sample_rate={sr} for sample '{sample.path}'"
    )
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/feature_frontend/nodes.py
FUNCTION:    FeatureFrontendNode._normalize
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Normalize features to zero mean and unit variance.

WHAT IT ACTUALLY DOES:
`if std <= 1e-8: return x` — returns the un-normalized array silently when
the feature matrix is constant (e.g., all-zero mel spectrogram from a silent
audio clip). The caller in `process()` does not check whether normalization
was applied, and the metadata records `"normalized": self.config.normalize`
as `True` even when normalization was skipped.

THE BUG / RISK:
Silent metadata lie — `metadata["normalized"] = True` even when the feature
array was not normalized (because std ≤ 1e-8). Downstream models that expect
normalized inputs will receive un-normalized (constant) features without
any indication.

EVIDENCE:
```python
def _normalize(self, x: np.ndarray) -> np.ndarray:
    std = np.std(x)
    if std <= 1e-8:
        return x  # not normalized, but caller records normalized=True
    return (x - mean) / std
```

```python
# In process():
feature_array = FeatureArray(
    ...
    metadata={
        ...
        "normalized": self.config.normalize,  # always True if normalize=True
    },
)
```

REPRODUCTION SCENARIO:
Silent audio → all-zero mel spectrogram → std=0 → normalization skipped.
metadata["normalized"] = True (lie).

IMPACT:
Silent wrong metadata; downstream models receive un-normalized constant features
without warning.

FIX DIRECTION:
Return a flag from `_normalize` or add a metadata key:
```python
"normalized": self.config.normalize and (np.std(features) > 1e-8),
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/feature_frontend/nodes.py
FUNCTION:    FeatureFrontendNode._append_deltas
CATEGORY:    Contract Mismatch
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Stack delta and/or delta-delta onto the feature matrix (axis 0).
Docstring: "delta_delta=True only → appends delta2 (without delta1)"

WHAT IT ACTUALLY DOES:
When `delta=False` and `delta_delta=True`, the code computes:
```python
d2 = librosa.feature.delta(features, order=2)
```
`librosa.feature.delta(..., order=2)` computes the second-order delta of
`features` directly. However, the standard definition of delta-delta is the
delta of the delta (i.e., delta of d1, not delta-order-2 of the original).
When `delta=True` and `delta_delta=True`, the code computes delta-order-2 of
the original features, NOT the delta of d1. These are numerically different.

More importantly: when `delta_delta=True` but `delta=False`, the docstring
says "appends delta2 (without delta1)" — this is a non-standard configuration
that produces a feature matrix where the second-order derivative is present
but the first-order derivative is absent. Most ML models trained on
MFCC+delta+delta2 expect all three in order. This silent mis-ordering will
cause shape mismatches or wrong model inputs.

EVIDENCE:
```python
parts = [features]
if self.config.delta:
    d1 = librosa.feature.delta(features).astype(np.float32)
    parts.append(d1)
if self.config.delta_delta:
    d2 = librosa.feature.delta(features, order=2).astype(np.float32)
    parts.append(d2)
return np.concatenate(parts, axis=0)
```
When delta=True, delta_delta=True: output is [features, delta(features), delta2(features)]
Standard is: [features, delta(features), delta(delta(features))]
These differ numerically.

REPRODUCTION SCENARIO:
config: delta=True, delta_delta=True
→ d2 = delta(features, order=2) ≠ delta(delta(features))
→ model trained on standard delta-delta gets wrong inputs

IMPACT:
Silent wrong result — model receives non-standard delta-delta features;
accuracy degradation without any error.

FIX DIRECTION:
```python
if self.config.delta_delta:
    # Compute delta of delta (standard definition)
    d1 = librosa.feature.delta(features).astype(np.float32)
    d2 = librosa.feature.delta(d1).astype(np.float32)
    if self.config.delta:
        parts = [features, d1, d2]
    else:
        parts = [features, d2]
    return np.concatenate(parts, axis=0)
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/feature_frontend/nodes.py
FUNCTION:    FeatureFrontendNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Transpose from (F, T) → (T, F) for downstream compatibility.

WHAT IT ACTUALLY DOES:
`if features.ndim == 2: features = features.T` — this transpose is applied
AFTER `fixed_length` padding/truncation. However, `fixed_length` operates on
the ALREADY-TRANSPOSED shape `(T, F)`. The code checks `features.ndim == 2`
for the transpose, then checks `features.ndim == 2` again for fixed_length.
The fixed_length block correctly uses `T, F = features.shape` after the
transpose — this is correct.

However, for `feature_type == "raw"`, `_extract_raw` returns shape `(1, N)`
(1 channel, N samples). After transpose: `(N, 1)`. Then `fixed_length` pads/
truncates the time axis (N). This means for raw waveforms, `fixed_length`
truncates/pads the sample count, not the frame count — which is correct for
raw waveforms but the metadata records `"shape": list(features.shape)` AFTER
the transpose, so shape is `(fixed_length, 1)` which is correct.

The actual bug: for 1-D features (zcr, spectral_centroid, spectral_rolloff),
`_extract_zcr` returns shape `(1, T)`. After transpose: `(T, 1)`. The
`fixed_length` block then pads/truncates to `(fixed_length, 1)`. This is
correct. No bug here.

Re-examining: the `_normalize` call happens BEFORE the transpose:
```python
if self.config.normalize and feature_type != "raw":
    features = self._normalize(features)  # operates on (F, T)

if features.ndim == 2:
    features = features.T  # now (T, F)
```
`_normalize` computes global mean/std over the entire (F, T) matrix — this is
correct for global normalization. No bug.

No finding for this item — analysis confirmed correct.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/feature_frontend/nodes.py
FUNCTION:    FeatureFrontendNode.process
CATEGORY:    Type Safety
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validates feature_type via if/elif chain; raises ValueError for unknown types.

WHAT IT ACTUALLY DOES:
`feature_type = self.config.feature_type.lower()` — the comparison is done
on the lowercased value, but `FeatureArray.feature_type` is set to
`feature_type + delta_suffix` where `feature_type` is already lowercased.
The `Config.feature_type` default is `"log_mel"` (lowercase). If a user
passes `"Log_Mel"`, it is lowercased to `"log_mel"` and works correctly.
This is fine.

However, `self.config.feature_type` is a plain `str` with no Pydantic
validator — any string is accepted at config time. The ValueError is only
raised at `process()` time, not at `setup()` or config validation time.
This means a misconfigured node passes validation and only fails when
the pipeline is running.

EVIDENCE:
```python
class Config(NodeConfig):
    feature_type: str = "log_mel"  # no validator
```

REPRODUCTION SCENARIO:
Config(feature_type="mel_log")  # typo — accepted at config time
node.process(samples)  # ValueError raised mid-pipeline

IMPACT:
Late error detection — pipeline fails mid-run instead of at startup.

FIX DIRECTION:
Add a Pydantic validator:
```python
from pydantic import validator
VALID_FEATURE_TYPES = {"log_mel", "mfcc", "spectrogram", "chroma", "zcr",
                       "spectral_centroid", "spectral_rolloff", "raw"}
@validator("feature_type")
def check_feature_type(cls, v):
    if v.lower() not in VALID_FEATURE_TYPES:
        raise ValueError(f"feature_type must be one of {VALID_FEATURE_TYPES}")
    return v.lower()
```

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
| Top Risk | `_append_deltas` computes delta-delta as `librosa.feature.delta(features, order=2)` instead of `delta(delta(features))`, silently producing non-standard features that will degrade model accuracy without any error. |
