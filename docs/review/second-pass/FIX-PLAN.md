# Fix Plan — app/core Deep Review
**Source:** Second-pass review (185 findings across 47 files)
**Execution:** Sequential — one wave at a time, no parallel fixes
**Status legend:** ⬜ Not started · 🔄 In progress · ✅ Done · ⏭ Deferred

---

## Overview

| Tier | Severity | Waves | Findings |
|------|----------|-------|----------|
| 1 | 🔴 Critical | 1–3 | 4 |
| 2 | 🟠 High | 4–20 | 37 |
| 3 | 🟡 Medium | 21–45 | 94 |
| 4 | 🔵 Low | 46–50 | 50 |
| **Total** | | **50 waves** | **185** |

---

## TIER 1 — 🔴 Critical (Waves 1–3)


### Wave 1 — Thread Safety: Registry + Catalogue ✅
**Files:** `app/core/nodes/registry.py`, `app/core/nodes/catalogue.py`

| ID | Finding | Fix |
|----|---------|-----|
| G1-24 | TOCTOU `KeyError` in `find_compatible_nodes` — `_metadata` accessed outside lock after `_classes` snapshot | Take a single snapshot of both `_classes` and `_metadata` under one lock acquisition in `find_compatible_nodes` |
| G1-38 | `TypeCatalogue` has no thread safety — concurrent `register` + `resolve` races | Add `threading.RLock` to `TypeCatalogue.__init__`; wrap `register()` and `resolve()` with `with self._lock:` |

**Acceptance:** No `KeyError` under concurrent `register`/`unregister`/`find_compatible_nodes`. `TypeCatalogue.resolve()` safe under concurrent `register()`.

---

### Wave 2 — asyncio Crash in Pipeline ✅
**File:** `app/core/pipeline.py`

| ID | Finding | Fix |
|----|---------|-----|
| G2-01 | `asyncio.run()` inside running event loop crashes FastAPI route handlers | Add running-loop guard at top of `run_pipeline_ir()`: detect running loop via `asyncio.get_running_loop()`, raise `RuntimeError` directing callers to use `await run_pipeline_ir_async()` |

**Acceptance:** Calling `run_pipeline_ir()` from an async context raises a clear `RuntimeError`. Calling from a sync context (CLI, tests) still works.

---

### Wave 3 — Path Traversal in Ingestion ✅
**File:** `app/core/ingestion.py`

| ID | Finding | Fix |
|----|---------|-----|
| G3-23 | HuggingFace dataset `label` used as directory name without sanitisation — path traversal | Sanitize `label` with `re.sub(r'[^\w\-]', '_', label)[:64]`; add `Path.resolve()` boundary check against `BASE_INPUT` |

**Acceptance:** A label value of `"../../etc"` or `"/tmp/evil"` is sanitized to a safe string and cannot escape `datasets/input/`.

---

## TIER 2 — 🟠 High (Waves 4–20)

### Wave 4 — Node Base: Event Loop + Observer Contract ⬜
**File:** `app/core/nodes/base.py`

| ID | Finding | Fix |
|----|---------|-----|
| G1-02 | `asyncio.get_event_loop()` deprecated in Python 3.10+ | Replace with `asyncio.get_running_loop()` in `process_stream` |
| G1-03 | Observer stored on `Node` but lifecycle hooks never call it | Wire `self.observer` calls into `on_start`, `on_end`, `on_error` hooks; or add explicit docstring contract that observer is called by the executor only |

**Acceptance:** `process_stream` uses `get_running_loop()`. Observer contract is unambiguous.

---

### Wave 5 — Compat: Union/Optional Schema ⬜
**File:** `app/core/nodes/compat.py`

| ID | Finding | Fix |
|----|---------|-----|
| G1-42 | `_type_to_schema` does not handle `Union`/`Optional` — produces invalid JSON Schema | Add `Union`/`Optional` branch: for `Optional[X]` return `{**schema_of_X, "nullable": True}`; for multi-member `Union` return `{"oneOf": [...]}` |

**Acceptance:** `_type_to_schema(Optional[str])` returns `{"type": "string", "nullable": True}`. `_type_to_schema(Union[int, str])` returns `{"oneOf": [...]}`.

---

### Wave 6 — Observers: Missing Traceback ⬜
**File:** `app/core/nodes/observers.py`

| ID | Finding | Fix |
|----|---------|-----|
| G1-51 | `LoggingObserver.on_node_error` logs exception message but not traceback | Add `"traceback": traceback.format_exc()` to the JSON payload in `on_node_error` |

**Acceptance:** `on_node_error` log entry contains a `"traceback"` key with the full formatted traceback.

---

### Wave 7 — nodes/__init__.py: Import Side Effects ⬜
**File:** `app/core/nodes/__init__.py`

| ID | Finding | Fix |
|----|---------|-----|
| G1-58 | Module-level side effects at import time — full plugin load + discovery on every import | Add clear module docstring warning; add `GRAPHYN_SKIP_PLUGIN_LOAD` documentation |
| G1-59 | Unhandled `AutoDiscovery` exception aborts entire `app.core.nodes` import | Wrap `AutoDiscovery(registry).run(...)` in `try/except Exception` that re-raises as `ImportError` with a helpful message identifying the offending plugin |

