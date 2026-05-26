# Functional Review — app/domain/project_manager.py

**Group:** 12 — Domain & Models  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/domain/project_manager.py
FUNCTION:    ProjectManager.validate_annotations
CATEGORY:    Contract Mismatch
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return `{total_samples, annotated_count, unannotated_count, missing_labels}` where `missing_labels` is the set of WAV files with no annotation.

WHAT IT ACTUALLY DOES:
Collects all `.wav` files via `d.rglob("*.wav")` and stores their paths relative to the project dir. The annotations dict is keyed by `sample_path` values that were stored by `add_annotations` — which stores whatever `sample_path` the caller provides (could be absolute, relative to project, relative to version dir, or any other convention). The set subtraction `all_wav - annotated` compares these two key spaces, which are almost certainly in different formats.

THE BUG / RISK:
If annotations were added with paths like `"v1/train/yes/abc.wav"` (relative to project dir) but `rglob` produces `"v1/train/yes/abc.wav"` (also relative to project dir via `wav.relative_to(d)`), they match. However, if any caller stores annotations with absolute paths, or paths relative to the version dir, or paths from the ingestion service (which uses absolute paths), the intersection is empty and every WAV file appears as unannotated. This is a silent wrong result — `annotated_count` is 0 and `missing_labels` contains every file.

EVIDENCE:
Lines ~290–310:
```python
for wav in d.rglob("*.wav"):
    rel = str(wav.relative_to(d))
    all_wav.add(rel)
annotations = self._read_annotations_dict(name)
annotated = set(annotations.keys())
missing = sorted(all_wav - annotated)
```
No normalization of annotation keys before comparison.

REPRODUCTION SCENARIO:
1. `add_annotations(name, [{"sample_path": "/abs/path/to/v1/train/yes/abc.wav", "label": "yes"}])`
2. `validate_annotations(name)` → `all_wav` contains `"v1/train/yes/abc.wav"`, `annotated` contains `"/abs/path/to/v1/train/yes/abc.wav"` → intersection is empty → `annotated_count = 0`.

IMPACT:
Silent wrong result — callers believe all samples are unannotated when they are not. Quality gate decisions based on this output are incorrect.

FIX DIRECTION:
Normalize both key sets to the same relative-to-project-dir format before comparison. In `_read_annotations_dict`, attempt to resolve absolute paths relative to the project dir. Or document and enforce that `sample_path` must always be relative to the project dir.

--------------------------------------------------------------------
FILE:        app/domain/project_manager.py
FUNCTION:    ProjectManager._estimate_snr
CATEGORY:    Edge Case
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Estimate SNR using first 100ms as noise profile; supports 16-bit, 24-bit, and 32-bit PCM WAV files.

WHAT IT ACTUALLY DOES:
The 24-bit unpacking loop iterates `for i in range(0, len(raw) - 2, 3)`. For a `raw` buffer whose length is exactly a multiple of 3 (e.g., 300 bytes = 100 samples), `range(0, 298, 3)` stops at index 297, correctly reading the last 3-byte sample at indices 297, 298, 299. However, for a buffer of length 3 (one sample), `range(0, 1, 3)` = `[0]`, which reads `raw[0]`, `raw[1]`, `raw[2]` — correct. For a buffer of length 1 or 2 (truncated/corrupt file), `range(0, -1, 3)` or `range(0, 0, 3)` = empty — returns `[]`, which triggers the `not noise_samples` fallback and returns 20.0. This is safe but silently returns a fallback for corrupt files.

More critically: for multi-channel 24-bit audio, the channel-averaging loop assumes samples are interleaved as `[ch0_s0, ch1_s0, ch0_s1, ch1_s1, ...]`. The `_unpack_samples` function unpacks all bytes as individual samples without accounting for the fact that each "frame" contains `n_channels` samples. The channel-averaging code then does `sum(noise_samples[i:i + n_channels]) / n_channels` which is correct for the interleaved layout. However, for 24-bit stereo, `_unpack_samples` returns `2 * noise_frames` values (one per channel per frame), and the averaging loop steps by `n_channels=2`, which is correct. This appears to work.

