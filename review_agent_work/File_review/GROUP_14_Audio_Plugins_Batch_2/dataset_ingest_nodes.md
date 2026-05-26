# Functional Review — PluginPackage/Audio/dataset_ingest/nodes.py

**Group:** 14 — Audio Plugins Batch 2
**Reviewed:** 2026-05-26
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/dataset_ingest/nodes.py
FUNCTION:    DatasetIngestNode._load_zip
CATEGORY:    Resource Leak
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Extract ZIP to a temp directory, then scan as filesystem.

WHAT IT ACTUALLY DOES:
Uses `tempfile.TemporaryDirectory()` as a context manager, which deletes the
temp dir when the `with` block exits. `_load_filesystem(tmp_dir)` is called
inside the `with` block and returns a list of `AudioSample` objects. Each
`AudioSample` stores `path=file_path` where `file_path` is a path inside
`tmp_dir`. When the `with` block exits, `tmp_dir` is deleted — but the
`AudioSample.path` fields still point to the now-deleted temp paths.

THE BUG / RISK:
Any downstream node that tries to re-read the audio file from `sample.path`
(e.g., for integrity checks, re-loading, or provenance) will get a
FileNotFoundError. The audio data itself is in `sample.data` (loaded by
librosa), so the data is not lost — but the path metadata is a dangling
reference.

EVIDENCE:
```python
with tempfile.TemporaryDirectory() as tmp_dir:
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(tmp_dir)
    samples = self._load_filesystem(tmp_dir)
# tmp_dir deleted here; sample.path values are now dangling
return samples
```

REPRODUCTION SCENARIO:
node = DatasetIngestNode(config=Config(source_type="zip", path="data.zip"))
samples = node.process({})["output"]
# samples[0].path → "/tmp/tmpXXXXXX/class_a/file.wav" (deleted)
Path(samples[0].path).exists()  # → False

IMPACT:
Dangling path references in all AudioSample objects from ZIP/TAR ingestion.
Any downstream node relying on sample.path for re-reading will fail.

FIX DIRECTION:
After loading, rewrite each sample's path to the original zip path + internal
member path, or document that path is not valid after ZIP extraction:
```python
samples = self._load_filesystem(tmp_dir)
# Rewrite paths to canonical form: zip_path::member_path
for s in samples:
    rel = os.path.relpath(s.path, tmp_dir)
    s.path = f"{zip_path}::{rel}"
return samples
```
The same issue applies to `_load_tar`.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/dataset_ingest/nodes.py
FUNCTION:    DatasetIngestNode._load_tar
CATEGORY:    Resource Leak
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Extract TAR archive to a temp directory, then scan as filesystem.

WHAT IT ACTUALLY DOES:
Identical dangling-path issue as `_load_zip` — temp dir is deleted after
`_load_filesystem()` returns, leaving all `AudioSample.path` values pointing
to deleted temp files.

EVIDENCE:
```python
with tempfile.TemporaryDirectory() as tmp_dir:
    with tarfile.open(tar_path, "r:*") as tf:
        tf.extractall(tmp_dir, members=_safe_members(tf, tmp_dir))
    samples = self._load_filesystem(tmp_dir)
# tmp_dir deleted; sample.path values are dangling
return samples
```

REPRODUCTION SCENARIO:
Same as _load_zip above, with source_type="tar".

IMPACT:
Same as _load_zip — dangling path references in all returned AudioSample objects.

FIX DIRECTION:
Same as _load_zip — rewrite paths or document the limitation.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/dataset_ingest/nodes.py
FUNCTION:    DatasetIngestNode._load_filesystem
CATEGORY:    Performance
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Walk directory tree; subdirectory names become labels. Supports resume checkpoint.

WHAT IT ACTUALLY DOES:
`_append_checkpoint(file_path)` is called for every successfully loaded file,
opening and closing the checkpoint file once per file. For a dataset of 100,000
files, this is 100,000 file open/close/write/flush operations — one per file.
On network filesystems or slow disks, this is catastrophically slow.

