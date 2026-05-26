# Functional Review — PluginPackage/Audio/stream_processor/nodes.py

**Group:** 15 — Audio Plugins Batch 3
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/stream_processor/nodes.py
FUNCTION:    StreamProcessorNode.process
CATEGORY:    State Bug
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Rolling window processor: buffers incoming chunks, emits windowed audio,
keeps leftover samples for the next call.

WHAT IT ACTUALLY DOES:
`self._buffer` and `self._sample_buffer` are instance-level state initialised
in `setup()`. The `process()` method appends incoming chunks to `self._buffer`,
concatenates all buffered samples (including the leftover from `self._sample_buffer`),
emits windows, stores the leftover back in `self._sample_buffer`, then calls
`self._buffer.clear()`.

The bug: `self._buffer` is cleared at the end of every `process()` call, but
the concatenation at the top of `process()` uses ALL chunks currently in
`self._buffer` (including those from the current call). This means the buffer
acts as a single-call accumulator, not a true rolling buffer. The `max_buffer_size`
drop logic is correct for the current call's chunks, but since the buffer is
always cleared at the end, the `max_buffer_size` limit only applies within a
single `process()` call, not across calls.

More critically: if `setup()` is never called (e.g. direct instantiation
without going through NodeExecutor), `self._buffer` and `self._sample_buffer`
do not exist. `process()` will raise `AttributeError: 'StreamProcessorNode'
object has no attribute '_buffer'`.

EVIDENCE:
```python
def process(self, chunks: list[AudioSample]) -> list[AudioSample]:
    # ...
    for chunk in chunks:
        if len(self._buffer) >= self.config.max_buffer_size:  # AttributeError if setup() not called
            ...
        self._buffer.append(chunk)
    # ...
    self._buffer.clear()  # always cleared — not a true rolling buffer
```

REPRODUCTION SCENARIO:
```python
node = StreamProcessorNode()
# setup() not called
node.process([AudioSample(...)])  # AttributeError: '_buffer'
```

IMPACT:
AttributeError if setup() not called. The rolling buffer semantics are
misleading — the buffer does not persist state across calls (it is always
cleared). The `_sample_buffer` (leftover samples) does persist correctly.

FIX DIRECTION:
Add a guard in `process()`:
```python
if not hasattr(self, "_buffer"):
    self.setup()
```
Or document clearly that `setup()` must be called. The buffer-clearing
behaviour is intentional (process all buffered chunks each call) but should
be documented.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/stream_processor/nodes.py
FUNCTION:    StreamProcessorNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Buffer incoming chunks and emit windowed audio.

WHAT IT ACTUALLY DOES:
`all_data = np.concatenate([c.data.astype(np.float32) for c in self._buffer])`
— if any chunk's `data` is 2D (stereo), `np.concatenate` will concatenate
along axis 0, producing a 2D array. Subsequent operations (`all_data[pos:pos +
window_samples]`) will slice along axis 0, producing 2D windows. `_apply_hann`
multiplies by a 1D Hann window, which will broadcast incorrectly for 2D arrays.
The resulting `AudioSample.data` will be 2D, which may cause issues downstream.

EVIDENCE:
```python
all_data = np.concatenate(
    [c.data.astype(np.float32) for c in self._buffer]
)  # 2D if any chunk is stereo
# ...
window = all_data[pos:pos + window_samples]  # 2D slice
if self.config.overlap_add:
    window = self._apply_hann(window)  # hann is 1D → broadcast issue
```

REPRODUCTION SCENARIO:
Pass stereo AudioSamples (data.ndim == 2) to process().

IMPACT:
Silent wrong result — 2D windows emitted instead of 1D. Downstream nodes
expecting 1D audio will fail or produce wrong results.

FIX DIRECTION:
```python
all_data = np.concatenate(
    [c.data.astype(np.float32).flatten() if c.data.ndim > 1
     else c.data.astype(np.float32) for c in self._buffer]
)
```
Or mix to mono: `c.data.mean(axis=1) if c.data.ndim > 1 else c.data`.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/stream_processor/nodes.py
FUNCTION:    StreamProcessorNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Emit windowed chunks; keep leftover samples for next call.

WHAT IT ACTUALLY DOES:
`template = list(self._buffer)[0] if self._buffer else None` — converts the
deque to a list just to get the first element. This is O(n) for a deque.
`self._buffer[0]` would be O(1). Minor performance issue.

More importantly: if `chunks` is empty (empty list passed to process()),
`self._buffer` remains empty after the loop. `all_data` is `np.array([])`.
`np.concatenate([])` raises `ValueError: need at least one array to concatenate`.

EVIDENCE:
```python
all_data = np.concatenate(
    [c.data.astype(np.float32) for c in self._buffer]
) if self._buffer else np.array([], dtype=np.float32)
```

Wait — the code does check `if self._buffer` before concatenating. So empty
`chunks` → empty `self._buffer` → `all_data = np.array([])`. Then
`np.concatenate([self._sample_buffer, all_data])` is called if
`len(self._sample_buffer) > 0`. `np.concatenate([arr, np.array([])])` works
correctly. So empty chunks is handled safely.

The actual issue: `template = list(self._buffer)[0]` — after `self._buffer.clear()`
is called at the end, `template` still holds a reference to the first chunk.
But `template` is used before `self._buffer.clear()`, so this is safe.

Re-examining: the `template` is captured before the window loop, and
`self._buffer.clear()` is called after the window loop. So `template` is valid
throughout. No bug here.

Revised finding: the `list(self._buffer)[0]` is an O(n) operation where
`self._buffer[0]` would be O(1). Low severity.

EVIDENCE:
```python
template = list(self._buffer)[0] if self._buffer else None  # O(n) — use self._buffer[0]
```

IMPACT:
Minor performance issue for large buffers. No correctness impact.

FIX DIRECTION:
```python
template = self._buffer[0] if self._buffer else None
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/stream_processor/nodes.py
FUNCTION:    StreamProcessorNode.process
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Warn if processing latency exceeds target_latency_ms.

WHAT IT ACTUALLY DOES:
`elapsed_ms = (time.monotonic() - t_start) * 1000` measures wall-clock time
for the entire `process()` call, including numpy concatenation and window
extraction. This is a reasonable proxy for processing latency. However,
`t_start` is captured before the buffer health check loop, so it includes
the time to iterate over `chunks` and check buffer size. For large `chunks`
lists, this may inflate the latency measurement.

No functional bug — this is a minor measurement imprecision.

EVIDENCE:
```python
t_start = time.monotonic()
for chunk in chunks:  # included in latency measurement
    ...
```

IMPACT:
Latency warnings may fire for large input batches even if processing is fast.
No correctness impact.

FIX DIRECTION:
Move `t_start` after the buffer health check loop. No critical fix needed.

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
| Top Risk | `process()` raises AttributeError if `setup()` was not called; stereo audio produces 2D windows that silently corrupt downstream processing |
