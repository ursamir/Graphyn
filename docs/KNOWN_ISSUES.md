# Known Issues

- ~~`nodes/registry.py` `find_compatible_nodes` TOCTOU `KeyError` (G1-24)~~ — single lock acquisition now snapshots both `_classes` and `_metadata`; loop uses `meta_snapshot.get()` with `None` guard
- ~~`nodes/catalogue.py` `TypeCatalogue` had no thread safety (G1-38)~~ — `threading.RLock` added; `register`, `resolve`, `list_types`, `__contains__` all wrapped with `with self._lock:`

---

## Active Issues

### 1. Auth token read at import time — MCP and REST API

**Files:** `app/mcp/auth.py` line 12, `app/api/main.py` line 35

`_TOKEN = _api_token()` and `_API_TOKEN = api_token()` are captured at module
import time. Token rotation or late injection (secrets manager, container
orchestrator) requires a full process restart. Fix: read inside `check_auth()`
and `_auth_dep()` on every call.

### 2. Webhook SSRF — no private IP blocking

**File:** `app/core/webhook.py`

`save()` validates scheme and netloc but does not block RFC 1918, loopback, or
link-local addresses. An attacker who can call `PUT /api/v1/system/webhooks`
can reach internal services (AWS IMDS, internal admin panels). Fix: resolve
hostname and reject private IP ranges before writing config.

### 3. Ingest URL — no download size limit

**File:** `app/domain/ingestion.py` ~line 145

`response.content` buffers the entire response body in memory. A large response
exhausts server memory. Fix: use `httpx` streaming with a max-bytes counter.

### 4. CORS `allow_headers=["*"]` with `allow_credentials=True`

**File:** `app/api/main.py` lines 56–65

The CORS spec forbids `allow_headers=*` when `allow_credentials=True`. Browsers
reject such responses. Fix: enumerate specific headers.

### 5. Observer double-fire per node

**File:** `app/core/node_executor.py`, `app/core/nodes/base.py`

`NodeExecutor.execute()` calls `observer.on_node_start/end/error` directly.
`base.py` `on_start/on_end/on_error` also call the observer. Every observer
event fires twice per node. Fix: remove direct observer calls from
`NodeExecutor.execute()`.

### 6. `asyncio.get_event_loop()` deprecated

**File:** `app/mcp/server.py` line 87

`asyncio.get_event_loop()` is deprecated in Python 3.10+ in async contexts.
Fix: use `asyncio.get_running_loop()`.

### 7. `WebhookService` missing `__init__`

**File:** `app/core/webhook.py`

No `__init__` method — `_config_cache` is never initialized. `notify()` calls
`self.load()` on every invocation (disk read per event). Fix: add `__init__`
with `self._config_cache: dict | None = None`.

### 8. Hardcoded `Path("workspace")` in `data.py`

**File:** `app/api/routers/data.py` lines 15–17

`WORKSPACE_ROOT = Path("workspace").resolve()` — same class of bug fixed in
`system.py` and `pipelines.py` but missed here. Fix: use `datasets_input_dir()`
and `datasets_output_dir()` from `config.py`.

### 9. `_write_checkpoint` only saves first list port

**File:** `app/core/checkpoint.py` lines 44–47

Stops at the first list port — multi-port nodes lose all but the first port on
resume. `pipeline_cache.py` was fixed to handle all ports; `checkpoint.py` was
not. Fix: iterate all ports, write each to its own subdirectory.

### 10. Domain leaks in platform infrastructure

**Files:** `app/core/pipeline_cache.py`, `app/core/artifact_store.py`, `app/core/checkpoint.py`

All three import `AudioSample`, write WAV files, or use audio-specific
duck-typing. Platform infrastructure must not know about audio. Fix: pluggable
serializer registry — domain registers its handler at startup.

### 11. `RunManager.__init__` broken `_WORKSPACE` sentinel

**File:** `app/core/run_journal.py` lines ~55–60

