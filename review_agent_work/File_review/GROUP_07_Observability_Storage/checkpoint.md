# Functional Review — app/core/checkpoint.py

**Group:** 7 — Observability & Storage  
**Reviewed:** 2026-05-26  
**Reviewer:** Functional Correctness Agent

---

## Findings

--------------------------------------------------------------------
FILE:        app/core/checkpoint.py
FUNCTION:    _write_checkpoint
CATEGORY:    Silent Failure Risk
SEVERITY:    HIGH
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Write a node's outputs to a checkpoint directory as WAV files + manifest.json.

WHAT IT ACTUALLY DOES:
When `outputs` contains no AudioSample ports (e.g. a node that outputs only
JSON-serializable data), the function logs a warning and returns silently
without writing any checkpoint. Non-audio outputs are never checkpointed.

THE BUG / RISK:
The docstring says "Write a node's outputs to a checkpoint directory" but the
function only checkpoints AudioSample outputs. Any node that produces
non-audio outputs (feature arrays, prediction results, model artifacts) will
silently not be checkpointed. On resume, those nodes will re-execute even if
their outputs were expensive to compute. The caller receives no error — the
warning is only visible in logs.

EVIDENCE:
```python
if not audio_ports:
    log.warning(
        "Node '%s' has no AudioSample outputs — checkpoint not written; "
        "node will re-execute on resume.",
        node_id,
    )
    return
```

REPRODUCTION SCENARIO:
Call `_write_checkpoint(run_base_path, "trainer_node", {"model": model_artifact})`.
The function returns without writing anything. On resume, the trainer re-runs.

IMPACT:
Silent wrong result — resume does not skip expensive non-audio nodes. No data
loss, but potentially very long re-execution times and user confusion.

FIX DIRECTION:
Either (a) extend checkpoint to support non-audio types via the serializer
registry (preferred), or (b) update the docstring to clearly state
"only AudioSample outputs are checkpointed" and emit a structured event
rather than a plain warning so callers can detect the skip.

--------------------------------------------------------------------
FILE:        app/core/checkpoint.py
FUNCTION:    _write_checkpoint
CATEGORY:    Resource Leak
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Write checkpoint data atomically.

WHAT IT ACTUALLY DOES:
Writes port subdirectories and WAV files via `handler.serialize()`, then
writes `manifest.json` with a plain `open()` + `json.dump()`. If the process
is killed between the last `handler.serialize()` call and the `manifest.json`
write, the checkpoint directory exists with port data but no manifest.

THE BUG / RISK:
`_load_checkpoint_outputs` checks for `manifest.json` first and returns `None`
if it is missing. So a partial write (port dirs written, manifest not yet
written) leaves orphaned port directories that are never cleaned up and never
used for resume. The checkpoint is silently discarded on the next load.

EVIDENCE:
```python
for port_name, samples in audio_ports.items():
    port_dir = os.path.join(checkpoint_dir, f"port_{port_name}")
    os.makedirs(port_dir, exist_ok=True)
    handler.serialize(samples, _Path(port_dir))   # ← crash here leaves orphan dirs

top_manifest_path = os.path.join(checkpoint_dir, "manifest.json")
with open(top_manifest_path, "w", encoding="utf-8") as f:   # ← never reached
    json.dump(...)
```

REPRODUCTION SCENARIO:
SIGKILL the process after `handler.serialize()` completes for the last port
but before `manifest.json` is written. The checkpoint directory is left in a
partial state. On next run, `_load_checkpoint_outputs` returns `None` and the
node re-executes, but the orphaned port directories remain on disk forever.

IMPACT:
Disk space leak (orphaned WAV files). No data corruption — resume falls back
to re-execution correctly.

FIX DIRECTION:
Write manifest to a `.tmp` file first, then `os.replace()` atomically:
```python
tmp_manifest = top_manifest_path + ".tmp"
with open(tmp_manifest, "w", encoding="utf-8") as f:
    json.dump({"checkpointed_ports": sorted(audio_ports.keys())}, f, indent=2)
os.replace(tmp_manifest, top_manifest_path)
```

--------------------------------------------------------------------
FILE:        app/core/checkpoint.py
FUNCTION:    _write_checkpoint
CATEGORY:    Edge Case
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Prevent path traversal via node_id.

WHAT IT ACTUALLY DOES:
Uses `os.path.abspath` (which does NOT resolve symlinks) for the prefix check,
as documented in the SA-C1 comment. However, the check only guards against
`..` sequences in `node_id`. It does not guard against `node_id` values that
contain null bytes (`\x00`), which on some filesystems can truncate the path
at the OS level.

