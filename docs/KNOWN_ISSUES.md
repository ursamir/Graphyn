# Limitations & known issues

> Current platform limitations. Remove entries when fixed; add newly discovered gaps here.

---

## Resolved recently

### (resolved 2026-10-07) REVIEW-F10-MODEB — F10 + Mode B enterprise + ArtifactRef A+C review findings

Found in a deep review of commits `81decad` (F10) and `d4b87c7` (Mode B enterprise, ArtifactRef A+C, Editor fixes). Regression tests: `unit_test/core/test_distributed_review_fixes.py`.

- **Worker identity:** worker tokens are confined to the worker protocol allowlist (`worker_scope_allows`) on the REST API, and MCP rejects them (`forbidden`). Unbound worker tokens fail closed unless an mTLS id is present or `GRAPHYN_WORKER_UNBOUND_TOKENS=1`. The `X-Graphyn-Mtls-Worker-Id` test header never counts as verified and is ignored when `GRAPHYN_ENV` is production, prod or staging. With mTLS enabled, worker mutations without a client certificate get 403.
- **Register:** self-registration can no longer set admin fields (`allowed_plugins`, `plugin_hashes`, `trusted`, `max_claimed`, `usage_*`). A new worker is trusted only when trust is not required. `plugin_hashes` is hidden from non-operators.
- **Blobs:** a worker may GET only its job's input blobs, explicit `blob_grants`, or its own output keys. Signing uses only `GRAPHYN_BLOB_SIGNING_KEY` (no API-token fallback). Signed URL TTL is capped at 3600 s. Workers refuse absolute blob URLs outside the control origin, so the bearer token is never sent to a foreign host.
- **Jobs:** job events and `GET /jobs/{id}` are restricted to the claiming worker, and events return 409 unless the job is claimed or running. Events carry a monotonic `_seq`, and the control plane deduplicates by `_seq` after the event cap.
- **Quotas:** quota checks use the effective pool (`job.pool` plus `claim_pools`), and usage counters update atomically (`registry.increment_usage`).
- **Validation:** VAL-PLACE findings now also apply to remote-only node types.
- **Worker spool:** each worker gets its own spool directory, writes are atomic, spooled job ids stay in `active_job_ids`, and the spool is flushed before register.
- **mTLS serving:** `mtls_serve` forces `h11` with SSL. A worker refuses an `http://` control URL while mTLS is on. The new overlay is `docker-compose.modeb-mtls.yml`.
- **Blob encryption:** the GBE2 envelope is AES-256-GCM with an HKDF-derived key and a key id; rotation uses `GRAPHYN_BLOB_ENCRYPTION_OLD_KEYS`. GBE1 blobs are still readable.
- **ArtifactRef:** directory packing is deterministic and content hashes cover the real file bytes. Hydration is digest-checked and extracts to a temp dir before `os.replace`. Empty files and hardlinks are handled, and unsafe tar member names are rejected.
  - Model, deployment and TFLite serializers write v2 manifests with a `path_map`, so roles round-trip.
  - `run_outputs` and `run_summary` read the role manifests. Every interface calls `register_builtin_serializers()`.
  - Removed the stale sibling `model.keras` probes and the deployment fallback to the labels dir. Added the missing `csv_table` ArtifactRef import.
- **Editor (UI):** the last-run poller starts only after a stream handoff, reports followed runs, stops on `missing` and backs off on `unknown`. A stream error triggers one reconcile.
  - `openPipelineInEditor` is workspace-scoped.
  - Run-time stamping no longer rewrites a user-picked legacy `workspace/artifacts/<slug>/dataset/...` ingest path; only template loads migrate it, and the inspector flags it.
- **Datasets (UI):** "Load more" is keyed to the current selection, and the "All" split chip is always reachable with a count from the unfiltered listing. The "Also in the library" panel can be collapsed.
  - Templates no longer rewrite another view's URL after an await.
  - Malformed `%` escapes in a URL no longer throw.
- **Workers (UI):** the ACL form validates `max_claimed`, explains a 403, does not invent a Trusted badge when `trusted` is not reported, and the drawer follows polling.

### (resolved 2026-10-01) UI-REVIEW-BACKEND — orphan schedules, run-output attribution, cancel events

Found in a live console review. These are source fixes; a running API container needs a rebuild to pick them up.

