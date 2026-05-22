# app/core Review Workbook

**Session started:** May 2026  
**Scope:** Full review of every file in `app/core/` — purpose, correctness, intent.  
**Status:** ✅ Complete — all 1443 tests pass.

---

## Mental Model

The platform has four interfaces (REST API, SDK, CLI, MCP) that all share `app/core/`.  
Execution flow: `GraphIR` → `PipelineGraph` → `NodeExecutor` per node → `RunManager` bookkeeping.  
Plugins live in `PluginPackage/` (source) and `plugins/` (installed). The registry is populated at startup by `PluginManager.load_enabled_plugins()` then `AutoDiscovery.run()`.

---

## Files Reviewed

| File | Purpose | Issues Found | Fixed |
|---|---|---|---|
| `nodes/base.py` | Node base class, SISO wrapper | None | — |
| `nodes/ports.py` | Port descriptors, PortDataType | None | — |
| `nodes/config.py` | NodeConfig Pydantic base | None | — |
| `nodes/metadata.py` | NodeMetadata capability fields | None | — |
| `nodes/retry.py` | RetryPolicy with exponential backoff | None | — |
| `nodes/registry.py` | NodeRegistry singleton | None | — |
| `nodes/discovery.py` | AutoDiscovery — scans dirs, registers nodes | 3 bugs (see below) | ✅ |
| `nodes/catalogue.py` | TypeCatalogue — FQN → type mapping | None | — |
| `nodes/compat.py` | CompatibilityChecker, JSON schema helpers | None | — |
| `nodes/errors.py` | Exception hierarchy | None | — |
| `nodes/observers.py` | NodeObserver, LoggingObserver, CompositeObserver | None | — |
| `nodes/__init__.py` | Startup: PluginManager → AutoDiscovery | 2 bugs (see below) | ✅ |
| `ir/models.py` | GraphIR, IRNode, IREdge, IRMetadata Pydantic models | None | — |
| `ir/loader.py` | load_ir, dump_ir, version checking | IRValidationError undocumented | ✅ |
| `ir/migrate.py` | YAML → IR JSON migration utility | None | — |
| `ir/yaml_shim.py` | YAML compat shim | None | — |
| `ir/__init__.py` | Public IR API re-exports | None | — |
| `pipeline.py` | DAG executor, NodeExecutor, run_pipeline_ir | 3 bugs (see below) | ✅ |
| `validation.py` | Pipeline config validation | None | — |
| `conditions.py` | Conditional edge expression evaluator | Docstring inaccurate | ✅ |
| `events.py` | EventSource: FileWatcher, Timer, Queue | None | — |
| `executor.py` | ParallelExecutor — wave-based async execution | `get_event_loop()` deprecated | ✅ |
| `pipeline_cache.py` | PipelineCache — WAV + JSON cache | 2 bugs (see below) | ✅ |
| `sdk.py` | Pipeline, PipelineNode, ArtifactCollection | 2 bugs (see below) | ✅ |
| `run_manager.py` | RunManager — run lifecycle, pause/cancel/resume | Frozen path at import | ✅ |
| `logger.py` | PipelineLogger — structured event emission | `print()` instead of `logging` | ✅ |
| `config.py` | Centralised env var / path resolution | None | — |
| `registry_runtime.py` | Returns NodeRegistry singleton | None | — |
| `ingestion.py` | URL + HuggingFace audio ingestion | Frozen path at import | ✅ |
| `project_manager.py` | Project lifecycle, annotations, versions, stats | 2 bugs (see below) | ✅ |
| `quality_checker.py` | Audio quality checks (SNR, clipping, duplicates) | Frozen path at import | ✅ |
| `artifact_store.py` | Content-addressed artifact registry | None | — |
| `provenance.py` | Artifact lineage tracking | Thread-safety gap | ✅ |
| `webhook.py` | Fire-and-forget HTTP POST notifications | Frozen path + unused import | ✅ |
| `runtime_backend.py` | RuntimeBackend abstraction + LocalPythonBackend | None | — |
| `utils/hash.py` | stable_hash() — MD5 for seeding | FIPS incompatibility | ✅ |
| `plugins/manager.py` | PluginManager — install/uninstall/enable/disable | None | — |
| `plugins/loader.py` | PluginLoader — manifest validation + node registration | None | — |
| `plugins/manifest.py` | PluginManifest Pydantic model + TOML/JSON parser | None | — |
| `plugins/store.py` | PluginStore — JSON registry persistence | None | — |
| `plugins/installer.py` | Source resolution: git/http/local/index | Zip-slip vulnerability | ✅ |
| `plugins/index.py` | PluginIndexClient — remote/local index | 2 bugs (see below) | ✅ |
| `plugins/dependencies.py` | DependencyChecker — PEP 508 verification | None | — |
| `plugins/errors.py` | Plugin exception hierarchy | None | — |
| `plugins/__init__.py` | Error re-exports | None | — |
| `PluginPackage/Audio/segmenter/nodes.py` | Segmenter — fixed/silence/VAD/event modes | No config validation | ✅ |

