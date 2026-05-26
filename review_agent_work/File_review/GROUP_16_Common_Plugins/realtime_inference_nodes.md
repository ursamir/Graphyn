# Functional Review — PluginPackage/Common/realtime_inference/nodes.py

**Group:** 16 — Common Plugins  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Common/realtime_inference/nodes.py
FUNCTION:    RealtimeInferenceNode.process
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Run inference on a list of FeatureArray objects. Streaming ASR mode buffers
frames and emits when buffer is full."

WHAT IT ACTUALLY DOES:
The `_asr_buffer` is an instance variable that persists across multiple calls
to `process()`. It is initialized in `setup()` and reset in `setup()`. However,
between calls to `process()`, the buffer is NOT cleared. If `process()` is
called multiple times (e.g., in a streaming pipeline where each call processes
one chunk), the buffer accumulates frames across calls. The partial-buffer
flush at the end of `process()` clears the buffer after emitting, but only if
`streaming_asr` mode is active AND there are remaining frames.

The real issue: if `process()` is called with `mode="streaming_asr"` and the
buffer fills exactly at the end of a call (all frames consumed), the buffer is
cleared. But if the pipeline switches from `streaming_asr` to `classification`
mode between calls (config mutation), the stale `_asr_buffer` from the previous
call is never cleared and accumulates indefinitely.

THE BUG / RISK:
`_asr_buffer` accumulates across `process()` calls if mode changes or if
`setup()` is not called between pipeline runs. Memory grows unboundedly.

EVIDENCE:
```python
def setup(self) -> None:
    self._asr_buffer: list = []   # reset only in setup()

def process(self, features):
    if not hasattr(self, "_asr_buffer"):
        self._asr_buffer = []     # fallback init — but not cleared between calls
    for f in features:
        if self.config.mode == "streaming_asr":
            self._asr_buffer.append((f, probs))
            if len(self._asr_buffer) >= self.config.streaming_buffer_size:
                ...
                self._asr_buffer.clear()
            continue
        # If mode != streaming_asr, buffer is never cleared
```

REPRODUCTION SCENARIO:
```python
node = RealtimeInferenceNode(Config(model_path="...", mode="streaming_asr"))
node.setup()
node.process(features_chunk_1)  # buffer partially filled
node.config.mode = "classification"
node.process(features_chunk_2)  # buffer never cleared, grows indefinitely
```

IMPACT:
Memory leak. In long-running streaming pipelines, `_asr_buffer` grows without
bound if mode changes.

FIX DIRECTION:
Clear the buffer at the start of each `process()` call when not in streaming_asr mode:
```python
if self.config.mode != "streaming_asr" and hasattr(self, "_asr_buffer"):
    self._asr_buffer.clear()
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/realtime_inference/nodes.py
FUNCTION:    RealtimeInferenceNode.process
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Run inference on a list of FeatureArray objects."

WHAT IT ACTUALLY DOES:
Reshapes each feature with `inp = f.data[np.newaxis, ..., np.newaxis]`. This
assumes `f.data` is a 2-D array `(T, F)`, producing shape `(1, T, F, 1)`.
If `f.data` is 1-D (e.g., raw waveform samples), the result is `(1, N, 1)` —
a 3-D tensor, not 4-D. If `f.data` is 3-D (e.g., already has a channel dim),
the result is `(1, T, F, C, 1)` — a 5-D tensor. Both cases cause the TFLite
interpreter to raise a shape mismatch error.

THE BUG / RISK:
Non-2D feature arrays cause shape mismatch errors in the inference backend.
The error message from TFLite/PyTorch/ONNX is not user-friendly.

EVIDENCE:
```python
inp = f.data[np.newaxis, ..., np.newaxis].astype(np.float32)
# If f.data.ndim == 1: inp.shape = (1, N, 1) — wrong
# If f.data.ndim == 3: inp.shape = (1, T, F, C, 1) — wrong
```

REPRODUCTION SCENARIO:
```python
f = FeatureArray(data=np.zeros(16000), ...)  # 1-D waveform
node.process([f])  # TFLite raises shape mismatch
```

IMPACT:
Crash with confusing backend-specific error.

FIX DIRECTION:
```python
data = f.data
if data.ndim == 1:
    data = data[:, np.newaxis]  # (N,) → (N, 1)
elif data.ndim > 2:
    data = data.reshape(data.shape[0], -1)  # flatten extra dims
inp = data[np.newaxis, ..., np.newaxis].astype(np.float32)  # (1, T, F, 1)
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/realtime_inference/nodes.py
FUNCTION:    RealtimeInferenceNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Adaptive frame-skipping: skip every Nth frame based on adaptive_skip_ratio."

WHAT IT ACTUALLY DOES:
Computes `skip_interval = max(2, int(1.0 / max(0.01, 1.0 - adaptive_skip_ratio)))`.
For `adaptive_skip_ratio=0.5`, `skip_interval = max(2, int(1/0.5)) = 2`.
For `adaptive_skip_ratio=0.9`, `skip_interval = max(2, int(1/0.1)) = 10`.
For `adaptive_skip_ratio=0.0`, `skip_interval = max(2, int(1/1.0)) = 2`.