- **Orphan schedules** (`app/core/pipelines/schedules.py`, `ProjectManager.delete`): deleting a project disables its schedules (`orphaned: true`, `disabled_reason`). A permanent start error (`Project not found` / `Pipeline '…' not found`) auto-disables the schedule instead of failing every hour. `GET /system/schedules?project=` filters by project.
- **Run outputs** (`app/core/runs/run_outputs.py`): ProjectManager metadata under `datasets/output/<project>/` (`project.json`, `spec.md`, `pipelines/`, `snapshots/`, …) is no longer attributed to `audio_exporter_*`. Exporter configs with `version_tag` attribute only `<dir>/<version_tag>/`. Truncation is visible through the `X-Graphyn-Outputs-Truncated` header, `?with_meta=1` (`truncated_by_node: {node: {shown, total}}`), and `?node_id=&limit=&offset=` paging. The 400 cap is filled run-level → models/metrics/small summaries → bulk files, round-robin per node, and source-node (ingest) input files are not listed as outputs (`inputs_by_node`).
- **Notifications**: cancelled runs now emit `pipeline_cancelled` (webhook, email, in-app `warning`). Before, nothing was emitted, even though the map pointed `cancelled` at `pipeline_failed`.
- **Credentials**: responses add `secret_fields_set: {field: bool}`, so `""` (never set) and `"***"` (set, redacted) are no longer ambiguous.
- **Readiness**: the new `catalog` section (`bundled_plugins`, `installed_plugins`, `partial_catalog`, `warnings`) is informational and does not change `ready`.
- **Templates**: starter templates carry `metadata.title`. Template summaries and example discovery expose a unique `title`, and `ex-NN-*` copies get an `(example NN)` suffix.
- **Run → saved pipeline**: `POST /pipelines/run` never writes `pipelines/*.graph.json` (regression test added). The file seen in the review came from the console's "open template in workspace" flow, which PUTs the template as a project pipeline.
- **503 on /pipelines/run**: the only server-side source is `draining` (shutdown). It now carries `retryable: true` and `Retry-After: 30`. No 503 appeared in the API or nginx logs for that session.

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

### UX-DATASETS-2026-10-05 — Dataset counts / naming gaps found in the UI walkthrough

- **EXPORT-SILENT-SKIP** — `audio_exporter` skips samples with empty data or an invalid sample rate with only a log warning. Run lineage reports the input count (e.g. 3,709 clips) while the version holds 3,705 files; nothing in the run or Datasets says 4 were dropped. Surface a `skipped` count in the node output / run summary. (The warnings also land in the collapsed "N updates" group in run Logs, so even the log trail is easy to miss.)
- **RUN-OUTPUTS-BASENAMES** — Runs → Run outputs lists files by basename only. Worst case seen: the edge-optimizer step listed **six identical `labels.txt` rows** (different subdirs). Mitigated 2026-10-05: rows with a colliding basename now show their parent dir (`file · 22 B · int8/`). Step summaries ("Got manifest.json, … +4 more") still use bare basenames; show paths relative to the step's output folder there too.
- **MODEL-DATASET-NAME** — Models → Made from shows `Load prepared dataset · path · <hash> · 3,708 files`: no dataset name/version link, and the count includes `labels.csv` / `lineage.json` / `metadata.json` (Datasets now reports 3,705 data files). Third count for the same data: run banner "3,705 clips", step 1 "3,706 audio clips", Made-from "3,708 files".
- **INGEST-COUNT-OFF-BY-ONE** — prepare run header says “Used 1,200 clips from speech-commands” while step 1 reports “1,201 audio clips” (Inputs lists 1,200 files).
- **SHIP-EXISTING-PACKAGE** — Ship wizard step 3 only enables Download after *this session's* package run; a package built earlier from the same model (visible under Models → Used in) is not detected, so users re-run packaging or hunt through the old run's outputs. Offer "a package for this model already exists (built <time>) — Download" when one is found.
- **RUN-ROW-EMPTY-METRIC-SLOT** — Runs list rows for pipelines without metrics render a stray blank line between status and age (`Done\n \n3h ago`) — a metric placeholder renders empty instead of being omitted.

### AUDIT-2026-10 — Backend contract gaps (outputs inventory follow-on)

Found by a wider backend logical-gap audit after the generic `publish_files` / `file_tree` / `list_files` redesign. Not style issues — ownership and runtime holes.

