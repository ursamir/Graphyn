# Functional Review — PluginPackage/Audio/voice_converter/nodes.py

**Group:** 15 — Audio Plugins Batch 3
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/voice_converter/nodes.py
FUNCTION:    VoiceConverterNode._convert_speechbrain
CATEGORY:    Resource Leak
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Voice conversion using SpeechBrain; caches model in `self._vc_model`.

WHAT IT ACTUALLY DOES:
`converted = self._vc_model.convert_voice(wav_tensor, target_wav)` returns a
PyTorch tensor. The code then calls `converted.squeeze().numpy()`. If the
tensor is on GPU (CUDA), `.numpy()` raises `RuntimeError: Can't call numpy()
on Tensor that requires grad or is on GPU`. The code does not call
`.detach().cpu()` before `.numpy()`.

EVIDENCE:
```python
with torch.no_grad():
    if target_wav is not None:
        converted = self._vc_model.convert_voice(wav_tensor, target_wav)
    else:
        converted = self._vc_model.convert_voice(wav_tensor, wav_tensor)

y_out = converted.squeeze().numpy()  # RuntimeError if on GPU
```

REPRODUCTION SCENARIO:
Run on a CUDA-capable machine where SpeechBrain loads to GPU. `convert_voice`
returns a CUDA tensor. `.numpy()` raises RuntimeError.

IMPACT:
Crash on GPU systems. The node claims `requires_gpu=False` but will crash
when a GPU is present and SpeechBrain uses it automatically.

FIX DIRECTION:
```python
y_out = converted.squeeze().detach().cpu().numpy()
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/voice_converter/nodes.py
FUNCTION:    VoiceConverterNode._convert_speechbrain
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Cache the SpeechBrain voice conversion model in `self._vc_model`.

WHAT IT ACTUALLY DOES:
`if not hasattr(self, "_vc_model"): self._vc_model = VoiceConversion.from_hparams(...)`
— the model is loaded lazily on the first call. There is no `setup()` method
defined for this node, so the model is not pre-loaded during the setup phase.

This means:
1. First call to `process()` incurs model load latency.
2. If `VoiceConversion.from_hparams()` raises (network error, model not found),
   the exception propagates out of `process()` mid-execution, leaving
   `self._vc_model` unset. The next call retries the load.
3. No thread safety — concurrent calls may both enter the `if not hasattr`
   branch simultaneously and load the model twice.

EVIDENCE:
```python
if not hasattr(self, "_vc_model"):
    self._vc_model = VoiceConversion.from_hparams(
        source="speechbrain/voice-conversion-vctk-coqui-tts",
        savedir="pretrained_models/voice_conversion",
    )
```

REPRODUCTION SCENARIO:
Two threads call `process()` simultaneously on the same node instance. Both
enter the `if not hasattr` branch and both attempt to load the model.

IMPACT:
Race condition in concurrent use; repeated model load on failure; no setup-time
validation.

FIX DIRECTION:
Implement `setup()` to pre-load the model:
```python
def setup(self) -> None:
    backend = self._resolve_backend()
    if backend == "speechbrain":
        from speechbrain.inference.conversion import VoiceConversion
        self._vc_model = VoiceConversion.from_hparams(
            source="speechbrain/voice-conversion-vctk-coqui-tts",
            savedir="pretrained_models/voice_conversion",
        )
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/voice_converter/nodes.py
FUNCTION:    VoiceConverterNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Transform speaker identity or vocal style for each input AudioSample.

WHAT IT ACTUALLY DOES:
Does not validate that `samples` is non-empty or that individual samples have
non-zero data. A sample with `data = np.array([])` is passed to
`_convert_speechbrain` or `_convert_knnvc`. In `_convert_speechbrain`,
`torch.from_numpy(y).unsqueeze(0)` produces a `(1, 0)` tensor.
`self._vc_model.convert_voice(wav_tensor, ...)` will raise inside SpeechBrain
for zero-length input.

EVIDENCE:
```python
for sample in samples:
    new_sample = copy.deepcopy(sample)
    if backend == "speechbrain":
        new_sample = self._convert_speechbrain(new_sample)  # no zero-length check
```

REPRODUCTION SCENARIO:
Pass `AudioSample(data=np.array([]))` to process().

