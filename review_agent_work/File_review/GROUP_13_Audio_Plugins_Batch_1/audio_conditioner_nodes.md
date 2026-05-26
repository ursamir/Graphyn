# Functional Review — PluginPackage/Audio/audio_conditioner/nodes.py

**Group:** 13 — Audio Plugins Batch 1  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_conditioner/nodes.py
FUNCTION:    AudioConditionerNode._condition_one
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Condition a single AudioSample; return None if the sample should be skipped.

WHAT IT ACTUALLY DOES:
After `librosa.effects.trim()`, if the audio is entirely silence, `trim` returns
an empty array `y = np.array([])`. All subsequent operations then operate on a
zero-length array:
- `_apply_preemphasis`: `np.concatenate([[y[0]], ...])` raises `IndexError` because
  `y[0]` on an empty array fails.
- `_peak_normalize`: `np.max(np.abs(y))` returns `-inf` for empty array (numpy
  raises `ValueError: zero-size array`).
- `_rms_normalize`: `np.mean(y**2)` returns `nan` for empty array.
- `new_sample.data = y.astype(np.float32)` stores a zero-length array downstream.

EVIDENCE:
```python
# line ~196
if self.config.trim_silence:
    y, _ = librosa.effects.trim(y, top_db=self.config.trim_threshold_db)
# No check for len(y) == 0 after trim
```

REPRODUCTION SCENARIO:
Pass an AudioSample containing only silence (all zeros). `librosa.effects.trim`
returns `y = np.array([])`.

IMPACT:
Crash (`IndexError` or `ValueError`) or silent propagation of a zero-length
AudioSample downstream, causing failures in subsequent nodes.

FIX DIRECTION:
```python
if self.config.trim_silence:
    y, _ = librosa.effects.trim(y, top_db=self.config.trim_threshold_db)
    if len(y) == 0:
        return None  # entirely silent — skip
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_conditioner/nodes.py
FUNCTION:    AudioConditionerNode._apply_preemphasis
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Apply pre-emphasis filter: `y[n] = y[n] - coeff * y[n-1]`.

WHAT IT ACTUALLY DOES:
`np.concatenate([[y[0]], y[1:] - coeff * y[:-1]])` — when `y` has exactly 1
sample, `y[1:]` is empty and `y[:-1]` is empty, so the result is `[y[0]]`
(correct). However when `y` is empty (zero samples), `y[0]` raises `IndexError`.

EVIDENCE:
```python
def _apply_preemphasis(self, y: np.ndarray, coeff: float) -> np.ndarray:
    return np.concatenate([[y[0]], y[1:] - coeff * y[:-1]])
```

REPRODUCTION SCENARIO:
Called after `trim_silence` produces an empty array (see finding above), or
directly with a zero-length array.

IMPACT:
`IndexError: index 0 is out of bounds for axis 0 with size 0`.

FIX DIRECTION:
```python
if len(y) == 0:
    return y
return np.concatenate([[y[0]], y[1:] - coeff * y[:-1]])
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_conditioner/nodes.py
FUNCTION:    AudioConditionerNode._lufs_normalize
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Normalize audio to a target LUFS level using ITU-R BS.1770-4.

WHAT IT ACTUALLY DOES:
When `meter.integrated_loudness()` raises an exception (e.g. audio too short
for the BS.1770 gating window, which requires ~400ms), the function returns `y`
unchanged with no warning or metadata flag. The caller has no way to know
normalization was skipped.

EVIDENCE:
```python
try:
    loudness = meter.integrated_loudness(y_2d)
except Exception:
    return y  # can't measure — return unchanged
```

REPRODUCTION SCENARIO:
Pass a 100ms AudioSample with `normalize_method="lufs"`. pyloudnorm raises
because the gating window requires at least ~400ms. The sample is returned
at its original loudness, but `metadata["conditioning"]["normalize_method"]`
still says `"lufs"`, implying normalization was applied.

