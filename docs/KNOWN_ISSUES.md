# Limitations & known issues

> Current platform limitations. Remove entries when fixed; add newly discovered gaps here.

---

## Open — Fix This Sprint

### PLUGIN-LOAD-1 — Plugin startup can fail with stale installed bytecode

**Detail:** After loader module-naming changes, old `__pycache__` entries under `~/.graphyn/plugins/installed/` can cause startup warnings such as: `Plugin 'feature-frontend' declared 1 entry point(s) but no node types were registered`. Runtime install/upgrade still succeeds.  
**Workaround:** Clear stale plugin caches (`~/.graphyn/plugins/installed/**/__pycache__`) and rerun plugin load/install.

### EVENT-DRIVEN-EXIT-1 — Event-driven demos may not terminate promptly

**Files:** `examples/15_event_driven_pipeline/event_driven_demo.py`, `app/core/events.py`  
**Detail:** On some Linux environments, file-watcher event loops may continue running briefly after cancel, causing long waits in scripted full-suite runs.  
**Workaround:** Run with a process timeout in CI/sweeps; treat output artifacts and completion logs as pass criteria.

### TF-GPU-CC12-1 — Keras training unsupported on compute capability ≥12

**Files:** `app/core/tf_runtime.py` (`select_keras_device`), `PluginPackage/Common/trainer/nodes.py`  
**Detail:** RTX 50-series (e.g. RTX 5070 Ti, CC 12.0) is visible to TensorFlow but Keras `fit` fails (PTX/libdevice/XLA JIT). Soft-placement CPU fallback without pinning also fails (CPU weights + GPU train step).  
**Workaround:** Platform defaults Keras to CPU on CC ≥12. Force that class of GPU only with `GRAPHYN_TF_FORCE_GPU=1` (expected to fail until TF/CUDA support catches up). FaceRecognition and other GPU apps are left alone: memory growth + `GRAPHYN_TF_GPU_MIN_FREE_MIB` (default 4096). Opt-in compose overlay `docker-compose.gpu.yml` is required before Graphyn can see the NVIDIA device at all.

---

## Open — Distributed / cancel limits

### DIST-CANCEL-1 — In-process `node.process()` cannot be forcibly interrupted mid-call

**Files:** `app/core/node_executor.py`, `app/core/distributed/backend.py`, worker CLI  
**Detail:** Isolated plugin subprocesses honour cancel via process-group terminate; cooperative cancel runs between retries / before `process`. Non-isolated in-process `process()` is observed only before/after the call, between retries, or when it returns.  
**Workaround:** Prefer `runtime=isolated` for long GPU/training nodes; use job cancel + worker cancel-watch for remote jobs.

### DIST-CANCEL-2 — Streaming `execute_stream` cancel is cooperative only (partial)

**Files:** `app/core/node_executor.py`  
**Detail:** `execute_stream` now polls `request_cancel` / `cancel_check` before start and between yielded items (raises `cancelled by control plane`). It still cannot interrupt mid-yield inside `node.process_stream` — same cooperative limit as non-isolated `process()` (DIST-CANCEL-1).  
**Status:** Cooperative checks landed; full mid-stream interrupt deferred. Regression: `unit_test/core/test_node_executor_cancel.py`.

### DIST-RECLAIM-1 — Preferred-worker pin after lease reclaim (mitigated)

**Was:** Reclaimed jobs could stay pinned to a dead preferred worker.  
**Now:** `reclaim_expired_leases` calls `widen_placement_after_reclaim` (`mode=worker` → `mode=auto`, clears pin; keeps tags/GPU/VRAM/pool). `lease_generation` increments so a stale worker `complete` after reclaim is rejected (fencing).  
**Remaining edge cases (still open):**
- Very short lease TTL under network partition / clock skew can cause reclaim storms (job flip-flops pending↔claimed).
- A dead worker that still holds a process may finish after reclaim; fencing rejects that complete, but the late side-effects (artifacts written locally) are not rolled back.
- Heartbeat lease renew failures are logged but do not fail the heartbeat response — missed renewals still rely on reclaim.

---

## Open — Deferred (Architectural Work Required)


### UI-A11Y-1 — Accessibility polish incomplete (not WCAG-certified)

**Files:** `graphyn-ui/src/**`  
**Detail:** Phase 7 added focus-visible outlines, `role="alert"` on ErrorBanner, page `h1` via PageHeader, icon-button labels, Settings dialog focus restore/Tab trap, ConfirmButton Escape-to-disarm, and a contrast bump for failed-node status text. Remaining gaps (not claimed fixed):
- No full screen-reader audit of every route; React Flow canvas/handles remain weakly announced.
- Some muted/meta text still uses `text-ink-400` (~3.4:1 on white) for non-critical chrome.
- Dropdown/action menus (plugins/templates/builder “more”) are not full ARIA menus with arrow-key roving tabindex.
- Toasts lack live-region politeness tuning; ConfirmButton is two-click arming, not a modal dialog.
**Do not claim** full WCAG 2.x AA compliance in product or trust docs.


### SCALE-3 — `run-async` status tracking uses `meta.json` polling

**File:** `app/api/routers/pipelines.py` → `GET /api/v1/runs/{run_id}/status`  
**Severity:** Low  
**Detail:** Correct for single-worker; under high concurrency prefer an in-memory status cache coordinated with `run_control.py`.  
**Workaround:** Poll status at ≥500ms.

### RBAC-1 — Role-based access control not shipped

**Detail:** Auth is shared Bearer / optional local unlock (unauthenticated-dev when `GRAPHYN_API_TOKEN` unset). No per-user roles, tenants, or OIDC. Resource capabilities for the current model are documented in `docs/TRUST_MODEL.md` §2 — that matrix is **not** RBAC.  
**Future:** when multi-user is supported, cross-project access must be prevented by default.  
**Do not claim done** in market/vision docs until implemented.