**Acceptance:** A bad plugin raises `ImportError` with a message pointing to the plugin file, not a raw `DuplicateNodeTypeError`.

---

### Wave 8 — Pipeline: Execution Correctness (4 fixes) ⬜
**File:** `app/core/pipeline.py`

| ID | Finding | Fix |
|----|---------|-----|
| G2-02 | `parallel=True` + `event_driven=True` silently executes both branches | Add mutual-exclusion guard at top of `run_pipeline_ir_async`: `if parallel and event_driven: raise ValueError(...)` |
| G2-04 | `_write_checkpoint` path traversal via unsanitised `node_id` | Add `os.path.realpath` boundary check: resolve checkpoint path and assert it starts with `run_base_path` |
| G2-05 | No cancel check between waves in parallel mode | Add `if run.is_cancelled: break` between waves in the parallel execution loop |
| G2-06 | Event-driven mode ignores conditional edges | Apply same condition-check logic from sequential loop inside `_handle_source` before assembling each input port value |

**Acceptance:** Passing both flags raises `ValueError`. A `node_id` with `../` raises `ValueError`. Cancel signal stops parallel execution at next wave boundary. Conditional edges are respected in event-driven mode.

---

### Wave 9 — Validation: None Node ID Guard ⬜
**File:** `app/core/validation.py`

| ID | Finding | Fix |
|----|---------|-----|
| G2-12 | `_validate_dag_edges` does not guard against `None` node IDs from empty `from`/`to` lists | Add explicit `if from_id is None: raise ValueError("Edge 'from' field is missing or empty")` and same for `to_id` |

**Acceptance:** An edge dict with `"from": []` raises `ValueError: Edge 'from' field is missing or empty`.

---

### Wave 10 — Pipeline Cache: TOCTOU + Multi-Port ⬜
**File:** `app/core/pipeline_cache.py`

| ID | Finding | Fix |
|----|---------|-----|
| G2-16 | `has()` / `load()` TOCTOU race — cache entry can disappear between check and read | Document that `load()` returning `None` is a valid miss signal; update all callers to treat `None` as a cache miss without a prior `has()` check |
| G2-17 | `save()` drops all but first AudioSample port — multi-port nodes lose data | Fix `save()` to iterate all AudioSample ports and write each to a named subdirectory; fix `load()` to reconstruct all ports by port name |

**Acceptance:** A node with two AudioSample output ports (`output`, `augmented`) has both ports correctly saved and loaded. `load()` returning `None` is handled gracefully by all callers.

---

### Wave 11 — Executor: Concurrent Artifact Registration ⬜
**File:** `app/core/executor.py`

| ID | Finding | Fix |
|----|---------|-----|
| G2-22 | Concurrent artifact registration in `_run_node` not thread-safe | Verify `RunManager.register_artifact` uses `_artifacts_lock`; if artifact registration reads `run_manager.artifacts` before writing, move that read-modify pattern to a post-wave serial step |

**Acceptance:** Concurrent `_run_node` calls for nodes in the same wave do not produce duplicate or missing artifact registrations.

---

### Wave 12 — IR Models: Immutability ⬜
**File:** `app/core/ir/models.py`

| ID | Finding | Fix |
|----|---------|-----|
| G2-31 | `dependency_requirements: list[str]` is mutable inside a `frozen=True` model | Change to `tuple[str, ...]` with `default=()` |
| P-23 | `IRNode.config` dict is mutable despite `frozen=True` on the model | Add `@field_validator("config", mode="before")` that calls `copy.deepcopy(v)` on construction |

**Acceptance:** `ir_node.config["key"] = "mutated"` raises `TypeError` (MappingProxyType) or the mutation does not affect the original. `ir_node.capability_metadata.dependency_requirements.append(...)` raises `AttributeError`.

---

### Wave 13 — RunManager: Resume State + Path Safety ⬜
**File:** `app/core/run_manager.py`

| ID | Finding | Fix |
|----|---------|-----|
| G3-01 | `update_resume_state` read-modify-write not locked — concurrent node completions lose entries | Protect the entire read-modify-write with `self._meta_lock` |
| G3-04 | `update_resume_state` raises uncaught `JSONDecodeError` on corrupt state file | Wrap `json.load` in `try/except (json.JSONDecodeError, ValueError)` with a warning log and graceful return |
| G3-05 | Checkpoint path constructed from unsanitised `os.listdir` entry — symlink escape | Add `Path.resolve()` boundary check: assert resolved path starts with `runs_dir_path` |

**Acceptance:** Two concurrent `update_resume_state` calls both persist their node IDs. A corrupt `resume_state.json` logs a warning and does not crash. A symlink named `../../etc` in the runs directory is skipped.

---

### Wave 14 — ArtifactStore: Dedup Index Gap ⬜
**File:** `app/core/artifact_store.py`

| ID | Finding | Fix |
|----|---------|-----|
| G3-09 | Deduplicated artifacts not added to `by_run` secondary index — `list(run_id=X)` returns incomplete results | Call `self._append_by_run(run_id, existing.artifact_id)` in the deduplication early-return path before returning |

**Acceptance:** `artifact_store.list(run_id=X)` returns deduplicated artifacts that were registered during run X.

---

### Wave 15 — Ingestion: IngestionJob Status Race ⬜
**File:** `app/core/ingestion.py`

