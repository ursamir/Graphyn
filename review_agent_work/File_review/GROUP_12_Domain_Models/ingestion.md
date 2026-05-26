# Functional Review — app/domain/ingestion.py

**Group:** 12 — Domain & Models  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/domain/ingestion.py
FUNCTION:    IngestionService.stream_job
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Yield progress events from the job as they arrive, polling until the job is no longer running.

WHAT IT ACTUALLY DOES:
Calls `self.get_job(job_id)` once at the start, then polls `job.status` and `job.read_progress()` on the returned object. When the job was loaded from Redis (cross-worker path), the returned `IngestionJob` is a frozen snapshot — its `status` and `progress` fields are never updated after construction.

THE BUG / RISK:
For Redis-backed cross-worker streaming, `stream_job` will yield all events that existed at the moment `get_job()` was called, then immediately exit the loop because `job.status` is already `"completed"` or `"failed"` in the snapshot. Any events appended after the snapshot was taken are silently dropped. The caller receives a partial event stream with no indication that it is incomplete.

EVIDENCE:
Lines ~370–395 (`stream_job`): `job = self.get_job(job_id)` — single call, no re-fetch.  
Lines ~130–145 (`_load_job_from_redis`): constructs a new `IngestionJob` from Redis data at a single point in time; the object is never refreshed.

REPRODUCTION SCENARIO:
1. Worker A starts a URL job with 10 URLs.
2. Worker B calls `stream_job(job_id)` while the job is still running.
3. `get_job` falls through to Redis, which has 3 events so far and `status="running"`.
4. `stream_job` yields those 3 events, then checks `job.status` — still `"running"` on the snapshot.
5. Worker A appends 7 more events and sets status to `"completed"`.
6. The snapshot object on Worker B never sees these updates; the loop spins forever (or until the process is killed).

IMPACT:
Infinite loop / hang in the SSE streaming path for cross-worker scenarios. Callers (API SSE endpoint) will hang indefinitely, consuming a connection and a thread.

FIX DIRECTION:
For the Redis path, `stream_job` must re-poll Redis on each iteration rather than relying on the in-memory snapshot. Either re-fetch the job from Redis each loop iteration, or implement a Redis pub/sub or BLPOP-based streaming approach. Minimum fix:
```python
while True:
    job = self.get_job(job_id)   # re-fetch each iteration
    current_events = job.read_progress()
    ...
```

--------------------------------------------------------------------
FILE:        app/domain/ingestion.py
FUNCTION:    IngestionService._run_url_job
CATEGORY:    Resource Leak
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Download each URL, validate, and check for corruption; write to dest_dir.

WHAT IT ACTUALLY DOES:
Opens `dest_path` for writing with `open(dest_path, "wb")`, then inside the same `with` block checks the download size limit. When the limit is exceeded, it calls `out_f.close()` explicitly and then `dest_path.unlink()`. However, `out_f.close()` is called while still inside the `with open(...)` block — the `with` statement will call `close()` again on exit, which is harmless for files but the real issue is that `out_f.close()` is called before the `with` block exits, meaning the `raise ValueError(...)` that follows will propagate out of the `with` block, which will attempt to close an already-closed file handle.

THE BUG / RISK:
The double-close is benign for regular files in CPython, but the `dest_path.unlink(missing_ok=True)` is called inside the `with open(dest_path, "wb") as out_f:` block after `out_f.close()`. On Windows, unlinking an open file handle raises `PermissionError`. On Linux this works, but the pattern is fragile. More critically: if `dest_path.unlink()` itself raises (e.g., permission denied), the `ValueError` is swallowed and the oversized partial file is left on disk.

EVIDENCE:
Lines ~230–245:
```python
with open(dest_path, "wb") as out_f:
    for chunk in response.iter_bytes(chunk_size=65536):
        total_bytes += len(chunk)
        if total_bytes > _MAX_DOWNLOAD_BYTES:
            out_f.close()
            dest_path.unlink(missing_ok=True)
            raise ValueError(...)
        out_f.write(chunk)
```

REPRODUCTION SCENARIO:
On Windows: download a file > 500 MB. `out_f.close()` is called, then `dest_path.unlink()` raises `PermissionError` because the `with` block still holds the file open at the OS level (the explicit `close()` may not flush the OS handle on all platforms).