Additionally, `_load_checkpoint()` is called once at the start and returns a
`set[str]`. For large checkpoints (100k+ entries), loading the entire set into
memory at startup is acceptable, but the per-file append pattern means the
checkpoint file grows to 100k lines with no compaction.

THE BUG / RISK:
On large datasets, the per-file checkpoint append makes ingestion O(N) file
operations just for checkpointing, independent of the actual audio loading.
This can make ingestion 10-100x slower than necessary.

EVIDENCE:
```python
for fname in audio_files:
    ...
    sample = self._load_file(file_path, dir_label, ...)
    if sample is not None:
        samples.append(sample)
        label_counts[dir_label] = ...
        self._append_checkpoint(file_path)  # file open/write/close per file
```

REPRODUCTION SCENARIO:
Dataset with 100,000 files → 100,000 checkpoint file opens.
On NFS: ~1ms per open → 100 seconds just for checkpointing.

IMPACT:
Severe performance degradation on large datasets with resume_from enabled.

FIX DIRECTION:
Batch checkpoint writes — collect paths and flush every N files (e.g., N=100):
```python
checkpoint_buffer = []
...
checkpoint_buffer.append(file_path)
if len(checkpoint_buffer) >= 100:
    self._flush_checkpoint(checkpoint_buffer)
    checkpoint_buffer.clear()
# flush remainder after loop
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/dataset_ingest/nodes.py
FUNCTION:    DatasetIngestNode._load_s3
CATEGORY:    Resource Leak
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Scan an S3 bucket/prefix and load matching audio files; clean up temp files.

WHAT IT ACTUALLY DOES:
The `finally: os.unlink(tmp_path)` block correctly cleans up the temp file
after each S3 download. However, if `s3.download_file()` raises an exception
(e.g., network error, permission denied), the exception propagates out of the
`try` block, the `finally` runs (correct), but the exception is NOT caught —
it propagates up to `process()` and aborts the entire ingestion run, losing
all samples loaded so far.

THE BUG / RISK:
A single S3 download failure aborts the entire dataset ingestion. For large
datasets with occasional network errors, this means the entire run must be
restarted from the checkpoint.

EVIDENCE:
```python
try:
    s3.download_file(bucket, key, tmp_path)
    sample = self._load_file(tmp_path, label, ...)
    ...
finally:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
# No except for download failure — propagates up
```

REPRODUCTION SCENARIO:
S3 download fails for one file (transient network error).
→ entire _load_s3() aborts; all previously loaded samples lost.

IMPACT:
Data loss on transient errors; no partial result recovery.

FIX DIRECTION:
```python
try:
    s3.download_file(bucket, key, tmp_path)
    sample = self._load_file(...)
    ...
except Exception as exc:
    log.warning("DatasetIngestNode: failed to download S3 key '%s': %s", key, exc)
    sample = None
finally:
    ...
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/dataset_ingest/nodes.py
FUNCTION:    DatasetIngestNode._load_manifest
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Load from CSV or JSON manifest with columns: path, label.

WHAT IT ACTUALLY DOES:
For CSV manifests, uses `csv.DictReader` which silently returns `None` for
missing columns (when the CSV has no header row or the header doesn't match
"path"/"label"). `entry.get("path", "")` returns `""` for a missing column,
which triggers the `if not file_path: log.warning(...)` guard — so this is
handled. However, if the CSV has a BOM (byte order mark) at the start, the
first column header becomes `"\ufeffpath"` instead of `"path"`, causing all
path values to be silently empty and all entries to be skipped with a warning.

THE BUG / RISK:
CSV files saved from Excel or Windows tools often have a UTF-8 BOM. The
`open(..., encoding="utf-8")` call does not strip the BOM, so the first
column header is `"\ufeffpath"` and all entries are silently skipped.