| ID | Finding | Fix |
|----|---------|-----|
| G3-22 | `IngestionJob.status` written without lock — data race between worker thread and `stream_job` reader | Add `set_status(status: str)` method to `IngestionJob` that acquires `_lock`; replace all direct `job.status = ...` assignments with `job.set_status(...)` |

**Acceptance:** Concurrent `set_status` and `stream_job` reads do not produce torn reads or missed final status transitions.

---

### Wave 16 — ProjectManager: O(N) + Path Traversal ⬜
**File:** `app/core/project_manager.py`

| ID | Finding | Fix |
|----|---------|-----|
| G3-26 | `list_samples()` opens every WAV file for metadata before paginating — O(N) file opens per page | Apply `offset`/`limit` pagination to the file list before reading WAV metadata; only open files in the requested page |
| G3-30 | Project `name` used as directory component without path traversal check | Add `_SAFE_NAME_RE = re.compile(r'^[\w\-]{1,128}$')` validation at all entry points (`create`, `rename`, `delete`, etc.) |

**Acceptance:** `list_samples(limit=10, offset=0)` opens at most 10 WAV files. A project name of `"../runs"` raises `ValueError`.

---

### Wave 17 — PluginManager: Duplicate Guard + Temp Cleanup ⬜
**File:** `app/core/plugins/manager.py`

| ID | Finding | Fix |
|----|---------|-----|
| G4-01 | Duplicate-install guard bypassed for URL/path sources — `_parse_name_version` returns raw URL as name | Move duplicate check to after manifest is parsed; use `manifest.name` as the authoritative lookup key |
| G4-02 | Temp-dir cleanup not in `finally` — leaks on manifest parse failure | Wrap Steps 5–8 in a single `try/finally` that always calls `shutil.rmtree(resolved_tmpdir, ignore_errors=True)` |

**Acceptance:** Installing the same plugin twice from a URL raises `PluginAlreadyInstalledError`. A manifest parse failure does not leave a temp directory on disk.

---

### Wave 18 — PluginLoader: Platform Version Fallback ⬜
**File:** `app/core/plugins/loader.py`

| ID | Finding | Fix |
|----|---------|-----|
| G4-06 | `"0.0.0"` fallback blocks all plugins with `>=X.Y` specifiers when `app.__version__` is unset | When `app.__version__` cannot be determined, log a `WARNING` and skip the platform compat check rather than blocking with `"0.0.0"` |

**Acceptance:** In a dev environment without `app.__version__` set, plugins with `platform_version = ">=1.0"` load successfully with a warning log.

---

### Wave 19 — Security: Git Injection + Index Download + pip Timeout ⬜
**Files:** `app/core/plugins/installer.py`, `app/core/plugins/index.py`, `app/core/plugins/dependencies.py`

| ID | File | Finding | Fix |
|----|------|---------|-----|
| G4-23 | `installer.py` | Git URL passed without `--` separator — flag injection via crafted URL | Add `"--"` before `clone_url` in the `subprocess.run` git clone command list |
| G4-25 | `index.py` | `_fetch_remote` uses blocking full-body `httpx.get` with no size limit | Replace with `httpx.stream("GET", url, timeout=10)` + byte-count limit (10 MB) mirroring `_download_with_limit` pattern |
| G4-28 | `dependencies.py` | `_auto_install` subprocess has no timeout — hangs indefinitely | Add `timeout=300` to `subprocess.run`; catch `subprocess.TimeoutExpired` and raise `PluginDependencyError` |

**Acceptance:** A git URL of `"--upload-pack=evil"` is treated as a URL, not a flag. An index server returning >10 MB raises `PluginInstallError`. A hanging pip install is killed after 5 minutes.

---

### Wave 20 — SDK: Missing Methods ⬜
**File:** `app/core/sdk.py`

| ID | Finding | Fix |
|----|---------|-----|
| G5-17 | SDK missing `Pipeline.validate()` — REST API and CLI both expose it | Add `Pipeline.validate() -> list[str]` that delegates to the same validation logic used by the REST API router; returns empty list if valid |
| G5-20 | SDK missing `pause()`, `resume()`, `cancel()` on `Pipeline` | Add `Pipeline.pause()`, `Pipeline.resume()`, `Pipeline.cancel()` that delegate to `get_active_run(self._last_run_id)` and call the corresponding `RunManager` methods |

**Acceptance:** `pipeline.validate()` returns `[]` for a valid pipeline and a non-empty list for an invalid one. `pipeline.cancel()` cancels an in-progress run.

---

## TIER 3 — 🟡 Medium (Waves 21–45)

### Wave 21 — Open Items: N-06 + N-04 + N-10 ⬜
**Files:** `app/core/nodes/base.py`, `app/core/nodes/ports.py`, `app/core/nodes/registry.py`

| ID | Finding | Fix |
|----|---------|-----|
| N-06 | `port.name` can drift from dict key — no validator | Add `port.name == dict_key` check in `Node.__init_subclass__`; raise `ValueError` on mismatch |
| N-04 | `setup()` not enforced before `process()` | Add docstring warning to `setup()` and `process()` clarifying that direct `process()` calls bypass the lifecycle |
| N-10 | `find_compatible_nodes` O(N×M) | Add `# TODO: add inverted index when node count exceeds 200` comment in `find_compatible_nodes` |

