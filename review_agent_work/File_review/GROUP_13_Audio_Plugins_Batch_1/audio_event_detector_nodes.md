# Functional Review — PluginPackage/Audio/audio_event_detector/nodes.py

**Group:** 13 — Audio Plugins Batch 1  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_event_detector/nodes.py
FUNCTION:    AudioEventDetectorNode._detect_tflite
CATEGORY:    Resource Leak
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Run TFLite inference on an audio sample.

WHAT IT ACTUALLY DOES:
Creates a new `tflite.Interpreter` instance on every call to `_detect_tflite`.
Unlike the classifier node which caches `self._model_obj`, the event detector
allocates a fresh interpreter per sample. For a batch of 1000 samples, this
allocates and deallocates 1000 TFLite interpreters, each loading the model
file from disk. This is both a performance bug (O(n) model loads) and a
resource leak risk if the interpreter is not promptly garbage-collected.

EVIDENCE:
```python
def _detect_tflite(self, sample: AudioSample) -> list[dict]:
    ...
    interp = tflite.Interpreter(model_path=self.config.model_path)
    interp.allocate_tensors()
    # interp is local — new instance every call
```

REPRODUCTION SCENARIO:
Process a batch of 100 AudioSamples with `backend="tflite"`.

IMPACT:
100× model file reads; potential OOM from concurrent interpreter allocations;
severe performance degradation.

FIX DIRECTION:
Cache the interpreter on `self` (same pattern as `_yamnet_model`):
```python
if not hasattr(self, "_tflite_interp"):
    self._tflite_interp = tflite.Interpreter(model_path=self.config.model_path)
    self._tflite_interp.allocate_tensors()
interp = self._tflite_interp
```
Note: same thread-safety caveat as the classifier node applies.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_event_detector/nodes.py
FUNCTION:    AudioEventDetectorNode._detect_pytorch
CATEGORY:    Resource Leak
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Run PyTorch inference on an audio sample.

WHAT IT ACTUALLY DOES:
Creates a new `torch.jit.load(...)` model instance on every call to
`_detect_pytorch`. Same problem as `_detect_tflite` — O(n) model loads
for a batch of n samples.

EVIDENCE:
```python
def _detect_pytorch(self, sample: AudioSample) -> list[dict]:
    ...
    model = torch.jit.load(self.config.model_path, map_location="cpu")
    model.eval()
    # model is local — new instance every call
```

REPRODUCTION SCENARIO:
Process a batch of 100 AudioSamples with `backend="pytorch"`.

IMPACT:
100× model file reads; severe performance degradation; potential OOM.

FIX DIRECTION:
Cache on `self`:
```python
if not hasattr(self, "_pytorch_model"):
    self._pytorch_model = torch.jit.load(self.config.model_path, map_location="cpu")
    self._pytorch_model.eval()
model = self._pytorch_model
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_event_detector/nodes.py
FUNCTION:    AudioEventDetectorNode._detect_tflite
CATEGORY:    Silent Failure
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Detect events in an audio sample using a TFLite model.

WHAT IT ACTUALLY DOES:
The TFLite backend treats the entire audio as a single frame and assigns
`start=0.0` and `end=float(len(y) / sample.sample_rate)` to every detected
event. This means all events get the same timestamp span (the full audio
duration), regardless of when they actually occur. The output is structurally
valid but semantically wrong — it claims to provide temporal detection but
delivers only clip-level classification.

EVIDENCE:
```python
events.append({
    "event": label,
    "start": 0.0,
    "end": float(len(y) / sample.sample_rate),  # always full duration
    "confidence": round(float(conf), 4),
})
```

REPRODUCTION SCENARIO:
Use `backend="tflite"` with a 10-second audio clip. All detected events
report `start=0.0, end=10.0` regardless of actual event timing.

IMPACT:
Silent wrong result — callers relying on temporal event timestamps receive
incorrect data. The node's docstring promises "onset/offset timestamps" but
TFLite backend delivers only clip-level labels.

FIX DIRECTION:
Document clearly in the docstring that TFLite backend does not provide
temporal resolution (clip-level only), or implement frame-level windowing
for TFLite inference.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_event_detector/nodes.py
FUNCTION:    AudioEventDetectorNode._detect_pytorch
CATEGORY:    Silent Failure
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Detect events with onset/offset timestamps using a PyTorch model.

WHAT IT ACTUALLY DOES:
Same as TFLite: assigns `start=0.0` and `end=float(len(sample.data) / sample.sample_rate)`
to every event. No temporal windowing is performed.

EVIDENCE:
```python
events.append({
    "event": label,
    "start": 0.0,
    "end": float(len(sample.data) / sample.sample_rate),
    ...
})
```

REPRODUCTION SCENARIO:
Use `backend="pytorch"` with any multi-event audio clip.

IMPACT:
Same as TFLite: silent wrong temporal data.

FIX DIRECTION:
Same as TFLite: document limitation or implement frame-level windowing.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_event_detector/nodes.py
FUNCTION:    AudioEventDetectorNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Process a dict of inputs and return a dict with output samples and events.

WHAT IT ACTUALLY DOES:
`inputs.get("input") or []` — if `inputs` is `None` (not a dict), this raises
`AttributeError: 'NoneType' object has no attribute 'get'`. Also, if `inputs`
is a list (SISO calling convention used by some executors), `inputs.get("input")`
raises `AttributeError: 'list' object has no attribute 'get'`.

EVIDENCE:
```python
def process(self, inputs: dict) -> dict:
    samples: list[AudioSample] = inputs.get("input") or []
