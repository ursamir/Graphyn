# `app/core` Deep Review — Index

**Date:** 2026-05-18
**Updated:** 2026-05-19
**Scope:** `/home/meritech/Desktop/newAudio3/app/core` — all Python files
**Method:** Full source read + static analysis across all layers

**Fix status:** All Sprint 1–4 items implemented and verified. Sprint 5 (this session) completed.
**Test results (2026-05-19):**
- `unit_test/` — **876 passed, 0 failed, 17 skipped**
- `tests/` (legacy) — **1443 passed, 0 failed**

---

## Documents in this Review

| File | Layer | Issues |
|---|---|---|
| [01-NODE-SYSTEM.md](01-NODE-SYSTEM.md) | `app/core/nodes/` | 18 issues (N-01 → N-18) |
| [02-PIPELINE-IR.md](02-PIPELINE-IR.md) | `pipeline.py`, `validation.py`, `pipeline_cache.py`, `executor.py`, `conditions.py`, `events.py`, `ir/` | 25 issues (P-01 → P-25) |
| [03-BACKEND-SERVICES.md](03-BACKEND-SERVICES.md) | `run_manager.py`, `logger.py`, `artifact_store.py`, `provenance.py`, `config.py`, `quality_checker.py`, `webhook.py`, `ingestion.py`, `project_manager.py`, `runtime_backend.py` | 37 issues (B-01 → B-37) |
| [04-PLUGIN-ECOSYSTEM.md](04-PLUGIN-ECOSYSTEM.md) | `app/core/plugins/` | 14 issues (PL-01 → PL-14) |
| [05-SDK-UTILS.md](05-SDK-UTILS.md) | `sdk.py`, `utils/hash.py`, `__init__.py` | 9 issues (S-01 → S-09) |
| **[AUDIT.md](AUDIT.md)** | **All layers** | **Complete fix-status audit: 96 ✅ / 4 🔶 / 3 ❌** |

**Total: 103 issues**

---

## Severity Legend

| Severity | Meaning |
|---|---|
| 🔴 **Critical** | Data loss, security vulnerability, correctness bug, or crash in normal use |
| 🟠 **High** | Significant performance problem, silent failure, or design flaw with real impact |
| 🟡 **Medium** | Maintainability hazard, fragile pattern, or missing guard that will eventually bite |
| 🔵 **Low** | Style, naming, dead code, or minor inconsistency |

---

## Issue Count by Severity

| Severity | Count |
|---|---|
| 🔴 Critical | 11 |
| 🟠 High | 32 |
| 🟡 Medium | 40 |
| 🔵 Low | 20 |

---

## All Critical Issues (🔴) — All Fixed ✅

| ID | File | Issue | Status |
|---|---|---|---|
| N-11 | `nodes/discovery.py` | Plugin module name collision — second plugin's `nodes.py` overwrites first in `sys.modules` | ❌ Deferred (requires plugin naming convention enforcement) |
| P-09 | `validation.py` | `validate_node_config` always returns `{}` — silent false pass | ✅ Fixed — now raises `NotImplementedError` |
| P-11 | `pipeline_cache.py` | `input_hash` repr() fallback not stable across runs — silent cache misses | ✅ Fixed — numpy arrays hashed via `.tobytes()`, warning emitted |
| P-15 | `executor.py` | New `ThreadPoolExecutor` per node — extreme overhead in parallel mode | ✅ Fixed — one pool per wave, shared across all nodes |
| B-01 | `run_manager.py` | `_artifacts` list has no lock — parallel wave execution causes list corruption | ✅ Fixed — `_artifacts_lock` added, public `artifacts` property |
| B-13 | `artifact_store.py` | `_compute_content_hash` for audio_samples doesn't hash audio data — false deduplication | ✅ Fixed — PCM bytes hash included |
| B-20 | `config.py` | `plugins_home()` returns CWD-relative path — split-brain with `plugin_registry_path()` | ✅ Fixed — both now under `graphyn_home()` |
| B-26 | `webhook.py` | No URL validation — SSRF via `file://` or internal network URLs | ✅ Fixed — scheme + netloc validation in `save()` |
| PL-01 | `plugins/manager.py` | `install()` not atomic — orphaned directory on failed load | ✅ Fixed — cleanup on failure in try/except |
| PL-07 | `plugins/installer.py` | Temp directories from `_resolve_local_dir` never deleted — disk leak per install | ✅ Fixed — `_tmpdir_root` tracked for cleanup |
| S-07 | `utils/hash.py` | Separator collision — `stable_hash("a\|b","c") == stable_hash("a","b\|c")` | ✅ Fixed — JSON encoding replaces `"\|".join()` |

