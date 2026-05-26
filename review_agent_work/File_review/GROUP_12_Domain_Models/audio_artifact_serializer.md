# Functional Review — app/models/audio_artifact_serializer.py

**Group:** 12 — Domain & Models  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/models/audio_artifact_serializer.py
FUNCTION:    AudioSampleHandler.deserialize
CATEGORY:    Silent Failure Risk
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Read WAV + manifest.json from `src_dir` → list[AudioSample]. Returns `None` if the manifest is missing (cache/checkpoint miss).

WHAT IT ACTUALLY DOES:
If any single WAV file in the manifest fails to load (e.g., one corrupt file out of 1000), the entire `deserialize` call returns `None`. This means a cache or checkpoint with 999 valid samples and 1 corrupt sample is treated identically to a complete cache miss — all 999 valid samples are discarded and the upstream node must re-execute.

EVIDENCE:
Lines ~95–105:
```python
try:
    data, _sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
except Exception as exc:
    logger.warning(
        "AudioSampleHandler.deserialize: cannot read WAV %s (%s) — returning None",
        wav_path, exc,
    )
    return None
```
Returns `None` on the first failed WAV, abandoning all previously loaded samples.

REPRODUCTION SCENARIO:
1. A checkpoint directory contains 500 WAV files. File #250 is corrupt (disk error).
2. `deserialize` loads files 0–249 successfully, then fails on file 250.
3. Returns `None` — the checkpoint is treated as a miss.
4. The upstream node re-executes from scratch, potentially re-running expensive ML inference.

IMPACT:
Silent data loss — valid cached/checkpointed samples are discarded due to a single corrupt file. The pipeline re-executes unnecessarily, wasting compute. The caller has no way to distinguish "partial corruption" from "complete miss".

FIX DIRECTION:
Options: (a) skip corrupt files and return the partial list with a warning; (b) raise a specific exception so the caller can decide; (c) return a partial result with a flag indicating corruption. Option (a) is safest for cache hits:
```python
except Exception as exc:
    logger.warning("skipping corrupt WAV %s: %s", wav_path, exc)
    continue  # skip this sample, continue loading others
```

--------------------------------------------------------------------
FILE:        app/models/audio_artifact_serializer.py
FUNCTION:    AudioSampleHandler.serialize
CATEGORY:    Resource Leak
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Write a list[AudioSample] to `dest_dir` as WAV + manifest.json.

WHAT IT ACTUALLY DOES:
Writes WAV files for each sample, then writes `manifest.json`. If writing any WAV file raises (e.g., disk full), the exception propagates out of `serialize` without cleaning up the partially-written WAV files. The `dest_dir` is left in a partially-written state. On the next call to `deserialize`, the manifest is missing (not yet written), so `deserialize` returns `None` — this is correct behavior (cache miss). However, the orphaned partial WAV files consume disk space indefinitely.

EVIDENCE:
Lines ~55–80:
```python
for i, sample in enumerate(data):
    filename = f"{i}.wav"
    wav_path = dest_dir / filename
    ...
    sf.write(str(wav_path), sample_data, sample_rate)
    manifest_entries.append(...)
(dest_dir / "manifest.json").write_text(...)
```
No cleanup on failure.

REPRODUCTION SCENARIO:
Disk fills up after writing 500 of 1000 WAV files. `sf.write` raises `OSError`. Files 0–499 remain on disk. `manifest.json` is never written. On next run, `deserialize` returns `None` (correct), but 500 orphaned WAV files remain.

IMPACT:
Disk space leak. Not a correctness bug (the cache miss is handled correctly) but can cause disk exhaustion over time.

FIX DIRECTION:
Write to a temp directory first, then atomically rename to `dest_dir` on success. On failure, clean up the temp directory.

--------------------------------------------------------------------
FILE:        app/models/audio_artifact_serializer.py
FUNCTION:    AudioSampleHandler.serialize
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Write a list[AudioSample] to `dest_dir` as WAV + manifest.json.

WHAT IT ACTUALLY DOES:
For an empty list (`data = []`), the loop does not execute, `manifest_entries = []`, and `manifest.json` is written with `{"samples": []}`. `deserialize` on this manifest returns `[]` (empty list). This is correct behavior.

However, `serialize` does not validate that `data` is actually a list. If `data` is `None` or a non-iterable, `for i, sample in enumerate(data)` raises `TypeError`. The caller (artifact store) is expected to pass a list, but there is no guard.

EVIDENCE:
Line ~58: `for i, sample in enumerate(data):` — no type check on `data`.

REPRODUCTION SCENARIO:
A node's `process()` returns `None` for the audio output port. The artifact store calls `serialize(None, dest_dir)`. `enumerate(None)` raises `TypeError: 'NoneType' object is not iterable`.

IMPACT:
Unhandled `TypeError` propagates to the artifact store, which may not handle it gracefully. The error message is confusing ("NoneType is not iterable" rather than "expected list[AudioSample]").

FIX DIRECTION:
Add a guard: `if not isinstance(data, list): raise TypeError(f"Expected list[AudioSample], got {type(data).__name__}")`.

--------------------------------------------------------------------
FILE:        app/models/audio_artifact_serializer.py
FUNCTION:    AudioSampleHandler.compute_content_hash_input
CATEGORY:    Performance
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return a stable JSON string for SHA-256 hashing of a list[AudioSample].

WHAT IT ACTUALLY DOES:
For each sample, calls `raw_data.tobytes()` to compute a PCM hash. For large audio arrays (e.g., 10 minutes at 44100 Hz = 26.5M float32 samples = 106 MB), this materializes the entire audio data as a byte string just to compute a 16-character hex prefix. This is called every time the pipeline cache checks whether a node's output has changed.

EVIDENCE:
Lines ~120–130:
```python
pcm_hash = hashlib.sha256(raw_data.tobytes()).hexdigest()[:16]
```
Full `tobytes()` for potentially large arrays.

REPRODUCTION SCENARIO:
Pipeline cache calls `compute_content_hash_input` on a list of 100 × 10-minute audio samples. Each `tobytes()` call materializes 106 MB. Total: 10.6 GB of byte string allocation just for cache key computation.

IMPACT:
High memory usage and slow cache key computation for large audio datasets. Not a correctness bug.

FIX DIRECTION:
Hash only a fixed-size prefix (e.g., first 4096 bytes) of the audio data, combined with the array shape and dtype, for a fast approximate fingerprint:
```python
prefix = raw_data.flat[:1024].tobytes()  # first 1024 float32 values = 4 KB
pcm_hash = hashlib.sha256(prefix).hexdigest()[:16]
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
| Top Risk | `deserialize` returns `None` (cache miss) when any single WAV file in a checkpoint is corrupt, silently discarding all valid samples and forcing full re-execution of upstream nodes. |