THE BUG / RISK:
A `node_id` containing a null byte (e.g. `"node\x00../../etc/passwd"`) may
bypass the prefix check on systems where `os.path.abspath` does not strip null
bytes, and the resulting path is passed to `os.makedirs`. Python's `open()`
raises `ValueError: embedded null byte` on CPython, so this is low-severity
in practice, but the guard is incomplete.

EVIDENCE:
```python
checkpoint_dir = os.path.join(run_base_path, "checkpoints", f"node_{node_id}")
checkpoint_dir_abs = os.path.abspath(checkpoint_dir)
run_base_abs = os.path.abspath(run_base_path)
if not checkpoint_dir_abs.startswith(run_base_abs + os.sep) ...
```
No null-byte check before `os.path.abspath`.

REPRODUCTION SCENARIO:
`_write_checkpoint("/runs/r1", "node\x00../../tmp/evil", {})` — on CPython
this raises `ValueError` from `open()`, but the `makedirs` call may succeed
first depending on OS.

IMPACT:
Low in practice (CPython raises before file write), but the guard is
incomplete and could be a security issue on non-CPython runtimes.

FIX DIRECTION:
Add `if '\x00' in node_id: raise ValueError(...)` before the abspath check.

--------------------------------------------------------------------
FILE:        app/core/checkpoint.py
FUNCTION:    _find_latest_checkpoint
CATEGORY:    Performance
SEVERITY:    MEDIUM
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Search runs/ for the most recent checkpoint for node_id.

WHAT IT ACTUALLY DOES:
Iterates over every run directory in `runs/`, reads `meta.json` for each,
and falls back to `os.path.getmtime` if `meta.json` is missing. This is an
O(N) scan over all runs every time a node needs to find its latest checkpoint.

THE BUG / RISK:
In a long-running system with thousands of runs, this scan will be slow.
More critically, the function holds no lock while scanning, so a concurrent
run that is creating a new run directory mid-scan may produce an inconsistent
view (a run directory exists but its `meta.json` has not been written yet).

EVIDENCE:
```python
for run_dir_name in os.listdir(runs_dir_path):
    ...
    meta_path = os.path.join(runs_dir_path, run_dir_name, "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
```
No lock, no pagination, no index.

REPRODUCTION SCENARIO:
System with 10,000 completed runs. Each resume call scans all 10,000 run
directories. With 100ms I/O per directory, this takes ~17 minutes.

IMPACT:
Performance degradation at scale. No data corruption.

FIX DIRECTION:
Maintain a per-node checkpoint index file (e.g. `checkpoints/node_{id}/latest_run`)
updated on each checkpoint write, so lookup is O(1).

--------------------------------------------------------------------
FILE:        app/core/checkpoint.py
FUNCTION:    _load_checkpoint_outputs
CATEGORY:    Silent Failure Risk
SEVERITY:    LOW
--------------------------------------------------------------------
WHAT IT CLAIMS TO DO:
Load checkpoint outputs from a prior run's checkpoint directory.

WHAT IT ACTUALLY DOES:
In the legacy single-port format path, passes `checkpoint_dir` (the root
checkpoint directory) to `handler.deserialize()`. If the handler's
`deserialize()` implementation expects a directory containing only WAV files
and a manifest, but the root checkpoint directory also contains `port_*/`
subdirectories (from a partially-migrated checkpoint), the handler may
silently return wrong data or `None`.

THE BUG / RISK:
A checkpoint directory that was partially written in the new multi-port format
(has `port_*/` dirs but no `checkpointed_ports` key in `manifest.json`) falls
through to the legacy path. The handler is given the root dir which contains
subdirectories, not WAV files. The result depends on the handler implementation
— it may return `None` (safe) or may return an empty list (silent wrong result).

EVIDENCE:
```python
# Legacy single-port format (flat manifest.json at checkpoint root)
samples = handler.deserialize(_Path(checkpoint_dir))
if samples is None:
    return None
return {"output": samples}
```
No check that `checkpoint_dir` does not contain `port_*/` subdirectories.

REPRODUCTION SCENARIO:
A checkpoint written by a version that wrote `port_output/` but used the old
manifest format (no `checkpointed_ports` key). `_load_checkpoint_outputs`
falls through to the legacy path and passes the root dir to the handler.

IMPACT:
Potential silent wrong result (empty output list) depending on handler.

FIX DIRECTION:
Before falling through to the legacy path, check that no `port_*/`
subdirectories exist in `checkpoint_dir`. If they do, log a warning and
return `None` to force re-execution.

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
| Top Risk | `_write_checkpoint` silently skips checkpointing for all non-AudioSample node outputs, causing unexpected re-execution on resume with no error surfaced to the caller. |
