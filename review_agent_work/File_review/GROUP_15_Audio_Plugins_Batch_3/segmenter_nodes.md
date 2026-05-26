# Functional Review — PluginPackage/Audio/segmenter/nodes.py

**Group:** 15 — Audio Plugins Batch 3
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/segmenter/nodes.py
FUNCTION:    SegmenterNode.process
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Segment each AudioSample in the input list using the configured mode.

WHAT IT ACTUALLY DOES:
Iterates over `samples` without checking whether the list is empty or whether
individual `AudioSample.data` arrays are zero-length before dispatching to
mode-specific helpers.

THE BUG / RISK:
An empty `samples` list returns `[]` silently (acceptable), but a sample with
`data = np.array([])` (zero samples) is passed directly into `_segment_fixed`,
`_segment_silence`, etc. In `_segment_fixed`, `range(0, len(y) - window_size + 1, step)`
evaluates to `range(0, 0 - window_size + 1, step)` which is an empty range when
`window_size > 1`, so it silently returns `[]`. In `_segment_event`, `librosa.feature.rms`
on a zero-length array raises a `ValueError` from librosa. In `_segment_vad`, the
`y_int16.tobytes()` call produces an empty bytes object and the loop produces no
segments — silent empty return. Behaviour is inconsistent across modes for the same
zero-length input.

EVIDENCE:
```python
# _segment_fixed (line ~185)
for i in range(0, len(y) - window_size + 1, step):  # silent empty range
# _segment_event (line ~240)
rms = librosa.feature.rms(y=y, frame_length=frame_len, hop_length=hop)[0]
# raises ValueError for zero-length y
```

REPRODUCTION SCENARIO:
```python
node = SegmenterNode(config=SegmenterNode.Config(mode="event"))
node.process([AudioSample(path="x", sample_rate=16000, data=np.array([]), label="")])
# raises ValueError from librosa
```

IMPACT:
Crash in event mode; silent empty output in other modes. Inconsistent contract
across modes for the same input — callers cannot predict behaviour.

FIX DIRECTION:
Add a guard at the top of `process()`:
```python
for s in samples:
    if s.data is None or len(s.data) == 0:
        log.warning("SegmenterNode: skipping zero-length sample %s", s.path)
        continue
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/segmenter/nodes.py
FUNCTION:    SegmenterNode._segment_fixed
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Produce fixed-length windows with optional overlap from an AudioSample.

WHAT IT ACTUALLY DOES:
Uses `range(0, len(y) - window_size + 1, step)` which silently produces no
segments when `len(y) < window_size`. There is no warning or metadata to
indicate that the sample was too short to produce any output.

THE BUG / RISK:
A caller passing a 500 ms sample with `window_ms=1000` gets an empty list
with no indication of why. This is a silent failure — the sample is consumed
and discarded without any log message.

EVIDENCE:
```python
for i in range(0, len(y) - window_size + 1, step):
    # never entered if len(y) < window_size
```

REPRODUCTION SCENARIO:
```python
node = SegmenterNode(config=SegmenterNode.Config(mode="fixed", window_ms=1000))
result = node.process([AudioSample(path="x", sample_rate=16000,
                                   data=np.zeros(8000), label="")])
# 8000 samples = 500ms < 1000ms window → result == [] with no warning
```

IMPACT:
Silent data loss — samples shorter than the window are silently dropped.

FIX DIRECTION:
```python
if len(y) < window_size:
    log.warning("SegmenterNode: sample %s (%d samples) shorter than window "
                "(%d samples) — no segments produced", s.path, len(y), window_size)
    return []
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/segmenter/nodes.py
FUNCTION:    SegmenterNode._segment_vad
CATEGORY:    Async Bug / Type Safety
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Perform VAD segmentation using webrtcvad, resampling to a supported rate if needed.

WHAT IT ACTUALLY DOES:
The VAD frame-to-original-sample conversion uses integer division:
`start_s = seg_start_frame * frame_samples * sr // vad_sr`
When `sr == vad_sr` this is exact. When `sr != vad_sr`, the integer division
truncates fractional samples, which is acceptable. However, `frame_samples` is
computed as `int(vad_sr * frame_ms / 1000)` where `frame_ms = 30`. For
`vad_sr = 8000`, `frame_samples = 240`. The multiplication
`seg_start_frame * 240 * sr` can overflow a Python int only for astronomically
large frame counts, so no overflow risk. The real issue is that `y_vad` is
resampled but the VAD operates on `y_vad` while the output intervals are mapped
back to `y` (original). If `sr` is not in `VAD_RATES` and the resampled length
differs from `len(y) * vad_sr / sr`, the final `intervals.append((start_s, len(y)))`
for the trailing speech segment is correct, but intermediate interval ends
computed as `i * frame_samples * sr // vad_sr` may slightly overshoot `len(y)`.
The `end_sample = min(end_sample, len(y))` clamp in the extraction loop
handles this correctly.

