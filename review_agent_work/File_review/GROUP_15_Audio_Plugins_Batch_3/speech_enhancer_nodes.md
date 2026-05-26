# Functional Review — PluginPackage/Audio/speech_enhancer/nodes.py

**Group:** 15 — Audio Plugins Batch 3
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/speech_enhancer/nodes.py
FUNCTION:    SpeechEnhancerNode._denoise_deepfilter
CATEGORY:    Resource Leak
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Denoise using DeepFilterNet (df package). Uses cached model from setup().

WHAT IT ACTUALLY DOES:
`enhanced = enhance(model, df_state, audio_tensor)` — the `enhance` function
from the `df` package returns a PyTorch tensor. The code then calls
`enhanced.squeeze(0).numpy()`. If the tensor is on GPU (CUDA), `.numpy()`
raises `RuntimeError: Can't call numpy() on Tensor that requires grad or is
on GPU`. The code does not call `.detach().cpu()` before `.numpy()`.

EVIDENCE:
```python
enhanced = enhance(model, df_state, audio_tensor)
y_out = enhanced.squeeze(0).numpy()  # RuntimeError if on GPU
```

REPRODUCTION SCENARIO:
Run on a CUDA-capable machine where DeepFilterNet loads to GPU. `enhance()`
returns a CUDA tensor. `.numpy()` raises RuntimeError.

IMPACT:
Crash on GPU systems. The node claims `requires_gpu=False` but will crash
when a GPU is present and DeepFilterNet uses it automatically.

FIX DIRECTION:
```python
y_out = enhanced.squeeze(0).detach().cpu().numpy()
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/speech_enhancer/nodes.py
FUNCTION:    SpeechEnhancerNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Apply configured enhancement operations (denoise, dereverb, vocal_isolation,
telephony_mode) to each input AudioSample.

WHAT IT ACTUALLY DOES:
Does not validate that `samples` is non-empty or that individual samples have
non-zero data. A sample with `data = np.array([])` is passed to the enhancement
functions:
- `_denoise_spectral`: `nr.reduce_noise(y=y, sr=sr, ...)` — noisereduce may
  raise or return an empty array for zero-length input.
- `_denoise_deepfilter`: `torch.from_numpy(y_in).unsqueeze(0)` produces a
  `(1, 0)` tensor; `enhance()` may raise inside DeepFilterNet.
- `_telephony_bandpass`: `sosfilt(sos, y)` on empty array returns empty array
  (safe).
- `_vocal_isolation`: `librosa.effects.hpss(y)` on empty array raises
  `librosa.util.exceptions.ParameterError`.

EVIDENCE:
```python
for sample in samples:
    new_sample = copy.deepcopy(sample)
    y = new_sample.data.astype(np.float32)  # may be empty
    if self.config.denoise:
        y = self._denoise_spectral(y, sr)  # may raise for empty y
```

REPRODUCTION SCENARIO:
Pass `AudioSample(data=np.array([]))` with `vocal_isolation=True`.

IMPACT:
Crash from librosa for zero-length audio with vocal_isolation enabled.

FIX DIRECTION:
```python
for sample in samples:
    if sample.data is None or len(sample.data) == 0:
        log.warning("SpeechEnhancerNode: skipping zero-length sample %s", sample.path)
        output.append(sample)
        continue
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/speech_enhancer/nodes.py
FUNCTION:    SpeechEnhancerNode._telephony_bandpass
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Apply 300 Hz–3400 Hz bandpass filter (ITU-T G.712 telephony band).

WHAT IT ACTUALLY DOES:
`nyq = sr / 2.0; low = 300.0 / nyq; high = min(3400.0 / nyq, 0.999)`.
When `sr <= 600` Hz (e.g. a very low sample rate), `low = 300.0 / (sr/2)` ≥ 1.0.
`butter(4, [low, high], btype="band")` raises `ValueError: Digital filter
critical frequencies must be 0 < Wn < 1` when `low >= 1.0`.

EVIDENCE:
```python
nyq = sr / 2.0
low = 300.0 / nyq  # >= 1.0 when sr <= 600
high = min(3400.0 / nyq, 0.999)
sos = butter(4, [low, high], btype="band", output="sos")  # ValueError
```

REPRODUCTION SCENARIO:
Pass an AudioSample with `sample_rate=400` and `telephony_mode=True`.

IMPACT:
Crash with ValueError for very low sample rates.

FIX DIRECTION:
```python
if low >= 1.0 or low >= high:
    log.warning("SpeechEnhancerNode: sample rate %d Hz too low for telephony "
                "bandpass (300-3400 Hz) — skipping filter", sr)
    return y
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/speech_enhancer/nodes.py
FUNCTION:    SpeechEnhancerNode._dereverb_spectral
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Docstring says "Simplified dereverberation via Wiener filter smoothing" and
explicitly notes it is "not a full WPE dereverberation algorithm."

WHAT IT ACTUALLY DOES:
Applies `scipy.signal.wiener(y, mysize=5)` — a 5-sample Wiener filter. This
is a noise-smoothing filter, not a dereverberation algorithm. The docstring
correctly documents this limitation.

THE BUG / RISK:
The `dereverb` config option is documented as "apply dereverberation" but the
implementation is a noise smoother. Users enabling `dereverb=True` will get
minimal dereverberation effect. This is a contract mismatch between the
high-level config description and the actual implementation, though the
function-level docstring is honest.

EVIDENCE:
Config docstring: "dereverb (bool): apply dereverberation (default False)"
Implementation: `wiener(y, mysize=5)` — 5-sample smoothing filter.

IMPACT:
User expectation mismatch — `dereverb=True` provides negligible dereverberation.
No crash, no data loss.

FIX DIRECTION:
Update the Config docstring for `dereverb` to note the limitation:
"spectral backend: applies a 5-sample Wiener smoothing filter (not full WPE)."

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/speech_enhancer/nodes.py
FUNCTION:    SpeechEnhancerNode.process (stereo handling)
CATEGORY:    Silent Failure
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Enhance audio samples.

WHAT IT ACTUALLY DOES:
`y = new_sample.data.astype(np.float32)` — if `data` is stereo (ndim > 1),
`y` is 2D. `_denoise_spectral` calls `nr.reduce_noise(y=y, sr=sr)` — noisereduce
accepts 2D arrays and processes each channel. `_denoise_deepfilter` calls
`torch.from_numpy(y_in).unsqueeze(0)` producing `(1, channels, N)` — wrong
shape for DeepFilterNet which expects `(1, N)`. `_vocal_isolation` calls
`librosa.effects.hpss(y)` which requires 1D input and raises for 2D.

EVIDENCE:
```python
y = new_sample.data.astype(np.float32)  # may be 2D
# passed to _vocal_isolation → librosa.effects.hpss(y) → raises for 2D
```

IMPACT:
Crash for stereo audio with vocal_isolation or deepfilter backend.

FIX DIRECTION:
```python
y = new_sample.data.astype(np.float32)
if y.ndim > 1:
    y = y.mean(axis=1)  # mix to mono for processing
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | UNSAFE |
| Test Hostile | NO |
| Top Risk | `.numpy()` on GPU tensor in `_denoise_deepfilter` crashes on any CUDA system |