The skip logic is `if frame_count % skip_interval == 0: continue`. This skips
every Nth frame, not a fraction of frames. For `adaptive_skip_ratio=0.5`, it
skips every 2nd frame (50% skip rate). For `adaptive_skip_ratio=0.9`, it skips
every 10th frame (10% skip rate). The formula is inverted: higher
`adaptive_skip_ratio` means LESS skipping, not more. The config docstring says
"fraction of frames to skip when adaptive=True", implying higher = more skipping.

THE BUG / RISK:
The `adaptive_skip_ratio` semantics are inverted. A user setting
`adaptive_skip_ratio=0.9` (expecting 90% of frames to be skipped) gets only
10% skipped. This is a contract mismatch.

EVIDENCE:
```python
skip_interval = max(2, int(1.0 / max(0.01, 1.0 - self.config.adaptive_skip_ratio)))
# adaptive_skip_ratio=0.9 → skip_interval=10 → skips 10% of frames
# Expected: skip 90% of frames
```

REPRODUCTION SCENARIO:
```python
node = RealtimeInferenceNode(Config(model_path="...", adaptive=True, adaptive_skip_ratio=0.9))
# User expects 90% frame skip; gets 10% skip
```

IMPACT:
Silent wrong behavior. CPU load reduction is much less than expected.

FIX DIRECTION:
Fix the formula to match the documented semantics:
```python
# Skip every Nth frame where N = 1/(1-ratio) → skip ratio fraction of frames
# Simpler: skip if frame_count % round(1/(1-ratio)) == 0
skip_interval = max(2, round(1.0 / max(0.01, 1.0 - self.config.adaptive_skip_ratio)))
```
Wait — this is the same formula. The actual fix is to change the semantics:
```python
# skip_ratio = fraction to skip → keep every (1/(1-skip_ratio))th frame
# OR: skip if rng.random() < skip_ratio (probabilistic)
```
Or fix the formula to `int(1.0 / max(0.01, self.config.adaptive_skip_ratio))`:
```python
skip_interval = max(2, int(1.0 / max(0.01, self.config.adaptive_skip_ratio)))
# adaptive_skip_ratio=0.9 → skip_interval=1 (skip every frame — too aggressive)
```
The cleanest fix is probabilistic skipping:
```python
import random
if self.config.adaptive and random.random() < self.config.adaptive_skip_ratio:
    continue
```
--------------------------------------------------------------------

--------------------------------------------------------------------
FILE:        PluginPackage/Common/realtime_inference/nodes.py
FUNCTION:    RealtimeInferenceNode.process (streaming_asr mode)
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
"Buffer frames, emit when buffer full (CTC-style)."

WHAT IT ACTUALLY DOES:
In `streaming_asr` mode, after the `continue` statement skips the
classification/wake_word logic, the code falls through to the partial-buffer
flush at the end of `process()`. However, the `continue` statement is inside
the `for f in features` loop. After the loop, the partial flush runs:

```python
if self.config.mode == "streaming_asr" and self._asr_buffer:
    ...
    self._asr_buffer.clear()
```

This means the partial buffer is ALWAYS flushed at the end of every `process()`
call, even if the buffer is not full. This defeats the purpose of buffering —
every call emits a partial result regardless of `streaming_buffer_size`.

THE BUG / RISK:
The partial-buffer flush at the end of `process()` emits a result for every
call, even when the buffer has only 1 frame. The `streaming_buffer_size` config
is effectively ignored for the last batch of frames in each call.

EVIDENCE:
```python
# End of process():
if self.config.mode == "streaming_asr" and self._asr_buffer:
    # Always runs if any frames were buffered but not yet emitted
    all_probs = np.mean([p for _, p in self._asr_buffer], axis=0)
    ...
    self._asr_buffer.clear()
```

REPRODUCTION SCENARIO:
```python
node = RealtimeInferenceNode(Config(model_path="...", mode="streaming_asr", streaming_buffer_size=10))
node.setup()
node.process([f1, f2, f3])  # 3 frames — buffer has 3, emits partial result immediately
```

IMPACT:
Streaming ASR emits partial results on every call. The `streaming_buffer_size`
is only respected within a single call, not across calls.

FIX DIRECTION:
The partial flush should only happen when the stream is explicitly ended (e.g.,
a sentinel value or a separate `flush()` method). Remove the end-of-call flush
or make it opt-in:
```python
# Only flush at end of call if explicitly requested
# (e.g., last frame has a special flag, or add a flush() method)
```
--------------------------------------------------------------------

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 1 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | UNSAFE |
| Resource Safety | SAFE |
| Test Hostile | PARTIAL |
| Top Risk | `_asr_buffer` accumulates across process() calls when mode changes — unbounded memory growth in long-running streaming pipelines |