THE BUG / RISK:
The actual risk is that `webrtcvad` requires exactly `frame_bytes` bytes per
frame. If the audio is stereo (ndim > 1), `y_vad` will be 2D and
`y_int16.tobytes()` will interleave channels, producing frames that are twice
as long as expected. `vad.is_speech(frame, vad_sr)` will raise a
`webrtcvad.Error` for wrong frame size. The exception is caught by the bare
`except Exception: speech = False` handler, so all frames are silently marked
as non-speech and the function returns an empty list.

EVIDENCE:
```python
y_int16 = np.clip(y_vad * 32767, -32768, 32767).astype(np.int16)
pcm_bytes = y_int16.tobytes()  # stereo → 2× bytes per frame
# ...
try:
    speech = vad.is_speech(frame, vad_sr)
except Exception:
    speech = False  # silent failure for all frames
```

REPRODUCTION SCENARIO:
Pass a stereo AudioSample (data.ndim == 2) with mode='vad'. All frames fail
silently → empty output list.

IMPACT:
Silent wrong result — stereo audio produces no VAD segments with no warning.

FIX DIRECTION:
```python
if y_vad.ndim > 1:
    y_vad = y_vad.mean(axis=1)  # mix to mono before VAD
```
Add before `y_int16 = np.clip(...)`.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/segmenter/nodes.py
FUNCTION:    SegmenterNode._segment_event
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Energy-threshold event detection: find frames above threshold_db, merge
consecutive active frames, enforce min_gap_ms, extract audio chunks.

WHAT IT ACTUALLY DOES:
The gap-counting logic has a subtle off-by-one: when `gap_count` reaches
`min_gap_frames`, the event end is recorded as `i - gap_count`. This means
the event end is set to the frame index where the gap *started*, not the
last active frame. For a gap of exactly `min_gap_frames`, the end is correct.
But the `gap_count` variable is never reset when a new event starts after a
gap — `gap_count = 0` is only set inside `if a:` (active frame) and inside
the gap-closing branch. If a new event starts immediately after a gap closes,
`gap_count` is reset to 0 correctly. However, if `in_event` is False and
`gap_count > 0` from a previous event, and a new active frame arrives, the
`gap_count = 0` reset inside `if a: if not in_event:` block is correct.

The real bug: when `in_event` is True and the audio ends while still in an
event (`if in_event: intervals.append((event_start, len(active)))`), the
`gap_count` is not reset. This is fine because the loop has ended. But the
`frame_end` for this trailing event is `len(active)`, and
`end_sample = min(frame_end * hop + frame_len, len(y))` correctly clamps it.

The actual silent failure: `rms_db = librosa.amplitude_to_db(rms, ref=np.max)`
— when `rms` is all zeros (silence-only audio), `np.max(rms) == 0`, and
`librosa.amplitude_to_db` with `ref=0` produces `-inf` for all frames.
`active = rms_db >= threshold_db` where `threshold_db` is a finite negative
number (e.g. -30.0) evaluates to `False` for all `-inf` values. Result: empty
output with no warning. This is technically correct behaviour but is a silent
failure for silence-only audio.

EVIDENCE:
```python
rms_db = librosa.amplitude_to_db(rms, ref=np.max)
# ref=np.max → ref=0 for silence → all values are -inf
active = rms_db >= threshold_db  # all False → no events
```

REPRODUCTION SCENARIO:
Pass a silence-only AudioSample with mode='event'. Returns [] with no log.

IMPACT:
Silent empty output for silence-only audio. No warning to caller.

FIX DIRECTION:
```python
if np.max(rms) < 1e-10:
    log.debug("SegmenterNode: silence-only audio in event mode — no events detected")
    return []
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/segmenter/nodes.py
FUNCTION:    SegmenterNode._apply_overlap_merge
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Extend each interval end by a fraction of the segment's own length for
silence/VAD modes.

WHAT IT ACTUALLY DOES:
Extends the end of each interval by `overlap * seg_len` samples. This can
cause adjacent intervals to overlap significantly, and the extended end is
not clamped to `len(y)` here — the clamping happens in the callers. However,
if two adjacent intervals overlap after extension, the resulting segments will
contain duplicate audio data. This is intentional for overlap-add but is not
documented as such.

THE BUG / RISK:
For silence mode with high overlap (e.g. 0.9), adjacent segments will heavily
overlap. The docstring says "extend each interval end by a fraction of the
segment's own length" but does not warn that this can cause significant
duplication. Low severity because the config validator enforces overlap < 1.0.

EVIDENCE:
```python
overlap_samples = int(seg_len * self.config.overlap)
result.append((start, end + overlap_samples))
# no clamping here; clamping done in callers
```

IMPACT:
Duplicate audio data in overlapping segments. Expected behaviour for
overlap-add but undocumented.

FIX DIRECTION:
Add a note in the docstring that overlapping segments will contain duplicate
audio data. No code change required.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | MEDIUM |
| Silent Failures | 3 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `_segment_event` crashes on zero-length audio via librosa ValueError; `_segment_vad` silently returns empty output for stereo audio |
