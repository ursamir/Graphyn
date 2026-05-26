# Functional Review — PluginPackage/Audio/audio_generator/nodes.py

**Group:** 13 — Audio Plugins Batch 1  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_generator/nodes.py
FUNCTION:    AudioGeneratorNode._generate_musicgen
CATEGORY:    Resource Leak
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Load MusicGen once and reuse it across calls.

WHAT IT ACTUALLY DOES:
`self._musicgen_model` is loaded lazily on first call. If `process()` raises
after model load (e.g. during `generate_with_chroma`), the model remains
loaded on `self`. On the next call, the cached model is reused — this is
correct. However, there is no `teardown()` method to release the model.
AudioCraft MusicGen loads large transformer weights (300MB–3.3GB depending
on size) onto GPU/CPU. If the node is destroyed without teardown, these
weights are not explicitly released.

More critically: `model.set_generation_params()` is called on every
`process()` call, mutating the shared model object. If two concurrent calls
hit `process()` simultaneously, one call's `set_generation_params` can
overwrite the other's parameters mid-generation.

EVIDENCE:
```python
model = self._musicgen_model
model.set_generation_params(...)  # mutates shared model state
...
wav = model.generate(prompts)
```
No lock around `set_generation_params` + `generate`.

REPRODUCTION SCENARIO:
Two pipeline waves call `process()` concurrently on the same node instance.
Call A sets `duration_s=5.0`, Call B sets `duration_s=30.0`. Call A's
generation uses 30.0s parameters.

IMPACT:
Wrong generation parameters applied silently; no error raised.

FIX DIRECTION:
Add a threading.Lock around `set_generation_params` + `generate`:
```python
with self._model_lock:
    model.set_generation_params(...)
    wav = model.generate(prompts)
```
Also implement `teardown()` to release model memory.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_generator/nodes.py
FUNCTION:    AudioGeneratorNode._generate_musicgen
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Load conditioning audio from `conditioning_audio` path and use it for
melody-conditioned generation.

WHAT IT ACTUALLY DOES:
```python
if Path(self.config.conditioning_audio).exists():
    mel_data, mel_sr = sf.read(self.config.conditioning_audio, dtype="float32")
    melody_wavs = torch.from_numpy(mel_data).unsqueeze(0).unsqueeze(0)
```
Then calls:
```python
wav = model.generate_with_chroma(prompts, melody_wavs, mel_sr)
```
`mel_sr` is defined only inside the `if` block. If `conditioning_audio` is
set but the file does not exist, `melody_wavs` remains `None` and `mel_sr`
is never defined. The code then falls through to:
```python
if melody_wavs is not None:
    wav = model.generate_with_chroma(prompts, melody_wavs, mel_sr)
```
Since `melody_wavs is None`, it falls to `model.generate(prompts)` — silently
ignoring the missing conditioning file with no warning.

EVIDENCE:
```python
if Path(self.config.conditioning_audio).exists():
    ...
    mel_sr = ...  # only defined here
# mel_sr not defined if file doesn't exist
if melody_wavs is not None:
    wav = model.generate_with_chroma(prompts, melody_wavs, mel_sr)  # mel_sr used here
```

REPRODUCTION SCENARIO:
Set `conditioning_audio="/nonexistent/melody.wav"`. File doesn't exist.
`melody_wavs=None`, so `generate_with_chroma` is not called. Generation
proceeds unconditionally with no warning that the conditioning file was missing.

IMPACT:
Silent wrong result — user expects melody-conditioned output but gets
unconditional generation.