IMPACT:
Silent wrong result — metadata claims LUFS normalization was applied but it
was not. Downstream loudness-sensitive nodes receive incorrectly normalized audio.

FIX DIRECTION:
```python
except Exception as e:
    log.warning("AudioConditionerNode: LUFS normalization failed (%s) — returning unchanged", e)
    return y
```
Also set a metadata flag `"lufs_normalization_skipped": True` in `_condition_one`.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_conditioner/nodes.py
FUNCTION:    AudioConditionerNode._apply_compression
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Apply dynamic range compression above threshold_db with the given ratio.

WHAT IT ACTUALLY DOES:
Uses `np.maximum(abs_y, 1e-9)` in the denominator to avoid division by zero.
When `abs_y` is exactly 0 (silence), the gain formula computes:
`threshold_amp * (0 / threshold_amp)^(1/ratio) / 1e-9`
= `threshold_amp * 0 / 1e-9` = 0.
This is mathematically correct (gain=0 for zero-amplitude samples), but the
`np.where` condition `abs_y > threshold_amp` is False for silence, so the
`else` branch returns `gain=1.0` — correct. The `1e-9` guard is only reached
when `abs_y > threshold_amp`, so it is never triggered for silence. This is
actually safe.

However, the function does not validate `ratio > 0`. If `ratio=0`, the
exponent `1.0/ratio` raises `ZeroDivisionError`.

EVIDENCE:
```python
gain = np.where(
    abs_y > threshold_amp,
    threshold_amp * (abs_y / threshold_amp) ** (1.0 / ratio) / np.maximum(abs_y, 1e-9),
    1.0,
)
```
`ratio` comes from `self.config.compress_ratio` with default 4.0 but no
validator enforcing `> 0`.

REPRODUCTION SCENARIO:
Set `compress=True, compress_ratio=0`.

IMPACT:
`ZeroDivisionError` in `process()` with no clear error message.

FIX DIRECTION:
Add Pydantic validator:
```python
@validator("compress_ratio")
def ratio_positive(cls, v):
    if v <= 0: raise ValueError("compress_ratio must be > 0")
    return v
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_conditioner/nodes.py
FUNCTION:    AudioConditionerNode._condition_one
CATEGORY:    Type Safety
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Condition a single AudioSample and return a conditioned copy.

WHAT IT ACTUALLY DOES:
`copy.deepcopy(sample)` is called on every sample. For large audio arrays
(e.g. 10 minutes at 44.1kHz = ~26M float32 samples = ~100MB), this doubles
peak memory usage per sample. In batch processing with `batch_size > 0`, all
samples in a batch are deep-copied simultaneously, multiplying memory usage.

EVIDENCE:
```python
new_sample = copy.deepcopy(sample)  # line ~175
```

REPRODUCTION SCENARIO:
Process a batch of 10 × 10-minute audio files. Each deepcopy allocates ~100MB;
peak memory = 2GB just for copies.

IMPACT:
OOM in production with large audio files; no memory guard or warning.

FIX DIRECTION:
Copy only the data array: `new_sample.data = sample.data.copy()` and copy
metadata shallowly, rather than deep-copying the entire object.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_conditioner/nodes.py
FUNCTION:    AudioConditionerNode.process
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Process a list of AudioSample objects.

WHAT IT ACTUALLY DOES:
No None-guard on `samples`. If `samples` is `None`, `for sample in samples`
raises `TypeError: 'NoneType' object is not iterable`.

EVIDENCE:
```python
def process(self, samples: list[AudioSample]) -> list[AudioSample]:
    output: list[AudioSample] = []
    batch_size = self.config.batch_size
    if batch_size <= 0:
        for sample in samples:   # no None check
```

REPRODUCTION SCENARIO:
Upstream node returns `None` from its output port.

IMPACT:
Crash with opaque TypeError.

FIX DIRECTION:
```python
if not samples:
    return []
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
| Top Risk | Silence-trimmed empty array propagates through the conditioning pipeline causing IndexError or zero-length AudioSample downstream |