---

### Wave 22 — nodes/base.py: Medium Fixes ⬜
**File:** `app/core/nodes/base.py`

| ID | Finding | Fix |
|----|---------|-----|
| G1-04 | `_siso_process` uses `inputs.get("input")` — silently returns `None` for missing key | Replace with explicit `if "input" not in inputs: raise KeyError(...)` |
| G1-06 | `setup()` docstring implies false enforcement contract | Add note: "Enforcement of this ordering is the responsibility of the pipeline executor" |

---

### Wave 23 — nodes/metadata.py: Validators ⬜
**File:** `app/core/nodes/metadata.py`

| ID | Finding | Fix |
|----|---------|-----|
| G1-14 | `_version_format` regex accepts single-digit versions — undocumented relaxation | Add comment explaining why single-digit versions are accepted; or tighten to require `MAJOR.MINOR` minimum |
| G1-19 | `memory_requirements` accepts arbitrary strings — no format validation | Add validator with regex `r"^\d+(\.\d+)?\s*(B|KB|MB|GB|TB)$"` or add docstring noting it is a free-form hint |

---

### Wave 24 — nodes/retry.py: Bounds + Docs ⬜
**File:** `app/core/nodes/retry.py`

| ID | Finding | Fix |
|----|---------|-----|
| G1-21 | `attempt_index` 0-indexed — non-standard vs tenacity/backoff | Add warning to docstring: "Note: attempt_index is 0-indexed (0 = first retry). Differs from tenacity which uses 1-indexed attempt numbers." |
| G1-22 | No upper bound on `max_attempts` — unbounded retry loops possible | Add validator: `if v > 100: raise ValueError("max_attempts must be <= 100")` |

---

### Wave 25 — nodes/registry.py: Medium Fixes ⬜
**File:** `app/core/nodes/registry.py`

| ID | Finding | Fix |
|----|---------|-----|
| G1-25 | `get_config_schema` no guard for non-Pydantic `Config` class | Add `if not hasattr(cfg, "model_json_schema"): raise TypeError(...)` |
| G1-27 | `list_nodes` full copy — no pagination | Add `# TODO: add pagination when node count exceeds ~500` comment |
| G1-29 | `to_json`/`parse_metadata_list` round-trip lossiness undocumented | Add docstring note about `data_type` FQN string serialisation |

---

### Wave 26 — nodes/discovery.py: Medium Fixes ⬜
**File:** `app/core/nodes/discovery.py`

| ID | Finding | Fix |
|----|---------|-----|
| G1-30 | `_register_node` mutates ClassVar `metadata` in-place — stale on re-registration | Add comment explaining the guard and its limitation |
| G1-31 | `_pascal_to_snake` incorrect for 2-letter acronyms (`IONode` → `i_o`) | Fix regex or add special-case; add `IONode` to docstring examples |
| G1-33 | Bare `except Exception` in `_scan_directory` masks fatal errors | Narrow to `except (ImportError, AttributeError, TypeError, ValueError)` |

---

### Wave 27 — nodes/catalogue.py: Error Message ⬜
**File:** `app/core/nodes/catalogue.py`

| ID | Finding | Fix |
|----|---------|-----|
| G1-39 | `resolve()` error message lists all registered types — can be very long | Truncate: `f"Registered types (first 20): {sorted(self._types)[:20]}"` |

---

### Wave 28 — nodes/compat.py: Design + Docs ⬜
**File:** `app/core/nodes/compat.py`

| ID | Finding | Fix |
|----|---------|-----|
| G1-41 | `Optional[X] → X` rejected — design decision undocumented | Add docstring note: "Optional[X] output is NOT compatible with X input — use an explicit null-check node" |
| G1-43 | `check_connection` takes instances; `are_compatible` takes types — inconsistent API | Add `check_connection_classes(src_class, src_port, dst_class, dst_port)` class-level variant |
| G1-46 | `are_compatible` docstring missing Rules 3b–3d | Add Rules 3b (`list` plain input), 3c (`object` universal sink), 3d (`object` universal source) to docstring |

---

### Wave 29 — nodes/errors.py: Structure ⬜
**File:** `app/core/nodes/errors.py`

| ID | Finding | Fix |
|----|---------|-----|
| G1-47 | `PipelineGraphError` belongs in pipeline layer, not node layer | Move to `app/core/pipeline_errors.py`; re-export from `nodes/errors.py` for backward compatibility |
| G1-48 | All exceptions are string-only — no structured fields | Add structured `__init__` with typed fields to `NodeNotFoundError` and `DuplicateNodeTypeError` |

---

### Wave 30 — nodes/observers.py: NullObserver + Docs ⬜
**File:** `app/core/nodes/observers.py`

| ID | Finding | Fix |
|----|---------|-----|
| G1-53 | No `NullObserver` — callers must check `observer is not None` | Add `NullObserver(NodeObserver)` no-op implementation |
| G1-56 | `NodeObserver` docstring says "class name" but should say "node_type string" | Update: "node_type: The node_type string (e.g. 'clean'), not the class name (e.g. 'CleanNode')" |

---

### Wave 31 — pipeline.py: Medium Fixes ⬜
**File:** `app/core/pipeline.py`