IMPACT:
Partial oversized files left on disk; potential `PermissionError` on Windows that is caught by the outer `except Exception` and reported as a download failure with a confusing message.

FIX DIRECTION:
Close and unlink outside the `with` block, or use a flag:
```python
size_exceeded = False
with open(dest_path, "wb") as out_f:
    for chunk in ...:
        total_bytes += len(chunk)
        if total_bytes > _MAX_DOWNLOAD_BYTES:
            size_exceeded = True
            break
        out_f.write(chunk)
if size_exceeded:
    dest_path.unlink(missing_ok=True)
    raise ValueError(...)
```

--------------------------------------------------------------------
FILE:        app/domain/ingestion.py
FUNCTION:    IngestionService._run_hf_job
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Stream a HuggingFace dataset and save audio samples; set status to "completed" or "failed".

WHAT IT ACTUALLY DOES:
When `_get_audio_duration` returns `None` for a saved sample, it silently sets `duration = 0.0` and counts the sample as a success (`total_files += 1`). A file that could not be decoded is counted as successfully ingested.

EVIDENCE:
Lines ~340–355:
```python
duration = _get_audio_duration(str(saved_path))
if duration is None:
    duration = 0.0
total_files += 1
total_duration += duration
```

REPRODUCTION SCENARIO:
HuggingFace dataset contains a sample whose `array` is all zeros or whose format soundfile/librosa cannot decode. `_save_hf_audio_sample` writes the file, `_get_audio_duration` fails to decode it and returns `None`, but the sample is still counted as a success.

IMPACT:
Silent wrong result — the summary event reports more successfully ingested files than are actually usable. Downstream quality checks may flag these files, but the ingestion job reports success.

FIX DIRECTION:
Treat `duration is None` as a soft warning (not a hard failure), but do not count the sample in `total_files`. Log a warning and emit a progress event with `status="warning"`.

--------------------------------------------------------------------
FILE:        app/domain/ingestion.py
FUNCTION:    _register_job (module-level)
CATEGORY:    State Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Add a job to the in-process store, evicting old completed jobs if over the limit.

WHAT IT ACTUALLY DOES:
The eviction logic acquires `_jobs_lock`, checks `len(_jobs) > _MAX_COMPLETED_JOBS`, then removes completed/failed jobs. However, the newly registered job is added to `_jobs` before the eviction check, so the condition `len(_jobs) > _MAX_COMPLETED_JOBS` is evaluated with the new job already present. The slice `to_remove[:len(_jobs) - _MAX_COMPLETED_JOBS]` uses `len(_jobs)` after the new job is added, which is correct in intent but the comment says "evicting old completed jobs when over the limit" — the limit is 200, but the check fires when `len > 200`, meaning up to 201 jobs can exist momentarily. This is minor but the eviction count calculation uses the live `len(_jobs)` which includes the new job, so it may evict one more job than necessary.

EVIDENCE:
Lines ~175–185:
```python
_jobs[job.job_id] = job          # added first
if len(_jobs) > _MAX_COMPLETED_JOBS:
    to_remove = [...]
    for jid in to_remove[:len(_jobs) - _MAX_COMPLETED_JOBS]:
```
`len(_jobs)` here is already `_MAX_COMPLETED_JOBS + 1` (new job included), so `len(_jobs) - _MAX_COMPLETED_JOBS = 1`. This is actually correct for the common case, but if multiple threads call `_register_job` concurrently and both pass the `len > 200` check before either evicts, both will try to evict the same jobs, potentially causing a `KeyError` on `del _jobs[jid]` if the key was already removed by the other thread.

REPRODUCTION SCENARIO:
Two threads call `start_url_job` simultaneously when `len(_jobs) == 200`. Both acquire `_jobs_lock` sequentially (lock is held), so this is actually safe — the lock prevents the race. The real issue is the off-by-one: the dict can grow to 201 before eviction fires.

IMPACT:
Low — at most 1 extra job in memory. Not a crash risk due to the lock.

FIX DIRECTION:
Change condition to `>= _MAX_COMPLETED_JOBS` to keep the dict at exactly `_MAX_COMPLETED_JOBS` entries.

