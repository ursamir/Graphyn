# Functional Review — app/core/pipeline_cache.py

**Group:** 7 — Observability & Storage  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/pipeline_cache.py
FUNCTION:    PipelineCache.save
CATEGORY:    Resource Leak
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Save node outputs to cache. Writes manifest.json atomically after writing
all audio port subdirectories.

WHAT IT ACTUALLY DOES:
Writes `port_*/` subdirectories via `handler.serialize()` in a loop, then
writes `manifest.json` with a plain `open()` + `json.dump()` (no atomic
rename). If the process is killed between the last `handler.serialize()` call
and the `manifest.json` write, the cache directory exists with port data but
no manifest.

THE BUG / RISK:
`load()` uses `top_manifest_path.exists()` as the primary discovery mechanism
(SA-PC3 fix). A partial write leaves orphaned `port_*/` directories that are
never cleaned up and never used (the manifest-based path returns `[]` for
`cached_ports`, and the directory-scan fallback path is only reached when
`top_manifest_path` does NOT exist). The orphaned directories consume disk
space indefinitely.

EVIDENCE:
```python
for port_name, audio_samples in audio_ports.items():
    port_dir = cache_dir / f"port_{port_name}"
    port_dir.mkdir(parents=True, exist_ok=True)
    handler.serialize(audio_samples, port_dir)   # ← crash here leaves orphan

top_manifest_path = cache_dir / "manifest.json"
with open(top_manifest_path, "w", encoding="utf-8") as f:   # ← never reached
    json.dump({"cached_ports": sorted(audio_ports.keys())}, f, indent=2)
```

REPRODUCTION SCENARIO:
SIGKILL after `handler.serialize()` completes for the last port but before
`manifest.json` is written. Cache directory is left in a partial state.
`load()` finds `manifest.json` missing, falls through to directory scan,
finds `port_*/` dirs, and tries to load them — but `cached_ports` is None
so `port_dirs` is set to `[]` via the `else` branch. Actually the directory
scan fallback IS reached here (since `top_manifest_path` does not exist),
so the orphaned data IS loaded. This means a partial write can produce a
cache hit with potentially incomplete data.

THE DEEPER BUG: When `top_manifest_path` does NOT exist, `load()` falls
through to the directory scan:
```python
port_dirs = [
    d for d in cache_dir.iterdir()
    if d.is_dir() and d.name.startswith("port_")
] if cache_dir.is_dir() else []
```
This will find the partially-written `port_*/` dirs and attempt to load them.
If only 2 of 3 ports were written before the crash, `load()` returns a dict
with only 2 ports — a silent wrong result.

IMPACT:
Silent wrong result — cache returns incomplete outputs (missing ports) after
a partial write. Downstream nodes receive fewer inputs than expected.

FIX DIRECTION:
Write manifest atomically:
```python
tmp = cache_dir / "manifest.json.tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump({"cached_ports": sorted(audio_ports.keys())}, f, indent=2)
tmp.replace(cache_dir / "manifest.json")
```

--------------------------------------------------------------------
FILE:        app/core/pipeline_cache.py
FUNCTION:    PipelineCache.save (outputs.json path)
CATEGORY:    Resource Leak
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Write JSON-serializable outputs to `outputs.json`.

WHAT IT ACTUALLY DOES:
Writes `outputs.json` with a plain `open()` + `json.dump()` (no atomic
rename). If the process is killed mid-write, `outputs.json` is left in a
truncated/corrupt state.

THE BUG / RISK:
`load()` reads `outputs.json` with `json.load()` and catches `Exception`,
returning `None` on failure. So a corrupt `outputs.json` causes a cache miss
and re-execution — this is safe but the corrupt file is never cleaned up,
consuming disk space.

EVIDENCE:
```python
outputs_path = cache_dir / "outputs.json"
with open(outputs_path, "w", encoding="utf-8") as f:
    json.dump(serializable, f, indent=2)
```
No atomic rename.

REPRODUCTION SCENARIO:
SIGKILL during `json.dump()` for a large outputs dict. `outputs.json` is
truncated. Next `load()` call gets a JSON parse error, returns `None`, node
re-executes. Corrupt file remains on disk.

IMPACT:
Disk space leak (corrupt file never cleaned). No data corruption — re-execution
is safe.

FIX DIRECTION:
```python
tmp = cache_dir / "outputs.json.tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(serializable, f, indent=2)
tmp.replace(outputs_path)
```

--------------------------------------------------------------------
FILE:        app/core/pipeline_cache.py
FUNCTION:    PipelineCache.input_hash
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Compute a stable hash for any node input value.

WHAT IT ACTUALLY DOES:
For AudioSample lists, hashes by `path`, `sample_rate`, and `data.shape`.
If `sample.data` is `None` (a valid state for a lazy-loaded AudioSample),
`sample.data.shape` raises `AttributeError`, which is caught by the outer
`except Exception` in the Pydantic model path — but the AudioSample branch
has NO try/except. The `AttributeError` propagates up uncaught.

THE BUG / RISK:
`input_hash` is called from `compute_key`, which is called from the
orchestrator/executor before every node execution. An `AttributeError` here
crashes the entire pipeline execution, not just the cache lookup.

EVIDENCE:
```python
if hasattr(first, "path") and hasattr(first, "sample_rate") and hasattr(first, "data"):
    parts = []
    for sample in inputs:
        shape = sample.data.shape if sample.data is not None else ()
        # ↑ sample.data is checked for None, but what if sample.data is not None
        # yet has no .shape attribute (e.g. a plain bytes object)?
        path = getattr(sample, "path", None) or getattr(sample, "source_path", str(id(sample)))
```
`sample.data` could be a bytes object (no `.shape`), a list, or any object
that has a `data` attribute but not a numpy array. The `hasattr(first, "data")`
check only confirms the attribute exists, not that it has `.shape`.