The `_WORKSPACE != "workspace"` condition is almost always `True` (since
`_project_dir()` returns an absolute path), making the `else` branch unreachable.
Both branches resolve to the same path so there is no functional bug, but the
logic is misleading. Fix: simplify to `base_dir = str(_project_dir() / "runs")`.

### 12. Plugin install accepts arbitrary remote code

**File:** `app/api/routers/plugins.py`, `app/core/plugins/manager.py`

`POST /api/v1/plugins/install` accepts a `source` string passed to
`PluginInstaller.resolve()` which fetches and executes code from `git+`,
`http://`, or `https://` URLs with no allowlist, signature verification, or
sandboxing. Any authenticated user can install a malicious node. Inherent to
plugin systems — minimum mitigation: require auth (done), add checksum
verification, never expose publicly.

### 13. `_run_dir()` validation weaker than `_safe_child()`

**File:** `app/api/routers/runs.py` line 18

`run_id.replace("-", "").isalnum()` allows `--` (empty after stripping). Path
is constructed without `resolve()` + `is_relative_to()` check, inconsistent
with `_safe_child()` used in `data.py`.

### 14. Condition evaluator: no AST depth limit

**File:** `app/core/conditions.py`

No depth limit on the AST. Deeply nested expressions pass the whitelist but
fail at runtime with `TypeError` instead of a clean `ConditionEvaluationError`.

### 15. `ArtifactStore` serialization inside global lock

**File:** `app/core/artifact_store.py`, `register()`

WAV file serialization runs under `self._lock`, blocking all concurrent artifact
registrations. In parallel wave execution this serializes what should be
parallel work.

### 16. `ArtifactStore` has no eviction or size limit

**File:** `app/core/artifact_store.py`

Artifacts accumulate on disk forever. `system/cleanup` does not touch the
artifact store. Long-running deployments will exhaust disk.

### 17. `PipelineCache.input_hash()` `repr()` fallback not stable across restarts

**File:** `app/core/pipeline_cache.py`

`repr()` includes object memory addresses — cache keys for nodes that reach
this fallback are random across process restarts, making the cache useless.

### 18. `PipelineCache.has()` TOCTOU not fixed at call sites

**File:** `app/core/pipeline_cache.py`, `orchestrator.py`, `executor.py`

`has()` docstring warns about TOCTOU but call sites still use `has()` + `load()`
as two separate operations. Fix: call `load()` directly and treat `None` as miss.

### 19. `on_error` called twice on final retry failure

**File:** `app/core/node_executor.py`

`node.on_error()` is called inside the retry loop on the last failed attempt,
then called again outside the loop before re-raising. Observer error counts are
inflated for nodes that exhaust their retry budget.

### 20. `list_runs()` reads all `meta.json` files — no pagination

**File:** `app/api/routers/runs.py`

`GET /api/v1/runs` reads every `meta.json` on every call. No pagination, no
index, no caching. Unbounded with thousands of runs.

### 21. SISO detection is fragile

**File:** `app/core/nodes/base.py`, `_maybe_wrap_siso()`

Detection relies on second parameter name not being `"inputs"`. A multi-port
node named `process(self, data)` is incorrectly wrapped as SISO. Convention is
undocumented at the call site.

### 22. `SpeechEnhancerNode._resolve_backend()` called twice

**File:** `PluginPackage/Audio/speech_enhancer/nodes.py`

`process()` falls back to `_resolve_backend()` if `_resolved_backend` is falsy,
probing packages on every call when `setup()` was not called first.

### 23. `IngestionService` job store is process-local

**File:** `app/domain/ingestion.py`

`_jobs` is a module-level dict. In multi-worker deployments, job streaming
requests routed to a different worker than the one that started the job return
404.

### 24. Active run registry is process-local

**File:** `app/core/run_control.py`

`_ACTIVE_RUNS` is process-local. Pause/resume/cancel requests routed to a
different worker than the one running the pipeline return 404. Documented in
module docstring; Redis migration path is the fix.

