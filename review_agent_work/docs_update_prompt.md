# Documentation Update Agent — Graphyn Platform

You are a Senior Technical Writer and Engineer. Your task is to **fully rewrite and restructure the `/home/meritech/Desktop/newAudio3/docs/` directory** to reflect the current, post-review, post-fix state of the Graphyn platform. You have complete authority to delete, rename, merge, and create documents.

---

## Context: What Was Done

A 104-file functional review was completed across the entire codebase, followed by a systematic fix pass. Every confirmed bug was fixed. The codebase is now in a clean, production-quality state. The documentation must reflect this — not the state the code was in before the review.

**Key changes made during the review/fix cycle that docs must reflect:**

### Architecture (already implemented — docs must catch up)
- `pipeline.py` was split into: `orchestrator.py`, `planner.py`, `node_executor.py`, `checkpoint.py`, `executor.py` — `pipeline.py` is now a re-export shim only
- `run_manager.py` was split into: `run_journal.py` (persistence), `run_control.py` (active run registry + Redis-backed) — `run_manager.py` is now a re-export shim
- Domain services moved to `app/domain/`: `ingestion.py`, `project_manager.py`, `quality_checker.py`
- `ArtifactSerializerRegistry` added (`app/core/artifact_serializer.py`) — platform no longer imports `AudioSample` directly
- `RuntimeBackend` ABC added (`app/core/runtime_backend.py`) — all interfaces call `get_backend().execute()`, not `run_pipeline_ir()` directly
- `registry_runtime.py` added — `resolve_capability()` lives here, not in orchestrator
- `app/core/config.py` now has `GRAPHYN_REDIS_URL`, `GRAPHYN_STRICT_COMPAT`, `GRAPHYN_PLUGIN_ALLOWED_SOURCES` env vars

### Fixes applied to all 29 plugin nodes (Common + Audio)
All nodes now have:
- Proper None/empty input guards
- Correct error handling (no silent failures)
- Thread-safe model caching where applicable
- Atomic file writes (tmp+rename pattern)
- NaN detection in training loops
- Correct metadata propagation

### Specific behavioral changes docs must reflect
- `DatasetBuilderNode`: `has_split_metadata` uses `all(...)` not `any(...)` — mixed batches fall back to auto-split
- `DatasetBalancerNode`: `_flag_synthetic` now returns `aug_flags` tuple; `target_count < 0` raises `ValueError`
- `EmbeddingGeneratorNode`: model cache keyed on `model_id`; empty audio samples skipped with warning
- `EvaluatorNode`: empty test set returns error artifact; model output dim mismatch raises `ValueError`; `torch.jit.load` tried before `torch.load`
- `TrainerNode`: `TerminateOnNaN` callback added; NaN detection in PyTorch loop; CUDA OOM caught; `X_train_repr.npy` capped at 1000 samples; `ModelBuilderNode` has None/zero-class guard
- `EdgeOptimizerNode`: INT8 raises `ValueError` when `X_train_repr.npy` absent (no silent wrong-shape zeros); model_path existence check added
- `RealtimeInferenceNode`: `_asr_buffer` cleared on mode change; non-2D feature data normalised; adaptive skip is now probabilistic; end-of-call partial flush removed
- `MultimodalFusionNode`: attention/cross-attention project all modalities to `output_dim` before dot-product; `backend="pytorch"` logs warning
- `ExperimentTrackerNode`: MLflow failure falls back to JSON; git timeout reduced to 1s
- `DeploymentPackagerNode`: MCU hex written incrementally (no 50MB RAM spike); `getattr` guard for `artifact.labels`
- `DatasetVersionerNode`: try/except+rmtree cleanup on write failure; empty labels warning

---

## What to Delete

Remove these files entirely — they are legacy, redundant, or superseded:

| File | Reason |
|---|---|
| `docs/PLATFORM_HANDOFF.md` | Session continuity doc from a prior build session. References old architecture (monolithic `pipeline.py`, `run_manager.py`), old bug list, old roadmap. All content is now either wrong or covered by better docs. |
| `docs/TEAM_TAKEOVER.md` | Onboarding doc written mid-build. References old architecture, old file paths, old "open work items" that are now complete. Superseded by `OVERVIEW.md` + `ARCHITECTURE.md`. |
| `docs/PRODUCT_OVERVIEW.md` | Sales presentation slides. Not technical documentation. Out of scope for a `docs/` directory. Contains roadmap items (Web UI, Video domain) that are still future work — misleading as current state. |
| `docs/SYSTEM_DESIGN.md` | 1500-line deep-dive written against the old monolithic `pipeline.py`. References `pipeline.py` as the primary executor (wrong — it's now a shim), old `run_manager.py` structure, old `_infer_artifact_type` location, old observer double-fire bug (now fixed). Content is now split across `ARCHITECTURE.md`, `PIPELINE_EXECUTION.md`, and `BACKEND_CORE.md`. |
| `docs/FRONTEND.md` | Documents the deprecated `audiobuilder/` Visual UI. The file itself says "Deprecated (new frontend is yet to build)". Remove it. |
| `docs/OVERVIEW.md` | Superseded by `README.md` which already serves as the entry point. The content overlaps heavily. Merge any unique content into `README.md` then delete. |

---

## What to Keep and Update

These files stay but need targeted updates:

### `docs/README.md` — Entry Point Index
**Keep.** Update:
- Remove reference to `OVERVIEW.md` (being deleted — merge its unique content here)
- Update the Documentation Map table to reflect the new file set
- Update the "Architecture in One Diagram" to show the new split: `orchestrator.py`, `planner.py`, `node_executor.py`, `checkpoint.py` instead of monolithic `pipeline.py`; `run_journal.py` + `run_control.py` instead of `run_manager.py`; `app/domain/` for domain services
- Update "What Changed" table to add the architecture splits
- Update Quick Start examples to use `get_backend().execute()` as the canonical entry point
- Remove the "What Changed in the Pydantic Migration" section — that migration is ancient history, not current state

### `docs/ARCHITECTURE.md` — System Layers + Data Flows
**Keep.** Update:
- **Section 1 (System Layers):** Replace `app/core/pipeline.py` with the actual split files: `orchestrator.py`, `planner.py`, `node_executor.py`, `checkpoint.py`. Replace `app/core/run_manager.py` with `run_journal.py` + `run_control.py`. Add `app/domain/` layer for `ingestion.py`, `project_manager.py`, `quality_checker.py`. Add `runtime_backend.py` to the Backend Abstraction Layer. Add `registry_runtime.py` to the Node Layer.
- **Section 2 (Component Dependency Graph):** Update to show `get_backend().execute()` as the entry point. Show `run_journal.py` and `run_control.py` as separate modules. Show `app/domain/` as a separate layer below Backend Services.
- **Section 3 (Data Flow: Pipeline Execution):** Replace `run_pipeline_ir()` with `get_backend().execute()` → `LocalPythonBackend` → `orchestrator.run_pipeline_ir_async()`. Update checkpoint step to reference `checkpoint.py`.
- **Section 4 (Data Flow: Artifact Lifecycle):** Update to show `ArtifactSerializerRegistry` — platform calls `registry.get("audio_samples")`, domain registers `AudioSampleHandler` at startup.
- **Section 6 (Registry Bootstrap):** Update to show `initialize_registry()` calls `register_audio_serializer()` to register the domain serializer.
- **Section 8 (Execution Modes):** No changes needed — modes are unchanged.
- **Section 10 (Security Boundaries):** Add `GRAPHYN_PLUGIN_ALLOWED_SOURCES` to the table.
- **Section 11 (Phase History):** Add Phase 9: "Post-review fix pass — 104 files reviewed, all confirmed bugs fixed. Architecture splits: pipeline.py → orchestrator/planner/node_executor/checkpoint/executor; run_manager.py → run_journal/run_control; domain services → app/domain/; ArtifactSerializerRegistry; RuntimeBackend ABC."

### `docs/NODE_SYSTEM.md` — Node Base, Registry, Discovery
**Keep.** Update:
- Add `registry_runtime.py` to the Directory Layout section
- Update `resolve_capability()` entry to show it lives in `registry_runtime`, not orchestrator
- Update the Data Types table: add `DatasetArtifact`, `EmbeddingVector`, `ExperimentArtifact` as plugin-owned types (they exist in plugin `types.py` files)
- No other changes needed — node system is stable

### `docs/PIPELINE_EXECUTION.md` — DAG Executor, IR, Caching
**Keep.** Update:
- **Overview diagram:** Replace `run_pipeline_ir()` with `get_backend().execute()` → `orchestrator.run_pipeline_ir_async()`. Add `planner.py` and `node_executor.py` as separate boxes.
- **Primary Execution Entry Point section:** Replace the direct `run_pipeline_ir` import with `get_backend().execute()` as canonical. Keep `run_pipeline_ir` as internal/backward-compat note.
- **`PipelineGraph` section:** Update file reference from `pipeline.py` to `planner.py`.
- **`NodeExecutor` section:** Update file reference from `pipeline.py` to `node_executor.py`.
- **`run_pipeline()` section:** Mark as deprecated shim. The canonical path is `get_backend().execute()`.
- **`PipelineCache` section:** Update to note that cache uses `ArtifactSerializerRegistry` for type detection — no longer imports `AudioSample` directly.
- **Checkpoints section:** Update file reference to `checkpoint.py`.
- **`validate_pipeline()` section:** Update to note that IR JSON validation path now includes port checks and cycle checks (fixed in review).
- Remove the YAML format examples from the body — YAML is deprecated. Keep only a one-line note pointing to `graphyn migrate`.

### `docs/BACKEND_CORE.md` — RunManager, Logger, ArtifactStore, etc.
**Keep.** This needs the most significant updates:
- **`RunManager` section:** Replace with two sections:
  - `RunJournal` (`app/core/run_journal.py`): persistence — `save_graph_ir`, `save_metadata`, `save_logs`, `mark_failed`, `mark_cancelled`, atomic writes via tmp+rename. `run_id` is now full 32-char UUID4 (not 8-char hex).
  - `RunControl` (`app/core/run_control.py`): active run registry — `register_active_run`, `get_active_run`, `deregister_active_run`, `is_active_on_another_worker()`. Redis-backed when `GRAPHYN_REDIS_URL` is set; in-process dict otherwise.
  - Keep `RunManager` (`app/core/run_manager.py`) as a one-line note: "re-export shim for backward compatibility — use `run_journal` and `run_control` directly."
- **`PipelineLogger` section:** Update to note `put_nowait` (non-blocking) is used for queue emission — no longer blocks on full queue.
- **`ArtifactSerializerRegistry` section:** Expand significantly. This is now a first-class platform component. Document: `ArtifactTypeHandler` ABC methods, `AudioSampleHandler` registration pattern, fail-open design, how `artifact_store` and `pipeline_cache` use it.
- **`IngestionService` section:** Update file path to `app/domain/ingestion.py`. Note: `stream_job` re-fetches Redis each iteration (fixed). Size-exceeded flag breaks out of `with open` before unlink (fixed).
- **`ProjectManager` section:** Update file path to `app/domain/project_manager.py`. Note key fixes: `validate_annotations` normalizes absolute keys; `_estimate_snr` returns None for files ≤100ms; `create_snapshot` validates name; `deduplicate` raises ValueError above 10k files.
- **`QualityChecker` section:** Update file path to `app/domain/quality_checker.py`. Note key fixes: `_check_snr` excludes noise region; `run()` wrapped in try/except; empty-array guards in all check methods.
- **`WebhookService` section:** Note DNS rebinding fix — resolves once, connects to IP directly with Host header.
- **`stable_hash()` section:** Note that `default=str` was removed — non-serializable objects now raise `TypeError` (prevents non-stable hashes from memory-address strings).

### `docs/API_REFERENCE.md` — REST Endpoints
**Keep.** Update:
- **`POST /api/v1/pipelines/run` section:** Update request body to show IR JSON as the primary format (not YAML). YAML is still accepted but deprecated.
- **`POST /api/v1/pipelines/run-async` section:** Note that status is now read from `RunJournal` / `meta.json` — not from an in-memory dict. The `run_id` returned is a full UUID4.
- **`GET /api/v1/runs/{run_id}/status` section:** Add `progress_pct=null` when `num_nodes` is absent (fixed).
- **Artifacts section:** Add `GET /api/v1/artifacts/{artifact_id}/lineage` endpoint.
- **Plugins section:** Add note that `GET /api/v1/plugins/{name}` now surfaces `installing`/`failed`/`installed` states for async installs.
- **Run Control section:** Update `pause`/`resume`/`cancel` responses to show correct status strings: `"pause_requested"` (not `"paused"`), `"cancel_requested"` (not `"cancelled"`).

### `docs/SDK_AND_CLI.md` — Python SDK and CLI
**Keep.** Update:
- **`Pipeline.run()` section:** Update to show `get_backend().execute()` as the underlying call.
- **`Pipeline._build_ir()` section:** Note that `edges=[]` is now treated as auto-chain (not disconnected graph).
- **`Pipeline.to_yaml()` section:** Add deprecation warning note.
- **CLI `graphyn run` section:** Add `--parallel`, `--resume`, `--include-nodes`, `--exclude-nodes`, `--event-driven` flags (these exist in the code but may be missing from docs).
- **CLI `graphyn inspect` section:** Add this command — it exists in `app/cli/main.py` and prints graph summary + capability report.
- **CLI `graphyn nodes` section:** Add `--capability` filter flag.
- **CLI `graphyn artifacts replay` section:** Note that `run_id` prefix matching is supported.

### `docs/MCP_SERVER.md` — MCP Tools
**Keep.** Update:
- **Tool count:** Update from "15 tools" to the actual count. Verify against `app/mcp/tool_registry.py`.
- **`execute_pipeline` section:** Note that `_on_done` callback now marks run failed on unhandled background exception (CRITICAL fix).
- **`replay_run` section:** Note that `_on_replay_done` callback now marks run failed on background exception.
- **`pause_run`/`resume_run`/`cancel_run` section:** Update status strings to `"pause_requested"` / `"cancel_requested"`. Note `OSError` guard on pause/resume. Note `_run_not_active_error()` now distinguishes completed vs never-existed.
- **`list_artifacts` section:** Note `limit` param (default 200) added.
- **`optimize_execution` section:** Note `is_disconnected` field added to response; `unknown_capability_nodes` warning added.
- **Error Contract table:** Add `registry_error` error type (returned when `registry.list_nodes()` fails in discovery handler).

### `docs/PLUGIN_GUIDE.md` — Writing Plugins
**Keep.** Update:
- **Node Template section:** Update `_flag_synthetic` example to show the correct 3-tuple return `(X, y, aug_flags)` pattern.
- **Backend Pattern section:** Add note that `setup()` must initialize all instance variables that `process()` uses — `hasattr` guards are a fallback, not a substitute.
- **Lifecycle Hooks section:** Add note that `teardown()` must reset `_setup_done`-style flags so the node can be re-setup.
- **Quality Checklist:** Add items:
  - [ ] `setup()` initializes all instance variables used by `process()`
  - [ ] `teardown()` resets setup state so node can be re-initialized
  - [ ] Empty/None input guards at the top of `process()`
  - [ ] No silent failures — log warnings for skipped inputs, raise errors for invalid config
  - [ ] Atomic file writes (write to tmp, then `os.replace`) for any file output
  - [ ] Thread-safe model caching (cache keyed on model ID, not just `is None`)
- **Registered Plugins section:** Update the node count and list to match current state (29 nodes confirmed complete).

### `docs/DATA_FLOW_AND_WORKSPACE.md` — Data Types, Workspace Layout
**Keep.** Update:
- **Pipeline Data Flow diagram:** Replace `run_pipeline_ir()` with `get_backend().execute()`. Add `orchestrator.py`, `planner.py`, `node_executor.py` as separate steps.
- **`AudioSample` Lifecycle section:** Update the plugin node chain to reflect current node names and behavior. Note that `audio_conditioner` now uses `model_copy()` + `data.copy()` instead of `deepcopy` (performance fix).
- **Workspace Directory Layout:** Add `artifacts/` and `provenance/` directories (they exist and are used). Add `resume_state.json` to the run directory layout.
- **Security Boundaries section:** Add `GRAPHYN_PLUGIN_ALLOWED_SOURCES` to the table. Add `run_id` ASCII-only regex validation.

### `docs/NODE_CATALOGUE.md` — All 29 Nodes
**Keep.** Update:
- **Common Plugins table:** Add `model_builder` as a node type (it's a separate node class in `trainer/nodes.py` — `ModelBuilderNode` with `node_type="model_builder"`). Total is now 30 nodes (18 Audio + 12 Common).
- **Capability Matrix:** Add `model_builder` row.
- **Dependencies table:** Verify all entries are accurate against current `plugin.toml` files.

### `docs/KNOWN_ISSUES.md` — Open Issues
**Keep but rewrite.** The current file says all tiers are empty. That's correct — all known issues were fixed. But the file should be more useful:
- Add a brief "All issues resolved as of the 104-file review pass (May 2026)" statement
- Add a "How to Report" section
- Add a "Deferred Items" section for the one deferred finding from the review: the `run-async` in-memory `_async_runs` dict (noted in TEAM_TAKEOVER.md as Priority 1 — still not fixed, still a real issue)
- Keep the format clean and ready for new issues

---

## What to Create

Create these new documents:

### `docs/DOMAIN_SERVICES.md` — NEW
Document `app/domain/` — the three domain services that were separated from platform core:

```markdown
# Domain Services

Services in `app/domain/` are domain-specific (audio ML) and depend on platform
infrastructure but are not part of the platform core. Platform code never imports
from `app/domain/` — domain code registers into platform registries at startup.

## `IngestionService` — `app/domain/ingestion.py`
[full documentation of URL ingestion, HuggingFace ingestion, job lifecycle,
progress events, size limits, path sanitization]

## `ProjectManager` — `app/domain/project_manager.py`
[full documentation of project lifecycle, versioning, snapshots, taxonomy,
quality reports, deduplication]

## `QualityChecker` — `app/domain/quality_checker.py`
[full documentation of quality checks: SNR, clipping, DC offset, bandwidth,
outliers, duplicates; contract.json format; quality_report.json format]

## `AudioSampleHandler` — `app/models/audio_artifact_serializer.py`
[document the ArtifactTypeHandler implementation: serialize/deserialize WAV,
manifest.json format, content hash computation, registration via register_audio_serializer()]
```

---

## Formatting Rules

Apply these rules to every document you write or update:

1. **No legacy references.** Remove all mentions of: `pipeline.py` as the primary executor, `run_manager.py` as the primary run service, `audiobuilder/` Visual UI, YAML as a first-class format, `app/core/nodes/audio/` or `app/core/nodes/ml/` directories (they don't exist), `run_id` as 8-char hex (it's now full UUID4), `_async_runs` in-memory dict as the status source.

2. **Canonical entry point.** The canonical execution entry point is `get_backend().execute()` → `LocalPythonBackend` → `orchestrator.run_pipeline_ir_async()`. Never say `run_pipeline_ir()` is the entry point — it's an internal implementation detail.

3. **File paths must be accurate.** Before writing any file path, verify it exists in the codebase. The split files are: `app/core/orchestrator.py`, `app/core/planner.py`, `app/core/node_executor.py`, `app/core/checkpoint.py`, `app/core/executor.py`, `app/core/run_journal.py`, `app/core/run_control.py`, `app/domain/ingestion.py`, `app/domain/project_manager.py`, `app/domain/quality_checker.py`.

4. **No aspirational content.** Do not document features that don't exist yet (Web UI, Video domain, Document Processing domain, environment isolation). These belong in a ROADMAP.md if needed, not in technical docs.

5. **Fixes are the new baseline.** Do not mention bugs that were fixed as "known issues" or "limitations." The fixed behavior is the correct behavior. Document what the code does now, not what it used to do.

6. **Concise and precise.** Each section should be as long as it needs to be and no longer. Prefer tables and code blocks over prose for reference material.

7. **Cross-references.** Every document should have a clear "See also" or link to related documents. No document should be a dead end.

---

## Execution Order

Process files in this order to avoid forward-reference problems:

1. **Delete** the 6 files listed in "What to Delete"
2. **Create** `docs/DOMAIN_SERVICES.md`
3. **Update** `docs/ARCHITECTURE.md` (foundation — other docs reference it)
4. **Update** `docs/NODE_SYSTEM.md`
5. **Update** `docs/PIPELINE_EXECUTION.md`
6. **Update** `docs/BACKEND_CORE.md`
7. **Update** `docs/DATA_FLOW_AND_WORKSPACE.md`
8. **Update** `docs/API_REFERENCE.md`
9. **Update** `docs/SDK_AND_CLI.md`
10. **Update** `docs/MCP_SERVER.md`
11. **Update** `docs/PLUGIN_GUIDE.md`
12. **Update** `docs/NODE_CATALOGUE.md`
13. **Update** `docs/KNOWN_ISSUES.md`
14. **Update** `docs/README.md` last (it references all other docs)

---

## Verification Checklist

After completing all updates, verify:

- [ ] No document references `pipeline.py` as the primary executor
- [ ] No document references `run_manager.py` as the primary run service
- [ ] No document references `audiobuilder/` or the Visual UI as active
- [ ] No document references YAML as a first-class pipeline format
- [ ] `docs/README.md` Documentation Map lists all current docs and no deleted ones
- [ ] `docs/ARCHITECTURE.md` Phase History includes Phase 9 (review/fix pass)
- [ ] `docs/BACKEND_CORE.md` has `RunJournal` and `RunControl` sections (not `RunManager`)
- [ ] `docs/BACKEND_CORE.md` has `ArtifactSerializerRegistry` section
- [ ] `docs/DOMAIN_SERVICES.md` exists and documents all three domain services
- [ ] `docs/KNOWN_ISSUES.md` mentions the deferred `run-async` status tracking issue
- [ ] `docs/NODE_CATALOGUE.md` includes `model_builder` node
- [ ] All 6 legacy files are deleted
- [ ] No broken cross-references between documents

---

## Source Files to Read Before Writing

Read these files to get accurate current state before writing any section:

| Topic | Read |
|---|---|
| Architecture splits | `app/core/orchestrator.py`, `app/core/planner.py`, `app/core/node_executor.py`, `app/core/checkpoint.py` |
| Run services | `app/core/run_journal.py`, `app/core/run_control.py` |
| Domain services | `app/domain/ingestion.py`, `app/domain/project_manager.py`, `app/domain/quality_checker.py` |
| Serializer registry | `app/core/artifact_serializer.py`, `app/models/audio_artifact_serializer.py` |
| Runtime backend | `app/core/runtime_backend.py` |
| Registry runtime | `app/core/registry_runtime.py` |
| Config/env vars | `app/core/config.py` |
| MCP tool count | `app/mcp/tool_registry.py` |
| Common plugin nodes | `PluginPackage/Common/*/nodes.py` (all 11 directories) |
| Node catalogue | `PluginPackage/NODES.md` |
| Plugin architecture | `PluginPackage/ARCHITECTURE.md` |