| ID | Finding | Fix |
|----|---------|-----|
| G2-03 | Condition expression evaluated twice — TOCTOU | Cache condition result from first evaluation pass; reuse in skip-node check |
| G2-07 | `run_pipeline_ir_async` is 740 lines — violates SRP | Add `# TODO: extract _run_sequential, _run_parallel, _run_event_driven` comment |
| G2-08 | Partial checkpoint data silently discarded — no entry index in warning | Include failing entry index in the warning message |
| G2-09 | O(N²) `_resolve_capability` scan in sequential loop | Pre-build `ir_nodes_map = {n.id: n for n in graph.nodes}` before the sequential loop |

---

### Wave 32 — pipeline_cache.py: Medium Fixes ⬜
**File:** `app/core/pipeline_cache.py`

| ID | Finding | Fix |
|----|---------|-----|
| G2-18 | `clear()` not atomic — partial deletion on error | Wrap each `shutil.rmtree` in `try/except`; log failures and continue; return summary of failed deletions |
| G2-19 | Double JSON serialization in `save()` | Attempt `json.dumps` once; catch `TypeError`/`ValueError` as the "not serializable" signal; reuse the result for writing |

---

### Wave 33 — ir/loader.py: Order + Atomicity ⬜
**File:** `app/core/ir/loader.py`

| ID | Finding | Fix |
|----|---------|-----|
| G2-34 | Pydantic validation before version check — wrong order | Check `data.get("schema_version")` from raw dict first; raise `IRVersionError` before `model_validate` |
| G2-35 | `dump_ir_to_file` not atomic — partial write on interrupt | Use tmp-file-then-`os.replace` pattern: write to `.tmp`, then `tmp.replace(p)` |

---

### Wave 34 — run_manager.py: Medium Fixes ⬜
**File:** `app/core/run_manager.py`

| ID | Finding | Fix |
|----|---------|-----|
| G3-02 | mtime fallback sorts incorrectly against ISO timestamps | Convert mtime to ISO: `datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()` |
| G3-03 | Imports private `_load_checkpoint_outputs` from `pipeline.py` | Promote `_load_checkpoint_outputs` to a public function in `pipeline.py` |

---

### Wave 35 — logger.py: Double Emit + Queue ⬜
**File:** `app/core/logger.py`

| ID | Finding | Fix |
|----|---------|-----|
| G3-06 | `summary()` emits two log entries for the same event | Remove `self.info(...)` call from `summary()`; include human-readable message inside the structured event |
| G3-07 | `deque` iteration in `save_logs` not atomic with concurrent appends | Add `snapshot()` method to `PipelineLogger` that returns a copy under a lock |
| G3-08 | `queue.put()` can block pipeline thread indefinitely | Replace with `queue.put_nowait(entry)` + `queue.Full` catch and warning log |

---

### Wave 36 — artifact_store.py: Lock + Cleanup ⬜
**File:** `app/core/artifact_store.py`

| ID | Finding | Fix |
|----|---------|-----|
| G3-11 | Single lock serializes all artifact registrations including disk I/O | Move `_serialize_data()` outside the lock; hold lock only for index read-modify-write |
| G3-12 | Partial `artifact_dir` not cleaned up on serialization failure | Add `try/except ArtifactSerializationError` that calls `shutil.rmtree(artifact_dir, ignore_errors=True)` before re-raising |

---

### Wave 37 — provenance.py: Atomicity + Sentinel ⬜
**File:** `app/core/provenance.py`

| ID | Finding | Fix |
|----|---------|-----|
| G3-13 | `None` assigned to `list[str]` variable on index read failure | Replace with `use_fast_path = True/False` sentinel flag |
| G3-14 | `record()` silently overwrites existing provenance | Document overwrite behaviour in docstring; consider appending to a list of provenance records |
| G3-15 | `by_run_path.write_text()` not atomic — crash corrupts index | Use tmp+replace pattern for both `by_run_path` and `by_hash_path` writes |

---

### Wave 38 — quality_checker.py: Docs + Degradation Warning ⬜
**File:** `app/core/quality_checker.py`

| ID | Finding | Fix |
|----|---------|-----|
| G3-16 | `_check_snr` docstring claims "non-silent frames" but uses whole-file mean | Update docstring: "signal_power = mean squared amplitude of the entire file (not VAD-filtered)" |
| G3-17 | Duplicate detection silently degrades without `librosa` | Add a finding to results when resampling is skipped: `{"check_name": "duplicates", "severity": "warning", "detail": "..."}` |
| G3-19 | O(N × file_size) peak memory — no batching | Add `# TODO: process files in batches` comment; document memory behaviour |

---

### Wave 39 — project_manager.py: Medium Fixes ⬜
**File:** `app/core/project_manager.py`

| ID | Finding | Fix |
|----|---------|-----|
| G3-24 | `datetime.utcnow()` deprecated in Python 3.12+ | Replace with `datetime.now(timezone.utc).year` |
| G3-27 | `ProjectManager` is a God Object (~1000 lines) | Add `# TODO: extract AnnotationService, VersionService, DatasetStatsService` comment |
| G3-28 | `_read_json` raises on corrupt JSON — callers not guarded | Add `except json.JSONDecodeError` with warning log and return `default` |
| G3-29 | `get_stats()` opens each WAV file twice | Merge `_wav_info` and `_estimate_snr` into a single file open in `get_stats()` |

