# Functional Review — PluginPackage/Audio/audio_exporter/nodes.py

**Group:** 13 — Audio Plugins Batch 1  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_exporter/nodes.py
FUNCTION:    AudioExporterNode.process
CATEGORY:    Error Handling
SEVERITY:    CRITICAL
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Export AudioSample objects to WAV files; if `append=False`, clear the output
directory first.

WHAT IT ACTUALLY DOES:
When `append=False` and `out_root.exists()`, calls `shutil.rmtree(out_root)`.
This is a destructive, irreversible operation. If `output_dir` is misconfigured
(e.g. set to `"."`, `"/"`, or a parent directory), `shutil.rmtree` will
silently delete the entire directory tree including source files, other
pipeline outputs, or system directories.

There is no validation that `output_dir` is a safe path (not `/`, not `.`,
not a parent of the workspace root, not a path containing `..`).

EVIDENCE:
```python
if not cfg.append and out_root.exists():
    import shutil
    shutil.rmtree(out_root)
```
`out_root = Path(cfg.output_dir) / cfg.version_tag` — if `output_dir="/"`,
`out_root = Path("/v1")` which is a root-level directory.

REPRODUCTION SCENARIO:
Set `output_dir="/"` and `version_tag="tmp"`. `shutil.rmtree("/tmp")` deletes
the system temp directory.

IMPACT:
Irreversible data loss; potential system damage.

FIX DIRECTION:
Validate `output_dir` is a relative path or is under a known safe root:
```python
out_root_resolved = out_root.resolve()
workspace_root = Path.cwd().resolve()
if not str(out_root_resolved).startswith(str(workspace_root)):
    raise ValueError(f"output_dir '{cfg.output_dir}' is outside the workspace root")
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_exporter/nodes.py
FUNCTION:    AudioExporterNode.process
CATEGORY:    Error Handling
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Write a `labels.csv` and `metadata.json` summary after exporting WAV files.

WHAT IT ACTUALLY DOES:
If `soundfile.write()` raises (e.g. disk full, permission denied, invalid
sample rate), the exception propagates uncaught, leaving the output directory
in a partially written state. The `labels.csv` and `metadata.json` are written
after all WAV files, so a mid-batch failure leaves no manifest for the files
that were successfully written.

EVIDENCE:
```python
sf.write(str(wav_path), data, sample.sample_rate)
# No try/except — disk full raises here, leaving partial output
```
`labels.csv` and `metadata.json` are written after the loop — never reached
on failure.

REPRODUCTION SCENARIO:
Disk fills up after writing 500 of 1000 WAV files.

IMPACT:
Partial output with no manifest; the 500 written files are orphaned with no
labels.csv to reference them.

FIX DIRECTION:
Write `labels.csv` and `metadata.json` incrementally, or wrap the loop in
try/except and write a partial manifest on failure.

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_exporter/nodes.py
FUNCTION:    AudioExporterNode.process
CATEGORY:    Silent Failure
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Assign splits to samples using `split_ratios`.

WHAT IT ACTUALLY DOES:
`sample.metadata.get("split")` returns the pre-assigned split if present.
The check `if split not in splits` falls through to random assignment if the
pre-assigned split is not in the configured `split_ratios` keys. However,
if `split_ratios` is empty (`{}`), `splits = []` and `weights = []`, and
`rng.choices([], weights=[], k=1)` raises `IndexError: Cannot choose from
an empty sequence`.

EVIDENCE:
```python
splits = list(cfg.split_ratios.keys())
weights = list(cfg.split_ratios.values())
...
split = rng.choices(splits, weights=weights, k=1)[0]
```
No guard for `len(splits) == 0`.

REPRODUCTION SCENARIO:
Set `split_ratios={}`.

IMPACT:
`IndexError` crash on first sample that needs split assignment.

FIX DIRECTION:
```python
if not splits:
    raise ValueError("AudioExporterNode: split_ratios must not be empty")
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_exporter/nodes.py
FUNCTION:    AudioExporterNode.process
CATEGORY:    Silent Failure
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Re-index rows in append mode to avoid ID collisions.

WHAT IT ACTUALLY DOES:
In append mode, re-indexes new rows by adding `offset = len(existing_rows)`:
```python
for r in rows:
    r["id"] = r["id"] + offset
```
However, `rows` is built with `idx` from `enumerate(samples)` starting at 0.
If the existing CSV has 100 rows, new rows get IDs 100, 101, ... — correct.
But `meta_entries` is built in parallel with `rows` and uses the original
`idx` (0-based), not the re-indexed ID. So `labels.csv` has IDs 100-199 but
`metadata.json` has IDs 0-99 for the same samples — the two files are
inconsistent.