---

## Bugs Fixed (Detailed)

### 1. `nodes/discovery.py` — Duplicate class check used `__qualname__` not identity
**File:** `app/core/nodes/discovery.py`  
**Problem:** `existing.__qualname__ == obj.__qualname__` is not sufficient — two different classes in different modules can share a `__qualname__`. Changed to `existing is obj` (identity check).

### 2. `nodes/discovery.py` — `plugins_dir=None` not respected (NameError risk)
**File:** `app/core/nodes/discovery.py`  
**Problem:** When `plugins_dir=None` was passed, the code fell through to `plugins_path = Path(plugins_dir)` which would raise `TypeError`. Added `_PLUGINS_DIR_DEFAULT` sentinel to distinguish "use default" from "skip entirely". The `else` block now wraps the entire scan body.

### 3. `nodes/__init__.py` — Double-loading of plugins at startup
**File:** `app/core/nodes/__init__.py`  
**Problem:** `PluginManager.load_enabled_plugins()` ran first, then `AutoDiscovery.run()` scanned `plugins_dir` again — loading every enabled plugin twice. Fixed by passing `plugins_dir=None` to `AutoDiscovery.run()` when `PluginManager` succeeded, skipping the redundant scan.

### 4. `pipeline.py` — Cache key used wrong node config (DAG index bug)
**File:** `app/core/pipeline.py`  
**Problem:** `pipeline_cfg.nodes[idx].config` used `idx` (topological enumeration index) to look up node config. In a DAG, topological order ≠ node list order. This silently used the wrong node's config for cache key computation. Fixed by looking up by `node_id` with `next(spec for spec in pipeline_cfg.nodes if spec.node_id == node_id)`.

### 5. `pipeline.py` — Top-level `import yaml` (unnecessary hard dependency)
**File:** `app/core/pipeline.py`  
**Problem:** `import yaml` at module top-level would crash if PyYAML wasn't installed, even though `yaml` is only used in the deprecated `run_pipeline()` function which already does a lazy import via `load_yaml_with_deprecation`. Removed the top-level import.

### 6. `pipeline_cache.py` — Unconditional top-level `import numpy` and `import soundfile`
**File:** `app/core/pipeline_cache.py`  
**Problem:** `import numpy as np` and `import soundfile as sf` at module top-level crash at import time if those packages aren't installed. Moved to lazy imports inside the functions that use them.

### 7. `executor.py` — `asyncio.get_event_loop()` deprecated in Python 3.10+
**File:** `app/core/executor.py`  
**Problem:** `asyncio.get_event_loop()` emits a `DeprecationWarning` in Python 3.10+ when called outside an async context and raises in 3.12+ in some configurations. Changed to `asyncio.get_running_loop()` which is correct since `run_wave` is always called from within a running event loop.