REPRODUCTION SCENARIO:
An AudioSample where `data` is a `bytes` object (e.g. raw PCM). `sample.data
is not None` is True, so `sample.data.shape` is evaluated → `AttributeError:
'bytes' object has no attribute 'shape'`. Pipeline crashes.

IMPACT:
Pipeline crash (unhandled exception propagates to orchestrator).

FIX DIRECTION:
```python
shape = getattr(sample.data, "shape", ()) if sample.data is not None else ()
```

--------------------------------------------------------------------
FILE:        app/core/pipeline_cache.py
FUNCTION:    PipelineCache.load (port_dirs path)
CATEGORY:    Silent Failure Risk
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Load cached node outputs from port subdirectories.

WHAT IT ACTUALLY DOES:
When `top_manifest_path` exists but `cached_ports` is `None` (legacy flat
manifest), `port_dirs` is set to `[]`. The code then falls through to the
legacy `manifest.json` handler. However, the legacy handler also reads
`manifest_path = cache_dir / "manifest.json"` — the same file that was
already read as `top_manifest_path`. This means the legacy path re-reads
the same file a second time, which is wasteful but not incorrect.

The real issue: if `top_manifest_path` exists AND `cached_ports` is `None`
AND the legacy handler's `handler.deserialize(cache_dir)` returns `None`,
the function returns `None` — a cache miss. But the cache directory exists
and contains a valid manifest. The caller re-executes the node and overwrites
the cache entry. This is safe but wastes the cached data.

THE BUG / RISK:
Not a correctness bug per se, but the double-read of `manifest.json` and the
ambiguous handling of `cached_ports is None` vs `cached_ports == []` creates
a subtle logic path where a valid legacy cache entry is silently discarded.

EVIDENCE:
```python
if top_manifest_path.exists():
    try:
        ...
        cached_ports = top_manifest_data.get("cached_ports")
        if cached_ports is not None:
            port_dirs = [cache_dir / f"port_{p}" for p in cached_ports]
        else:
            # Legacy flat manifest.json — fall through to the legacy handler below.
            port_dirs = []
    except Exception:
        port_dirs = []
```
When `cached_ports is None`, `port_dirs = []` and the `if port_dirs:` block
is skipped. The code then reaches the legacy handler which re-reads the same
`manifest.json`. If `cached_ports` is an empty list `[]` (a valid new-format
entry with zero ports), `port_dirs` is also `[]` and the same fallthrough
occurs — but this is a new-format entry, not a legacy one. The empty-list
case is silently treated as a legacy entry.

REPRODUCTION SCENARIO:
A node with zero audio output ports writes `manifest.json` with
`{"cached_ports": []}`. On load, `cached_ports = []` which is falsy, so
`port_dirs = []`, and the code falls through to the legacy handler which
tries to deserialize the root cache dir as a single-port WAV cache. The
handler returns `None`. Cache miss. Node re-executes every time.

IMPACT:
Silent cache miss for nodes with zero audio ports (edge case). No data
corruption.

FIX DIRECTION:
Distinguish `cached_ports is None` (legacy) from `cached_ports == []`
(new format, zero ports):
```python
if cached_ports is not None:
    if cached_ports == []:
        return {}   # valid empty cache hit
    port_dirs = [cache_dir / f"port_{p}" for p in cached_ports]
else:
    port_dirs = []  # legacy path
```

--------------------------------------------------------------------
FILE:        app/core/pipeline_cache.py
FUNCTION:    PipelineCache.clear
CATEGORY:    Error Handling
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Delete all cache entries. Returns {entries_deleted, bytes_freed}.

WHAT IT ACTUALLY DOES:
Iterates `self.BASE.iterdir()`, computes `bytes_freed` by summing file sizes,
then calls `shutil.rmtree(entry)`. If `shutil.rmtree` raises (e.g. permission
error), the exception propagates uncaught and `entries_deleted` / `bytes_freed`
reflect a partial state.

THE BUG / RISK:
The returned dict claims N entries deleted but only M were actually deleted
if an exception occurs mid-loop. The caller has no way to distinguish a
complete clear from a partial one.

EVIDENCE:
```python
for entry in self.BASE.iterdir():
    if entry.is_dir():
        for file in entry.rglob("*"):
            if file.is_file():
                bytes_freed += file.stat().st_size
        shutil.rmtree(entry)   # ← no try/except
        entries_deleted += 1
```

REPRODUCTION SCENARIO:
A cache entry directory is owned by a different user. `shutil.rmtree` raises
`PermissionError`. The function propagates the exception. The caller receives
no summary dict.

IMPACT:
Caller cannot determine how much was cleared. No data corruption.

FIX DIRECTION:
Wrap `shutil.rmtree` in a try/except and log a warning on failure, continuing
to the next entry.

---

## Functional Health Summary

| Field | Value |
|---|---|
| Overall Risk | HIGH |
| Silent Failures | 3 |
| Error Handling | PARTIAL |
| Async Safety | N/A |
| State Safety | SAFE |
| Resource Safety | UNSAFE |
| Test Hostile | NO |
| Top Risk | `save()` for audio ports is not atomic — a partial write leaves orphaned port directories that can be loaded as an incomplete (wrong) cache hit on the next run. |