---

### Wave 40 — plugins/: Medium Fixes ⬜
**Files:** `manifest.py`, `store.py`, `loader.py`, `index.py`, `dependencies.py`

| ID | File | Finding | Fix |
|----|------|---------|-----|
| G4-07 | `loader.py` | Accesses private `_classes` attribute of `NodeRegistry` | Add public `NodeRegistry.registered_types() -> frozenset[str]` method; use it in `loader.py` |
| G4-08 | `loader.py` | All-entry-points-fail returns `[]` silently | After loop, if `new_node_types` is empty and `manifest.entry_points` is non-empty, raise `PluginLoadError` |
| G4-10 | `manifest.py` | `load_manifest` calls `toml_path.exists()` twice — TOCTOU | Capture `chosen_path = toml_path if toml_path.exists() else json_path`; use for both load and source string |
| G4-11 | `manifest.py` | `__init__` override breaks Pydantic `model_copy()` and pickle | Remove `__init__` override; use `@classmethod from_dict(data)` factory that wraps `model_validate` |
| G4-15 | `store.py` | Lock released before `PluginRecord` construction — undocumented | Add comment explaining that `data` is a local snapshot and the lock only needs to protect the file read |
| G4-16 | `store.py` | `_save()` missing `os.fsync()` — data loss on power failure | Add `fh.flush(); os.fsync(fh.fileno())` before closing the temp file |
| G4-26 | `index.py` | `lookup()` silently falls back to string match on specifier parse failure | Log parse exception at WARNING; raise `PluginIndexError` with clear message about invalid specifier |
| G4-29 | `dependencies.py` | `pkg_version(req.name)` does not normalise package name | Use `packaging.utils.canonicalize_name(req.name)` before calling `importlib.metadata.version` |

---

### Wave 41 — sdk.py: Medium Fixes ⬜
**File:** `app/core/sdk.py`

| ID | Finding | Fix |
|----|---------|-----|
| G5-01 | `ArtifactCollection.get()` priority order masks artifact lookup | Separate into `get(key)` for raw dict and `get_artifact(node_id)` for artifact lookup |
| G5-02 | `_from_ir()` bypasses `_validate()` — unregistered node types silently accepted | Add optional `validate: bool = False` parameter; document the trade-off |
| G5-04 | `ArtifactCollection.lineage()` creates new `ProvenanceStore` per call | Cache `ProvenanceStore` as a module-level singleton |
| G5-05 | `_SubscriberLoggerClass` global lazy-init not thread-safe | Use `threading.Lock` to protect the lazy initialisation |
| G5-06 | `PipelineNode._validate()` catches bare `Exception` | Narrow to `except (KeyError, LookupError)` |
| G5-13 | `ArtifactCollection` dict-protocol methods not listed in docstring | Add supported method list to class docstring |
| G5-14 | `Pipeline.run()` missing `Raises` for `resume_run_id` not found | Add `Raises: ResumeError` to docstring |
| G5-15 | `install_plugin()` return type `PluginRecord` not in `TYPE_CHECKING` | Add `from app.core.plugins.store import PluginRecord` under `TYPE_CHECKING` |
| G5-18 | SDK missing `get_node_config_schema()` / `get_node_port_schema()` | Add module-level functions delegating to `registry.get_config_schema()` and `registry.get_port_schema()` |
| G5-19 | SDK missing `list_nodes()` top-level function | Add `list_nodes(category=None)` delegating to `registry.list_nodes()` |

---

### Waves 42–45 — Test Coverage Gaps ⬜

| Wave | Scope | Findings to address |
|------|-------|---------------------|
| 42 | Test files — G1 Node System | G1-05, G1-09, G1-12, G1-28, G1-35, G1-40, G1-45, G1-55 |
| 43 | Test files — G2 Pipeline & IR | G2-14, G2-20, G2-24, G2-26, G2-32 |
| 44 | Test files — G3 Backend + G4 Plugins | G3-17 test, G4-04, G4-09, G4-13, G4-17, G4-21, G4-22, G4-30 |
| 45 | Test files — G5 + Hypothesis property tests | G5-09, G5-10, G5-21, G5-22, G5-24 + all CP skeletons |

Each wave writes new test functions to the corresponding `unit_test/core/` file. No production code changes.

---

## TIER 4 — 🔵 Low (Waves 46–50)

### Wave 46 — nodes/ Low Findings (Part 1) ⬜
**Files:** `base.py`, `ports.py`, `config.py`, `metadata.py`, `retry.py`

| ID | File | Fix |
|----|------|-----|
| G1-01 | `base.py` | Add inline comment explaining SISO double-wrap guard edge case |
| G1-08 | `ports.py` | Add `PortDataType` dual-role (type vs instance) note to docstring |
| G1-10 | `ports.py` | Add `OutputPort` asymmetry note to docstring |
| G1-11 | `config.py` | Add comment explaining `populate_by_name=True` purpose |
| G1-13 | `config.py` | Update docstring example to match steering file pattern |
| G1-17 | `metadata.py` | Return `v.strip()` in `_non_empty` validator |
| G1-18 | `metadata.py` | Add parametrised version string tests |
| G1-20 | `retry.py` | Add note to docstring: "If backoff_seconds=0.0, all waits are 0 regardless of multiplier" |
| G1-23 | `retry.py` | Add test for constant backoff (`multiplier=1.0`) |