#### AUDIT-ISOLATED-PUBLISH-1 (P0) — `publish_files` lost across isolated workers — **FIXED 2026-10**

Worker envelope + host `IsolatedResult` / `Node.accept_published_file_trees`. See `docs/WORKLOG_OUTPUTS_AND_VIEWERS.md`.

#### AUDIT-PUBLISH-ADOPTION-1 (P1) — Only `audio_exporter` calls `publish_files` — **PARTIAL 2026-10**

`evaluator` + `edge_optimizer` now publish; other path writers (trainer, packagers, …) still pending.

#### AUDIT-CACHE-PUBLISH-1 (P1) — Cache hits skip `file_tree` registration

**Evidence:** [`app/core/execution/executor.py`](app/core/execution/executor.py) / orchestrator drain `publish_files` only when `not cache_hit`. Cached nodes re-emit port artifacts but not path inventories for the new run_id.  
**Fix direction:** Persist published-tree summary in cache payload, or re-register `file_tree` from cache metadata on hit.

#### AUDIT-RUN-OUTPUTS-DEAD-1 (P1) — Domain walk / audio heuristics still in `run_outputs`

**Evidence:** [`app/core/runs/run_outputs.py`](app/core/runs/run_outputs.py) still defines `_DATASET_AUDIO_SUFFIXES`, `_DATASET_META_NAMES`, `_collect_artifact_data_dir` / summarize helpers (`labels.csv` / wav summarization, ~76–82, ~493–569, ~788–838) plus ProjectManager meta / `version_tag` layout sniffing (~109–124, ~900–914) while primary listing uses `handler.list_files`.  
**Risk:** Listing contract and implementation disagree; easy to re-wire scavenger paths.  
**Fix direction:** Delete unused helpers; attribute only via ArtifactRecord / `publish_files`.

#### AUDIT-PATH-RESOLVE-DUP-1 (P2) — `workspace/` path normalisation triplicated

**Evidence:** Same “strip `workspace/` then `project_dir()`” logic in `app/core/artifacts/file_tree.py`, `app/core/runs/run_outputs.py` (`_resolve_artifact_data_dir`), `app/core/paths/workspace_paths.py`.  
**Risk:** Divergent jail/edge-case behaviour (absolute vs relative, symlink).  
**Fix direction:** One helper in `app.core.paths` used by all three.

#### AUDIT-MCP-INPUTS-WALK-1 (P2) — MCP input listing full-tree `rglob` — **FIXED 2026-10**

**Was:** [`app/mcp/handlers/workspace.py`](app/mcp/handlers/workspace.py) `list_data_inputs_handler` counted with unbounded `path.rglob("*")`.  
**Fix:** Shared `count_files_budgeted` in [`dataset_inputs.py`](app/core/mlops/dataset_inputs.py) (cap 50k); MCP + `label_counts` use it. `label_counts` also caches under `datasets/input/.graphyn_inventories/<label>.json` (mtime signature) so large trees are not re-walked on every list.

#### AUDIT-DATA-INVENTORY-1 (P0) — Data API scavenges `labels.csv` + `rglob("*.wav")` — **FIXED 2026-10**

**Was:** Output detail fell back to wav-tree scavenges; `/stats` 404'd without `labels.csv`.  
**Fix:** Prefer `manifest.json` inventory for samples and stats when `labels.csv` is absent (`source: "manifest"`); no `*.wav`-only walk.

#### AUDIT-RUN-DIR-JAIL-1 (P1) — `run_control` resolves run dirs without the jail used by `runs`

**Evidence:** [`app/api/routers/run_control.py`](app/api/routers/run_control.py) `_run_dir` (~48–49) vs jailed `_run_dir` in [`app/api/routers/runs.py`](app/api/routers/runs.py); MCP artifacts handler also has its own resolve.  
**Impact:** Same semantic, divergent safety — control endpoints weaker than history/download.  
**Fix direction:** One shared `safe_run_dir()` for API + MCP.

#### AUDIT-CAPABILITY-DUP-1 (P1) — MCP reimplements `resolve_capability`

**Evidence:** Local `_resolve_capability` in [`app/mcp/handlers/discovery.py`](app/mcp/handlers/discovery.py) (~105–143) vs `app.core.host.registry_runtime.resolve_capability`.  
**Impact:** Capability field sets can drift from IRCapabilityMetadata defaults (AGENTS.md: import from `registry_runtime`).  
**Fix direction:** Call `registry_runtime.resolve_capability` only.