EVIDENCE:
```python
rows.append({"id": idx, ...})
meta_entries.append({"id": idx, ...})
# Later:
for r in rows:
    r["id"] = r["id"] + offset  # only rows is re-indexed, not meta_entries
```

REPRODUCTION SCENARIO:
Run with `append=True` on a directory with 50 existing entries. `labels.csv`
IDs = 50-99; `metadata.json` IDs = 0-49.

IMPACT:
Silent data inconsistency between `labels.csv` and `metadata.json`; downstream
tools joining on `id` will get wrong matches.

FIX DIRECTION:
Re-index `meta_entries` in the same loop:
```python
for r, m in zip(rows, meta_entries):
    r["id"] = r["id"] + offset
    m["id"] = m["id"] + offset
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_exporter/nodes.py
FUNCTION:    AudioExporterNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Avoid filename collisions by appending a counter suffix.

WHAT IT ACTUALLY DOES:
The collision-avoidance loop:
```python
counter = 0
while wav_path.exists():
    counter += 1
    wav_path = label_dir / f"{stem}_{counter:03d}.wav"
```
Has no upper bound on `counter`. In a directory with thousands of existing
files with the same stem, this loop runs indefinitely (or until the filesystem
is exhausted). In practice this is unlikely but the loop is unbounded.

EVIDENCE:
```python
while wav_path.exists():
    counter += 1
    wav_path = label_dir / f"{stem}_{counter:03d}.wav"
```

REPRODUCTION SCENARIO:
Directory already contains `sample_000000.wav` through `sample_000999.wav`.
Loop runs 1000 iterations before finding a free name.

IMPACT:
Performance degradation; potential infinite loop if filesystem is full and
`wav_path.exists()` always returns True due to OS error.

FIX DIRECTION:
Add a maximum iteration guard:
```python
if counter > 9999:
    raise RuntimeError(f"Too many collisions for stem '{stem}'")
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_exporter/nodes.py
FUNCTION:    AudioExporterNode.process
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Compute `duration_s` for each exported sample.

WHAT IT ACTUALLY DOES:
```python
"duration_s": round(len(data) / sample.sample_rate, 4) if sample.sample_rate else 0,
```
If `sample.sample_rate` is 0 (invalid), the guard returns 0 — correct.
However, `sf.write(str(wav_path), data, sample.sample_rate)` is called
before this check, and `soundfile.write` with `samplerate=0` raises
`SoundFileError: Error opening ... : System error`. This error propagates
uncaught and leaves a partial file on disk.

EVIDENCE:
```python
sf.write(str(wav_path), data, sample.sample_rate)  # raises if sample_rate=0
...
"duration_s": round(len(data) / sample.sample_rate, 4) if sample.sample_rate else 0,
```

REPRODUCTION SCENARIO:
Pass an AudioSample with `sample_rate=0`.

IMPACT:
Crash with soundfile error; partial WAV file left on disk.

FIX DIRECTION:
Validate `sample.sample_rate > 0` before writing:
```python
if not sample.sample_rate or sample.sample_rate <= 0:
    log.warning("AudioExporterNode: sample %d has invalid sample_rate, skipping", idx)
    continue
```

--------------------------------------------------------------------
FILE:        PluginPackage/Audio/audio_exporter/nodes.py
FUNCTION:    AudioExporterNode.process
CATEGORY:    Edge Case
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Process a list of AudioSample objects.

WHAT IT ACTUALLY DOES:
No None-guard on `samples`. If `samples` is `None`, `for idx, sample in enumerate(samples)`
raises `TypeError: 'NoneType' object is not iterable`.

EVIDENCE:
```python
def process(self, samples: list[AudioSample]) -> list[AudioSample]:
    ...
    for idx, sample in enumerate(samples):
```

REPRODUCTION SCENARIO:
Upstream node returns `None`.

IMPACT:
Crash with opaque TypeError.

FIX DIRECTION:
```python
if not samples:
    return []
```

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | CRITICAL |
| Silent Failures | 2 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | SAFE |
| Test Hostile | NO |
| Top Risk | shutil.rmtree on misconfigured output_dir can irreversibly delete arbitrary filesystem directories |