### 8. `sdk.py` — `_make_subscriber_logger` used wrong attribute name `_queue`
**File:** `app/core/sdk.py`  
**Problem:** `getattr(base_logger, "_queue", None)` — the attribute is `queue` (public), not `_queue`. The queue was never preserved when wrapping a base logger. Also, the existing logger's `logs` list and `start_time` were discarded when creating the wrapper. Fixed both.

### 9. `sdk.py` — `_make_subscriber_logger` discarded base logger state
**File:** `app/core/sdk.py`  
**Problem:** A new `_SubscriberLogger` was always created fresh, losing any events already emitted to the base logger. Fixed by copying `logs` and `start_time` from the base logger into the wrapper.

### 10. `run_manager.py` — `_WORKSPACE` frozen at import time
**File:** `app/core/run_manager.py`  
**Problem:** `_WORKSPACE = str(_project_dir())` evaluated `GRAPHYN_PROJECT_DIR` at module import time. If the env var was set after import (e.g. in tests), `RunManager` would still write to the old path. Fixed by reading `_WORKSPACE` at `RunManager.__init__` time via a self-module reference, preserving the patchable module attribute for test isolation.

### 11. `project_manager.py`, `quality_checker.py`, `webhook.py`, `ingestion.py` — Frozen class-level paths
**Files:** All four  
**Problem:** `BASE = _WORKSPACE / "datasets" / "output"` (and similar) evaluated paths at class definition time. Changed to `@property` methods that call `_project_dir()` / `_webhooks_path()` / `_datasets_input_dir()` at access time.

### 12. `project_manager.py` — `_estimate_snr` dead code + stereo bug
**File:** `app/core/project_manager.py`  
**Problem 1:** `snr = 20.0 * (signal_rms / noise_rms)` was computed then immediately discarded — the next line recomputed it with `math.log10`. Dead code.  
**Problem 2:** Multi-channel WAV files were unpacked as if mono — interleaved samples from all channels were treated as a single mono stream, producing wrong RMS values. Fixed by averaging channels to mono before computing RMS.  
**Problem 3:** `import math` was placed after the dead `snr` assignment. Moved to top of function.

### 13. `provenance.py` — `record()` wrote artifact file outside the lock
**File:** `app/core/provenance.py`  
**Problem:** `{artifact_id}.json` was written before acquiring `self._lock`, then the lock was acquired only for the `by_run` update. Two concurrent calls for the same artifact could interleave writes. Moved the record file write inside the lock.

### 14. `logger.py` — `_emit` used bare `print()` instead of `logging`
**File:** `app/core/logger.py`  
**Problem:** Every log entry was printed to stdout unconditionally with no way to suppress or redirect output. Changed to use Python's `logging` module at the appropriate level (INFO/WARNING/ERROR).

### 15. `utils/hash.py` — `hashlib.md5()` fails on FIPS systems
**File:** `app/core/utils/hash.py`  
**Problem:** `hashlib.md5(s.encode())` raises `ValueError` on FIPS-compliant systems where MD5 is blocked for security use. Added `usedforsecurity=False` flag and a module docstring clarifying the non-security intent.

### 16. `plugins/installer.py` — Zip-slip / tar-slip path traversal vulnerability
**File:** `app/core/plugins/installer.py`  
**Problem:** `zipfile.ZipFile.extractall()` and `tarfile.extractall()` are vulnerable to path traversal — archive members with `../` paths can write files outside `dest_dir`. Added member path validation before extraction for both ZIP and TAR formats.

### 17. `plugins/index.py` — `lookup()` did exact string match on version specifier
**File:** `app/core/plugins/index.py`  
**Problem:** `lookup(name, version=">=1.0")` did `e.version == ">=1.0"` — always `False`. The `version` parameter from `_parse_name_version()` is a PEP 440 specifier string, not an exact version. Fixed to use `packaging.specifiers.SpecifierSet` for proper constraint matching. Bare version strings (e.g. `"1.2.0"`) are normalised to `"==1.2.0"`.

