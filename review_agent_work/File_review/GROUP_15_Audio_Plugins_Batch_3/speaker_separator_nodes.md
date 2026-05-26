# Functional Review — PluginPackage/Audio/speaker_separator/nodes.py

**Group:** 15 — Audio Plugins Batch 3
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/speaker_separator/nodes.py
FUNCTION:    SpeakerSeparatorNode.setup
CATEGORY:    Silent Failure
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Pre-load models once to avoid reloading on every process() call.

WHAT IT ACTUALLY DOES:
In the `pyannote` branch, if `PyannotePipeline.from_pretrained()` raises any
exception *other than* `ImportError` (e.g. network error, invalid auth token,
model not found on HuggingFace Hub), the exception propagates out of `setup()`
correctly. However, the `except ImportError: pass` block silently swallows
`ImportError` even though `_resolve_backend()` already verified the import
succeeds. This means if the import somehow fails at model-load time (e.g. a
lazy import inside pyannote), `self._pyannote_pipeline` remains `None` and
`setup()` completes without error.

Then in `_separate_pyannote()`, the fallback path
`if getattr(self, "_pyannote_pipeline", None) is not None` is False, so it
re-runs `PyannotePipeline.from_pretrained()` on every `process()` call —
defeating the caching purpose and potentially causing repeated network calls.

EVIDENCE:
```python
# setup(), lines ~100-107
try:
    from pyannote.audio import Pipeline as PyannotePipeline
    self._pyannote_pipeline = PyannotePipeline.from_pretrained(...)
    log.info(...)
except ImportError:
    pass  # swallows ImportError silently; _pyannote_pipeline stays None
```

REPRODUCTION SCENARIO:
If pyannote is installed but `from_pretrained` triggers a lazy import that
raises ImportError, setup() completes silently with `_pyannote_pipeline=None`,
and every process() call re-downloads the model.

IMPACT:
Silent performance regression — model reloaded on every call. No error surfaced
to the caller.

FIX DIRECTION:
Remove the `except ImportError: pass` blocks in `setup()`. The import check
was already done in `_resolve_backend()`. Any exception from `from_pretrained`
should propagate:
```python
self._pyannote_pipeline = PyannotePipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    use_auth_token=token or None,
)
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/speaker_separator/nodes.py
FUNCTION:    SpeakerSeparatorNode._separate_speechbrain
CATEGORY:    Resource Leak
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Source separation using SpeechBrain SepFormer; uses cached model from setup().

WHAT IT ACTUALLY DOES:
`est_sources = model.separate_batch(audio_tensor)` returns a tensor of shape
`(1, N, num_sources)`. The code then does:
```python
src = est_sources[0, :, i].numpy()
```
This calls `.numpy()` on a PyTorch tensor. If the tensor is on GPU (CUDA),
`.numpy()` raises a `RuntimeError: Can't call numpy() on Tensor that requires
grad or is on GPU`. The code does not call `.detach().cpu()` before `.numpy()`.

EVIDENCE:
```python
est_sources = model.separate_batch(audio_tensor)  # may be on GPU
# ...
src = est_sources[0, :, i].numpy()  # RuntimeError if on GPU
```

REPRODUCTION SCENARIO:
Run with a CUDA-capable GPU where SepFormer loads to GPU. `separate_batch`
returns a CUDA tensor. `.numpy()` raises RuntimeError.

IMPACT:
Crash on GPU systems. The node claims `requires_gpu=False` but will crash
when a GPU is present and SpeechBrain uses it automatically.

FIX DIRECTION:
```python
src = est_sources[0, :, i].detach().cpu().numpy()
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/speaker_separator/nodes.py
FUNCTION:    SpeakerSeparatorNode._separate_speechbrain
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Resample input to 8kHz for SepFormer, then resample output back to original sr.

WHAT IT ACTUALLY DOES:
The resampling uses `librosa` imported inside the conditional block. If
`sr != 8000`, librosa is imported and used. However, `audio_tensor` is built
from `y_in` (the resampled audio) but the output `src` is resampled back using
`in_sr` (which is 8000 when resampled). The output sample rate is set to `sr`
(original). This is correct.

The edge case: if `y` (input) is stereo (ndim > 1), `y.astype(np.float32)`
preserves the 2D shape. `torch.from_numpy(y_in).unsqueeze(0)` produces a
3D tensor `(1, channels, N)` instead of `(1, N)`. `model.separate_batch`
expects `(batch, time)` — this will raise a shape error inside SpeechBrain.