### 25. `ParallelExecutor` creates new `ThreadPoolExecutor` per wave

**File:** `app/core/executor.py`

New pool created and destroyed for every wave. For pipelines with many waves
this adds repeated pool creation/teardown overhead.

### 26. `ArtifactStore.get_versions()` full directory scan

**File:** `app/core/artifact_store.py`

`get_versions()` calls `self.list()` with no filter — O(N) disk reads. No
`by_name/` secondary index.

### 27. `run-async` status tracking uses two sources of truth

**File:** `app/api/routers/pipelines.py`

`POST /api/v1/pipelines/run-async` maintains an in-memory `_async_runs` dict in addition to `RunManager`'s `meta.json`. The in-memory dict is lost on server restart. After a restart, read status from `GET /api/v1/runs/{run_id}/status` (reads `meta.json`), not from the in-memory dict.

### 28. Frontend generates linear YAML only

**File:** `audiobuilder/src/utils/yaml.ts`

`generateYAML()` always produces the linear pipeline format (no `edges` key). DAG pipelines must be written manually in IR JSON and loaded via "Load Pipeline" or the CLI/SDK.

---

## Resolved Issues

- ~~`pipeline.py` god module (1,457 lines) mixed DAG building, node execution, checkpointing, and orchestration~~ — split into `planner.py`, `node_executor.py`, `checkpoint.py`, `orchestrator.py`; `pipeline.py` kept as re-export shim
- ~~`run_manager.py` mixed persistence, control plane, and artifact facade~~ — split into `run_journal.py` (persistence) and `run_control.py` (active run registry); `run_manager.py` kept as re-export shim
- ~~`app/core/ingestion.py`, `app/core/project_manager.py`, `app/core/quality_checker.py` were domain services in platform infrastructure~~ — moved to `app/domain/`; all callers updated; no shims left behind
- ~~Hardcoded `Path("workspace")` in `app/api/routers/system.py`~~ — replaced with `runs_dir()` and `cache_dir()` from `config.py`
- ~~Hardcoded `TEMPLATES_DIR = Path("workspace/configs/templates")` in `app/api/routers/pipelines.py`~~ — replaced with `_templates_dir()` function using `project_dir()`
- ~~Graph hash computed twice per run~~ — `orchestrator.py` now uses `run._graph_hash` set by `save_graph_ir()`

- ~~`Pipeline.validate()` in `sdk.py` called `validate_pipeline(pipeline_cfg)` with one argument; `validate_pipeline` requires two `(config, registry)`; every call raised `TypeError` caught by bare `except Exception`, making `validate()` always return a non-empty errors list and impossible to distinguish a valid pipeline from an invalid one~~ — added inline `get_registry()` call and passed `registry` as second argument to `validate_pipeline` (Task 9)

- ~~`pipeline.py` `run_pipeline_ir_async` generated a second independent `run_id = str(uuid.uuid4())` and passed it to every `NodeExecutor`; observer callbacks received the UUID4 while `RunManager` persisted a different 16-char hex `run_id` to `meta.json`, making the two values impossible to correlate~~ — replaced with `run_id = run.run_id`; `import uuid` removed; all observer events and `meta.json` now carry the same `run_id` (Task 5)

- ~~`_infer_artifact_type()` was defined in `pipeline.py`, encoding domain knowledge about `AudioSample`, `DatasetArtifact`, and feature-array duck-typing; `executor.py` imported it from `pipeline.py`, creating a cross-layer dependency from the executor into the orchestration module~~ — function moved to `app/core/artifact_store.py` alongside `ArtifactStore` and `SUPPORTED_ARTIFACT_TYPES`; `pipeline.py` and `executor.py` now import from `artifact_store.py` (Tasks 6–7)

- ~~`pipeline.py` contained two definitions of `run_pipeline_ir_async` with identical signatures; Python silently shadowed the first with the second, making the first dead code~~ — dead first definition removed; `pipeline.py` now contains exactly one definition of `run_pipeline_ir_async` (Task 4)