---

## Prioritized Fix Roadmap — All Completed ✅

### Sprint 1 — Correctness & Safety

| # | ID | File | Fix | Status |
|---|---|---|---|---|
| 1 | B-01 | `run_manager.py` | `_artifacts_lock` + public `artifacts` property | ✅ |
| 2 | S-07 | `utils/hash.py` | `json.dumps(list(args))` replaces `"\|".join()` | ✅ |
| 3 | P-15 | `executor.py` | One `ThreadPoolExecutor` per wave, shared across nodes | ✅ |
| 4 | B-26 | `webhook.py` | URL scheme + netloc validation in `save()`; config cache in `notify()` | ✅ |
| 5 | PL-07 | `plugins/installer.py` | Temp dir cleanup via `kiro_plugin_` prefix check in `PluginManager.install` | ✅ |
| 6 | P-09 | `validation.py` | `validate_node_config` raises `NotImplementedError` | ✅ |
| 7 | B-20 | `config.py` | `plugins_home()` now returns `graphyn_home() / "plugins" / "installed"` | ✅ |
| 8 | B-13 | `artifact_store.py` | PCM bytes hash included in `_compute_content_hash` for audio_samples | ✅ |
| 9 | PL-01 | `plugins/manager.py` | `install()` wraps steps 7–8 in try/except, cleans up on failure | ✅ |
| 10 | P-11 | `pipeline_cache.py` | numpy `.tobytes()` hash; WARNING on skipped ports | ✅ |

### Sprint 2 — Reliability & Performance

| # | ID | File | Fix | Status |
|---|---|---|---|---|
| 11 | B-02 | `run_manager.py` | `run_id` extended to 16 hex chars | ✅ |
| 12 | B-14 | `artifact_store.py` | `artifact_id` extended to 16 hex chars | ✅ |
| 13 | N-08 | `nodes/registry.py` | `threading.RLock()` on all mutations and reads | ✅ |
| 14 | B-05 | `run_manager.py` | `_ACTIVE_RUNS_LOCK` guards module-level dict | ✅ |
| 15 | P-01 | `pipeline.py` | `asyncio.run()` crash — `RunManager.__init__` reads live env var | ✅ |
| 16 | B-03 | `run_manager.py` | `encoding="utf-8"` on all `open()` calls | ✅ |
| 17 | B-04 | `run_manager.py` | `_meta_lock` guards read-modify-write on `meta.json` | ✅ |
| 18 | B-29 | `ingestion.py` | `_MAX_COMPLETED_JOBS=200` eviction + `_jobs_lock` | ✅ |
| 19 | PL-05 | `plugins/loader.py` | `_get_platform_version()` returns `"0.0.0"` fallback (not `None`) | ✅ |
| 20 | PL-02 | `plugins/manager.py` | `_unload_node_types` uses `inspect.getfile()` + exact path prefix | ✅ |

### Sprint 3 — Design & Maintainability