EVIDENCE:
```python
with open(manifest_path, "r", encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f)
    entries = list(reader)
# If CSV has BOM, first header is "\ufeffpath" not "path"
```

REPRODUCTION SCENARIO:
manifest.csv saved from Excel with UTF-8 BOM encoding.
→ all entries skipped with "manifest entry missing 'path'" warnings.
→ returns empty list silently.

IMPACT:
Silent empty result — entire dataset ingestion produces zero samples with
only per-entry warnings; no top-level error indicating the manifest is malformed.

FIX DIRECTION:
```python
with open(manifest_path, "r", encoding="utf-8-sig", newline="") as f:
```
`utf-8-sig` automatically strips the BOM.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/dataset_ingest/nodes.py
FUNCTION:    DatasetIngestNode._deduplicate
CATEGORY:    Performance
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Remove duplicate waveforms using an MD5 hash of the data bytes. Stores only
32-byte hex strings to avoid OOM.

WHAT IT ACTUALLY DOES:
`s.data.tobytes()` materialises the entire waveform as a bytes object in memory
before hashing. For a 10-minute audio file at 16kHz float32, this is
10*60*16000*4 = ~38MB per sample. For a dataset of 10,000 such files, the
peak memory during deduplication is 38MB * (batch size) just for the tobytes()
call, plus the MD5 computation.

More critically: `hashlib.md5()` is used for deduplication. MD5 has known
collision vulnerabilities. While accidental collisions are extremely rare for
audio data, using MD5 for data integrity is a code smell. The docstring in
`_load_file` uses SHA256 for integrity — the inconsistency is confusing.

THE BUG / RISK:
Memory spike during deduplication of large audio files. MD5 collision risk
(low probability but non-zero for adversarial inputs).

EVIDENCE:
```python
key = hashlib.md5(s.data.tobytes()).hexdigest()
```

REPRODUCTION SCENARIO:
Dataset with 1000 x 10-minute audio files.
→ each tobytes() call allocates 38MB; peak memory = 38MB * concurrent samples.

IMPACT:
OOM risk on large datasets; MD5 collision risk (low).

FIX DIRECTION:
Use a rolling hash or hash only a prefix of the data for large files:
```python
# Hash first 64KB + length as a fast dedup key
data_bytes = s.data.tobytes()
key = hashlib.sha256(data_bytes[:65536] + str(len(data_bytes)).encode()).hexdigest()
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/dataset_ingest/nodes.py
FUNCTION:    DatasetIngestNode._load_filesystem (non-recursive branch)
CATEGORY:    Contract Mismatch
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Non-recursive mode: only files directly in root_path. Applies limit per label.

WHAT IT ACTUALLY DOES:
In the non-recursive branch, the limit check is `if self.config.limit > 0 and len(samples) >= self.config.limit: break`.
This limits the TOTAL number of samples, not per-label. In the recursive branch,
the limit is per-label (`label_counts.get(dir_label, 0) >= self.config.limit`).
The two branches have inconsistent limit semantics.

EVIDENCE:
```python
# Recursive branch: per-label limit
if label_counts.get(dir_label, 0) >= self.config.limit:
    continue

# Non-recursive branch: total limit
if self.config.limit > 0 and len(samples) >= self.config.limit:
    break
```

REPRODUCTION SCENARIO:
recursive=False, limit=10, root_path has 20 files.
→ stops after 10 total files (correct for total limit).
recursive=True, limit=10, two subdirs with 20 files each.
→ takes 10 from each subdir = 20 total (per-label limit).

IMPACT:
Inconsistent behavior between recursive and non-recursive modes; users
expecting per-label limits in non-recursive mode will get total limits.

FIX DIRECTION:
Document the difference explicitly, or unify the limit semantics.

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
| Top Risk | ZIP and TAR ingestion produce AudioSample objects with dangling path references pointing to deleted temp directories — any downstream node that re-reads from sample.path will get FileNotFoundError. |
