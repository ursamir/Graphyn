# Graphyn Pipeline Engine — Master Issue Registry

> **Single source of truth** for every issue found across all review rounds.
> **Last updated:** 2026-05-25
> **Codebase root:** `/home/meritech/Desktop/newAudio3`

---

## Status Legend

| Symbol | Meaning |
|---|---|
| 🔴 | **Open** — not yet fixed |
| 🟡 | **Deferred** — fix requires architectural work |
| 🟢 | **Resolved** — fixed and verified |

---

## Quick Reference — All Open Issues

| ID | Severity | Category | File | Summary |
|---|---|---|---|---|
| **Fix Immediately** | | | | |
| NEW-4 | High | Bug | `core/executor.py` | Parallel executor silently ignores all edge conditions |
| NEW-5 | High | Concurrency | `core/executor.py` | `node_stats` list mutated concurrently without a lock |
| SA-O1 | High | Concurrency | `core/executor.py` | `node_outputs` compound read-modify-write not GIL-safe |
| SA-O2 | High | Bug | `core/orchestrator.py` | `deregister_active_run` not called on event-driven exception path |
| SA-O7 | High | Bug | `core/orchestrator.py` | Resume does not validate graph hash — stale checkpoints silently reused |
| NEW-12 | Medium | Security | `core/webhook.py` | DNS rebinding bypasses SEC-3 save-time SSRF check |
| **Fix This Sprint** | | | | |
| NEW-6 | Medium | Bug | `core/pipeline_cache.py` | `input_hash` loses port identity — cache key collisions for multi-port nodes |
| NEW-7 | Medium | Resource Leak | `mcp/handlers/execution.py` | Per-call `ThreadPoolExecutor` leak in `execute_pipeline` / `replay_run` |
| NEW-9 | Medium | Security | `api/routers/run_control.py` | No `run_id` validation on pause/resume/cancel endpoints |
| SA-O4 | Medium | Bug | `core/orchestrator.py` | Excluded node passthrough overwrites multi-port outputs with `"output"` key |
| SA-C2 | Medium | Bug | `core/checkpoint.py` | Non-audio nodes silently not checkpointed; no warning on resume |
| SA-RJ1 | Medium | Bug | `core/run_journal.py` | `_write_meta` not atomic — corrupt `meta.json` on crash |
| SA-RJ2 | Medium | Bug | `core/run_journal.py` | `_meta_lock` inconsistently applied — concurrent writes can overwrite |
| NEW-15 | Low | Bug | `mcp/handlers/artifacts.py` | `inspect_run` sorts runs lexicographically, not chronologically |
| **Fix When Touching the File** | | | | |
| ARCH-5 | Medium | Bug | `core/sdk.py` | `PipelineNode._ir_node` always uses `_0` suffix |
| BUG-4 | Medium | Performance | `core/run_journal.py` | `find_latest_checkpoint()` O(N) scan over all runs |
| NEW-8 | Medium | Bug | `api/main.py` | Static mount paths frozen at import time |
| NEW-10 | Medium | Bug | `core/artifact_store.py` | `cleanup()` leaves stale `by_name/` and `by_run/` index entries |
| NEW-18 | Medium | Bug | `app/cli/main.py` | `RUNS_DIR` frozen at module import time |
| NEW-19 | Medium | Bug | `plugins/text-stats/` | Orphaned installed plugin — no `PluginPackage/` source |
| SA-C1 | Medium | Security | `core/checkpoint.py` | Path traversal guard follows symlinks — escape possible |
| NEW-11 | Low | Bug | `core/provenance.py` | Graph hash truncated to 16 chars in index key |
| NEW-13 | Low | Architecture | `api/routers/artifacts.py` | `_replay_executor` `max_workers=1` undocumented |
| NEW-16 | Low | Architecture | `mcp/handlers/execution.py` | Unnecessary extra thread layer in `execute_pipeline` |
| SA-O3 | Low | Quality | `core/orchestrator.py` | `event_loop` parameter accepted but never used |
| SA-O5 | Low | Quality | `core/orchestrator.py` | `_collect_stream` duplicated as `_collect_stream_parallel` |
| SA-P1 | Low | Bug | `core/planner.py` | Legacy YAML parser silently drops edge `condition` field |
| SA-P2 | Low | Performance | `core/planner.py` | `_compute_waves` is O(N²) for deep linear pipelines |
| SA-P3 | Low | Bug | `core/planner.py` | `stable_hash` seed ignores node config |
| SA-NE1 | Low | Bug | `core/node_executor.py` | `teardown()` called when `setup()` was never called |
| SA-NE2 | Low | Quality | `core/node_executor.py` | `_last_duration` etc. injected as dynamic attributes on foreign object |
| SA-NE3 | Low | Quality | `core/node_executor.py` | Streaming nodes cannot use `RetryPolicy` |
| SA-C3 | Low | Quality | `core/checkpoint.py` | Missing WAV file not identified in checkpoint load error message |
| SA-PC1 | Low | Quality | `core/pipeline_cache.py` | `has()` TOCTOU method still public despite docstring warning |
| SA-PC3 | Low | Quality | `core/pipeline_cache.py` | `save()` writes no top-level manifest — fragile `port_*` dir scan |
| SA-PC4 | Low | Bug | `core/pipeline_cache.py` | `clear()` does not update content-hash index |
| SA-AS1 | Low | Quality | `core/artifact_store.py` | Artifact IDs truncated to 16 hex chars |
| SA-AS3 | Low | Quality | `core/artifact_store.py` | Confusing `OSError` on concurrent rename race in `register()` |
| SA-AS4 | Low | Quality | `core/artifact_store.py` | `list()` slow-path scan skips `by_run/` but not `by_name/` |
| SA-AS5 | Low | Security | `core/artifact_store.py` | `_by_name_path` allows `.` and `..` as artifact names |
| SA-RC2 | Low | Quality | `core/run_control.py` | `get_active_run` returns `None` with no case distinction |
| SA-RJ3 | Low | Bug | `core/run_journal.py` | Mixed `+00:00` vs `Z` timezone formats break checkpoint sort order |
| SA-RJ4 | Low | Quality | `core/run_journal.py` | `update_resume_state` silently no-ops if `resume_state.json` missing |
| SA-RJ5 | Low | Bug | `core/run_journal.py` | `register_artifact` never passes `name` — `by_name` index never populated |
| SA-B2 | Low | Bug | `core/nodes/base.py` | SISO wrapper doesn't validate `inputs` is a dict |
| SA-B3 | Low | Quality | `core/nodes/base.py` | `process_stream` default GIL limitation undocumented |
| SA-B4 | Low | Bug | `core/nodes/base.py` | `__init_subclass__` wraps abstract intermediaries |
| SA-B5 | Low | Quality | `core/nodes/base.py` | Deferred import of private `_type_to_schema` from sibling module |
| **Deferred** | | | | |
| ARCH-1 | High | Architecture | `core/pipeline_cache.py` | Domain leak — imports `AudioSample` |
| ARCH-2 | High | Architecture | `core/artifact_store.py` | Domain leak — WAV serialization in platform infrastructure |
| ARCH-3 | High | Architecture | `core/checkpoint.py` | Domain leak — entirely audio-specific |
| SEC-6 | High | Security | `api/routers/plugins.py` | Plugin install accepts arbitrary remote code execution |
| SCALE-1 | Medium | Scalability | `core/run_control.py` | Active run registry is process-local |
| SCALE-2 | Medium | Scalability | `domain/ingestion.py` | Ingest job store is process-local |