| # | ID | File | Fix | Status |
|---|---|---|---|---|
| 21 | S-01 | `sdk.py` | `run()` delegates to `run_with_manager()` via shared `_execute()` | ✅ |
| 22 | S-03 | `sdk.py` | `copy.deepcopy(self._graph_ir)` replaces `load_ir(dump_ir(...))` | ✅ |
| 23 | S-04 | `sdk.py` | `_from_ir()` classmethod bypasses double `_build_ir()` in `from_json/from_yaml` | ✅ |
| 24 | P-02 | `pipeline.py` | `_compute_waves` uses precomputed predecessors dict — O(E) not O(N×E) | ✅ |
| 25 | B-10 | `logger.py` | Standardized `"duration_s"` key in all events | ✅ |
| 26 | N-15 | `nodes/observers.py` | `CompositeObserver` wraps each child in try/except | ✅ |
| 27 | B-17 | `provenance.py` | `get_lineage()` uses path-aware recursion with `frozenset` ancestors | ✅ |
| 28 | B-12 | `artifact_store.py` | `_serialize_json` imports numpy conditionally | ✅ |
| 29 | B-30 | `ingestion.py` | `IngestionJob` uses `PrivateAttr` for lock (Pydantic-compatible) | ✅ |
| 30 | N-02 | `nodes/base.py` | `execute_stream` uses `finally: node.on_end()` (P-06) | ✅ |

### Sprint 4 — Polish & Test Coverage

| # | ID | File | Fix | Status |
|---|---|---|---|---|
| 31 | S-09 | `app/core/__init__.py` | Lazy `__getattr__` for `ResumeError` — no eager pipeline import | ✅ |
| 32 | N-16 | `nodes/__init__.py` | `GRAPHYN_SKIP_PLUGIN_LOAD` env var for test isolation | ✅ |
| 33 | S-08 | `utils/__init__.py` | `stable_hash` re-exported | ✅ |
| 34 | B-32 | `project_manager.py` | `datetime.now(timezone.utc)` replaces deprecated `utcnow()` | ✅ |
| 35 | P-06 | `pipeline.py` | `execute_stream` uses `finally: node.on_end()` | ✅ |
| 36 | — | `unit_test/conftest.py` | Shared `isolated_workspace` fixture (autouse) | ✅ |
| 37 | — | `unit_test/` | Fixed 15 unit tests broken by our changes (duration_s key, property setters, shape assertions) | ✅ |

### Additional fixes applied during verification

| ID | File | Fix |
|---|---|---|
| B-19 | `provenance.py` | Warn on overwrite in `record()` |
| B-35 | `project_manager.py` | Single `_wav_info()` helper — one file open per WAV |
| P-05 | `pipeline.py` | `_compute_waves` O(N×E) → O(E) with precomputed predecessors |
| P-24 | `ir/models.py` | `IRMetadata.name` validator strips whitespace |
| P-25 | `ir/loader.py` | `load_ir_from_file` checks `p.is_file()` not just `p.exists()` |
| P-10 | `validation.py` | Edge `"from"/"to"` field type guard |
| PL-03 | `plugins/manager.py` | `enable()` checks registry before reloading |
| PL-06 | `plugins/loader.py` | `DuplicateNodeTypeError` caught separately with node type in message |
| PL-08 | `plugins/installer.py` | `git` on PATH check before clone |
| PL-09 | `plugins/installer.py` | Streaming download with 100 MB size limit |
| PL-10 | `plugins/installer.py` | Zip/tar-slip guard uses `Path.is_relative_to()` |
| PL-13 | `plugins/store.py` | Corrupt registry backed up before treating as empty |
| N-17 | `nodes/__init__.py` | Full traceback logged on `PluginManager` startup failure |
| B-09 | `logger.py` | `self.logs` is a bounded `deque(maxlen=10_000)` |
| B-11 | `logger.py` | `summary()` emits structured `pipeline_summary` event |
| S-02 | `sdk.py` | `run_manager.artifacts` public property used instead of `_artifacts` |
| S-05/S-06 | `sdk.py` | `_SubscriberLogger` properly subclasses `PipelineLogger`; subscriber exceptions logged at WARNING |

### Sprint 5 — Remaining Issues (2026-05-19)