- ~~`ResumeError` defined in `pipeline.py` caused circular import; `run_manager.py` used deferred in-method imports as workaround~~ — `ResumeError` moved to `app/core/nodes/errors.py`; `pipeline.py` and `run_manager.py` updated to import from `errors.py` (Tasks 1–3)

- ~~`segmenter` Config accepted `overlap >= 1.0` silently~~ — `@pydantic.field_validator` added; raises `ValidationError` at construction; installed copy synced
- ~~`plugins/` installed copies drifted from `PluginPackage/` source~~ — all `nodes.py`, `types.py`, `plugin.toml` files synced
- ~~`NodeExecutor` cache key used wrong node config in DAG pipelines~~ — fixed to look up by `node_id` not topological index
- ~~`pipeline.py` had top-level `import yaml`~~ — removed; yaml is only used via lazy import in deprecated `run_pipeline()`
- ~~`pipeline_cache.py` had unconditional top-level `import numpy` and `import soundfile`~~ — moved to lazy imports
- ~~`executor.py` used deprecated `asyncio.get_event_loop()`~~ — changed to `asyncio.get_running_loop()`
- ~~`sdk.py` `_make_subscriber_logger` used wrong attribute `_queue` (should be `queue`)~~ — fixed; base logger `logs` and `start_time` now preserved
- ~~`run_manager.py` `_WORKSPACE` frozen at import time~~ — now read at `RunManager.__init__` time
- ~~`project_manager.py`, `quality_checker.py`, `webhook.py`, `ingestion.py` class-level paths frozen at import~~ — converted to `@property` methods
- ~~`project_manager._estimate_snr` had dead `snr` assignment and stereo channel bug~~ — fixed; channels averaged to mono before RMS
- ~~`provenance.py` `record()` wrote artifact file outside the lock~~ — moved inside `self._lock`
- ~~`logger.py` used bare `print()` for all log output~~ — changed to `logging` module
- ~~`utils/hash.py` `hashlib.md5()` fails on FIPS systems~~ — added `usedforsecurity=False`
- ~~`plugins/installer.py` vulnerable to zip-slip / tar-slip path traversal~~ — member path validation added before extraction
- ~~`plugins/index.py` `lookup()` did exact string match on version specifier~~ — fixed to use `packaging.specifiers.SpecifierSet`
- ~~`plugins/index.py` `fetch()` cache write not thread-safe~~ — added `threading.Lock` with double-checked locking
- ~~`nodes/discovery.py` duplicate class check used `__qualname__` not identity~~ — changed to `existing is obj`
- ~~`nodes/discovery.py` `plugins_dir=None` not respected (NameError risk)~~ — added `_PLUGINS_DIR_DEFAULT` sentinel
- ~~`nodes/__init__.py` double-loaded plugins at startup~~ — `AutoDiscovery.run(plugins_dir=None)` skips scan when `PluginManager` succeeded
- ~~`conditions.py` docstring said "comparisons only" but arithmetic was allowed~~ — docstring updated
- ~~`ir/loader.py` `IRValidationError` appeared to be dead code~~ — docstring added explaining reserved-for-future-use intent
- ~~`system/cleanup` ignores `older_than_days`~~ — now filters by mtime
- ~~Legacy dead router files~~ — `cleanup.py`, `merge.py`, `registry_api.py`, `webhooks.py`, `templates_write.py` deleted
- ~~REST API bypasses SDK~~ — `/run`, `/run-async`, `/replay` now delegate to `Pipeline.run_with_manager()`
- ~~MCP handlers bypass SDK~~ — `execute_pipeline` and `replay_run` now delegate to `Pipeline.run()`
- ~~`Pipeline.run()` did not set `_last_run_id`~~ — fixed
- ~~MCP `run_control.py` inconsistent error format~~ — all errors now use `{"error": True, "error_type": ..., "message": ...}`
- ~~`PipelineGraph._build()` used old registry import~~ — now uses `get_registry()`
- ~~`TensorBatch` and `DeploymentArtifact` missing~~ — added to `app/models/`
- ~~Node capability metadata all generic defaults~~ — all nodes now have accurate capability fields
- ~~`PipelineCache` only caches AudioSample lists~~ — now caches all JSON-serializable outputs
- ~~`IngestionJob` progress list not thread-safe~~ — `threading.Lock` via `append_progress()` / `read_progress()`
- ~~No SDK event subscription API~~ — `Pipeline.subscribe(callback)` added
- ~~`input_overrides` dead parameter~~ — now applied to all active nodes
- ~~CLI missing `runs pause/resume/cancel`~~ — added
- ~~No MCP execution optimization tool~~ — `optimize_execution` added (15th MCP tool)
- ~~No runtime backend abstraction~~ — `RuntimeBackend` ABC + `LocalPythonBackend` added
- ~~`Pipeline.run()` artifact tracking never wired~~ — `run_pipeline_ir_async()` and `ParallelExecutor._run_node()` now call `run_manager.register_artifact()` after each node; `ArtifactStore` deduplication now stamps returned records with the current `run_id`; numpy arrays in Pydantic models serialized via `_numpy_default` encoder; pass-through artifacts skip provenance re-write to prevent false cycle detection
- ~~`FileWatcherSource` segfaults on process exit~~ — `watchfiles.awatch` now receives `stop_event`; `FileWatcherSource.close()` sets the stop event and waits 0.3s for the Rust thread to exit; event-driven pipeline loop polls `run.is_cancelled` and uses a `_cancel_watcher` task to close sources gracefully
- ~~`ReverbNode` validates path at construction~~ — `ReverbNode` removed; use `augmentation_pipeline` plugin with `type="reverb"` instead
- ~~`FormatConvertNode` does not update metadata for stereo~~ — `FormatConvertNode` removed; use `audio_conditioner` plugin instead
- ~~`ExportNode` returns `{}` but typed as sink~~ — `ExportNode` removed; use `deployment_packager` plugin instead
- ~~`run_pipeline_ir()` crashed with `RuntimeError: This event loop is already running` when called from an async context (FastAPI route, async test, Jupyter) (G2-01)~~ — running-loop guard added: `asyncio.get_running_loop()` is checked before `asyncio.run()`; if a loop is detected the function raises a clear `RuntimeError` directing the caller to use `await run_pipeline_ir_async(...)` instead
- ~~`exclude_nodes` passes `None` to downstream nodes~~ — excluded nodes now store pass-through outputs so downstream active nodes receive the upstream data; boundary-node input assembly checks `node_outputs` before falling back to checkpoint; demo node IDs corrected to match 8-node pipeline (`_6`/`_7` suffixes)
- ~~Example 08 `stream_client.py` crashes with unhandled `ConnectError` when server is not running~~ — wrapped health check in `try/except httpx.ConnectError` for a clean warning + `sys.exit(0)`
- ~~`examples/README.md` pipeline descriptions for examples 01–05 described wrong sink nodes and non-existent features~~ — README updated: examples 01–05 use `audio_exporter` (not `dataset_builder`/`dataset_versioner`); example 01 noise injection is Gaussian (not file-based); example 04 annotator adds duration labels (not GE2E contrastive metadata); example 05 `environment_simulator` is skipped (pyroomacoustics not installed), codec is OGG not MP3; example 10 resume speedup claim removed (timing is machine-dependent); example 11 lineage description corrected to `dataset_versioner` (no model trained); example 17 node counts corrected to 4/8 (not 3/7)
- ~~`ingestion.py` `_run_hf_job` used raw dataset label as directory name, enabling path traversal (G3-23)~~ — `_sanitize_label()` helper added; strips non-alphanumeric/hyphen/underscore chars and truncates to 64 chars; applied to `label_override` and `label_col` paths in `_run_hf_job`, and to the `label` parameter in `_run_url_job`; `is_relative_to()` boundary check added in `_run_hf_job` as defence-in-depth