---

## Fix Immediately — Before Next Deployment

### NEW-4 — Parallel executor silently ignores all edge conditions
**Severity:** High | **Category:** Bug | **File:** `app/core/executor.py`, `_run_node()` input assembly block

The sequential path in `orchestrator.py` evaluates `edge_conditions` before assembling inputs. The parallel executor's `_run_node()` assembles inputs with no condition evaluation — `edge_conditions` is never passed to `run_wave()` or `_run_node()`. Any pipeline using `parallel=True` with conditional edges silently passes data on every edge regardless of the condition. No error is raised.

**Fix:** Pass `edge_conditions` and `graph` to `run_wave()` / `_run_node()` and apply the same condition evaluation logic as the sequential path before assembling each input.

---

### NEW-5 — `node_stats` list mutated concurrently without a lock in parallel mode
**Severity:** High | **Category:** Concurrency | **File:** `app/core/executor.py`, `_run_node()` ~line 285

`node_stats.append(...)` is called from multiple concurrent coroutines with no lock. Ordering is non-deterministic. The orchestrator uses `node_stats[-1]["node_id"]` to determine the last completed node on cancellation — this can return the wrong node in parallel mode.

**Fix:** Protect `node_stats.append()` with a `threading.Lock` passed into `_run_node`.

---

### SA-O1 — `node_outputs` compound read-modify-write not GIL-safe in parallel mode
**Severity:** High | **Category:** Concurrency | **File:** `app/core/executor.py`, `_run_node()` ~line 165; `app/core/orchestrator.py` lines 196–230

`node_outputs` is a plain `dict` passed by reference to all concurrent `_run_node` tasks. Python's GIL protects individual `dict.__setitem__` calls, but compound read-modify-write sequences such as `inputs.setdefault(dst_port, []).append(value)` are not atomic. Two nodes in the same wave reading from `node_outputs` while a third is writing can observe a partially-updated state. Distinct from NEW-5 (which is about `node_stats` ordering) — this is about potential data corruption in the input assembly step.

