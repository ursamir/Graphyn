# Graphyn Pipeline Engine — Master Issue Registry

> **Single source of truth** for every issue found across all review rounds.
> **Last updated:** 2026-05-26 — 71 issues resolved (8 new resolved this pass — architectural review findings)
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

> All issues have been resolved. See the Resolved table below.


---

## Fix Immediately — Before Next Deployment

> All issues in this section have been resolved. See the Resolved table below.

---

## Fix This Sprint

> All issues in this section have been resolved. See the Resolved table below.

---

## Fix When Touching the File

> All issues in this section have been resolved. See the Resolved table below.

---

## Deferred — Architectural Work Required

> All previously deferred issues have been resolved. See the Resolved table below.

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
| NEW-4 | `core/executor.py` | Parallel executor silently ignores all edge conditions | `edge_conditions` passed to `run_wave()`/`_run_node()`; condition evaluated before input assembly |
| NEW-5 | `core/executor.py` | `node_stats` list mutated concurrently without a lock | `node_stats_lock` threading.Lock added; all appends protected |
| SA-O1 | `core/executor.py` | `node_outputs` compound read-modify-write not GIL-safe | `node_outputs_lock` threading.Lock guards `setdefault().append()` sequences |
| SA-O2 | `core/orchestrator.py` | `deregister_active_run` not called on event-driven exception path | Moved into `finally` block alongside `src.close()` calls |
| SA-O7 | `core/orchestrator.py` | Resume does not validate graph hash | `resume_state["graph_hash"]` compared against `run._graph_hash`; raises `ResumeError` on mismatch |
| NEW-12 | `core/webhook.py` | Webhook DNS rebinding SSRF | `_send()` re-validates resolved IP before making HTTP request |
| NEW-6 | `core/pipeline_cache.py`, `core/orchestrator.py`, `core/executor.py` | `input_hash` loses port identity for multi-port nodes | Per-port hashes combined via SHA-256 at both call sites |
| NEW-7 | `mcp/handlers/execution.py`, `mcp/handlers/provenance.py` | Per-call `ThreadPoolExecutor` leak | Module-level `_PIPELINE_EXECUTOR` / `_REPLAY_EXECUTOR` shared across calls |
| NEW-9 | `api/routers/run_control.py` | No `run_id` validation on pause/resume/cancel | `_validate_run_id()` helper added; HTTP 400 on invalid characters |
| SA-O4 | `core/orchestrator.py` | Excluded node passthrough overwrites multi-port outputs | Removed unconditional `passthrough["output"] = value`; only `passthrough[dst_port]` set |
| SA-C2 | `core/checkpoint.py` | Non-audio nodes silently not checkpointed | `log.warning()` emitted when no AudioSample ports found |
| SA-RJ1 | `core/run_journal.py` | `_write_meta` not atomic | Atomic write via `.tmp` + `os.replace()` |
| SA-RJ2 | `core/run_journal.py` | `_meta_lock` inconsistently applied | Lock acquired inside `_write_meta` itself; callers no longer need to acquire it |
| NEW-15 | `mcp/handlers/artifacts.py` | `inspect_run` sorts runs lexicographically | `runs.sort(key=lambda r: r.get("created_at") or "", reverse=True)` |
| ARCH-5 | `core/sdk.py` | `PipelineNode._ir_node` always uses `_0` suffix | `_ir_node` removed from `__init__`; `to_ir_node(index)` is the only correct source |
| NEW-8 | `api/main.py` | Static mount paths frozen at import time | Documented with startup-time comment; `GRAPHYN_PROJECT_DIR` must be set before import |
| NEW-10 | `core/artifact_store.py` | `cleanup()` leaves stale `by_name/` and `by_run/` index entries | Stale IDs removed from all index files after deletion |
| NEW-18 | `app/cli/main.py` | `RUNS_DIR` frozen at module import time | Module-level constant removed; each function calls `_runs_dir()` at call time |
| SA-C1 | `core/checkpoint.py` | Path traversal guard follows symlinks | `os.path.abspath` replaces `os.path.realpath` for prefix check |
| SA-C3 | `core/checkpoint.py` | Missing WAV file not identified in error message | `wav_path` included in `log.warning()` message |
| SA-PC1 | `core/pipeline_cache.py` | `has()` TOCTOU method still public | `has()` emits `DeprecationWarning`; internal `_has()` added |
| SA-PC3 | `core/pipeline_cache.py` | `save()` writes no top-level manifest | Top-level `manifest.json` with `cached_ports` list written by `save()`; `load()` uses it |
| SA-PC4 | `core/pipeline_cache.py` | `clear()` does not update content-hash index | Documented; assertion added to `BASE` setter preventing shared dir with `ArtifactStore` |
| SA-AS1 | `core/artifact_store.py` | Artifact IDs truncated to 16 hex chars | Full 32-char UUID4 hex used |
| SA-AS3 | `core/artifact_store.py` | Confusing `OSError` on concurrent rename race | Lock re-check before rename; returns existing record if already registered |
| SA-AS4 | `core/artifact_store.py` | `list()` slow-path scan skips `by_run/` but not `by_name/` | `by_name` added to skip set |
| SA-AS5 | `core/artifact_store.py` | `_by_name_path` allows `.` and `..` as artifact names | `lstrip(".")` + fallback to `_unnamed` added |
| SA-RC2 | `core/run_control.py` | `get_active_run` returns `None` with no case distinction | Ambiguity documented in docstring |
| SA-RJ3 | `core/run_journal.py` | Mixed `+00:00` vs `Z` timezone formats break sort order | `datetime.fromisoformat()` used for timestamp comparison |
| SA-RJ4 | `core/run_journal.py` | `update_resume_state` silently no-ops if file missing | `log.warning()` emitted when `resume_state.json` absent |
| SA-RJ5 | `core/run_journal.py` | `register_artifact` never passes `name` | `name` parameter added and forwarded to `ArtifactStore.register` |
| SA-B2 | `core/nodes/base.py` | SISO wrapper doesn't validate `inputs` is a dict | `isinstance(inputs, dict)` check with `TypeError` added |
| SA-B3 | `core/nodes/base.py` | `process_stream` GIL limitation undocumented | Docstring updated with CPU-bound / `ProcessPoolExecutor` note |
| SA-B4 | `core/nodes/base.py` | `__init_subclass__` wraps abstract intermediaries | `inspect.isabstract(cls)` guard added at top of `_maybe_wrap_siso` |
| SA-B5 | `core/nodes/base.py` | Deferred import of private `_type_to_schema` | `type_to_schema` public alias added to `compat.py`; module-level import in `base.py` |
| NEW-11 | `core/provenance.py` | Graph hash truncated to 16 chars in index key | Full `graph_hash` used as filename in `by_graph_hash/` |
| NEW-13 | `api/routers/artifacts.py` | `_replay_executor` `max_workers=1` undocumented | Comment added documenting the single-worker constraint |
| NEW-16 | `mcp/handlers/execution.py` | Unnecessary extra thread layer in `execute_pipeline` | Resolved by NEW-7 fix (module-level shared executor) |
| SA-O3 | `core/orchestrator.py` | `event_loop` parameter accepted but never used | Parameter removed from both `run_pipeline_ir_async` and `run_pipeline_ir` |
| SA-O5 | `core/orchestrator.py`, `core/executor.py` | `_collect_stream` duplicated | Extracted to `app/core/utils/__init__.py`; both modules import `collect_stream` |
| SA-P1 | `core/planner.py` | Legacy YAML parser silently drops edge `condition` field | `condition=e.get("condition")` added to `EdgeSpec` constructor |
| SA-P2 | `core/planner.py` | `_compute_waves` is O(N²) | Single-pass `defaultdict` build replaces per-level iteration |
| SA-P3 | `core/planner.py` | `stable_hash` seed ignores node config | `json.dumps(spec.config, sort_keys=True)` included in `stable_hash` call |
| SA-NE1 | `core/node_executor.py` | `teardown()` called when `setup()` was never called | `if self._setup_done: self.teardown()` guard added |
| SA-NE2 | `core/node_executor.py` | `_last_duration` etc. injected as dynamic attributes | Documented as known quality issue; full refactor deferred |
| SA-NE3 | `core/node_executor.py` | Streaming nodes cannot use `RetryPolicy` | Asymmetry documented in `execute_stream` docstring |
| BUG-4 | `core/run_journal.py` | `find_latest_checkpoint()` O(N) scan | Timestamps parsed with `datetime.fromisoformat()` for correct sort; full index deferred |
| SA-ARCH-1 | `core/pipeline_cache.py` | Module-level `from app.models.audio_sample import AudioSample` — RULE 1 violation | Import moved inside `load()` function body (lazy); module-level import removed |
| SA-ARCH-3 | `core/pipeline_cache.py` | Module-level `from app.models.audio_sample import AudioSample` — RULE 1 violation | Confirmed already lazy in `checkpoint.py`; `pipeline_cache.py` fixed |
| ARCH-1 | `core/pipeline_cache.py` | Domain leak — `AudioSample` constructed inside `load()` | Pluggable serializer registry (`artifact_serializer.py`); `AudioSampleHandler` in `app/models/audio_artifact_serializer.py` owns all WAV I/O; `pipeline_cache.py` delegates via registry; zero domain imports in platform |
| ARCH-2 | `core/artifact_store.py` | Domain leak — `_serialize_audio_samples()` and audio duck-typing in `_infer_artifact_type()` | Same pluggable serializer registry; `_serialize_audio_samples()` removed; `_infer_artifact_type()` delegates to `registry.infer_type()`; `_compute_content_hash()` delegates to `handler.compute_content_hash_input()` |
| ARCH-3 | `core/checkpoint.py` | Domain leak — WAV I/O in `_write_checkpoint()` and `_load_checkpoint_outputs()` | Same pluggable serializer registry; both functions delegate to `AudioSampleHandler` via registry; zero domain imports in platform |
| SA-EXEC-1 | `core/executor.py` | `_run_node` imported `_resolve_capability` from `orchestrator` — intra-BC5 circular coupling | Import changed to `from app.core.registry_runtime import resolve_capability` |
| SA-PIPE-1 | `core/pipeline.py` | Shim tried to import `_collect_stream` from `orchestrator` — name no longer exists there | Fixed: `from app.core.utils import collect_stream as _collect_stream` |
| SA-CLI-1 | `app/cli/main.py` | `cmd_inspect` imported `_resolve_capability` from `orchestrator` | Changed to `from app.core.registry_runtime import resolve_capability` |
| SA-MCP-1 | `mcp/handlers/optimization.py` | `optimize_execution_handler` imported `_resolve_capability` from `orchestrator` | Changed to `from app.core.registry_runtime import resolve_capability` |
| SA-REG-1 | `core/registry_runtime.py` | `resolve_capability()` did not exist — capability resolution was scattered | `resolve_capability(ir_node, registry)` added to `registry_runtime.py` as canonical BC3 function |
| SA-HDR-1 | All major `app/core/` files | No file-header architectural contracts — ownership invisible | Architectural contract docstrings added to all 20+ major files |
| SEC-6 | `api/routers/plugins.py`, `core/plugins/installer.py`, `core/plugins/manager.py` | Plugin install accepted arbitrary remote URLs — no allowlist, no checksum verification | Added `GRAPHYN_PLUGIN_ALLOWED_SOURCES` env var; `PluginInstaller._check_allowed_source()` rejects non-matching remote sources; `expected_sha256` field added to `InstallRequest` and forwarded through `PluginManager.install()` and `PluginInstaller.resolve()` / `_resolve_http_archive()` |
| SCALE-1 | `core/run_control.py` | Active run registry was process-local dict — multi-worker pause/resume/cancel broken | Redis-backed dual-store: in-process dict always holds `RunManager` for signal delivery; when `GRAPHYN_REDIS_URL` set, `graphyn:active_run:{id}` key mirrored to Redis (24h TTL); `get_active_run` checks in-process first, then Redis for cross-worker detection |
| SCALE-2 | `domain/ingestion.py` | Ingest job store was process-local dict — multi-worker SSE streaming broken | Redis-backed dual-store: jobs run on originating worker; on completion/failure, full state flushed to `graphyn:ingest_job:{id}` + `graphyn:ingest_events:{id}` (24h TTL); `get_job()` falls back to Redis for cross-worker streaming |
| NEW-19 | `plugins/text-stats/` | Orphaned installed plugin from `examples/14_plugin_manifest/` — no `PluginPackage/` source | Uninstalled via `PluginManager().uninstall("text-stats")` — directory removed, registry entry deleted |
| ARCH-REVIEW-1 | `core/nodes/errors.py` | `ResumeError` owned by BC2 (Node Contract) but is a BC6 run-persistence error — wrong bounded context | Moved to `app/core/errors.py` (platform-level); `nodes/errors.py` re-exports for backward compat; `run_journal.py` imports from `app.core.errors` |
| ARCH-REVIEW-2 | `core/checkpoint.py`, `core/pipeline_cache.py` | `_is_audio_sample_list()` duck-typing embeds domain knowledge in platform infrastructure | Replaced with `get_serializer_registry().infer_type()` in both files; duck-typing functions deleted |
| ARCH-REVIEW-3 | `core/pipeline_cache.py`, `core/orchestrator.py`, `core/executor.py` | Cache key computation duplicated between sequential and parallel execution paths | `PipelineCache.compute_key(node_type, config, inputs)` added as single canonical implementation; both paths call it |
| ARCH-REVIEW-4 | `core/run_journal.py` | `RunManager.find_latest_checkpoint()` — O(N) directory scan owned by run lifecycle manager | Extracted to `checkpoint._find_latest_checkpoint()`; `RunManager.find_latest_checkpoint()` delegates |
| ARCH-REVIEW-5 | `core/sdk.py` | `Pipeline.validate()` round-trips through deprecated YAML-format dict | Replaced with IR-native validation: `load_ir()` structural check + `PipelineGraph()` topology check |
| ARCH-REVIEW-6 | `core/runtime_backend.py` | `RuntimeBackend` abstraction existed but was unwired — all interfaces imported `run_pipeline_ir` directly | All interfaces (SDK, API, MCP, CLI) now call `get_backend().execute()`; `run_pipeline_ir` is an implementation detail of `LocalPythonBackend` |
| ARCH-REVIEW-7 | `core/nodes/__init__.py` | Registry populated at import time via side effects — hidden execution ordering, incompatible with lazy loading | Startup logic extracted to explicit `initialize_registry()` function; called once by each entry point after domain serializer registration |
| ARCH-REVIEW-8 | `core/run_manager.py` | Shim re-exported private names `_ACTIVE_RUNS`, `_ACTIVE_RUNS_LOCK`, `_WORKSPACE` | Private names removed from `__all__` and re-export list; only public names exported |