The real bug: `raw_signal = wf.readframes(n_frames - noise_frames)` — if `n_frames == noise_frames` (file is ≤ 100ms long), `raw_signal` is `b""` and `signal_samples = []`. The code then sets `signal_arr = [0.0]`, computes `signal_rms = 0.0`, and returns `20.0 * log10(max(0.0 / noise_rms, 1e-6))` = `20.0 * log10(1e-6)` = `-120.0 dB`. This is returned as the SNR for a file shorter than 100ms, which is a misleadingly low value (the file may be perfectly clean speech).

EVIDENCE:
Lines ~700–730 (in the full file):
```python
raw_signal = wf.readframes(n_frames - noise_frames)
...
signal_samples = _unpack_samples(raw_signal, sampwidth) if raw_signal else []
...
signal_arr = signal_samples if signal_samples else [0.0]
signal_rms = (sum(x**2 for x in signal_arr) / max(len(signal_arr), 1)) ** 0.5
```
For a 50ms file: `signal_arr = [0.0]`, `signal_rms = 0.0`, SNR = -120 dB.

REPRODUCTION SCENARIO:
Call `get_stats` on a version containing short (< 100ms) WAV files. The SNR histogram will show -120 dB for all short files, triggering false class-imbalance or outlier warnings.

IMPACT:
Silent wrong result — SNR is reported as -120 dB for files shorter than the noise profile window. Downstream quality decisions based on SNR are incorrect for short clips.

FIX DIRECTION:
When `n_frames <= noise_frames`, return a sentinel (e.g., `None` or `float('nan')`) and exclude these files from the SNR histogram, or use the entire file as both noise and signal estimate with a warning.

--------------------------------------------------------------------
FILE:        app/domain/project_manager.py
FUNCTION:    ProjectManager.create_snapshot
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Copy current working files to `snapshots/{snapshot_name}/`.

WHAT IT ACTUALLY DOES:
Iterates `d.iterdir()` and copies all items that are not version dirs and not the `snapshots` dir itself. However, it does not validate `snapshot_name` — any string is accepted, including `"."`, `".."`, `"../../../etc"`, or names with path separators. `self._snapshots_dir(name) / snapshot_name` would resolve to an arbitrary path outside the project directory.

EVIDENCE:
Lines ~530–545:
```python
snap_dir = self._snapshots_dir(name) / snapshot_name
snap_dir.mkdir(parents=True, exist_ok=True)
```
No validation of `snapshot_name`.

REPRODUCTION SCENARIO:
`create_snapshot("myproject", "../../../tmp/evil")` → `snap_dir` resolves to a path outside the workspace → files are copied there.

IMPACT:
Path traversal — arbitrary file write outside the workspace. Severity is MEDIUM because the API layer may validate snapshot names before calling this method, but the domain layer itself provides no defense.

FIX DIRECTION:
Apply `_validate_name(snapshot_name)` before constructing `snap_dir`, or add a boundary check: `assert snap_dir.resolve().is_relative_to(self._snapshots_dir(name).resolve())`.

--------------------------------------------------------------------
FILE:        app/domain/project_manager.py
FUNCTION:    ProjectManager.restore_version / restore_snapshot
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Atomically restore version/snapshot contents to the project root working area.

WHAT IT ACTUALLY DOES:
The temp directory is created at `d.parent / f".restore_tmp_{uuid}"` — i.e., as a sibling of the project directory, not inside it. `shutil.move(str(item), str(dst))` is used to move items from the temp dir to the project root. On Linux, `shutil.move` uses `os.rename` when source and destination are on the same filesystem, which is atomic. However, if `d.parent` and `d` are on different filesystems (e.g., `d.parent` is a mount point), `shutil.move` falls back to copy+delete, which is not atomic.

Additionally, `restore_version` does not validate the `version` string — any string is accepted, including `"."`, `".."`, or names with path separators. `d / version` could resolve outside the project directory.