---

### Wave 47 — nodes/ Low Findings (Part 2) ⬜
**Files:** `registry.py`, `discovery.py`, `catalogue.py`, `observers.py`, `__init__.py`

| ID | File | Fix |
|----|------|-----|
| G1-26 | `registry.py` | Change `from_json` from `@staticmethod` to `@classmethod` or document LSP limitation |
| G1-32 | `discovery.py` | Move `PluginLoader` import to top of `run()` method (before loop) |
| G1-34 | `discovery.py` | Add `# TODO: optimise for large plugin directories` comment |
| G1-37 | `discovery.py` | Add comment to `_PLUGINS_DIR_DEFAULT`: "Sentinel: distinguishes 'not passed' from None" |
| G1-40 | `catalogue.py` | Add test: `catalogue.register(str)` → verify `TypeError` |
| G1-49 | `errors.py` | Add `isinstance` hierarchy test for all exception subclasses |
| G1-50 | `errors.py` | Update `NodeTypeError` docstring to mention missing-port case |
| G1-52 | `observers.py` | Add note to `NodeObserver` docstring recommending `__repr__` implementation |
| G1-60 | `__init__.py` | Add comment explaining `PluginManager()` instantiation at startup |
| G1-61 | `__init__.py` | Add parametrised test for `GRAPHYN_SKIP_PLUGIN_LOAD` values |
| G1-62 | `__init__.py` | Move `from ... import` statements before `__all__` definition |

---

### Wave 48 — pipeline/ir/ Low Findings ⬜
**Files:** `pipeline.py`, `validation.py`, `pipeline_cache.py`, `executor.py`, `conditions.py`, `events.py`, `ir/`

| ID | File | Fix |
|----|------|-----|
| G2-10 | `pipeline.py` | Add note to `event_loop` param docstring: "accepted but ignored" |
| G2-11 | `pipeline.py` | Move late imports to top of `run_pipeline_ir_async` |
| G2-15 | `validation.py` | Add migration example to `validate_node_config` tombstone docstring |
| G2-21 | `pipeline_cache.py` | Rename `BASE.setter` to `_base_dir` or add `DeprecationWarning` |
| G2-25 | `conditions.py` | Add "Walrus operator not supported" note to module docstring |
| G2-30 | `events.py` | Initialise `_stop_event = asyncio.Event()` in `__init__` for all source classes |
| G2-33 | `ir/models.py` | Remove duplicate sentence from `IREdge.condition` docstring |
| G2-36 | `ir/loader.py` | Remove `IRValidationError` from `__all__` until it is used; add `# future use` comment |
| G2-37 | `ir/yaml_shim.py` | Add early guard: `if not raw_nodes: raise ValueError("Pipeline must contain at least one node")` |
| G2-39 | `ir/migrate.py` | Add `overwrite: bool = False` parameter; raise `FileExistsError` when file exists |
| G2-40 | `ir/migrate.py` | Add `Path(output_path).parent.mkdir(parents=True, exist_ok=True)` |
| G2-41 | `ir/__init__.py` | Add comment: "yaml_shim and migrate intentionally not re-exported (deprecated utilities)" |

---

### Wave 49 — backend/ Low Findings ⬜
**Files:** `run_manager.py`, `logger.py`, `quality_checker.py`, `webhook.py`, `runtime_backend.py`

| ID | File | Fix |
|----|------|-----|
| G3-18 | `quality_checker.py` | Remove unused `report_saved =` assignment; change to `self._persist(...)` |
| G3-20 | `webhook.py` | Initialise `_config_cache: dict | None = None` in `__init__`; use lock for lazy-load |
| G3-21 | `webhook.py` | Replace per-event `threading.Thread` with `ThreadPoolExecutor(max_workers=2)` |
| G3-25 | `project_manager.py` | Normalise WAV paths with `.as_posix()` in `validate_annotations()` |
| G3-31 | `runtime_backend.py` | Protect `_BACKEND_REGISTRY` reads/writes with `_BACKEND_INSTANCES_LOCK` |
| G3-32 | `runtime_backend.py` | Replace `__import__("threading").Lock()` with top-level `import threading` |

---

### Wave 50 — plugins/ + sdk/ Low Findings ⬜
**Files:** `plugins/manager.py`, `plugins/manifest.py`, `plugins/store.py`, `plugins/installer.py`, `plugins/index.py`, `plugins/errors.py`, `plugins/__init__.py`, `sdk.py`, `utils/__init__.py`

