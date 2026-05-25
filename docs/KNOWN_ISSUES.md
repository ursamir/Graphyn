# Known Issues

> **Single source of truth:** `docs/MASTER_ISSUE_REGISTRY.md`
> This file lists only currently open issues for quick reference.
> For full history, fix details, and resolved issues see the registry.

---

## Open — Fix Immediately (before next deployment)

| ID | Severity | File | Summary |
|---|---|---|---|
| NEW-4 | High | `core/executor.py` | Parallel executor silently ignores all edge conditions |
| NEW-5 | High | `core/executor.py` | `node_stats` list mutated concurrently without a lock in parallel mode |
| NEW-12 | Medium | `core/webhook.py` | Webhook DNS rebinding SSRF — SEC-3 save-time check bypassed at send time |
| SA-O1 | High | `core/executor.py` | `node_outputs` compound read-modify-write not GIL-safe in parallel mode |
| SA-O2 | High | `core/orchestrator.py` | `deregister_active_run` not called on event-driven exception path |
| SA-O7 | High | `core/orchestrator.py` | Resume does not validate graph hash — stale checkpoints silently reused |

---

## Open — Fix This Sprint

| ID | Severity | File | Summary |
|---|---|---|---|
| NEW-6 | Medium | `core/pipeline_cache.py` | `input_hash` loses port identity for multi-port nodes — cache key collisions |
| NEW-7 | Medium | `mcp/handlers/execution.py` | Per-call `ThreadPoolExecutor` leak in `execute_pipeline` and `replay_run` |
| NEW-9 | Medium | `api/routers/run_control.py` | No `run_id` validation on pause/resume/cancel endpoints |
| NEW-15 | Low | `mcp/handlers/artifacts.py` | `inspect_run` returns runs in lexicographic, not chronological, order |
| SA-O4 | Medium | `core/orchestrator.py` | Excluded node passthrough overwrites multi-port outputs with `"output"` key |
| SA-RJ1 | Medium | `core/run_journal.py` | `_write_meta` is not atomic — corrupt on crash |
| SA-RJ2 | Medium | `core/run_journal.py` | `_meta_lock` inconsistently applied — concurrent writes can overwrite |
| SA-C2 | Medium | `core/checkpoint.py` | Non-audio nodes silently not checkpointed; no warning to user |

---

## Open — Fix When Touching the File

| ID | Severity | File | Summary |
|---|---|---|---|
| ARCH-5 / NEW-14 | Medium | `core/sdk.py` | `PipelineNode._ir_node` always uses `_0` suffix |
| BUG-4 / NEW-17 | Medium | `core/run_journal.py` | `find_latest_checkpoint()` O(N) scan over all runs |
| NEW-8 | Medium | `api/main.py` | Static mount paths frozen at import time |
| NEW-10 | Medium | `core/artifact_store.py` | `cleanup()` leaves stale `by_name/` and `by_run/` index entries |
| NEW-18 | Medium | `app/cli/main.py` | `RUNS_DIR` frozen at module import time |
| NEW-19 | Medium | `plugins/text-stats/` | Orphaned installed plugin with no `PluginPackage/` source |
| NEW-11 | Low | `core/provenance.py` | Graph hash truncated to 16 chars in index key |
| NEW-13 | Low | `api/routers/artifacts.py` | `_replay_executor` `max_workers=1` undocumented |
| NEW-16 | Low | `mcp/handlers/execution.py` | Unnecessary extra thread layer in `execute_pipeline` |
| SA-O3 | Low | `core/orchestrator.py` | `event_loop` parameter accepted but never used |
| SA-O5 | Low | `core/orchestrator.py` | `_collect_stream` duplicated as `_collect_stream_parallel` |
| SA-P1 | Low | `core/planner.py` | Legacy YAML parser silently drops edge `condition` field |
| SA-P2 | Low | `core/planner.py` | `_compute_waves` is O(N²) for deep linear pipelines |
| SA-P3 | Low | `core/planner.py` | `stable_hash` seed ignores node config |
| SA-NE1 | Low | `core/node_executor.py` | `teardown()` called when `setup()` was never called |
| SA-NE2 | Low | `core/node_executor.py` | `_last_duration` etc. injected as dynamic attributes on foreign object |
| SA-NE3 | Low | `core/node_executor.py` | Streaming nodes cannot use `RetryPolicy` |
| SA-C1 | Medium | `core/checkpoint.py` | Path traversal guard follows symlinks — symlink escape possible |
| SA-C3 | Low | `core/checkpoint.py` | Missing WAV file not identified in checkpoint load error message |
| SA-PC1 | Low | `core/pipeline_cache.py` | `has()` TOCTOU method still public despite docstring warning |
| SA-PC3 | Low | `core/pipeline_cache.py` | `save()` writes no top-level manifest — fragile `port_*` dir scan |
| SA-PC4 | Low | `core/pipeline_cache.py` | `clear()` does not update content-hash index |
| SA-AS1 | Low | `core/artifact_store.py` | Artifact IDs truncated to 16 hex chars |
| SA-AS3 | Low | `core/artifact_store.py` | Confusing `OSError` on concurrent rename race in `register()` |
| SA-AS4 | Low | `core/artifact_store.py` | `list()` slow-path scan skips `by_run/` but not `by_name/` |
| SA-AS5 | Low | `core/artifact_store.py` | `_by_name_path` allows `.` and `..` as artifact names |
| SA-RC2 | Low | `core/run_control.py` | `get_active_run` returns `None` with no case distinction |
| SA-RJ3 | Low | `core/run_journal.py` | Mixed `+00:00` vs `Z` timezone formats break checkpoint sort order |
| SA-RJ4 | Low | `core/run_journal.py` | `update_resume_state` silently no-ops if `resume_state.json` missing |
| SA-RJ5 | Low | `core/run_journal.py` | `register_artifact` never passes `name` — `by_name` index never populated |
| SA-B2 | Low | `core/nodes/base.py` | SISO wrapper doesn't validate `inputs` is a dict |
| SA-B3 | Low | `core/nodes/base.py` | `process_stream` default GIL limitation undocumented |
| SA-B4 | Low | `core/nodes/base.py` | `__init_subclass__` wraps abstract intermediaries |
| SA-B5 | Low | `core/nodes/base.py` | Deferred import of private `_type_to_schema` from sibling module |

---

## Open — Deferred (Architectural Work Required)

| ID | Severity | File | Summary |
|---|---|---|---|
| ARCH-1 | High | `core/pipeline_cache.py` | Domain leak — imports `AudioSample` |
| ARCH-2 | High | `core/artifact_store.py` | Domain leak — WAV serialization in platform infrastructure |
| ARCH-3 | High | `core/checkpoint.py` | Domain leak — entirely audio-specific |
| SEC-6 | High | `api/routers/plugins.py` | Plugin install accepts arbitrary remote code execution |
| SCALE-1 | Medium | `core/run_control.py` | Active run registry is process-local |
| SCALE-2 | Medium | `domain/ingestion.py` | Ingest job store is process-local |
