# Limitations & known issues

> Current platform limitations. Remove entries when fixed; add newly discovered gaps here.

---

## Resolved recently

### (resolved 2026-09-30) STORE-CONCURRENCY — file-backed stores lost updates / double-executed under concurrency

- **Project files** (`app/domain/project_manager.py`): every write (project.json, links, taxonomy, contract, spec, annotations.jsonl, curation) is atomic (unique same-dir tmp + fsync + `os.replace`), and every read-modify-write holds a per-project lock (`<project>/.graphyn.lock`, threads + `fcntl`). Concurrent annotation POSTs no longer truncate each other (2000 → 8 repro); GETs never see a half-written file.
- **Idempotency-Key** (`app/api/idempotency.py`): `begin_idempotent` atomically reserves an in-flight placeholder; a concurrent same-key request gets **409 `idempotency_in_progress`** instead of executing twice. Failed handlers release it (`idempotency_guard` / `abort_idempotent`, wired into every caller); orphaned placeholders expire after 15 min.
- **Pipeline versions/envs** (`app/core/pipelines/pipeline_environments.py`): versions sort numerically (`v10` > `v9`, fixes `latest_version`); `vN` allocation, publish and promote run under the per-pipeline lock and a version file is never overwritten; a corrupt `environments.json` raises `EnvironmentsCorrupt` (copy saved as `environments.json.corrupt-<sha>`) instead of being read as `{}` and erasing the prod pointer on the next write.
- **Model registry** (`app/core/mlops/model_registry.py`, `app/api/routers/models.py`): `register_model` requires `runs/<run_id>` to exist and have succeeded (404 `run_not_found` / 409 `run_not_succeeded`); `publish_alias` no longer creates empty run dirs (raises `FileNotFoundError`); `POST /models` with `stage=prod` → **403 `prod_requires_approval`** (prod only via request-prod → approve-prod); registry RMW is locked + atomic.
- **If-Match** (`project_pipelines.py`, `ship_packages.py`): compare + write are done under one per-resource lock. Pipeline `resource_version` is now a content hash of the bytes returned (old `st_mtime_ns` tokens are still accepted once).
- **Dataset versions** (`app/core/mlops/dataset_versions.py`): `write_manifest` uses a unique tmp (concurrent GETs no longer fail `os.replace`); the delete guard (`find_references`) also scans run `graph.json` / `ir.json`.

### (resolved 2026-09-29) EVENT-DRIVEN-EXIT-1 — event-driven runs could linger after cancel/failure

`_run_event_driven` (`app/core/execution/orchestrator.py`) now runs a watcher that, on the first failure or cancel, closes **every** event source and cancels handler tasks still blocked on an idle source, so an idle watcher can no longer hang the run. The first terminal status wins (a later cancel never overwrites `failed`).

### (resolved 2026-09-29) RUN-LIFECYCLE — ghost `running` runs / terminal status overwrite