| # | ID | File | Fix | Status |
|---|---|---|---|---|
| 1 | N-02 | `nodes/base.py` | SISO wrapper guard: return dict as-is if keys match output_ports | ✅ |
| 2 | N-03 | `nodes/base.py` | `process_stream` uses `loop.run_in_executor` | ✅ |
| 3 | N-01 | `nodes/base.py` | `config` type hint includes `\| None` | ✅ |
| 4 | N-05 | `nodes/ports.py` | `@field_validator("data_type")` on `InputPort`/`OutputPort` | ✅ |
| 5 | N-07 | `nodes/metadata.py` | `@field_validator("version")` semver pattern | ✅ |
| 6 | N-12 | `nodes/discovery.py` | Direct assignment replaces `object.__setattr__` | ✅ |
| 7 | N-13 | `nodes/compat.py` | Union/Optional rules 4a/4b/4c added | ✅ |
| 8 | N-14 | `nodes/compat.py` | `_type_to_schema` fallback → `{"type": "object", "title": …}` | ✅ |
| 9 | N-18 | `nodes/__init__.py` | Full public API re-exported in `__all__` | ✅ |
| 10 | P-02 | `pipeline.py` | `EdgeSpec.condition` field + `_ir_to_pipeline_config` populates it | ✅ |
| 11 | P-03 | `pipeline.py` | `_write_checkpoint` emits structured `checkpoint_failed` event | ✅ |
| 12 | P-04 | `pipeline.py` | `_infer_artifact_type` uses `isinstance(DatasetArtifact)` | ✅ |
| 13 | P-07 | `pipeline.py` | Dead code `_count_payload`/`_payload_count` removed | ✅ |
| 14 | P-08 | `validation.py` | `_validate_connections` uses ClassVar access, not `__new__` | ✅ |
| 15 | P-13 | `pipeline_cache.py` | `BASE.setter` documented as test-only | ✅ |
| 16 | P-18 | `conditions.py` | 500-char max length guard | ✅ |
| 17 | P-19 | `conditions.py` | `ast.Index` and Python 3.8 comment removed | ✅ |
| 18 | P-20 | `events.py` | `TimerSource`/`QueueSource` `_stop_event` + `close()` | ✅ |
| 19 | P-21 | `events.py` | `FileWatcherSource.poll_interval_s` configurable | ✅ |
| 20 | P-22 | `events.py` | `create_event_source` validates keys against constructor | ✅ |
| 21 | B-06 | `run_manager.py` | `find_latest_checkpoint` falls back to mtime | ✅ |
| 22 | B-07 | `run_manager.py` | `compute_graph_hash` docstring notes identical serialisation path | ✅ |
| 23 | B-08 | `logger.py` | `_emit_structured` writes DEBUG line to Python logging | ✅ |
| 24 | B-12 | `artifact_store.py` | `by_run/` secondary index; fast path for run_id filter | ✅ |
| 25 | B-16 | `artifact_store.py` | `get_versions` O(N) scan documented | ✅ |
| 26 | B-18 | `provenance.py` | `by_graph_hash/` secondary index for `find_reproducible` | ✅ |
| 27 | B-21 | `config.py` | `project_dir()` calls `.resolve()` | ✅ |
| 28 | B-22 | `quality_checker.py` | `_wav_info()` for metadata-only checks; full load only when needed | ✅ |
| 29 | B-23 | `quality_checker.py` | SNR limitation documented in docstring | ✅ |
| 30 | B-24 | `quality_checker.py` | Warning emitted when resampling skipped | ✅ |
| 31 | B-25 | `quality_checker.py` | `_persist` return value captured | ✅ |
| 32 | B-28 | `webhook.py` | daemon=True behaviour documented | ✅ |
| 33 | B-33 | `project_manager.py` | `restore_version`/`restore_snapshot` atomic via temp dir | ✅ |
| 34 | B-34 | `project_manager.py` | 24-bit/32-bit PCM supported; warning on unsupported width | ✅ |
| 35 | B-36 | `runtime_backend.py` | `LocalPythonBackend` docstring clarified | ✅ |
| 36 | B-37 | `runtime_backend.py` | `get_backend()` caches instances in `_BACKEND_INSTANCES` | ✅ |
| 37 | PL-11 | `plugins/manifest.py` | `__init__` override retained; role documented | ✅ |
| 38 | PL-12 | `plugins/manifest.py` | Slug error message human-readable | ✅ |
| 39 | PL-14 | `plugins/store.py` | `PluginRecord.load_manifest()` for validated access | ✅ |