```

REPRODUCTION SCENARIO:
NodeExecutor passes a list instead of a dict (SISO convention), or passes None.

IMPACT:
`AttributeError` crash; confusing error message.

FIX DIRECTION:
Add a guard:
```python
if isinstance(inputs, list):
    samples = inputs
elif isinstance(inputs, dict):
    samples = inputs.get("input") or []
else:
    samples = []
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_event_detector/nodes.py
FUNCTION:    AudioEventDetectorNode._detect_yamnet
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Detect events in audio using YAMNet frame-level scores.

WHAT IT ACTUALLY DOES:
When `sample.data` is empty (zero samples), `librosa.resample` returns an
empty array, and `self._yamnet_model(y)` is called with an empty waveform.
TensorFlow may raise an error or return a zero-frame scores tensor. If it
returns zero frames, `scores_np` is shape `(0, 521)` and the for loop
produces no events — this is actually safe. However, if TF raises, the
exception propagates uncaught through `_detect` → `process`, crashing the
entire batch.

EVIDENCE:
```python
y = sample.data.astype(np.float32)
# No empty-array guard
scores, embeddings, spectrogram = self._yamnet_model(y)
```

REPRODUCTION SCENARIO:
Pass an AudioSample with `data = np.array([])`.

IMPACT:
Crash or silent empty result depending on TF version behavior.

FIX DIRECTION:
```python
if len(y) == 0:
    return []
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_event_detector/nodes.py
FUNCTION:    AudioEventDetectorNode._merge_events
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Merge consecutive same-class events and filter by minimum duration.

WHAT IT ACTUALLY DOES:
The merge condition `ev["start"] <= current["end"] + 0.01` uses a hardcoded
0.01s tolerance. This tolerance is not configurable and may be too tight for
some use cases (e.g. YAMNet's 0.48s hop means adjacent frames are always
0.48s apart, so this tolerance never triggers merging of non-adjacent frames).
The last event in the loop is appended after the loop only if it meets the
minimum duration — this is correct. However, the first event is initialized
as `current = dict(events[0])` without checking `min_dur_s`, so a single
short event that is the only event in the list will be appended regardless
of duration.

EVIDENCE:
```python
current = dict(events[0])
for ev in events[1:]:
    ...
if current["end"] - current["start"] >= min_dur_s:
    merged.append(current)
```
Wait — the final `if` check IS applied to `current`. So a single short event
IS filtered. This is correct. The hardcoded 0.01s tolerance is the only real
issue here.

REPRODUCTION SCENARIO:
Events with 0.48s hop — adjacent frames are 0.48s apart, so `ev["start"]`
(0.48) > `current["end"]` (0.48) + 0.01 is False — they ARE merged. Actually
`ev["start"] = 0.48` and `current["end"] = 0.48`, so `0.48 <= 0.48 + 0.01`
is True — merging works. Low severity.

IMPACT:
Minor: hardcoded tolerance may not work for all frame rates.

FIX DIRECTION:
Make the merge tolerance configurable or derive it from `frame_hop_ms`.

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
| Top Risk | TFLite and PyTorch backends silently return wrong temporal data (all events span full clip duration) despite the node claiming to provide onset/offset timestamps |
