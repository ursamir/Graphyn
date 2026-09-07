# Known Issues

> **Single source of truth for open issues.**  
> Add new findings here when discovered; remove when fixed.

---

## Open — Fix This Sprint

### DEPS-1 — Dependency manifest skew

**Files:** `requirements.txt`, `setup.py`  
**Detail:** Runtime uses `httpx`, `packaging`, optional `redis`; pins are incomplete/out of sync between files.  
**Fix:** Single source of deps; declare optional extras for redis/hf/tf.

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

### DIST-CANCEL-2 — Streaming `execute_stream` does not honour `request_cancel`

**Files:** `app/core/node_executor.py`  
**Detail:** Streaming path does not yet thread cancel checks through `execute_stream`.  
**Status:** Deferred with DIST-CANCEL-1; tracked in `docs/DISTRIBUTED_EXECUTION.md` §15.

### DIST-RECLAIM-1 — Preferred-worker pin after lease reclaim (mitigated)

**Was:** Reclaimed jobs could stay pinned to a dead preferred worker.  
**Now:** `reclaim_expired_leases` calls `widen_placement_after_reclaim` (`mode=worker` → `mode=auto`, clears pin; keeps tags/GPU/VRAM/pool). Remaining edge cases: very short lease windows under network partition — widen further if reclaim storms appear in ops.

---

## Open — Deferred (Architectural Work Required)

### SCALE-3 — `run-async` status tracking uses `meta.json` polling

**File:** `app/api/routers/pipelines.py` → `GET /api/v1/runs/{run_id}/status`  
**Severity:** Low  
**Detail:** Correct for single-worker; under high concurrency prefer an in-memory status cache coordinated with `run_control.py`.  
**Workaround:** Poll status at ≥500ms.

### RBAC-1 — Role-based access control not shipped

**Detail:** Auth is shared Bearer / optional local unlock. No per-user roles, tenants, or OIDC.  
**Do not claim done** in market/vision docs until implemented.

### OTEL-1 — OpenTelemetry traces not shipped

**Detail:** Structured logs + NDJSON + Trace UX (artifact→run→worker) exist. Per-node/job OTel spans across distributed workers are P3 (`docs/DISTRIBUTED_EXECUTION.md`).

### EDGE-LOOP-1 — Full Edge Impulse-style device feedback loop not shipped

**Detail:** Edge deploy wizard + `deployment_packager` / `edge_optimizer` exist. Device flash/feedback loop remains product gap (`docs/PRODUCT_VISION.md`).

---

## Resolved (kept for history)

### (resolved 2026-07-29) EDGE-DROP-1 / EDGE-DROP-2 / AUTH-MOUNT-1 / FE-YAML-1 / BACKEND-PATH-1 / AUTH-DEFAULT-1

- Pipelines/artifacts replay execute GraphIR via `get_backend().execute(graph)`.
- Bearer auth on `/files`, `/input-files`, `/run-files` when token auth enabled.
- `audiobuilder/` removed; `graphyn-ui/` is IR-native.
- CLI/API replay paths use `get_backend()`.
- `GRAPHYN_AUTH_REQUIRED=1` / `GRAPHYN_ENV=production|staging` fail-closed on empty tokens.

### (resolved 2026-09) Distributed P0–P2 + harden; pillars A–E console IA

See `docs/DISTRIBUTED_EXECUTION.md`, `docs/PRODUCT_VISION.md`. Mid-flight in-process cancel + stream cancel remain open above.

---

## How to Report

1. Add a row to the matching priority tier in this file.
2. Reference the source file (and approximate location).
3. Include a workaround if one exists.