| ID | File | Fix |
|----|------|-----|
| G4-03 | `manager.py` | Restructure `enable()` so `update_enabled` is inside the `try` block |
| G4-05 | `manager.py` | Add full NumPy-style docstring to `enable()` |
| G4-12 | `manifest.py` | Change `_rewrap_validation_error` return type from `-> None` to `-> NoReturn` |
| G4-14 | `manifest.py` | Add `_validate_optional_dependencies` validator mirroring `_validate_dependencies` |
| G4-18 | `store.py` | Add `-> "PluginManifest"` return type annotation to `PluginRecord.load_manifest()` |
| G4-19 | `installer.py` | Fix tmpdir cleanup mismatch — return `(resolved_dir, tmpdir)` tuple from all resolvers |
| G4-20 | `installer.py` | Add entry-count limit (100) to `_find_manifest_dir` nested iteration |
| G4-24 | `index.py` | Add `pytest` autouse fixture in `conftest.py` to reset `PluginIndexClient._cache` before each test |
| G4-27 | `index.py` | Add test for `lookup()` with invalid specifier string |
| G4-32 | `errors.py` | Add `KeyError` repr behaviour note to `PluginNotFoundError` docstring |
| G4-33 | `__init__.py` | Align docstring import order with actual import order |
| G5-03 | `sdk.py` | Add `allow_unicode=True` to `yaml.dump` in `to_yaml()` |
| G5-07 | `sdk.py` | Document idempotent unsubscribe behaviour in `subscribe()` docstring |
| G5-08 | `sdk.py` | Add note to `__init__` docstring: "Prefer Pipeline.from_json() for loading from file" |
| G5-11 | `sdk.py` | Add test: `get_last_run_id() == run_manager.run_id` after `run_with_manager()` |
| G5-12 | `sdk.py` | Add docstring note: "Load output YAML with yaml.safe_load(), not yaml.load()" |
| G5-16 | `sdk.py` | Move `import yaml` to module top level |
| G5-23 | `utils/__init__.py` | Update module docstring to list exported symbols |

---

## Execution Checklist

```
Wave  1  ✅  G1-24, G1-38   — registry.py + catalogue.py thread safety
Wave  2  ✅  G2-01           — pipeline.py asyncio crash
Wave  3  ✅  G3-23           — ingestion.py path traversal
Wave  4  ✅  G1-02, G1-03   — base.py event loop + observer
Wave  5  ✅  G1-42           — compat.py Union/Optional schema
Wave  6  ✅  G1-51           — observers.py missing traceback
Wave  7  ✅  G1-58, G1-59   — nodes/__init__.py import side effects
Wave  8  ✅  G2-02..G2-06   — pipeline.py execution correctness
Wave  9  ✅  G2-12           — validation.py None node ID guard
Wave 10  ✅  G2-16, G2-17   — pipeline_cache.py TOCTOU + multi-port
Wave 11  ✅  G2-22           — executor.py concurrent artifact registration
Wave 12  ✅  G2-31, P-23    — ir/models.py immutability
Wave 13  ✅  G3-01..G3-05   — run_manager.py resume state + path safety
Wave 14  ✅  G3-09           — artifact_store.py dedup index gap
Wave 15  ✅  G3-22           — ingestion.py IngestionJob status race
Wave 16  ✅  G3-26, G3-30   — project_manager.py O(N) + path traversal
Wave 17  ✅  G4-01, G4-02   — manager.py duplicate guard + temp cleanup
Wave 18  ✅  G4-06           — loader.py platform version fallback
Wave 19  ✅  G4-23..G4-28   — security: git injection + index + pip timeout
Wave 20  ✅  G5-17, G5-20   — sdk.py missing methods
Wave 21  ⬜  N-06, N-04, N-10 — open items
Wave 22  ⬜  G1-04, G1-06   — base.py medium
Wave 23  ⬜  G1-14, G1-19   — metadata.py medium
Wave 24  ⬜  G1-21, G1-22   — retry.py medium
Wave 25  ⬜  G1-25..G1-29   — registry.py medium
Wave 26  ⬜  G1-30..G1-33   — discovery.py medium
Wave 27  ⬜  G1-39           — catalogue.py medium
Wave 28  ⬜  G1-41..G1-46   — compat.py medium
Wave 29  ⬜  G1-47, G1-48   — errors.py medium
Wave 30  ⬜  G1-53, G1-56   — observers.py medium
Wave 31  ⬜  G2-03..G2-09   — pipeline.py medium
Wave 32  ⬜  G2-18, G2-19   — pipeline_cache.py medium
Wave 33  ⬜  G2-34, G2-35   — ir/loader.py medium
Wave 34  ⬜  G3-02, G3-03   — run_manager.py medium
Wave 35  ⬜  G3-06..G3-08   — logger.py medium
Wave 36  ⬜  G3-11, G3-12   — artifact_store.py medium
Wave 37  ⬜  G3-13..G3-15   — provenance.py medium
Wave 38  ⬜  G3-16..G3-19   — quality_checker.py medium
Wave 39  ⬜  G3-24..G3-29   — project_manager.py medium
Wave 40  ⬜  G4-07..G4-29   — plugins/ medium
Wave 41  ⬜  G5-01..G5-19   — sdk.py medium
Wave 42  ⬜  Test gaps G1
Wave 43  ⬜  Test gaps G2
Wave 44  ⬜  Test gaps G3/G4
Wave 45  ⬜  Test gaps G5 + Hypothesis
Wave 46  ⬜  Low: nodes/ part 1
Wave 47  ⬜  Low: nodes/ part 2
Wave 48  ⬜  Low: pipeline/ir/
Wave 49  ⬜  Low: backend/
Wave 50  ⬜  Low: plugins/sdk/
```

---

*Document generated from second-pass review — 185 findings · 50 waves · sequential execution*
*To begin: say "start Wave 1" or "start Wave N" to jump to a specific wave.*