EVIDENCE:
Lines ~460–490 (`restore_version`):
```python
version_dir = d / version
if not version_dir.exists():
    raise FileNotFoundError(...)
```
No validation that `version` is a safe path component.

REPRODUCTION SCENARIO:
`restore_version("myproject", "../other_project/v1")` → `version_dir` resolves to another project's version directory → its contents are copied into `myproject`.

IMPACT:
Path traversal — contents of arbitrary directories can be copied into the project root. MEDIUM because the API layer may validate version strings.

FIX DIRECTION:
Validate `version` with `_VERSION_RE` before use (the regex is already defined on the class). Add: `if not self._VERSION_RE.match(version): raise ValueError(...)`.

--------------------------------------------------------------------
FILE:        app/domain/project_manager.py
FUNCTION:    ProjectManager.deduplicate
CATEGORY:    Performance
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Find duplicate WAV files by SHA-256 hash.

WHAT IT ACTUALLY DOES:
Reads every WAV file in the version directory in full to compute SHA-256. For large datasets (tens of thousands of files), this is O(N × file_size) I/O with no progress reporting and no cancellation mechanism. The method runs synchronously in the API request handler thread.

EVIDENCE:
Lines ~800–825:
```python
for wav in sorted(version_dir.rglob("*.wav")):
    h = self._sha256_wav(wav)
    hash_to_files.setdefault(h, []).append(wav)
```
No batching, no progress, no timeout.

REPRODUCTION SCENARIO:
Version directory with 50,000 WAV files of 1 MB each = 50 GB of I/O in a single synchronous call.

IMPACT:
API request timeout / thread starvation. Not a correctness bug but a performance correctness issue — the method cannot complete in a reasonable time for large datasets.

FIX DIRECTION:
Run in a background thread (like ingestion jobs), or add a `max_files` limit with a warning, or use file size + first-N-bytes as a pre-filter before full SHA-256.

--------------------------------------------------------------------
FILE:        app/domain/project_manager.py
FUNCTION:    ProjectManager.generate_dataset_card
CATEGORY:    Silent Failure Risk
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Generate README.md markdown with stats, label distribution, citation template.

WHAT IT ACTUALLY DOES:
Uses `datetime.datetime.utcnow().year` in the BibTeX citation block. `utcnow()` is deprecated in Python 3.12+ and will be removed in a future version. It also does not use timezone-aware datetime, inconsistent with `_now()` which uses `datetime.timezone.utc`.

EVIDENCE:
Near end of file:
```python
year = {{{datetime.datetime.utcnow().year}}},
```

REPRODUCTION SCENARIO:
Python 3.12+ emits a `DeprecationWarning` on every call to `generate_dataset_card`.

IMPACT:
Low — deprecation warning only; no functional impact until `utcnow()` is removed.

FIX DIRECTION:
Replace with `datetime.datetime.now(datetime.timezone.utc).year`.

--------------------------------------------------------------------
FILE:        app/domain/project_manager.py
FUNCTION:    ProjectManager.list_all
CATEGORY:    Error Handling
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Return list of all project.json contents.

WHAT IT ACTUALLY DOES:
Calls `self._read_json(proj_file, {})` for each project directory. If `project.json` is malformed JSON, `_read_json` calls `json.load(f)` which raises `json.JSONDecodeError` — this exception is NOT caught in `_read_json` (the method has no try/except). The exception propagates out of `list_all`, causing the entire listing to fail because of one corrupt project file.

EVIDENCE:
`_read_json` (lines ~75–80):
```python
@staticmethod
def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)   # no try/except
```

REPRODUCTION SCENARIO:
One project's `project.json` is truncated (disk full during write). `list_all()` raises `json.JSONDecodeError` and returns nothing.

IMPACT:
The entire project listing API endpoint fails because of one corrupt file. Other projects are inaccessible.

FIX DIRECTION:
Wrap `json.load` in a try/except in `_read_json`, or add a try/except in `list_all` per-project iteration.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | `validate_annotations` silently returns wrong counts when annotation `sample_path` keys use a different path format than the WAV file paths discovered by `rglob`, causing all samples to appear unannotated. |
