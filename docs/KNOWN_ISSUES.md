# Known Issues

> **Single source of truth for open issues.**  
> Add new findings here when discovered; remove when fixed.

---

## Open — Fix Immediately (before next deployment)

### (resolved 2026-07-29) EDGE-DROP-1 / EDGE-DROP-2 / AUTH-MOUNT-1

Fixed in code:
- `app/api/routers/pipelines.py` now executes GraphIR directly through `get_backend().execute(graph)`.
- `app/api/routers/artifacts.py` replay now executes loaded GraphIR directly through `get_backend().execute(graph)`.
- `app/api/main.py` now enforces bearer auth on `/files`, `/input-files`, and `/run-files` via middleware when token auth is enabled.

---

## Open — Fix This Sprint

### (resolved 2026-07-29) FE-YAML-1 — audiobuilder was YAML-primary

**Was:** `audiobuilder/` canvas run/save emitted YAML and rejected non-linear graphs.  
**Status:** `audiobuilder/` removed. Replaced by `graphyn-ui/` — IR-native Builder with platform surfaces (Runs, Artifacts, Plugins, Templates, Data, Projects, System).

### (resolved 2026-07-29) BACKEND-PATH-1 — CLI/API paths bypass `get_backend()`

**Files:** `app/cli/main.py` (`cmd_artifacts_replay`), parts of `artifacts.py`  
**Detail:** Docs claim all interfaces use `get_backend().execute()`; CLI replay calls `orchestrator.run_pipeline_ir` directly.  
**Status:** Fixed for CLI artifact replay (`app/cli/main.py`) and artifact replay API path.

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
**Workaround:** Platform defaults Keras to CPU on CC ≥12. Force GPU only with `GRAPHYN_TF_FORCE_GPU=1` (expected to fail until TF/CUDA support catches up). FaceRecognition and other GPU apps are left alone (memory growth only).

---

## Open — Deferred (Architectural Work Required)

### SCALE-3 — `run-async` status tracking uses `meta.json` polling

**File:** `app/api/routers/pipelines.py` → `GET /api/v1/runs/{run_id}/status`  
**Severity:** Low  
**Detail:** Correct for single-worker; under high concurrency prefer an in-memory status cache coordinated with `run_control.py`.  
**Workaround:** Poll status at ≥500ms.

### (resolved) AUTH-DEFAULT-1 — Auth off when token unset

**Was:** Empty `GRAPHYN_API_TOKEN` meant allow-all even in deploy.  
**Now:** `GRAPHYN_AUTH_REQUIRED=1` or `GRAPHYN_ENV=production|staging` rejects empty tokens on API and MCP. Compose sets both. Local `GRAPHYN_ENV=development` stays optional-auth.

---

## How to Report

1. Add a row to the matching priority tier in this file.
2. Reference the source file (and approximate location).
3. Include a workaround if one exists.