FIX DIRECTION:
```python
if self.config.conditioning_audio:
    p = Path(self.config.conditioning_audio)
    if not p.exists():
        raise FileNotFoundError(
            f"AudioGeneratorNode: conditioning_audio '{p}' not found"
        )
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_generator/nodes.py
FUNCTION:    AudioGeneratorNode._tensors_to_samples
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Convert AudioCraft output tensors to a list of AudioSample objects.

WHAT IT ACTUALLY DOES:
`audio.squeeze().cpu().numpy()` — if the audio tensor has shape `(1, 1, N)`
(batch=1, channels=1, samples=N), `squeeze()` removes all size-1 dimensions
and returns shape `(N,)` — correct. However, if the model returns stereo
audio with shape `(1, 2, N)`, `squeeze()` returns shape `(2, N)` — a 2D
array. `AudioSample` expects a 1D float32 array for mono audio. Passing a
2D array may cause downstream nodes to fail or produce wrong results.

EVIDENCE:
```python
y = audio.squeeze().cpu().numpy().astype(np.float32)
```
No check on `y.ndim` after squeeze.

REPRODUCTION SCENARIO:
AudioCraft returns stereo output (possible with some model configurations).

IMPACT:
2D array stored in `AudioSample.data`; downstream nodes expecting 1D audio
crash or produce wrong results.

FIX DIRECTION:
```python
y = audio.squeeze().cpu().numpy().astype(np.float32)
if y.ndim > 1:
    y = y.mean(axis=0)  # mix to mono
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_generator/nodes.py
FUNCTION:    AudioGeneratorNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Accept a list of text prompts or an empty list for unconditional generation.

WHAT IT ACTUALLY DOES:
```python
text_prompts = [str(p) for p in prompts if str(p).strip()] if prompts else []
```
Filters out empty/whitespace prompts. If all prompts are whitespace, `text_prompts`
is empty and falls through to `config.prompt`. If `config.prompt` is also empty,
`text_prompts = [""]` — unconditional generation. This is documented behavior.

However, `str(p)` is called on each element without checking if `p` is a
valid string-convertible type. If `prompts` contains a non-serializable object
(e.g. a dict or AudioSample), `str(p)` produces a repr string like
`"{'key': 'value'}"` which is passed as a text prompt to the model — a silent
wrong input.

EVIDENCE:
```python
text_prompts = [str(p) for p in prompts if str(p).strip()] if prompts else []
```

REPRODUCTION SCENARIO:
Pass `prompts=[{"text": "jazz music"}]` (dict instead of str). `str({"text": "jazz music"})`
= `"{'text': 'jazz music'}"` is passed as the prompt.

IMPACT:
Silent wrong result — model receives a Python repr string as a prompt.

FIX DIRECTION:
```python
text_prompts = []
for p in (prompts or []):
    if not isinstance(p, str):
        raise TypeError(f"AudioGeneratorNode: prompt must be str, got {type(p)}")
    if p.strip():
        text_prompts.append(p)
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_generator/nodes.py
FUNCTION:    AudioGeneratorNode.setup
CATEGORY:    Testability
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Warn if no GPU is available.

WHAT IT ACTUALLY DOES:
`setup()` does not validate config fields: `duration_s > 0`, `temperature > 0`,
`top_k > 0`, `guidance_scale > 0`, `model_size` is one of "small"/"medium"/"large".
Invalid configs are only discovered at generation time, deep inside AudioCraft.

EVIDENCE:
No `@validator` or `model_validator` in `Config`.

REPRODUCTION SCENARIO:
Set `duration_s=-1.0`. AudioCraft raises an internal error with a confusing
traceback rather than a clear config validation error.

IMPACT:
Confusing error at generation time rather than clear config error at setup time.

FIX DIRECTION:
Add Pydantic validators for `duration_s`, `temperature`, `top_k`, `model_size`.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_generator/nodes.py
FUNCTION:    AudioGeneratorNode._generate_audiogen
CATEGORY:    Resource Leak
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Load AudioGen once and reuse it.

WHAT IT ACTUALLY DOES:
Same concurrency issue as MusicGen: `model.set_generation_params()` mutates
shared state without a lock. Lower severity than MusicGen because AudioGen
is less commonly used in concurrent pipelines.

EVIDENCE:
```python
model = self._audiogen_model
model.set_generation_params(...)  # mutates shared model state
wav = model.generate(prompts)
```

REPRODUCTION SCENARIO:
Two concurrent calls to `process()` with different `duration_s` values.

IMPACT:
Wrong generation parameters applied silently.

FIX DIRECTION:
Same as MusicGen: use a threading.Lock.

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
| Top Risk | Missing conditioning audio file is silently ignored — user expects melody-conditioned generation but receives unconditional output with no warning |