### 18. `plugins/index.py` — `fetch()` not thread-safe on cache write
**File:** `app/core/plugins/index.py`  
**Problem:** Two concurrent calls to `fetch()` could both see `_cache is None`, both fetch the index, and both write to `_cache` — a benign race but still a data race. Added `threading.Lock` with double-checked locking.

### 19. `conditions.py` — Docstring said "comparisons only" but arithmetic was allowed
**File:** `app/core/conditions.py`  
**Problem:** The module docstring listed only comparisons and boolean ops as allowed, but `ast.BinOp` with `Add`, `Sub`, `Mult`, `Div`, `Mod` was also in `_ALLOWED_NODE_TYPES`. Updated docstring to accurately reflect what's permitted.

### 20. `ir/loader.py` — `IRValidationError` appeared to be dead code
**File:** `app/core/ir/loader.py`  
**Problem:** `IRValidationError` was defined, exported, and documented in `__init__.py` but never raised anywhere. Added a docstring explaining it's reserved for future semantic validation passes.

### 21. `PluginPackage/Audio/segmenter/nodes.py` — No config validation on `overlap`
**File:** `PluginPackage/Audio/segmenter/nodes.py` + `plugins/segmenter/nodes.py`  
**Problem:** `overlap: float = 0.0` accepted any value including `>= 1.0`, which produces infinite or zero-length steps at runtime. Added `@pydantic.field_validator` for `overlap` (must be `[0, 1)`), `vad_aggressiveness` (must be 0–3), positive-int check for `window_ms`/`min_segment_ms`/`max_segment_ms`/`event_min_gap_ms`, and a cross-field validator ensuring `min_segment_ms < max_segment_ms`. Synced fix to installed `plugins/segmenter/nodes.py`.

### 22. `plugins/` — Installed copies drifted from PluginPackage source
**Files:** `plugins/dataset-balancer`, `embedding-generator`, `experiment-tracker`, `multimodal-fusion`, `speech-synthesizer`, `stream-processor`, `voice-converter` (nodes.py), `speech-synthesizer` (plugin.toml)  
**Problem:** The installed plugin files in `plugins/` were out of sync with their `PluginPackage/` source. Synced all `nodes.py`, `types.py`, and `plugin.toml` files.

### 23. `tests/test_migration.py` — Test expected runtime error, not construction error
**File:** `tests/test_migration.py`  
**Problem:** `test_invalid_overlap_raises_at_runtime` constructed a node with `overlap=1.5` without expecting an exception, then expected `process()` to raise. After fix #21, the exception fires at construction (correct behaviour). Updated test to `test_invalid_overlap_raises_at_construction` which wraps the constructor call in `pytest.raises`.

---

## Remaining Work / Known Gaps

None identified. All 1443 tests pass.

### Items Intentionally Left As-Is

| Item | Reason |
|---|---|
| `NodeExecutor.execute` calls `on_error` twice on exhaustion (once per attempt + once after) | Intentional by design — tests explicitly assert this behaviour |
| `_parse_pipeline_config` in `pipeline.py` (YAML-era function) | Still used by tests; kept for backward compat |
| `ArtifactCollection` is not a `dict` subclass | Intentional — `isinstance(collection, dict)` is `False` by design |
| `IRValidationError` never raised | Reserved for future semantic validation; documented |
| `conditions.py` allows arithmetic operators | Intentional — useful for threshold expressions like `len(output['output']) * 2 > 10` |

---

## How to Resume in a New Session

1. Read this file first for full context.
2. Run `venv/bin/python -m pytest tests/ -q` — should show `1443 passed`.
3. Check `docs/KNOWN_ISSUES.md` for any active issues.
4. The steering files in `.kiro/steering/` describe which files to update when modifying code.

### Key invariants to preserve
- `plugins/` (installed) must stay in sync with `PluginPackage/` (source) — use the sync script pattern in fix #22.
- `AutoDiscovery.run(plugins_dir=None)` skips the plugins scan (PluginManager already loaded them).
- `_WORKSPACE` in `run_manager.py` must remain a patchable module attribute for test isolation.
- All path resolution must go through `app/core/config.py` functions, never hardcoded.