EVIDENCE:
```python
y = sample.data.astype(np.float32)  # may be 2D if stereo
# ...
audio_tensor = torch.from_numpy(y_in).unsqueeze(0)  # (1, channels, N) if stereo
est_sources = model.separate_batch(audio_tensor)  # expects (1, N)
```

REPRODUCTION SCENARIO:
Pass a stereo AudioSample (data.ndim == 2) to speechbrain backend.

IMPACT:
Crash with shape mismatch error from SpeechBrain.

FIX DIRECTION:
```python
y = sample.data.astype(np.float32)
if y.ndim > 1:
    y = y.mean(axis=1)  # mix to mono
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/speaker_separator/nodes.py
FUNCTION:    SpeakerSeparatorNode._separate_pyannote
CATEGORY:    Resource Leak
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Diarize using pyannote.audio, then slice audio per speaker segment.

WHAT IT ACTUALLY DOES:
`waveform = torch.from_numpy(y).unsqueeze(0)` — if `y` is stereo (ndim > 1),
this produces a `(1, channels, N)` tensor. pyannote expects `(channels, N)`.
The `unsqueeze(0)` adds a batch dimension, producing `(1, channels, N)` for
stereo or `(1, 1, N)` for mono. pyannote's Pipeline expects `{"waveform": (C, N), "sample_rate": sr}`.
For mono audio, `y` is 1D, `unsqueeze(0)` gives `(1, N)` which is correct
(1 channel, N samples). For stereo, `y` is `(N, 2)`, `unsqueform(0)` gives
`(1, N, 2)` — wrong shape.

Additionally, `y = sample.data.astype(np.float32)` does not ensure mono.

EVIDENCE:
```python
y = sample.data.astype(np.float32)  # may be (N, 2) for stereo
waveform = torch.from_numpy(y).unsqueeze(0)  # (1, N, 2) — wrong for pyannote
audio_in = {"waveform": waveform, "sample_rate": sr}
diarization = pipeline(audio_in, **kwargs)  # may raise shape error
```

REPRODUCTION SCENARIO:
Pass a stereo AudioSample to pyannote backend.

IMPACT:
Crash or wrong diarization result for stereo audio.

FIX DIRECTION:
```python
y = sample.data.astype(np.float32)
if y.ndim > 1:
    y = y.mean(axis=1)
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/speaker_separator/nodes.py
FUNCTION:    SpeakerSeparatorNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Process a list of AudioSamples, separating speakers from each.

WHAT IT ACTUALLY DOES:
Does not validate that `samples` is non-empty or that individual samples have
non-zero data. An empty list returns `[]` silently (acceptable). A sample with
`data = np.array([])` is passed to `_separate_pyannote` or
`_separate_speechbrain`. In `_separate_pyannote`, `torch.from_numpy(y).unsqueeze(0)`
produces a `(1, 0)` tensor. pyannote may raise an error or return empty
diarization. In `_separate_speechbrain`, `model.separate_batch` on a zero-length
tensor will raise an error inside SpeechBrain.

EVIDENCE:
```python
for sample in samples:
    if backend == "pyannote":
        results = self._separate_pyannote(sample)  # no zero-length check
```

REPRODUCTION SCENARIO:
Pass `AudioSample(data=np.array([]))` to process().

IMPACT:
Crash from pyannote or SpeechBrain for zero-length audio.

FIX DIRECTION:
```python
for sample in samples:
    if sample.data is None or len(sample.data) == 0:
        log.warning("SpeakerSeparatorNode: skipping zero-length sample %s", sample.path)
        continue
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/speaker_separator/nodes.py
FUNCTION:    SpeakerSeparatorNode.Config (auth_token field)
CATEGORY:    State Bug
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Store HuggingFace auth token for pyannote models; warns not to store in
saved pipeline files.

WHAT IT ACTUALLY DOES:
The `auth_token` field is a plain `str` in the Pydantic config. If a pipeline
is serialised to JSON (e.g. for checkpointing), the token will be included in
the serialised output. The comment warns against this but there is no
enforcement (e.g. `exclude=True` in the field definition or a custom serialiser).

EVIDENCE:
```python
auth_token: str = ""
# WARNING: do not store auth_token in saved pipeline files
```

IMPACT:
Secret leakage if pipeline configs are serialised and stored or transmitted.

FIX DIRECTION:
Use Pydantic's `Field(exclude=True)` or mark as `SecretStr` to prevent
serialisation:
```python
from pydantic import Field, SecretStr
auth_token: SecretStr = Field(default=SecretStr(""), exclude=True)
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
| Resource Safety | UNSAFE |
| Test Hostile | PARTIAL |
| Top Risk | `.numpy()` on GPU tensor in `_separate_speechbrain` crashes on any CUDA system; stereo audio crashes both backends |
