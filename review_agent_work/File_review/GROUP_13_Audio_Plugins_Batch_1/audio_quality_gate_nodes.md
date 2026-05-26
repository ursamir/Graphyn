# Functional Review — PluginPackage/Audio/audio_quality_gate/nodes.py

**Group:** 13 — Audio Plugins Batch 1  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_quality_gate/nodes.py
FUNCTION:    AudioQualityGateNode._check_duration
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Reject samples outside the configured duration range.

WHAT IT ACTUALLY DOES:
`duration = len(sample.data) / sample.sample_rate` — if `sample.sample_rate`
is 0 (invalid), this raises `ZeroDivisionError`. The exception propagates
uncaught through `_check_sample` → `process`, crashing the entire batch.

EVIDENCE:
```python
def _check_duration(self, sample: AudioSample) -> str | None:
    duration = len(sample.data) / sample.sample_rate
```
No guard for `sample.sample_rate == 0`.

REPRODUCTION SCENARIO:
Pass an AudioSample with `sample_rate=0` (e.g. from a failed ingest node).

IMPACT:
`ZeroDivisionError` crash; entire batch fails.

FIX DIRECTION:
```python
if not sample.sample_rate or sample.sample_rate <= 0:
    return "invalid_sample_rate (sample_rate=0)"
duration = len(sample.data) / sample.sample_rate
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_quality_gate/nodes.py
FUNCTION:    AudioQualityGateNode._check_duration
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Reject samples outside the configured duration range.

WHAT IT ACTUALLY DOES:
`len(sample.data)` — if `sample.data` is `None`, this raises
`TypeError: object of type 'NoneType' has no len()`. The exception propagates
uncaught.

EVIDENCE:
```python
duration = len(sample.data) / sample.sample_rate
```
No guard for `sample.data is None`.

REPRODUCTION SCENARIO:
Pass an AudioSample with `data=None` (e.g. metadata-only sample from ingest).

IMPACT:
`TypeError` crash; entire batch fails.

FIX DIRECTION:
```python
if sample.data is None:
    return "no_data (data is None)"
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_quality_gate/nodes.py
FUNCTION:    AudioQualityGateNode._check_snr
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Estimate SNR using the 5th-percentile amplitude as the noise floor proxy.

WHAT IT ACTUALLY DOES:
For a silence-only audio sample (all zeros), `np.percentile(abs_data, 5)` = 0.0,
`noise_power = 0.0 < 1e-10`, so the function returns `None` (no rejection).
This is documented behavior ("essentially silent noise floor — can't estimate SNR").

However, for a sample with a very low but non-zero noise floor (e.g. quantization
noise at -96dBFS), `noise_power` may be above `1e-10` but the SNR estimate will
be extremely high (e.g. 80dB), passing the check even for very noisy audio.
The 5th-percentile proxy is a rough heuristic that can produce wildly inaccurate
SNR estimates for audio with non-stationary noise (e.g. music with quiet passages).

More concretely: for a sample where the signal is a single loud click followed
by silence, the 5th percentile of `abs_data` is near 0 (silence dominates),
giving a very high SNR estimate — the sample passes even though it's mostly
silence with a click.

EVIDENCE:
```python
abs_data = np.abs(sample.data)
noise_floor = float(np.percentile(abs_data, 5))
signal_power = float(np.mean(sample.data ** 2))
noise_power = noise_floor ** 2
```

REPRODUCTION SCENARIO:
Audio = 0.99s silence + 0.01s loud click. 5th percentile ≈ 0 → `noise_power < 1e-10`
→ returns None (no rejection). Sample passes SNR check despite being 99% silence.

IMPACT:
Silent wrong result — low-quality samples pass the SNR gate.

FIX DIRECTION:
Document the limitation clearly in the docstring. Consider using a proper
noise estimation algorithm (e.g. minimum statistics or NIST STNR) for
production use.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_quality_gate/nodes.py
FUNCTION:    AudioQualityGateNode._check_bandwidth
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Reject samples with insufficient spectral bandwidth.