#### AUDIT-PROMOTE-PRESENCE-DUP-1 (P1) — Duplicate “has artifacts?” walks

**Evidence:** Local `_dir_has_file` in [`app/api/routers/runs.py`](app/api/routers/runs.py) promote (~471–485) and `run_dir_has_artifacts` in [`app/core/paths/workspace_paths.py`](app/core/paths/workspace_paths.py) (~739–751).  
**Fix direction:** Promote calls `run_dir_has_artifacts` only.

#### AUDIT-DOMAIN-IN-CORE-TEMPLATES-1 (P1) — Materializer / slug encode audio layouts

**Evidence:** `AudioSample` + speech-commands `.wav` seeds in [`app/core/templates/pipeline_template_materializer.py`](app/core/templates/pipeline_template_materializer.py); `speech-commands-e2e` special-case in [`app/core/paths/workspace_paths.py`](app/core/paths/workspace_paths.py) `artifact_slug`.  
**Fix direction:** Seed/alias maps from template or pack metadata, not hardcoded platform path logic.

#### AUDIT-SUFFIX-ALLOWLIST-DUP-1 (P2) — Three competing “path is a file” suffix sets

**Evidence:** `run_outputs.ALLOWED_SUFFIXES`, `write_paths._FILE_SUFFIXES`, `workspace_paths` suffix set — e.g. `.flac` only in some.  
**Fix direction:** Single shared helper under `app.core.paths`.

#### AUDIT-PUBLISH-REGISTER-DUP-1 (P2) — `file_tree` drain duplicated in executor + orchestrator

**Evidence:** [`app/core/execution/executor.py`](app/core/execution/executor.py) (~393–414) and [`orchestrator.py`](app/core/execution/orchestrator.py) (~830–852).  
**Fix direction:** One `register_published_file_trees(...)` helper.

Source audit: [Audit scavenger smells](5b1cb9a4-f321-453d-a87b-0b623af9f247) (LG-01..LG-15; domain `project_manager` wav walks left as in-domain).

---

## Open — Cancel fencing / runtime integrity (AUDIT-2026-10-B)

From [Audit runtime failures](ebaf6289-81f1-4bde-bd4a-b03a942034ff). Durable `cancel_requested` exists, but status APIs / artifact commit / offline ack / MCP do not always treat it as truth. Not restating DIST-CANCEL-1 (mid-`process()`).

#### CANCEL-ARTIFACT-THROTTLE (P1) — Artifact commit uses throttled `is_cancelled`

**Evidence:** [`run_journal.py`](app/core/runs/run_journal.py) `is_cancelled` (~445–459) can return `False` for ≤0.5s without probing; `register_artifact` (~586–603) gates on that, and the meta fallback checks `status == cancelled` not the marker. Marker-only cancel can still commit artifacts.  
**Fix:** `register_artifact` / cancel_check → `poll_cancelled()` (or always honour marker).

#### CANCEL-STATUS-MARKER-BLIND (P1) — Status APIs ignore `cancel_requested`

**Evidence:** [`run_status.py`](app/core/runs/run_status.py) `load_durable_status` (~140–154) reads only `meta.json`; used by runs + run_control. Marker present + meta still `running` → Observe/control treat run as live.  
**Fix:** Teach `load_durable_status` to treat marker as cancelled (or pending-cancel).

#### CANCEL-OFFLINE-META-RACE (P1) — Offline cancel meta RMW unlocked

**Evidence:** [`run_control.py`](app/api/routers/run_control.py) (~189–210) unlocked meta rewrite; journal `_write_meta_field` uses in-process lock only. Concurrent executor write can restore `running`.  
**Fix:** Flock meta; CAS “first terminal wins” across processes.

#### CANCEL-OFFLINE-FALSE-ACK (P1) — Offline cancel acks even if durable writes fail

**Evidence:** [`run_control.py`](app/api/routers/run_control.py) (~183–188, ~219–233) swallows marker/meta errors then returns `{"status":"cancelled"}`.  
**Fix:** Fail HTTP unless marker (and ideally meta) write succeeded.

#### MCP-CANCEL-NO-OFFLINE (P1) — MCP cancel only works for in-process active runs