Every exit path of `run_pipeline_ir_async` leaves the run terminal (`succeeded` / `failed` / `cancelled`), tears down every executor that was set up and deregisters the run. `RunManager` status writes are compare-and-set (first terminal status wins); a durable `cancel_requested` marker makes cross-process / queued cancels stick. Resume/checkpoint/provenance/seed keys use the **logical** graph hash (pre run-scoping) in both Mode A and Mode B. See [PIPELINE_EXECUTION.md § Run lifecycle](./PIPELINE_EXECUTION.md#run-lifecycle).

### (resolved 2026-09-29) SECRET-ENV-NAME — graph-selected secret names could read any process env var

`app.core.trust.secrets.resolve_secret` only falls back to process env for secret-shaped names (`*_API_KEY`, `*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`, `*_DSN`, `*_URL`, `*_URI`) that do not start with `GRAPHYN_`, or names in `GRAPHYN_SECRET_ENV_ALLOWLIST`. `resolve_llm_credentials` and every plugin that takes a secret *name* from config (`http_request`, `http_webhook`, `rag_slack_connector`, `rag_notion_connector`, `vector_store_query`/`write`, `speaker_separator`, `structured_llm`, `asr_transcribe`) route through it. `structured_llm` also uses `llm_client.resolve_llm_endpoint` (key ↔ `base_url` binding). See [TRUST_MODEL.md](./TRUST_MODEL.md).

### (resolved 2026-09-29) MARKETPLACE-INGEST-CWD — empty dataset_ingest path scanned CWD

Marketplace templates (e.g. `tpl-audio-kws-retail`) kept the dataset root in `parameters.dataset_path` but materialized `dataset_ingest.config.path` as **empty**. UI showed the field description (“workspace/ relative path…”) as a placeholder. `resolve_ingest_dir("")` treated `Path("")` as `.` (CWD), then recursive `limit=0` loaded every audio file under the project into RAM (~60GB OOM). **Fix:** refuse empty/CWD/bare-workspace ingest roots; require filesystem `path`; materializer binds OOB seed datasets + sanitizes configs; catalog + generator write `config_overrides.path`.

### (resolved 2026-09-29) MARKETPLACE-OOB-SEED — fictional ingest paths + bad config keys

Materialized templates pointed at non-existent folders (`workspace/datasets/input/security-kws`) and wrote forbidden keys (`audio_conditioner.sample_rate`). **Fix:** out-of-box materialize rewrites ingest onto bundled seeds, remaps aliases, strips unknown Config fields via registry, default ingest `limit=8`.

### (resolved 2026-09-29) MARKETPLACE-QG-REJECTED-EDGE — quality gate wired ``rejected`` to next node

Linear materialize scoring tied on `list[AudioSample]` for `output` vs `rejected`; lexicographic sort preferred `rejected`, so SED/KWS chains fed the empty reject port into augmentation → empty dataset → `model_builder` “0 classes”. **Fix:** prefer primary output ports over side-channels when scores tie.

---

## Open — Fix This Sprint

### TEST-SUITE-1 — Full pytest suite residuals (2026-09-16)

**Source:** [`docs/DEEP_REVIEW.md`](./DEEP_REVIEW.md)  
**Progress:** DEEP_REVIEW P0–P3 code fixes landed. Suite improved from **92 failed + 49 errors** toward green; remaining failures are mostly ML model-download / optional-dep smoke tests and env-only items — not the original silent-wrong-results defects. CI gate is full `unit_test/` (`scripts/ci_smoke.sh`, Python 3.12).

### DEEP-REVIEW-P0 — Verification loop + critical defects (2026-09-16) — **CLOSED**

**Source:** [`docs/DEEP_REVIEW.md`](./DEEP_REVIEW.md)  
**Fixed in-tree (complete pass):** P0-1..P0-5; P1-1..P1-28; P2-1..P2-50; P3-1..P3-35 except host-only **P3-32** (`UI-BUILD-EACCES-1` below — needs local `sudo chown`). P3-22 CLI coverage expanded in `unit_test/cli/test_cli.py` (runs/secrets/artifacts/inspect). Large-module splits P3-13/14/18 remain incremental (helpers extracted; full god-module split deferred).

**Still open:** none of the DEEP_REVIEW correctness findings. Residual suite flakes and P3-32 ownership are tracked above / as UI-BUILD-EACCES.

**Fixed (2026-09-16, Mode B / plugins / scripts batch):** P2-10..P2-13, P2-20..P2-26, P2-35..P2-39, P2-41..P2-50 per §6 (disk queue fail-closed, blob atomic+hash verify, job cancel on backend failure, stale worker pin release, plugin.toml defaults, isolated runtime registry, registry quarantine, trace/meta stats, migrate aliases, heal/e2e scripts, deps/docker/events).

---

### PLUGIN-LOAD-1 — Plugin startup can fail with stale installed bytecode / vanished paths — mitigated

**Detail:** After loader module-naming changes, old `__pycache__` entries under `~/.graphyn/plugins/installed/` can cause startup warnings such as: `Plugin 'feature-frontend' declared 1 entry point(s) but no node types were registered`. Separately, pytest runs can leave `registry.json` entries pointing at vanished `/tmp/pytest-of-*/...` paths; previously those enabled-but-missing records blocked bundled auto-install and left `GET /api/v1/nodes` empty.  
**Mitigation (2026-09):** `PluginManager.load_enabled_plugins()` heals records when `{GRAPHYN_HOME}/plugins/installed/<name>` still has a manifest, otherwise prunes the stale record. `maybe_auto_install_and_load()` treats non-loadable enabled records as empty and installs bundled `PluginPackage` plugins. `initialize_registry()` falls back to AutoDiscovery on `plugins_home` when the manager leaves the registry empty.  
**Workaround (bytecode only):** Clear stale plugin caches (`~/.graphyn/plugins/installed/**/__pycache__`) and rerun plugin load/install. Do **not** set `GRAPHYN_SKIP_PLUGIN_LOAD=1` when starting the API/UI catalog.

### TF-GPU-CC12-1 — Keras training unsupported on compute capability ≥12

**Files:** `app/core/ml/tf_runtime.py` (`select_keras_device`), `PluginPackage/Common/trainer/nodes.py`  
**Detail:** RTX 50-series (e.g. RTX 5070 Ti, CC 12.0) is visible to TensorFlow but Keras `fit` fails (PTX/libdevice/XLA JIT). Soft-placement CPU fallback without pinning also fails (CPU weights + GPU train step).  
**Workaround:** Platform defaults Keras to CPU on CC ≥12. Force that class of GPU only with `GRAPHYN_TF_FORCE_GPU=1` (expected to fail until TF/CUDA support catches up). FaceRecognition and other GPU apps are left alone: memory growth + `GRAPHYN_TF_GPU_MIN_FREE_MIB` (default 4096). Opt-in compose overlay `docker-compose.gpu.yml` is required before Graphyn can see the NVIDIA device at all.

---

## Open — Distributed / cancel limits

### DIST-CANCEL-1 — In-process `node.process()` cannot be forcibly interrupted mid-call

**Files:** `app/core/execution/node_executor.py`, `app/core/execution/orchestrator.py`, `app/core/distributed/backend.py`, worker CLI  
**Now (2026-09-29):** Mode A local runs wire `NodeExecutor.set_cancel_check` for every executor, so a cancel terminates isolated plugin subprocesses (process-group terminate) and interrupts retry back-off; the orchestrator checks cancel (unthrottled `poll_cancelled`, incl. the durable `cancel_requested` marker) at every node boundary and refuses to start a run cancelled while queued. Remote jobs use job cancel + worker cancel-watch.  
**Still open:** a non-isolated in-process `process()` is observed only before/after the call, between retries, or when it returns.  
**Workaround:** Prefer `runtime=isolated` for long GPU/training nodes (`trainer`, `evaluator`, `edge_optimizer`, `realtime_inference` already default isolated). Full mid-call interrupt for in-process remains deferred.

### DIST-CANCEL-2 — Streaming `execute_stream` cancel is cooperative only (partial)

**Files:** `app/core/execution/node_executor.py`  
**Detail:** `execute_stream` now polls `request_cancel` / `cancel_check` before start and between yielded items (raises `cancelled by control plane`). It still cannot interrupt mid-yield inside `node.process_stream` — same cooperative limit as non-isolated `process()` (DIST-CANCEL-1).  
**Status:** Cooperative checks landed; full mid-stream interrupt deferred. Regression: `unit_test/core/test_node_executor_cancel.py`.

### DIST-RECLAIM-1 — Preferred-worker pin after lease reclaim (mitigated)

**Was:** Reclaimed jobs could stay pinned to a dead preferred worker.  
**Now:** `reclaim_expired_leases` calls `widen_placement_after_reclaim` (`mode=worker` → `mode=auto`, clears pin; keeps tags/GPU/VRAM/pool). `lease_generation` increments so a stale worker `complete` **and output upload** after reclaim is rejected (fencing — workers always report the generation they claimed; 409 = fenced/terminal). Heartbeat v2 renews only the worker's `active_job_ids`, and `GET` job polling never renews leases.  
**Remaining edge cases (still open):**
- Very short lease TTL under network partition / clock skew can cause reclaim storms (job flip-flops pending↔claimed).
- A dead worker that still holds a process may finish after reclaim; fencing rejects that complete. Generation-scoped output blobs from that attempt are deleted and recorded in `artifacts/distributed_blob_tombstones.jsonl`. Content-addressed `sha256/` blobs are recorded but not deleted (they may be shared). In-process side effects inside `node.process()` (files the node wrote itself) are still not rolled back.
- *(Mitigated 2026-09-15)* Heartbeat lease renew failures return HTTP 503 so workers retry instead of looking healthy while leases expire.

---

## Open — Known caveats of the 2026-09 hardening round

### MODEB-VERSION-SKEW-1 — Mixed-version Mode B workers reject new protocol fields

**Files:** `app/core/distributed/models.py` (`WorkerInfo`, `NodeJob`, `JobResult` use `extra="forbid"`)  
**Detail:** New fields (`NodeJob.finished_at`, `NodeJob.result_consumed_at`, `JobResult.output_sha256`, heartbeat `active_job_ids`) are rejected by older workers/control planes with a validation error.  
**Workaround:** Upgrade the control plane and every worker together (same commit). Drain workers before upgrading.

### PLUGIN-GIT-REDIRECT-1 — `git clone` plugin installs no longer follow HTTP redirects

**Files:** `app/core/plugins/installer.py` (`_git_protocol_config`: `-c http.followRedirects=false`, protocol allowlist)  
**Detail:** A redirect could leave the allowlisted host, so it is refused. Renamed/transferred GitHub repos that only resolve via redirect now fail to install.  
**Workaround:** Use the repository's current canonical URL (and update `GRAPHYN_PLUGIN_ALLOWED_SOURCES` to match).

### API-HOST-GUARD-1 — Tokenless API requires a loopback / IP-literal Host

**Files:** `app/api/main.py` (`host_header_allowed`)  
**Detail:** DNS-rebinding guard: while `GRAPHYN_API_TOKEN` is unset, requests whose `Host` is not `localhost` / `*.localhost` / an IP literal / `graphyn-api` (compose service) / a name in `GRAPHYN_ALLOWED_HOSTS` get **403**. Accessing an unauthenticated dev API through a LAN hostname (e.g. `http://gpu-box:8001`) breaks.  
**Workaround:** Set `GRAPHYN_API_TOKEN` (recommended), or list the hostname in `GRAPHYN_ALLOWED_HOSTS` (comma-separated; `*` disables the guard).

### IR-CAPABILITY-DEFAULT-1 — IR `capability_metadata` cannot force a field back to its default

**Files:** `app/core/host/registry_runtime.py` (`resolve_capability`, `_merge_ir_capability`)  
**Detail:** IR capability fields overlay plugin `NodeMetadata` only when explicitly set **and** different from the `IRCapabilityMetadata` default (a `dump_ir`/`load_ir` round-trip marks every field as set, so default-valued fields are treated as padding). E.g. IR `cacheable: true` cannot re-enable caching for a plugin that declares `cacheable = false`.  
**Workaround:** Change the plugin's metadata (`plugin.toml` / `NodeMetadata`) instead of the IR.

### AGENT-LOOP-EXTRACTIVE-1 — `agent_loop` is extractive only

**Files:** `PluginPackage/Agents/agent_loop/nodes.py`  
**Detail:** `agent_loop` calls no LLM and no tools: it scans the context for the goal's terms and returns goal + excerpt (`mode="extractive"`). `model`, `api_secret_name` and `tool_allowlist` are reserved and ignored.  
**Workaround:** Compose `prompt_template` → `llm_chat` → `tool_router` / `mcp_tool_call` for generative agent loops.

---

## Open — Deferred (Architectural Work Required)


### UI-A11Y-1 — Accessibility polish incomplete (not WCAG-certified)

**Files:** `graphyn-ui/src/**`  
**Detail:** Phase 7+ added focus-visible outlines, `role="alert"` on ErrorBanner, page `h1` via PageHeader, icon-button labels, Settings dialog focus restore/Tab trap, ConfirmButton Escape-to-disarm, toast container `aria-live="polite"`, and a `?` keyboard-help overlay. Remaining gaps (not claimed fixed):
- No full screen-reader audit of every route; React Flow canvas/handles remain weakly announced.
- Some muted/meta text still uses `text-ink-400` (~3.4:1 on white) for non-critical chrome.
- Dropdown/action menus (plugins/templates/builder “more”) are not full ARIA menus with arrow-key roving tabindex.
- ConfirmButton is two-click arming, not a modal dialog.
**Do not claim** full WCAG 2.x AA compliance in product or trust docs.

### UI-RESPONSIVE-1 — Desktop-first console layout (intentional)

**Files:** `graphyn-ui/src/**`  
**Detail:** The Graphyn console is designed **desktop-first**. Narrow/mobile breakpoints collapse the nav drawer and stack some split panes, but Builder canvas density, inspector width, and multi-column library views are optimized for ≥768px. Full responsive parity (touch targets, mobile Builder) is deferred — not a regression.


### SCALE-3 — `run-async` status tracking uses `meta.json` polling

**File:** `app/api/routers/pipelines.py` → `GET /api/v1/runs/{run_id}/status`  
**Severity:** Low  
**Detail:** Correct for single-worker; under high concurrency prefer an in-memory status cache coordinated with `run_control.py`.  
**Workaround:** Poll status at ≥500ms.

### RBAC-1 — Role-based access control not shipped

**Detail:** Auth is shared Bearer / optional local unlock (unauthenticated-dev when `GRAPHYN_API_TOKEN` unset). No per-user roles, tenants, or OIDC. Resource capabilities for the current model are documented in `docs/TRUST_MODEL.md` §2 — that matrix is **not** RBAC.  
**Future:** when multi-user is supported, cross-project access must be prevented by default.  
**Do not claim done** in market/vision docs until implemented.

### UI-BUILD-EACCES-1 — `npm run build` may fail on root-owned `graphyn-ui` artifacts

**Files:** `graphyn-ui/node_modules/.tmp`, `graphyn-ui/dist/`  
**Detail:** If UI was built as root, TypeScript incremental files under `node_modules/.tmp` are not writable.  
**Workaround:** `sudo chown -R "$USER:$USER" graphyn-ui/node_modules graphyn-ui/dist` (or delete those dirs and `npm ci`), then `npm run build`.

### OTEL-1 — OpenTelemetry traces not shipped

**Detail:** Structured logs + NDJSON + Trace UX (artifact→run→worker) exist. Per-node/job OTel spans across distributed workers are P3 (`docs/DISTRIBUTED_EXECUTION.md`).

### EDGE-LOOP-1 — Full Edge Impulse-style device feedback loop not shipped

**Detail:** Edge deploy wizard + `deployment_packager` / `edge_optimizer` exist. Device flash/feedback loop remains product gap (`docs/PRODUCT_VISION.md`).

---

## Resolved (kept for history)

### (resolved 2026-09-15) PROJECT_REVIEW Batches A–E (selected)

- **CI-UI-BUILD-1 / CI-GATE-1:** `scripts/ui_build.sh` cds into `graphyn-ui/`; `.github/workflows/ci.yml` + expanded `ci_smoke.sh`.
- **SEC-INLINE-EXEC-1 / YAML validate:** `assert_no_inline_secrets` on `LocalPythonBackend` / `DistributedBackend.execute`, MCP execute, YAML validate branch.
- **SEC input symlink:** resolve jail by default; Compose sets `GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS=1` so bind-mounted host dataset symlinks browse. Override to `0` to fail closed. `GET /data/inputs` returns `accessible: false` when still blocked.
- **Plugin allowlist prod:** empty allowlist denies remotes when `auth_required()`.
- **ASR/LLM egress:** share `validate_http_egress_url`.
- **SCHED-RACE-1:** flock + claim-before-tick; corrupt `schedules.json` fail-closed.
- **HB lease soft-fail:** heartbeat returns 503 when lease renew fails.
- **audio_exporter / balancer / node_types / WakeWord+Video honesty / doc counts / examples get_backend / IR 1.2 / faster-whisper → `[asr]` extra.**

### (resolved 2026-09-07) DEPS-1 dependency manifest skew

`setup.py` `install_requires` / `extras_require` is authoritative. `requirements.txt` mirrors the default runtime set. Declared direct imports: `httpx`, `packaging`; extras for `mcp`, `redis`, `events` (watchfiles), `vad` (webrtcvad), `hf`, `tf`, `dev`. Gate: `scripts/check_deps.py`. CI smoke: `scripts/ci_smoke.sh` (+ `scripts/ui_build.sh` for the console).

### (resolved 2026-09-07) PLUGIN-001 plugin installation lock is instance-local

`PluginManager` lifecycle ops (install/uninstall/enable/disable) use a process-wide RLock keyed by plugins home plus an exclusive flock on `install.lock`, so separate API-created managers and multi-process writers cannot race on the same install directory. Regression: multiprocess install stress in `unit_test/core/plugins/test_manager.py`.

### (resolved 2026-09-07) PLUGIN-002 plugin registry cross-process lost-update

`PluginStore` RMW uses a process-wide RLock (shared across instances) plus exclusive flock on `registry.lock` for the full load→mutate→atomic replace (same spirit as `DiskStateStore.mutate_queue`). Regression: multiprocess save/update stress in `unit_test/core/plugins/test_store.py`.

### (resolved 2026-09-07) SEC-002 python_code is not a real sandbox

Chose **Option A — trusted workflows only**. UI/docs/metadata no longer call AST-filtered `exec()` a sandbox; filters remain defense-in-depth (`allow_network` default off; `allowed_paths` explicit). Untrusted multi-tenant exposure needs future container isolation (Option B). Trust write-up: `docs/TRUST_MODEL.md`.

### (resolved 2026-09-07) SEC-003 HTTP egress policy

`http_request` / `http_webhook` share `app/core/trust/egress.py`. Default `GRAPHYN_HTTP_EGRESS_MODE=trusted` (no behaviour change). `restricted` blocks private/link-local/loopback/metadata ranges and optional `GRAPHYN_HTTP_EGRESS_ALLOWLIST`. ASR/LLM keep provider clients (documented; not wired). See `docs/TRUST_MODEL.md`.

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