**Fix:** Add a `threading.Lock` around compound read-modify-write operations on `node_outputs` inside `_run_node`. Document the wave-isolation invariant (nodes in a wave only read from prior waves' outputs) as a comment to clarify why simple reads are safe.

---

### SA-O2 — `deregister_active_run` not called on event-driven exception path
**Severity:** High | **Category:** Bug | **File:** `app/core/orchestrator.py`, event-driven `try/finally` block (~lines 370–395)

The `finally` block closes all event sources, but `deregister_active_run(run.run_id)` is only called in the normal completion path. If `asyncio.gather` raises an unexpected exception (not `CancelledError`), the `except asyncio.CancelledError` block swallows it and the run is never deregistered. The `_ACTIVE_RUNS` dict leaks the entry permanently for that process lifetime.

**Fix:** Move `deregister_active_run(run.run_id)` into the `finally` block alongside the `src.close()` calls, mirroring the pattern used in the sequential and parallel paths.

---

### SA-O7 — Resume does not validate graph hash — stale checkpoints silently reused
**Severity:** High | **Category:** Bug | **File:** `app/core/orchestrator.py`, resume logic (~lines 175–195)

`load_resume_state` returns a dict that includes `graph_hash` (written by `init_resume_state`). The orchestrator never compares `resume_state["graph_hash"]` against the current run's `graph_hash`. A user can resume a run against a completely different pipeline graph and the engine will silently reuse stale checkpoint outputs from the old graph, producing incorrect results.

**Fix:** After loading resume state, compare `resume_state.get("graph_hash")` against `run._graph_hash`. If they differ, raise `ResumeError`: `"Cannot resume: graph has changed since the checkpoint was written."`

---

### NEW-12 — Webhook DNS rebinding SSRF — SEC-3 save-time check bypassed at send time
**Severity:** Medium | **Category:** Security | **File:** `app/core/webhook.py`, `_send()`

`save()` resolves the hostname and rejects private IPs at configuration time. `_send()` makes the actual HTTP request without re-validating the resolved IP. A DNS rebinding attack (change DNS record after `save()` passes) bypasses the check. `httpx` resolves DNS fresh on every connection.

**Fix:** Re-validate the resolved IP in `_send()` before making the request:
```python
def _send(self, url, event, payload):
    from urllib.parse import urlparse
    hostname = urlparse(url).hostname or ""
    if hostname and _is_private_host(hostname):
        logger.warning("Webhook blocked: URL resolves to private address at send time")
        return
    # ... proceed with httpx request
```


---

## Fix This Sprint

### NEW-6 — `input_hash` loses port identity for multi-port nodes
**Severity:** Medium | **Category:** Bug | **File:** `app/core/pipeline_cache.py`; `app/core/orchestrator.py` ~line 389; `app/core/executor.py` ~line 203

Both call sites pass `list(inputs.values())` to `input_hash()`. Port names are lost. For non-JSON-serializable multi-port inputs, `input_hash` returns `""`, causing all cache keys for that node to collide — a node could receive stale cached outputs from a different input combination.

**Fix:** Hash each port separately and combine:
```python
combined = hashlib.sha256(
    "".join(cache.input_hash(v) for v in inputs.values()).encode()
).hexdigest()
```
Or redesign `input_hash` to accept `dict[str, Any]` and include port names.

---

### NEW-7 — `execute_pipeline` and `replay_run` MCP handlers create a new `ThreadPoolExecutor` per call
**Severity:** Medium | **Category:** Resource Leak | **Files:** `app/mcp/handlers/execution.py` lines ~55–62; `app/mcp/handlers/provenance.py` lines ~80–83

A new `ThreadPoolExecutor` is created on every call and `shutdown(wait=False)` is called immediately. Under load, many thread pools accumulate simultaneously, each holding OS thread resources for the duration of the pipeline run.

**Fix:** Use a module-level shared executor:
```python
_PIPELINE_EXECUTOR = ThreadPoolExecutor(max_workers=4)
# in handler:
_PIPELINE_EXECUTOR.submit(run_pipeline_ir, graph, ...)
```

---

### NEW-9 — `run_control` router accepts arbitrary `run_id` strings with no validation
**Severity:** Medium | **Category:** Security | **File:** `app/api/routers/run_control.py` — all three endpoints

The `pause_run`, `resume_run`, and `cancel_run` endpoints accept `run_id` as a path parameter with no length limit or character validation. Inconsistent with `runs.py` which validates with `isalnum()` + path traversal check.

**Fix:**
```python
if not run_id.replace("-", "").isalnum() or not run_id.replace("-", ""):
    raise HTTPException(status_code=400, detail="Invalid run_id")
```

---

### SA-O4 — Excluded node passthrough overwrites multi-port outputs with `"output"` key
**Severity:** Medium | **Category:** Bug | **File:** `app/core/orchestrator.py`, sequential path excluded-node branch (~lines 253–263)

When a node is excluded from partial execution, its outputs are synthesized by copying upstream values. The code sets `passthrough["output"] = value` unconditionally, which overwrites a previously set `passthrough[dst_port]` if `dst_port != "output"`. For multi-port excluded nodes this silently drops all ports except the last one processed.

**Fix:** Remove the unconditional `passthrough["output"] = value` line. Only set `passthrough[dst_port] = value` for each incoming edge's `dst_port`.

---

### SA-C2 — Non-audio nodes silently not checkpointed; no warning on resume
**Severity:** Medium | **Category:** Bug | **File:** `app/core/checkpoint.py`, `_write_checkpoint()` lines 55–58

If a node produces only non-audio outputs (e.g. a classifier producing a label dict), `_write_checkpoint` returns without writing anything. The orchestrator marks the node as completed in `resume_state.json`. On resume, `_load_checkpoint_outputs` returns `None` and the orchestrator re-executes it silently. Users who enable `checkpoint=True` expecting all nodes to be resumable will be surprised.

**Fix:** Log a `WARNING` when `_write_checkpoint` is called for a node with no audio ports:
```python
log.warning(
    "Node '%s' has no AudioSample outputs — checkpoint not written; "
    "node will re-execute on resume.", node_id
)
```

---

### SA-RJ1 — `_write_meta` is not atomic — corrupt `meta.json` on crash
**Severity:** Medium | **Category:** Bug | **File:** `app/core/run_journal.py`, `_write_meta()` lines 60–63

`_write_meta` opens the file and writes directly. If the process crashes mid-write, `meta.json` will be corrupt. `_save_index` in `artifact_store.py` uses an atomic rename pattern (`tmp → final`). `_write_meta` should do the same, since `meta.json` is the primary run status record.

**Fix:**
```python
def _write_meta(self, data: dict) -> None:
    path = os.path.join(self.base_path, "meta.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)  # atomic on POSIX
```

---

### SA-RJ2 — `_meta_lock` inconsistently applied — concurrent writes can overwrite
**Severity:** Medium | **Category:** Bug | **File:** `app/core/run_journal.py`, `_write_meta()` vs `_write_meta_field()` lines 60–76

`_write_meta_field` acquires `_meta_lock` before reading and writing. But `_write_meta` (called from `__init__`, `save_metadata`, `mark_failed`, `mark_cancelled`) does NOT acquire `_meta_lock`. If `save_metadata` and `pause()` are called concurrently, one will overwrite the other's changes.

**Fix:** Acquire `_meta_lock` inside `_write_meta` itself, making all callers automatically thread-safe. Combine with SA-RJ1 fix.

---

### NEW-15 — `inspect_run` MCP handler returns runs in lexicographic, not chronological, order
**Severity:** Low | **Category:** Bug | **File:** `app/mcp/handlers/artifacts.py` lines ~85–110

`sorted(_RUNS_DIR.iterdir(), reverse=True)` sorts by path name (hex string), not by `created_at`. AI agents using this tool to find the most recent run get an incorrect result.

**Fix:** Collect all runs first, then sort by `created_at`:
```python
runs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
```


---

## Fix When Touching the File

Issues in this section are real but low-urgency. Fix them the next time you edit the relevant file.

### `app/core/sdk.py`

**ARCH-5 — `PipelineNode._ir_node` always uses `_0` suffix**  
`self._ir_node = IRNode(id=f"{self.node_type}_0", ...)` in `__init__`. `to_ir_node(node_index)` exists and is used correctly by `Pipeline._build_ir()`, but `_ir_node` on the instance is always stale. Any code accessing `pn._ir_node.id` directly gets the wrong ID.  
**Fix:** Remove `_ir_node` from `__init__`, or set it lazily after position is known.

---

### `app/api/main.py`

**NEW-8 — Static mount paths frozen at import time**  
`_OUTPUT_ROOT`, `_INPUT_ROOT`, `_RUNS_ROOT` are resolved at module import time and passed to `StaticFiles`. If `GRAPHYN_PROJECT_DIR` is set after import (e.g. in tests), static mounts point to the wrong directories.  
**Fix:** Document as a startup-time freeze. Ensure `GRAPHYN_PROJECT_DIR` is set before importing `app.api.main`. Add a comment to this effect.

---

### `app/cli/main.py`

**NEW-18 — `RUNS_DIR` frozen at module import time**  
`RUNS_DIR = str(_runs_dir())` is resolved once at import time. Same class of bug as NEW-8. All CLI `runs` subcommands (`list`, `logs`, `pause`, `resume`, `cancel`) use this frozen path.  
**Fix:** Replace the module-level constant with a per-call `str(_runs_dir())` inside each subcommand function.

---

### `app/core/orchestrator.py`

**SA-O3 — `event_loop` parameter accepted but never used**  
`event_loop: Any = None` is declared in `run_pipeline_ir_async` but never referenced in the function body and not forwarded to `run_pipeline_ir`. Dead parameter.  
**Fix:** Remove the `event_loop` parameter from both `run_pipeline_ir_async` and `run_pipeline_ir` signatures.

**SA-O5 — `_collect_stream` duplicated as `_collect_stream_parallel`**  
Two functionally identical implementations of stream collection exist in `orchestrator.py` and `executor.py` with no shared abstraction. Any bug fix must be applied in two places.  
**Fix:** Extract to a shared utility in `app/core/utils.py` and import from both modules.

---

### `app/core/planner.py`

**SA-P1 — Legacy YAML parser silently drops edge `condition` field**  
`_parse_pipeline_config` never reads `e.get("condition")` when constructing `EdgeSpec`. Any condition on a legacy YAML edge is silently dropped. The IR path (`_ir_to_pipeline_config`) correctly copies `condition`.  
**Fix:** Add `condition=e.get("condition")` to the `EdgeSpec` constructor call in `_parse_pipeline_config`.

**SA-P2 — `_compute_waves` is O(N²) for deep linear pipelines**  
Wave computation iterates all nodes for each level. For deep linear pipelines (L ≈ N) this degrades to O(N²).  
**Fix:** Build the waves dict in a single pass:
```python
from collections import defaultdict
waves_dict = defaultdict(list)
for nid in self._topo_order:
    waves_dict[level[nid]].append(nid)
return [waves_dict[i] for i in range(max(level.values(), default=0) + 1)]
```

**SA-P3 — `stable_hash` seed ignores node config**  
`node_seed = stable_hash(seed, spec.node_type, i) % (2**32)` — config is not included. Two pipelines with the same seed, same node types in the same order, but different configs produce identical node seeds. For augmentation nodes this means random behavior is not config-dependent.  
**Fix:** Include config: `stable_hash(seed, spec.node_type, i, json.dumps(spec.config, sort_keys=True))`.

---

### `app/core/node_executor.py`

**SA-NE1 — `teardown()` called when `setup()` was never called**  
When `on_start()` raises on every retry, `teardown()` is called at the end of the retry loop without checking whether `setup()` was ever called.  
**Fix:** Guard with `if self._setup_done: self.teardown()` in the post-retry cleanup path.

**SA-NE2 — `_last_duration` etc. injected as dynamic attributes on foreign `Node` object**  
`node._last_duration = duration` etc. with `# type: ignore`. Side-channel coupling that bypasses the type system.  
**Fix:** Pass these values as explicit parameters to `node.on_end(duration, input_counts, output_counts)`.

**SA-NE3 — Streaming nodes cannot use `RetryPolicy`**  
`execute()` has full retry logic. `execute_stream()` has none. Undocumented behavioral asymmetry.  
**Fix:** Document the asymmetry in the `execute_stream` docstring. If retry is needed for streaming, wrap the `async for` in a retry loop.

---

### `app/core/checkpoint.py`

**SA-C1 — Path traversal guard follows symlinks — symlink escape possible**  
The guard uses `os.path.realpath` which resolves symlinks. If an attacker can create a symlink inside the run directory pointing to an arbitrary path, the guard will pass for the symlink target.  
**Fix:** Use `os.path.abspath` (does not resolve symlinks) for the prefix check.

**SA-C3 — Missing WAV file not identified in checkpoint load error message**  
When `sf.read(wav_path)` fails, the error message says "Checkpoint load failed" without identifying which file was missing.  
**Fix:** Include `wav_path` in the log message: `log.warning("Checkpoint load failed for node '%s' (file: %s): %s", node_id, wav_path, exc)`.

---

### `app/core/pipeline_cache.py`

**SA-PC1 — `has()` TOCTOU method still public despite docstring warning**  
The docstring warns about TOCTOU and recommends using `load()` directly. The method remains public and callable, inviting future misuse.  
**Fix:** Deprecate with `DeprecationWarning` or rename to `_has()`.

**SA-PC3 — `save()` writes no top-level manifest — fragile `port_*` dir scan**  
`load()` discovers ports by scanning for `port_*` directories. Any directory starting with `port_` created for another reason would be misread as a cache port. Inconsistent with `checkpoint.py` which writes a top-level `manifest.json`.  
**Fix:** Write a top-level `manifest.json` in `save()` listing all port names.

**SA-PC4 — `clear()` does not update content-hash index**  
`clear()` deletes all cache directories but does not touch any index file. If `ArtifactStore` and `PipelineCache` share the same base directory, `clear()` would delete artifact records without updating `ArtifactStore`'s `index.json`.  
**Fix:** Document that `PipelineCache` and `ArtifactStore` must not share the same base directory. Add an assertion in the `BASE` setter.

---

### `app/core/artifact_store.py`

**NEW-10 — `cleanup()` leaves stale `by_name/` and `by_run/` index entries**  
After deleting artifact directories, `by_name/` and `by_run/` index files still reference deleted IDs. The indexes grow unboundedly on systems with high artifact turnover.  
**Fix:** After collecting deleted artifact IDs, remove stale entries from all `by_name/` and `by_run/` index files.

**SA-AS1 — Artifact IDs truncated to 16 hex chars**  
`str(uuid.uuid4()).replace("-", "")[:16]` — 64 bits of entropy. Non-standard; collision risk at very high throughput (millions of artifacts).  
**Fix:** Use the full UUID4 hex string (32 chars).

**SA-AS3 — Confusing `OSError` on concurrent rename race in `register()`**  
If two concurrent `register()` calls for the same content hash both serialize before either acquires the lock, the second will find the hash in the index and discard its temp dir — correct. But if `rename()` fails with `OSError: File exists`, the error message is confusing since the artifact was actually registered successfully by the first caller.  
**Fix:** After acquiring the lock, re-check if the hash is already in the index before attempting the rename, and return the existing artifact ID if so.

**SA-AS4 — `list()` slow-path scan skips `by_run/` but not `by_name/`**  
`if not entry.is_dir() or entry.name == "by_run"` — `by_name/` is not skipped, wasting one `os.stat` call per run.  
**Fix:** `if not entry.is_dir() or entry.name in ("by_run", "by_name"):`.

**SA-AS5 — `_by_name_path` allows `.` and `..` as artifact names**  
`"".join(c if c.isalnum() or c in "-_." else "_" for c in name)[:128]` — a name of `"."` or `".."` passes through unchanged, producing directory references as filenames.  
**Fix:** After sanitization: `if safe in (".", "..") or not safe: safe = "_unnamed"` and `safe = safe.lstrip(".") or "_unnamed"`.

---

### `app/core/run_control.py`

**SA-RC2 — `get_active_run` returns `None` with no case distinction**  
Returns `None` whether the run never existed, already completed, or is on a different worker. The API layer cannot return accurate error messages.  
**Fix:** Document the ambiguity in the docstring. Consider typed result or distinct exceptions: `RunNotFoundError` vs `RunCompletedError` vs `RunOnOtherWorkerError`.

---

### `app/core/run_journal.py`

**BUG-4 — `find_latest_checkpoint()` O(N) scan over all runs**  
Scans every run directory on disk to find the latest checkpoint for a node. O(N) disk I/O on every partial-execution input assembly.  
**Fix:** Maintain a secondary index `checkpoints/by_node/{node_id}.json` updated by `_write_checkpoint()`.

**SA-RJ3 — Mixed `+00:00` vs `Z` timezone formats break checkpoint sort order**  
`find_latest_checkpoint` sorts by `created_at` as a string. ISO 8601 strings only sort correctly if they use the same timezone format. `"2026-05-25T10:00:00Z"` sorts before `"2026-05-25T10:00:00+00:00"` lexicographically even though they represent the same instant.  
**Fix:** Parse before sorting: `datetime.fromisoformat(created_at.replace("Z", "+00:00"))`.

**SA-RJ4 — `update_resume_state` silently no-ops if `resume_state.json` missing**  
If `init_resume_state` was never called, `update_resume_state` returns silently. Hard to detect in tests.  
**Fix:** Log a `WARNING` when called but `resume_state.json` does not exist.

**SA-RJ5 — `register_artifact` never passes `name` — `by_name` index never populated via run path**  
`register_artifact` always passes `name=None` to `ArtifactStore.register`. `get_versions(artifact_name)` always falls back to the full scan for artifacts registered during pipeline execution.  
**Fix:** Add `name: str | None = None` parameter to `register_artifact` and forward it to `ArtifactStore.register`.

---

### `app/core/nodes/base.py`

**SA-B2 — SISO wrapper doesn't validate `inputs` is a dict**  
The SISO wrapper calls `inputs.get("input")` without checking that `inputs` is a dict. A non-dict raises `AttributeError` with a confusing message.  
**Fix:**
```python
if not isinstance(inputs, dict):
    raise TypeError(
        f"{type(self).__name__}.process() expected a dict of port inputs, "
        f"got {type(inputs).__name__}"
    )
```

**SA-B3 — `process_stream` default GIL limitation undocumented**  
The default `process_stream` offloads `process()` to a `ThreadPoolExecutor`. If `process()` is CPU-bound, the GIL prevents true parallelism. Node authors may assume they get free parallelism.  
**Fix:** Add a comment noting that CPU-bound nodes should override `process_stream` and use a `ProcessPoolExecutor`.

**SA-B4 — `__init_subclass__` wraps abstract intermediaries**  
Every class inheriting from `Node` triggers `_maybe_wrap_siso`, including abstract base classes. If an abstract intermediary defines `process` with a non-`inputs` parameter name, it will be wrapped incorrectly.  
**Fix:** Add `if inspect.isabstract(cls): return` at the top of `_maybe_wrap_siso`.

**SA-B5 — Deferred import of private `_type_to_schema` from sibling module**  
`from app.core.nodes.compat import _type_to_schema` is a deferred import of a private function. Creates tight coupling and hides the dependency from static analysis.  
**Fix:** Make `_type_to_schema` public (`type_to_schema`) in `compat.py` and move the import to module level in `base.py`.

---

### `app/core/provenance.py`

**NEW-11 — Graph hash truncated to 16 chars in index key**  
`by_graph_hash/{graph_hash[:16]}.json` — unnecessary truncation. Two graphs sharing the same 16-char prefix collide into the same index file. A double-check is applied after lookup so correctness is maintained, but the truncation is pointless.  
**Fix:** Use the full `graph_hash` as the filename: `f"{graph_hash}.json"`.

---

### `app/api/routers/artifacts.py`

**NEW-13 — `_replay_executor` `max_workers=1` undocumented**  
Module-level singleton with a single worker thread. Concurrent replay requests queue silently. The constraint is undocumented.  
**Fix:** Add a comment documenting the constraint, or increase to a small pool (e.g. 4).

---

### `app/mcp/handlers/execution.py`

**NEW-16 — Unnecessary extra thread layer in `execute_pipeline`**  
The handler already runs in a thread (via `run_in_executor` in `server.py`), then creates another `ThreadPoolExecutor` to submit `run_pipeline_ir`. Redundant indirection. Resolved by the NEW-7 fix (module-level shared executor).

---

### `plugins/text-stats/`

**NEW-19 — Orphaned installed plugin — no `PluginPackage/` source**  
The `plugins/` managed directory contains `text-stats` but there is no corresponding source in `PluginPackage/Audio/` or `PluginPackage/Common/`. The installed copy cannot be updated from source, cannot be audited, and its origin is unknown.  
**Fix:** Either add the source to `PluginPackage/Common/text_stats/` and sync, or uninstall: `PluginManager().uninstall("text-stats")` and document the decision.


---

## Deferred — Architectural Work Required

### ARCH-1 — Domain leak: `pipeline_cache.py` imports `AudioSample`
**Severity:** High | **File:** `app/core/pipeline_cache.py` line 8

`from app.models.audio_sample import AudioSample` — platform cache must not know about audio. `load()` constructs `AudioSample` objects directly.

**Fix:** Pluggable serializer/deserializer registry. Domain registers its handler at startup; platform calls it by type string.

---

### ARCH-2 — Domain leak: `artifact_store.py` contains WAV serialization
**Severity:** High | **File:** `app/core/artifact_store.py`

`_serialize_audio_samples()` writes WAV files using `soundfile`. `_infer_artifact_type()` contains audio-specific duck-typing. Both are audio-domain knowledge inside platform infrastructure.

**Fix:** Same serializer registry pattern as ARCH-1.

---

### ARCH-3 — `checkpoint.py` is entirely audio-domain
**Severity:** High | **File:** `app/core/checkpoint.py`

Imports `soundfile`, `numpy`, writes WAV files, reads `sample.data`, `sample.sample_rate`, `sample.label`. Not platform infrastructure — an audio-domain checkpoint serializer in the wrong layer.

**Fix:** Replace with the pluggable serializer pattern. Platform writes opaque bytes; domain provides the serializer/deserializer.

---

### SEC-6 — Plugin install accepts arbitrary remote code execution
**Severity:** High | **File:** `app/api/routers/plugins.py`, `app/core/plugins/manager.py`

`POST /api/v1/plugins/install` accepts a `source` string passed to `PluginInstaller.resolve()` which fetches and executes code from `git+`, `http://`, or `https://` URLs. No allowlist, no signature verification, no sandboxing. Inherent to plugin systems.

**Mitigation:** Require auth (done). Add checksum verification. Never expose publicly.

---

### SCALE-1 — Active run registry is process-local
**Severity:** Medium | **File:** `app/core/run_control.py`

`_ACTIVE_RUNS` is a process-local dict. In multi-worker deployments, pause/resume/cancel requests routed to a different worker return 404. The split into `run_control.py` was done specifically to make this migration easy.

**Fix:** Replace `_ACTIVE_RUNS` with a Redis-backed store.

---

### SCALE-2 — Ingest job store is process-local
**Severity:** Medium | **File:** `app/domain/ingestion.py`

`_jobs` is a module-level dict. In multi-worker deployments, job streaming requests routed to a different worker return 404.

**Fix:** Same pattern as SCALE-1 — Redis-backed store.


---

## Resolved Issues

| ID | File | Issue | Fix Applied |
|---|---|---|---|
| SEC-1 | `mcp/auth.py` | Auth token read at import time | Token read on every call inside `check_auth()` |
| SEC-2 | `api/main.py` | Auth token read at import time | Token read on every call inside `_auth_dep()` |
| SEC-3 | `core/webhook.py` | Webhook SSRF — no private IP blocking | `_is_private_host()` added; `save()` rejects RFC 1918 / loopback / link-local ⚠️ see NEW-12 |
| SEC-4 | `domain/ingestion.py` | Ingest URL no download size limit | `httpx` streaming + 500 MB max-bytes counter in `_run_url_job()` |
| SEC-5 | `api/main.py` | CORS `allow_headers=["*"]` with credentials | Replaced with explicit header list |
| SEC-7 | `api/routers/runs.py` | `_run_dir()` path traversal gap | `resolve()` + `is_relative_to()` check added; empty-after-strip rejected |
| SEC-8 | `core/conditions.py` | Condition evaluator no AST depth limit | `_ast_depth()` helper added; max depth 12 enforced |
| ARCH-4 | `core/checkpoint.py` | `_write_checkpoint` only saved first list port | Rewrote to write each port to `port_<name>/` subdirectory |
| ARCH-6 | `core/artifact_store.py` | Serialization inside global lock | Serialization moved outside lock; temp dir + atomic rename |
| ARCH-7 | `core/artifact_store.py` | No eviction or size limit | `cleanup(older_than_days)` added; wired into system cleanup endpoint |
| ARCH-8 | `core/pipeline_cache.py` | `input_hash()` repr() fallback not stable | Returns `""` (guaranteed miss) instead of unstable `repr()` |
| ARCH-9 | `core/orchestrator.py` | `cache.has()` TOCTOU not fixed at call sites | `cache.has()` + `cache.load()` replaced with direct `cache.load()` |
| BUG-1 | `core/node_executor.py` | Observer double-fire per node | Direct observer calls removed from `NodeExecutor.execute()` |
| BUG-2 | `app/mcp/server.py` | `asyncio.get_event_loop()` deprecated | Replaced with `asyncio.get_running_loop()` |
| BUG-3 | `core/webhook.py` | `WebhookService` missing `__init__` | `__init__` added with `self._config_cache: dict \| None = None` |
| BUG-5 | `api/routers/pipelines.py` | Unbounded streaming queue | `Queue(maxsize=512)` replaces unbounded `Queue()` |
| BUG-6 | `core/node_executor.py` | `on_error` called twice on final retry | Post-loop duplicate call removed |
| BUG-7 | `api/routers/runs.py` | `list_runs()` no pagination | `limit`/`offset` query params added to `GET /api/v1/runs` |
| BUG-8 | `core/nodes/base.py` | SISO detection fragile | Explicit `_siso: ClassVar[bool]` flag added; inference kept as fallback |
| BUG-9 | `speech_enhancer/nodes.py` | `_resolve_backend()` called twice | Replaced with explicit `RuntimeError` guard |
| BUG-11 | `core/artifact_store.py` | `get_versions()` full directory scan | `by_name/` secondary index added; `get_versions()` uses it |
| SCALE-3 | `core/executor.py` | New `ThreadPoolExecutor` per wave | Single run-scoped pool via `_get_pool()`; `shutdown()` called after all waves |
| NEW-1 | `api/routers/data.py` | Hardcoded `Path("workspace")` | `_input_root()` / `_output_root()` functions using `config.py` |
| NEW-2 | `core/run_journal.py` | Broken `_WORKSPACE` sentinel | Sentinel logic removed; always uses `_project_dir() / "runs"` |
| NEW-3 | `core/node_executor.py` | `execute_stream()` observer coverage gap | Confirmed non-issue after BUG-1 fix; both paths fire once |
| R1-3.1 | `core/orchestrator.py` | Dual `run_id` — observer events reference wrong ID | `run_id = run.run_id` |
| R1-3.2 | `core/orchestrator.py` | `run_pipeline_ir_async` defined twice | Dead first definition removed |
| R1-3.3 | `core/sdk.py` | `Pipeline.validate()` always raises TypeError | `get_registry()` passed as second argument to `validate_pipeline` |
| R1-3.7 | `api/routers/pipelines.py` | `TEMPLATES_DIR` hardcoded relative path | `_templates_dir()` function using `project_dir()` |
| R1-3.8 | `api/routers/system.py` | `system.py` cleanup uses hardcoded `Path("workspace")` | `runs_dir()` and `cache_dir()` from `config.py` |
| R1-4.1 | `core/node_executor.py` | `on_error` called twice on final retry | Post-loop duplicate call removed (= BUG-6) |
| R1-4.8 | `core/checkpoint.py` | `_write_checkpoint` only saves first list port | Rewrote to iterate all ports (= ARCH-4) |
| R1-5.1 | `core/orchestrator.py` | Graph hash computed twice per run | `orchestrator.py` uses `run._graph_hash` |
| R1-7.5 | `PluginPackage/` | `document_processor` plugin directory empty | `plugin.toml` (disabled) + `__init__.py` stub added |
| R1-7.6 | `PluginPackage/audio_exporter/` | `audio_exporter` missing `__init__.py` | `__init__.py` added |
| R1-7.7 | `app/mcp/server.py` | MCP server uses deprecated `get_event_loop()` | Replaced with `get_running_loop()` (= BUG-2) |
| R1-7.8 | `core/webhook.py` | `WebhookService._config_cache` not initialized | `__init__` added (= BUG-3) |
| R1-7.9 | `setup.py` | Open version ranges | All core deps use `~=` compatible-release specifiers |
| — | `core/pipeline.py` | 1,457-line god module mixed 5 responsibilities | Split into `planner.py`, `node_executor.py`, `checkpoint.py`, `orchestrator.py` |
| — | `core/run_manager.py` | Mixed persistence, control plane, artifact facade | Split into `run_journal.py` + `run_control.py` |
| — | `app/core/` | Domain services in platform infrastructure | `ingestion.py`, `project_manager.py`, `quality_checker.py` moved to `app/domain/` |
| — | `core/nodes/errors.py` | `ResumeError` circular import | Moved from `pipeline.py` to `nodes/errors.py` |
| — | `core/artifact_store.py` | `_infer_artifact_type` in wrong layer | Moved from `pipeline.py` to `artifact_store.py` |