**Evidence:** [`mcp/handlers/run_control.py`](app/mcp/handlers/run_control.py) (~110–119) vs API offline path (~170–233). Queued/other-process → `run_not_active`; no marker.  
**Fix:** Mirror API offline durable cancel in MCP.

#### CACHEABLE-FAIL-OPEN (P1) — Registry errors treat nodes as cacheable

**Evidence:** [`cache_rescope.py`](app/core/execution/cache_rescope.py) `node_is_cacheable` (~45–59) `except: return True`.  
**Fix:** Fail closed (`return False`).

#### RUN-META-WIPE-ON-BAD-READ (P1) — Corrupt meta → `{}` then one-field rewrite

**Evidence:** [`run_journal.py`](app/core/runs/run_journal.py) (~126–135, ~202–219).  
**Fix:** Fail closed on corrupt meta; never replace full meta with a single field without merge under flock.

#### ARTIFACT-FORBIDDEN-SWALLOWED (P2) — `ArtifactCommitForbidden` does not fail the node

**Evidence:** orchestrator/executor `except Exception` around `register_artifact` logs and continues.  
**Fix:** Re-raise / fail node on `ArtifactCommitForbidden`.

#### CANCEL-CHECK-THROTTLED (P2) — Mode A cancel_check uses throttled probe

**Evidence:** orchestrator wires `run.is_cancelled` not `poll_cancelled` for isolated kill (~505–511).  
**Fix:** Use `poll_cancelled` for cancel_check / node boundaries.

#### WEBHOOK-CONFIG-RMW (P2) / PROPOSAL-CROSS-PROC (P2) — JSON stores without cross-process lock

**Evidence:** `notify/webhook.py` save; `agentic/proposals.py` thread lock only.  
**Fix:** Same atomic+flock pattern as schedules (STORE-CONCURRENCY).

#### MCP/REPLAY-MARK-FAILED-SILENT (P2) — Swallowed `mark_failed` can leave ghost running

**Evidence:** MCP execution done-callback / artifacts replay (~170–182 / ~209–218).  
**Fix:** Surface durable terminal write failures; retry or escalate.

---

### TEST-SUITE-1 — Full pytest suite residuals (2026-09-16)

**Progress:** The 2026-09 correctness pass landed. The suite moved from 92 failed and 49 errors toward green. Remaining failures are mostly ML model-download, optional-dependency smoke tests, and environment-only items. The CI gate is the full `unit_test/` suite (`scripts/ci_smoke.sh`, Python 3.12).
**Known residuals (2026-10-07, also failing before the F10 review fixes):**
- `unit_test/api/test_backend_review_round2.py::test_outputs_truncate_in_natural_order` , `unit_test/api/test_ui_review_backend_fixes.py::test_outputs_with_meta_and_node_paging` and `unit_test/api/test_outputs_inventory.py::test_listing_uses_artifact_inventory_not_labels_csv` — fixtures predate the index-only run-output listing (they write files without an ArtifactStore inventory).
- `unit_test/core/plugins/test_dep_isolation.py::test_isolated_process_uses_worker_not_host` — environment-dependent isolated-venv probe.
- `unit_test/plugins/*` (mlops / proposed nodes) and `test_example_templates` need installed plugins; skip under `GRAPHYN_SKIP_PLUGIN_LOAD=1`.

### DEEP-REVIEW-P0 — Verification loop + critical defects (2026-09-16) — **CLOSED**

**Fixed in-tree (complete pass):** P0-1..P0-5; P1-1..P1-28; P2-1..P2-50; P3-1..P3-35 except host-only **P3-32** (`UI-BUILD-EACCES-1` below — needs local `sudo chown`). P3-22 CLI coverage expanded in `unit_test/cli/test_cli.py` (runs/secrets/artifacts/inspect). Large-module splits P3-13/14/18 remain incremental (helpers extracted; full god-module split deferred).

**Still open:** none of that correctness pass. Residual suite flakes and P3-32 ownership are tracked above / as UI-BUILD-EACCES.

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

### DIST-ORPHAN-1 — Mode B run stays `running` after a control-plane restart (F19, 2026-10-08)

If the API process dies while a worker holds a job, the restarted control plane keeps the job but no backend thread owns the run any more; the run stays `running` until the abandoned-run reconcile (`GRAPHYN_STALE_RUN_HOURS`, at startup or `POST /system/cleanup`) or `POST /runs/{id}/cancel`. Seen live with run `35d43e94` (cancelled by hand).