IMPACT:
Crash from SpeechBrain for zero-length audio.

FIX DIRECTION:
```python
for sample in samples:
    if sample.data is None or len(sample.data) == 0:
        log.warning("VoiceConverterNode: skipping zero-length sample %s", sample.path)
        output.append(sample)
        continue
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/voice_converter/nodes.py
FUNCTION:    VoiceConverterNode._convert_speechbrain
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Resample input to 16kHz for SpeechBrain, then process.

WHAT IT ACTUALLY DOES:
`y = sample.data.astype(np.float32)` — if `data` is stereo (ndim > 1), `y`
is 2D. `torch.from_numpy(y).unsqueeze(0)` produces `(1, N, 2)` for stereo
instead of `(1, N)`. SpeechBrain's `convert_voice` expects `(1, N)` — this
will raise a shape error.

Additionally, `target_wav` loaded from `self.config.target_speaker` via
`sf.read` may also be stereo. The same shape issue applies.

EVIDENCE:
```python
y = sample.data.astype(np.float32)  # may be (N, 2) for stereo
# ...
wav_tensor = torch.from_numpy(y).unsqueeze(0)  # (1, N, 2) — wrong
```

REPRODUCTION SCENARIO:
Pass a stereo AudioSample to speechbrain backend.

IMPACT:
Crash with shape mismatch from SpeechBrain.

FIX DIRECTION:
```python
y = sample.data.astype(np.float32)
if y.ndim > 1:
    y = y.mean(axis=1)
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/voice_converter/nodes.py
FUNCTION:    VoiceConverterNode._convert_knnvc
CATEGORY:    Contract Mismatch
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Voice conversion using kNN-VC.

WHAT IT ACTUALLY DOES:
`y_out = knnvc.convert(y, sr, target_path)` — the return type of `knnvc.convert`
is assumed to be array-like. `np.asarray(y_out, dtype=np.float32)` handles
most return types. However, if `knnvc.convert` returns a PyTorch tensor on GPU,
`np.asarray()` will raise `TypeError: can't convert cuda:0 device type tensor
to numpy`. The code does not call `.detach().cpu()` before conversion.

EVIDENCE:
```python
y_out = knnvc.convert(y, sr, target_path)
sample.data = np.asarray(y_out, dtype=np.float32)  # fails for CUDA tensor
```

REPRODUCTION SCENARIO:
knnvc returns a CUDA tensor. `np.asarray()` raises TypeError.

IMPACT:
Crash on GPU systems.

FIX DIRECTION:
```python
import torch
if isinstance(y_out, torch.Tensor):
    y_out = y_out.detach().cpu().numpy()
sample.data = np.asarray(y_out, dtype=np.float32)
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/voice_converter/nodes.py
FUNCTION:    VoiceConverterNode._resolve_backend
CATEGORY:    Silent Failure
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Resolve the backend to use: speechbrain, knnvc, or pitch_only fallback.

WHAT IT ACTUALLY DOES:
When neither speechbrain nor knnvc is available, falls back to `"pitch_only"`
with a warning. If `pitch_shift_semitones == 0.0`, `_convert_pitch_only`
returns the sample unchanged. The caller gets back the original audio with
`voice_converter` metadata claiming conversion was applied, but no actual
conversion occurred.

EVIDENCE:
```python
log.warning("VoiceConverterNode: no conversion backend available — "
            "applying pitch shift only. ...")
return "pitch_only"
# ...
def _convert_pitch_only(self, sample):
    if abs(self.config.pitch_shift_semitones) < 0.01:
        return sample  # no-op — original audio returned unchanged
```

IMPACT:
Silent no-op when no backend is available and pitch_shift_semitones=0.
Metadata claims conversion was applied but audio is unchanged.

FIX DIRECTION:
When `pitch_shift_semitones == 0` and backend is `pitch_only`, add a warning:
```python
if backend == "pitch_only" and abs(self.config.pitch_shift_semitones) < 0.01:
    log.warning("VoiceConverterNode: no backend and no pitch shift — "
                "returning audio unchanged")
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
| Top Risk | `.numpy()` on GPU tensor in `_convert_speechbrain` crashes on any CUDA system; lazy model loading has a race condition in concurrent use |