### OTEL-1 — OpenTelemetry traces not shipped

**Detail:** Structured logs + NDJSON + Trace UX (artifact→run→worker) exist. Per-node/job OTel spans across distributed workers are P3 (`docs/DISTRIBUTED_EXECUTION.md`).

### EDGE-LOOP-1 — Full Edge Impulse-style device feedback loop not shipped

**Detail:** Edge deploy wizard + `deployment_packager` / `edge_optimizer` exist. Device flash/feedback loop remains product gap (`docs/PRODUCT_VISION.md`).

---

## Resolved (kept for history)

### (resolved 2026-09-07) DEPS-1 dependency manifest skew

`setup.py` `install_requires` / `extras_require` is authoritative. `requirements.txt` mirrors the default runtime set. Declared direct imports: `httpx`, `packaging`; extras for `mcp`, `redis`, `events` (watchfiles), `vad` (webrtcvad), `hf`, `tf`, `dev`. Gate: `scripts/check_deps.py`. CI smoke: `scripts/ci_smoke.sh` (+ `scripts/ui_build.sh` for the console).

### (resolved 2026-09-07) PLUGIN-001 plugin installation lock is instance-local

`PluginManager` lifecycle ops (install/uninstall/enable/disable) use a process-wide RLock keyed by plugins home plus an exclusive flock on `install.lock`, so separate API-created managers and multi-process writers cannot race on the same install directory. Regression: multiprocess install stress in `unit_test/core/plugins/test_manager.py`.

### (resolved 2026-09-07) PLUGIN-002 plugin registry cross-process lost-update

`PluginStore` RMW uses a process-wide RLock (shared across instances) plus exclusive flock on `registry.lock` for the full load→mutate→atomic replace (same spirit as `DiskStateStore.mutate_queue`). Regression: multiprocess save/update stress in `unit_test/core/plugins/test_store.py`.

### (resolved 2026-09-07) SEC-002 python_code is not a real sandbox

Chose **Option A — trusted workflows only**. UI/docs/metadata no longer call AST-filtered `exec()` a sandbox; filters remain defense-in-depth (`allow_network` default off; `allowed_paths` explicit). Untrusted multi-tenant exposure needs future container isolation (Option B). Trust write-up: `docs/TRUST_MODEL.md`.

### (resolved 2026-09-07) SEC-003 HTTP egress policy

`http_request` / `http_webhook` share `app/core/egress.py`. Default `GRAPHYN_HTTP_EGRESS_MODE=trusted` (no behaviour change). `restricted` blocks private/link-local/loopback/metadata ranges and optional `GRAPHYN_HTTP_EGRESS_ALLOWLIST`. ASR/LLM keep provider clients (documented; not wired). See `docs/TRUST_MODEL.md`.

### (resolved 2026-09-07) SEC-001 plugin source allowlist prefix matching

`plugin_source_is_allowed` now parses URLs structurally and requires host + path-segment boundaries (exact repo or subpath under `/owner/repo/`). Similarly prefixed repos (`repo` vs `repo-evil`/`repo2`), malicious hosts, and `..` / encoded traversal are rejected. Redirect hops continue to be re-checked fail-closed in installer/index download paths.


### (resolved 2026-07-29) EDGE-DROP-1 / EDGE-DROP-2 / AUTH-MOUNT-1 / FE-YAML-1 / BACKEND-PATH-1 / AUTH-DEFAULT-1

- Pipelines/artifacts replay execute GraphIR via `get_backend().execute(graph)`.
- Bearer auth on `/files`, `/input-files`, `/run-files` when token auth enabled.
- `audiobuilder/` removed; `graphyn-ui/` is IR-native.
- CLI/API replay paths use `get_backend()`.
- `GRAPHYN_AUTH_REQUIRED=1` / `GRAPHYN_ENV=production|staging` fail-closed on empty tokens.

### (resolved 2026-09-07) DIST-001 atomic cross-process job claim

`JobQueue.claim` + `DiskStateStore.mutate_queue` (exclusive flock) / Redis lock-or-WATCH. Regression: multiprocess claim stress in `unit_test/core/test_distributed_p2.py`.

### (resolved 2026-09-07) DIST-002 durable queue mutators

All whole-snapshot `JobQueue` mutators (`enqueue`, `claim`, `complete`, `renew_lease`, `append_events`, `cancel`, `mark_running`, `reclaim_expired_leases`, `renew_leases_for_worker`, `clear`) route through `store.mutate_queue` / `_durable_mutate` when a durable store is configured. In-memory path keeps `_reclaim_expired_leases_unlocked` + `_persist_unlocked`. Concurrent DiskStateStore races covered in `test_distributed_p2.py`.

### (resolved 2026-09-07) DIST-003 worker registry lost-update race

`WorkerRegistry` register/heartbeat/remove/clear now RMW via `store.mutate_workers` / `_durable_mutate_workers` (disk exclusive `workers.lock` + unique temp files; Redis lock-or-WATCH; memory RLock). Blind full-snapshot `save_workers` from a stale local cache is not used for production RMW. Regression: concurrent register/heartbeat/remove + unique-temp + Redis fake contract in `unit_test/core/test_distributed_registry_mutate.py`. Live Redis integration still pending (CI has no Redis).

### (resolved 2026-09) Distributed P0–P2 + harden; pillars A–E console IA

See `docs/DISTRIBUTED_EXECUTION.md`, `docs/PRODUCT_VISION.md`. Mid-flight in-process cancel + stream cancel remain open above.

---

## How to Report

1. Add a row to the matching priority tier in this file.
2. Reference the source file (and approximate location).
3. Include a workaround if one exists.