### SEG-DIAR-1 — `speaker_turn` diarization is classical, not neural (F19, 2026-10-08)

Offline MFCC + pitch embeddings with agglomerative clustering. No overlapping-speech handling; automatic speaker count can over-split a single voice — set `num_speakers` when known.

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

### MODEB-ON-ERROR-1 — IR `on_error` / `retry` not applied on Mode B **remote** workers

**Files:** `app/core/distributed/backend.py` (`_run_local_node`, `NodeJob`), `docs/PIPELINE_EXECUTION.md` (IR 1.3)  
**Detail:** Control-plane **local** nodes in `DistributedBackend` now stamp IR `on_error` / `retry` and skip caching routed failures (same as Mode A). Remote workers still do not receive those policies on `NodeJob`, so a node placed on a worker may still fail the job instead of routing/continuing.  
**Workaround:** Keep error-routing nodes on `placement: local` / Mode A, or use explicit `error_catch` / branch edges until `NodeJob` carries the policies.

### MODEB-VERSION-SKEW-1 — Mixed-version Mode B workers reject new protocol fields

**Files:** `app/core/distributed/models.py` (`WorkerInfo`, `NodeJob`, `JobResult` use `extra="forbid"`)  
**Detail:** New fields (`NodeJob.finished_at`, `NodeJob.result_consumed_at`, `JobResult.output_sha256`, heartbeat `active_job_ids`) are rejected by older workers/control planes with a validation error.  
**Workaround:** Upgrade the control plane and every worker together (same commit). Drain workers before upgrading.
**2026-10-07:** `NodeJob.blob_grants` / `NodeJob.claim_pools` and the GBE2 blob envelope add to the skew: upgrade together. GBE1 blobs stay readable; GBE2 needs the new code to decrypt.

### MODEB-SPOOL-PARTIAL-1 — Worker spool replays only `complete`

**Files:** `app/core/distributed/worker_spool.py`, `app/cli/cmd_worker.py`
**Detail:** `WorkerSpool.enqueue_blob` / `enqueue_events` exist but the worker only spools `complete` results during a control-plane outage. Output blobs are uploaded before `complete`, so a blob upload failure still fails the job, and job events emitted while disconnected are dropped.
**Workaround:** Keep control-plane outages shorter than the lease TTL; the job is reclaimed and rerun otherwise.

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
- ~~Muted text `text-ink-400` ~3.4:1 on white~~ — fixed in F19: ink-400 `#5e7387` (4.9:1 on white, 4.5:1 on ink-50), ink-500 `#506679`; enforced by `graphyn-ui/src/lib/contrast.test.ts` (palette + no muted text on dark ink surfaces). Colour contrast of other tokens is not audited.
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

### RBAC-1 — Role-based access control (local users) — **resolved (F11)**

**Was:** shared Bearer only; no per-user roles.  
**Now:** local users + global roles + per-project membership ACL (`app.core.trust.users` / `rbac`) and Access UI. Shared bearer remains break-glass.  
**Still open:** multi-org tenancy — see **ORG-1**. OIDC/SSO — see Wave 1 in `docs/ENTERPRISE_READINESS.md` (shipped when `GRAPHYN_OIDC_ENABLED=1`).

### ORG-1 — Multi-tenant org / workspace boundaries — **resolved (F13 / Wave 2)**

**Was:** no `org_id`; project membership only.  
**Now:** orgs + membership roles + active org; projects/credentials/workers scoped; default-org migration; Access → Organizations.  
**Still open:** full SaaS productization (Checkout/invoices UI); Wave 3 ships quota + metering + webhook seam.

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

`http_request` / `http_webhook` share `app/core/trust/egress.py`. **Update F19:** default is now `restricted` (SSRF-safe, IP-pinned, redirects re-checked; trusted internal targets via `GRAPHYN_HTTP_EGRESS_INTERNAL_ALLOW`); LLM providers, URL ingest, SMTP and S3 endpoints are wired too. Original note: default `GRAPHYN_HTTP_EGRESS_MODE=trusted`. `restricted` blocks private/link-local/loopback/metadata ranges and optional `GRAPHYN_HTTP_EGRESS_ALLOWLIST`. ASR/LLM keep provider clients (documented; not wired). See `docs/TRUST_MODEL.md`.

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