--------------------------------------------------------------------
FILE:        app/domain/ingestion.py
FUNCTION:    IngestionService._run_url_job
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Validate extension before downloading; skip unsupported extensions.

WHAT IT ACTUALLY DOES:
Uses `Path(url_path).suffix.lower()` to extract the extension from the URL path component. For URLs with query strings (e.g., `https://cdn.example.com/audio?file=speech.wav&token=abc`), `urlparse(url).path` returns `/audio` (no extension), so `suffix` is `""`, which is not in `SUPPORTED_EXTENSIONS`, and the URL is skipped with an "unsupported extension" error even though the file is a valid WAV.

EVIDENCE:
Lines ~210–225:
```python
parsed = urlparse(url)
url_path = parsed.path
suffix = Path(url_path).suffix.lower()
if suffix not in SUPPORTED_EXTENSIONS:
    ...continue
```

REPRODUCTION SCENARIO:
`url = "https://storage.example.com/audio?key=speech.wav"` → `parsed.path = "/audio"` → `suffix = ""` → skipped.

IMPACT:
Silent skip of valid audio URLs that use query-string-based routing. No error is raised to the caller — the URL is silently skipped with a misleading "unsupported extension" message.

FIX DIRECTION:
Also check the `Content-Type` response header after a HEAD request, or parse the `key` query parameter as a fallback for extension detection.

--------------------------------------------------------------------
FILE:        app/domain/ingestion.py
FUNCTION:    _save_hf_audio_sample
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Save a HuggingFace audio sample dict to dest_dir as a WAV file.

WHAT IT ACTUALLY DOES:
When `original_path` is provided, uses `Path(original_path).stem` as the filename stem without any sanitization. If `original_path` contains path separators (e.g., `"../../etc/passwd"`), `Path(original_path).stem` returns `"passwd"` (safe), but if it contains characters invalid for filenames on the target OS (e.g., `:`, `*`, `?` on Windows), `sf.write()` will raise an `OSError` that is caught and returns `None`, silently failing.

EVIDENCE:
Lines ~590–605:
```python
if original_path:
    stem = Path(original_path).stem
    filename = f"{stem}.wav"
```
No sanitization of `stem`.

REPRODUCTION SCENARIO:
HuggingFace dataset has `audio["path"] = "C:\\Users\\user\\audio.wav"` → `stem = "audio"` (safe on Linux). On Windows with `audio["path"] = "con"` → `filename = "con.wav"` → reserved name on Windows → `sf.write` raises `OSError`.

IMPACT:
Silent failure on Windows for reserved filenames; potential unexpected filenames from untrusted dataset metadata.

FIX DIRECTION:
Apply `_sanitize_label` or a similar regex to `stem` before using it as a filename.

--------------------------------------------------------------------
FILE:        app/domain/ingestion.py
FUNCTION:    IngestionService.stream_job (Redis path — infinite loop variant)
CATEGORY:    Async Bug
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Poll job progress until the job is no longer running.

WHAT IT ACTUALLY DOES:
When the job is loaded from Redis and `status` is already `"running"` in the snapshot (job started but not yet complete on another worker), the loop polls `job.read_progress()` on the frozen snapshot object. Since the snapshot never updates, `job.status` remains `"running"` forever, and the loop never exits.

EVIDENCE:
Lines ~370–395: `job = self.get_job(job_id)` — single fetch. The `while True` loop checks `job.status != "running"` on the same frozen object.

REPRODUCTION SCENARIO:
Cross-worker: job is `"running"` when `stream_job` is called. The snapshot has `status="running"`. The loop spins indefinitely at 10 Hz, consuming CPU.

IMPACT:
Infinite loop / CPU spin in the SSE streaming thread. This is the same root cause as the HIGH finding above but manifests differently (spin vs. premature exit depending on job state at snapshot time).

FIX DIRECTION:
Same as the HIGH finding — re-fetch from Redis each iteration.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | UNSAFE |
| State Safety | SAFE |
| Resource Safety | UNSAFE |
| Test Hostile | PARTIAL |
| Top Risk | `stream_job` hangs indefinitely or returns a partial event stream for cross-worker Redis-backed jobs due to a frozen snapshot object that is never refreshed. |