WHAT IT ACTUALLY DOES:
`librosa.feature.spectral_rolloff(y=sample.data, sr=sample.sample_rate, roll_percent=0.85)`
— if `sample.data` is empty (zero samples), librosa raises
`ParameterError: Audio buffer is not finite everywhere` or returns an empty
array. `np.mean([])` returns `nan`, and `nan < self.config.min_bandwidth_hz`
is `False` — so an empty audio sample passes the bandwidth check silently.

EVIDENCE:
```python
rolloff = librosa.feature.spectral_rolloff(
    y=sample.data, sr=sample.sample_rate, roll_percent=0.85
)
mean_rolloff = float(np.mean(rolloff))
if mean_rolloff < self.config.min_bandwidth_hz:
    return f"narrow_bandwidth ..."
```
`np.mean([])` = `nan`; `nan < 1000.0` = `False` → no rejection.

REPRODUCTION SCENARIO:
Pass an AudioSample with `data=np.array([])`.

IMPACT:
Silent wrong result — empty audio passes the bandwidth check.

FIX DIRECTION:
```python
if len(sample.data) == 0:
    return "empty_audio (zero samples)"
```
Add this guard at the start of `_check_bandwidth` (and ideally at the start
of `_check_sample` to short-circuit all checks).

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_quality_gate/nodes.py
FUNCTION:    AudioQualityGateNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Route each sample to output or rejected based on quality checks.

WHAT IT ACTUALLY DOES:
`inputs.get("input") or []` — if `inputs` is `None` or a list (SISO calling
convention), `inputs.get(...)` raises `AttributeError`.

EVIDENCE:
```python
def process(self, inputs: dict) -> dict:
    samples = inputs.get("input") or []
```

REPRODUCTION SCENARIO:
NodeExecutor passes a list instead of a dict.

IMPACT:
`AttributeError` crash.

FIX DIRECTION:
```python
if isinstance(inputs, list):
    samples = inputs
elif isinstance(inputs, dict):
    samples = inputs.get("input") or []
else:
    samples = []
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_quality_gate/nodes.py
FUNCTION:    AudioQualityGateNode._compute_quality_metadata
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Compute quality scores for samples.

WHAT IT ACTUALLY DOES:
`len(sample.data) / sample.sample_rate` — same ZeroDivisionError risk as
`_check_duration` if `sample.sample_rate == 0`. This function is called for
ALL samples (both passed and rejected), so even if `_check_duration` catches
the invalid sample rate and adds a rejection reason, `_compute_quality_metadata`
is still called and will crash.

EVIDENCE:
```python
def _compute_quality_metadata(self, sample: AudioSample) -> dict:
    duration = len(sample.data) / sample.sample_rate
```
Called unconditionally in `process()`:
```python
quality_scores = self._compute_quality_metadata(sample)
```

REPRODUCTION SCENARIO:
Pass an AudioSample with `sample_rate=0`. `_check_duration` adds a rejection
reason, but `_compute_quality_metadata` is called next and crashes.

IMPACT:
`ZeroDivisionError` crash even when the sample was already identified as invalid.

FIX DIRECTION:
```python
duration = len(sample.data) / sample.sample_rate if sample.sample_rate else 0
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_quality_gate/nodes.py
FUNCTION:    AudioQualityGateNode._check_lufs
CATEGORY:    Silent Failure
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Reject samples outside the configured LUFS loudness range.

WHAT IT ACTUALLY DOES:
When `meter.integrated_loudness()` raises (e.g. audio too short for BS.1770
gating), the function returns `None` (no rejection). This is documented
behavior. However, the `except Exception: return None` swallows all exceptions
including programming errors (e.g. wrong array shape), making debugging harder.

EVIDENCE:
```python
try:
    loudness = meter.integrated_loudness(sample.data)
except Exception:
    return None
```

REPRODUCTION SCENARIO:
`sample.data` has wrong shape (e.g. 3D array). pyloudnorm raises `ValueError`.
Silently returns None — LUFS check is skipped.

IMPACT:
Low: LUFS check is opt-in (`check_lufs=False` by default). But when enabled,
programming errors are silently swallowed.

FIX DIRECTION:
Narrow the exception:
```python
except (ValueError, RuntimeError):
    return None  # audio too short or invalid for BS.1770 gating
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
| Top Risk | ZeroDivisionError on sample_rate=0 crashes the entire batch in both _check_duration and _compute_quality_metadata |
