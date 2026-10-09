# Graphyn full review, Phase 1: summary

| Field | Value |
|---|---|
| Repo / branch | Server-99 `/home/meritech/Desktop/newAudio3`, `test/example-06-plugins` |
| Tip | `6978329f529c59567fdfa4397c5bea5a6b1c9099` ("F18.1: security fix agent-disable + credential org gate") |
| Date | 2026-10-08 (IST) |
| Live stack | `graphyn-api` :8001 healthy (Mode A, auth required, SMTP_DRY_RUN=1 verified); `graphyn-ui` :5173 OK; `graphyn-worker` (s99-ml) container up but **not registered** (Mode B down) |
| Constraints honoured | No product code was modified, committed or pushed. No rebuilds or restarts. FaceRecognition untouched. No real email/SMS/Slack sends. No paid APIs. |
| Honesty rule | Anything stubbed, placeholder, NotImplementedError, fake-data or docs-only = NOT IMPLEMENTED |

## Headline counts

| Area | Result |
|---|---|
| Node types (live) | **36** (35 plugins). All load. All 36 default modes ran live (Working). **11 sub-modes are stubs/placeholders**, 4 cross-cutting defects are Broken, 4 modes Need-external (paid LLMs, real SMTP, S3). |
| Docs claim | 49 node types (NODES.md), 9 packs / 156 manifests (AGENTS.md), 146–156 (platform catalog). Live is 36. |
| File templates | 129 total: **17 Runs**, 38 Validates-only, 3 Needs-external, **71 Invalid** (all invalid ones reference node types from removed packs) |
| Marketplace catalog | 3,032 entries. All materialize, but **only 112 (3.7%) validate**. RAG/TinyML/Vision/WakeWord/Video/MLOps: 0 valid. |
| HTTP API | 214 paths / 259 operations; 27 routers |
| MCP | 79 tools live (README says 77); `list_nodes` verified |
| Requirements (unique P0/P1 = 299) | PASS 41 · PARTIAL 27 · **FAIL 7** · UNVERIFIED 224. Only 17 of 339 SRS rows are referenced by ID anywhere in code or tests. |
| Backend unit tests | 3,381 collected: **2,802 passed / 195 failed / 307 errors** / 77 skipped (heavy tests skipped by default). 452 of the failures/errors come from removed plugins; 27 are real regressions or stale tests. |
| UI tests | Declared `npm test` (also used by CI) **fails** (vitest isn't resolvable). A workaround config runs **528/528** (260 suites). `tsc --noEmit` is clean. |
| Live runs created by the review | 87 runs in project `review-full-2026-10-08` (66 succeeded / 20 failed / 1 cancelled) plus 1 early run outside the project |

## Top 25 findings

| # | Sev | Finding | Evidence (file:line / run) |
|---|---|---|---|
| F-01 | **P0** | **Mode B ArtifactRef materialization is broken.** `root` is assigned only inside the `except` block, so every normal call raises `UnboundLocalError`. All cross-machine path-bearing inputs fail. Introduced in F15 (commit a1c5952). 20 distributed tests fail. | `app/core/distributed/transfer.py:229-244` (raises at :244); test_distributed_transfer ×8, test_modeb_fixes_backend ×6, wave_backend ×2, logical_hash ×3, backend_logs ×1 |
| F-02 | **P0** | **There is no SSRF protection by default for workflow HTTP nodes.** `GRAPHYN_HTTP_EGRESS_MODE` defaults to `trusted`. http_request reached the API on 127.0.0.1:8001 and attempted the cloud metadata IP. This contradicts SRS THREAT-008 / SEC-023 (P0). | `app/core/config.py:609`; runs 883b54d9 (loopback 200), 3670584c (169.254.169.254 attempted, timed out rather than blocked) |
| F-03 | P1 | **Mode B is not operational on the live stack**, yet ENTERPRISE_READINESS says Mode B self-host is "Available". The API was not started with the modeb overlay and the worker can't resolve the API. Readiness reports `worker_count:1` (it counts stale workers) while `GET /workers` returns `[]`. | `docker-compose.modeb.yml`; `app/core/host/readiness.py:229` (`include_stale=True`); `docs/ENTERPRISE_READINESS.md` |
| F-04 | P1 | **`DELETE /projects/{name}/pipelines/{pipeline}` always returns 500.** It imports the non-existent `disable_schedules_for_pipeline`; only `disable_schedules_for_project` exists. Introduced in F13 (3c7d872). | `app/api/routers/projects.py:1050`; `app/core/pipelines/schedules.py`; live: pipeline `review-del-test` cannot be deleted; test_project_pipelines::test_put_get_list_delete |
| F-05 | P1 | **Stub backends and targets report success.** edge_optimizer `tflm/executorch/ultralytics_export` write `BACKEND_STUB.txt` and point users to nodes that don't exist on this branch. deployment_packager `cmsis_pack/arduino/zephyr/pte_bundle` write `PACKAGE_STUB.txt`, and the description doesn't disclose it. | `PluginPackage/Common/edge_optimizer/nodes.py:256, 799-849`; `PluginPackage/Common/deployment_packager/nodes.py:940, 975-976, 1375-1382`; run 50daf859c7ea40818e23448a688616b9 |
| F-06 | P1 | **Inter-node payload contract is broken.** python_code emits `CodeResult{data,metadata}`, but set_map, json_transform, merge, if_switch, prompt_template, output_schema_validate, llm_chat, structured_llm and object_store operate on the wrapper. Only eval_gate and guardrail_filter unwrap it. | `PluginPackage/Common/python_code/nodes.py:231,287`; runs 168c5f5d, a5d2b9bd, 2c1163a5, fbee33c8 |
| F-07 | P1 | **The unit suite is red, yet docs claim "tests green".** The suite wasn't pruned when the RAG/Vision/Video/TinyML/WakeWord/MLOps packs were removed (452 failures/errors), and there are 27 real regressions on top. | `docs/ENTERPRISE_READINESS.md` exit criteria; TESTS.md |
| F-08 | P1 | **There is no separation of duties on prod promotion.** The same (unidentified, legacy-token) actor ran request-prod and then approve-prod, and model `review-full-kws-2026-10-08` is now in prod. | `app/core/mlops/model_registry.py:534-560` (no requester ≠ approver check); `app/api/routers/models.py:187-209` |
| F-09 | P1 | **The template catalog advertises about 2,900 templates that can't run.** Only 112 of 3,032 validate. 71 of 129 file templates (including example dirs 04, 12, 18, 19, 22–28) reference removed node types. The repo's own ≥95% gate test fails. | SWEEP_TEMPLATES.md; `unit_test/...full_catalog_validate_ge_95` (3.69%) |
| F-10 | P1 | **llm_chat defaults to provider `local`, which is an extractive echo, not an LLM.** Users get their input back as "LLM output". | `PluginPackage/Agents/llm_chat/nodes.py:147-151, 191-195`; run c366d9d7 |
| F-11 | P1 | **object_store `put` is a silent no-op** (returns `[]` and the run succeeds) for dict-without-path, CodeResult and CsvTableResult inputs. `_paths_from` ignores `.path` attributes. | `PluginPackage/Common/object_store/nodes.py:82-106, 262-270`; runs c2abc460, b8a6bf98, c3e3c178 (vs 5ff22117, which works with `{path}`) |
| F-12 | P2 | **The run outputs listing regressed**: natural ordering, meta/node paging, key-file prioritisation and use of the artifact inventory (4 failing tests). | `app/core/runs/run_outputs.py` (e.g. :1821) / `app/api/routers/runs.py:725`; tests: backend_review_round2, ui_review_backend_fixes, example06_app_fixes, outputs_inventory |
| F-13 | P2 | **The UI `npm test` (and CI) is broken.** It runs `npx vitest@3.2.4` against a config that imports `vitest/config`, but vitest is not a devDependency. | `graphyn-ui/package.json:10`; `graphyn-ui/vitest.config.ts:1`; `.github/workflows/ci.yml` |
| F-14 | P2 | **Ship packages are unsigned by default, and runtime and artifact format aren't validated.** Package pkg-8095716b4433 has runtime `tflite` but contains `model.keras`, signature `dev-unsigned`. | `app/api/routers/ship.py:77` (`unsigned_allowed=True`); `app/core/mlops/ship_packages.py` |
| F-15 | P2 | **`/experiments/compare` shows no metrics** (`metric_keys: []`) even though runs record `metrics_by_path` (test_accuracy). | `app/core/mlops/experiments.py:133, 286-299` |
| F-16 | P2 | **There is no build provenance.** `BUILD_INFO.json` `git_sha: null` and run meta `git_commit: null`, because the image was built without `GRAPHYN_GIT_SHA`. Sealed-run claims are weakened. | `Dockerfile:41-46`; `docker exec graphyn-api cat /app/BUILD_INFO.json` |
| F-17 | P2 | **segmenter `speaker_turn` is a placeholder** that falls back to silence segmentation, so it is not implemented. | `PluginPackage/Audio/segmenter/nodes.py:91, 427-435` |
| F-18 | P2 | **realtime_inference `ultralytics`/`auto` backends raise NotImplementedError for audio input**, even though they are offered in the backend enum. | `PluginPackage/Common/realtime_inference/nodes.py:98, 446` |
| F-19 | P2 | **csv_table can't read bundled dataset CSVs.** `datasets/input/*` entries are symlinks into `examples/`, and they're rejected as "outside the workspace" (or the path is doubled to `workspace/workspace/...`). dataset_ingest reads the same files fine. | `PluginPackage/Common/csv_table/nodes.py` (path resolution); runs 131a8e08, 8da9c3d9 (fail) vs 60772587 (artifact CSV ok) |
| F-20 | P2 | **Actor attribution is weak.** Runs record `actor: unidentified` / `legacy_token`, `legacy_token_disabled:false`, and OIDC is off. The audit trail can't attribute actions. | `/system/auth-status`; run meta |
| F-21 | P2 | **Docs drift on counts**: NODES.md and PluginPackage/ARCHITECTURE.md say 49 node types, AGENTS.md says 9 packs / 156 manifests, PLUGIN_GUIDE says 20/48, README says 77 MCP tools. Live: 36 types, 35 plugins, 79 tools. | `docs/NODES.md`, `AGENTS.md`, `README.md`, `docs/PLUGIN_GUIDE.md` |
| F-22 | P3 | **Plugin manifests and typing**: 8 plugin.toml files have no `runtime` key (7 Audio plus deployment_packager). Audio ports are `builtins.list` and Common/Agents ports are `object`, so wire-time type checking does nothing. | `PluginPackage/Audio/*/plugin.toml`, `PluginPackage/Common/deployment_packager/plugin.toml`; SWEEP_PLUGINS.csv |
| F-23 | P3 | **structured_llm `local_heuristic` produces fake extraction**: the full input text goes into every string field. | run 20a5ba9f / b1b535db |
| F-24 | P3 | **python_code's sandbox builtins lack standard exceptions** (`ValueError` etc.), so ordinary user code fails with NameError. | `PluginPackage/Common/python_code/nodes.py:249-262`; run 386a3819 |
| F-25 | P3 | **UX and honesty nits**: the if_switch expression must use `output[...]`, but the UI hint implies bare names. Marketplace seeds validate but fail at run time on empty required config. merge `append` of two dicts silently overwrites keys (`merge/nodes.py:92-93`). 4 UI route builders are typed `never`. `graphyn --help` boots the plugin manager, and the host CLI registry is stale (48 types vs 36 live). | runs 0365bb5a, fd8bdb40, 59571860; `graphyn-ui/src/routes/paths.ts` |

Correction to the earlier working notes: node-level **retry works**. Run f6e79faf logs "retrying (attempt 2/2)". It isn't listed as a defect.

## Verified working (highlights)

- Auth fail-closed (401). Secrets are never returned. The IR secret scanner rejects secrets (422 `secret_in_ir`). Run-id traversal returns 404. Secrets and credentials dirs are 0700.
- Run lifecycle: pause, resume, cancel, replay (7aedc1c0), verify, provenance, debug-report, compare/diff.
- HITL `awaiting_approval` → API approve → resume (bd929e4f). IR 1.3 `on_error` route (d6630a0e) and retry (f6e79faf).
- Full audio chain (6b4e8412, 1,200 clips → 2,518 wavs). Training chain: dataset_builder → model_builder → trainer → evaluator → edge_optimizer tflite int8 → deployment_packager edge (28dadbee). realtime_inference on the tflite model (78c0a2a5).
- llm_chat and structured_llm against local Ollama (tinyllama): real completions. credential_probe for ollama and smtp (redacted). send_email is dry-run only.
- MCP stdio: 79 tools, `list_nodes` OK. UI: 528/528 vitest, tsc clean, SPA fallback and /api proxy OK.

## Not verified, and why

| Item | Reason |
|---|---|
| Any Mode B execution (worker claim, placement, artifact transfer live) | The live Mode B stack is down. Bringing it up needs `docker compose -f docker-compose.yml -f docker-compose.modeb.yml up` (a container recreate), which is outside the no-restart constraint. The code path is broken anyway (F-01). |
| `heavy` pytest markers | Skipped by default. They need `GRAPHYN_RUN_HEAVY=1` and long training runs. |
| Paid LLM providers (openai_compat / anthropic / gemini), S3 object_store, real SMTP send | Prohibited (paid or outbound). Marked Needs-external. |
| OIDC login | Disabled on this stack. |
| UI manual click-through (FR-* UI requirements) | Not performed. Only vitest/tsc/HTTP checks were done. 224 SRS P0/P1 IDs remain UNVERIFIED. |
| Plugin install/uninstall, /system/cleanup, schedule firing, inbound webhook delivery | They would mutate the live registry or data, or need waiting on schedules. Not exercised. |
| `vite build` | Rebuild prohibited. |

## Review artifacts created on the live stack (cleanup list)

1. **Project** `review-full-2026-10-08` (created via API). Dir: `workspace/datasets/output/review-full-2026-10-08/` (contract.json, project.json, spec.md, taxonomy.json, `audio_export/v1` with 2,518 wavs, `tpl/<slug>/…` exporter outputs).
2. **Runs**: 87 in project `review-full-2026-10-08` (`GET /api/v1/runs?project=review-full-2026-10-08`), including replay 7aedc1c073e94e26bc6ed10ac736429d. One early run, `78c393874e9e4b67995a1ed39187ff6b` (graph `review-smoke-python-code`), sits outside the project. Run dirs are under `workspace/runs/<id>/`.
3. **Run artifacts**: `workspace/artifacts/review-full-2026-10-08/`, `workspace/artifacts/review-full-*/` (per graph name), `workspace/artifacts/review-smoke-python-code/`. Object-store and CSV files live inside these run dirs.
4. **Project pipeline** `review-del-test`. It can't be deleted via the API because of F-04; remove its pipeline files manually or after the fix.
5. **Registered model** `review-full-kws-2026-10-08` (staging and **prod** stage).
6. **Ship package** `pkg-8095716b4433` (Idempotency-Key `review-full-ship-1`).
7. **HITL decision files**: `workspace/artifacts/agents/hitl_approve/decisions/` for runs bd929e4f35ad4abf9983975feea429ee and a111938f65ce40f2bc7431423e94ba55.
8. **Metering** `run.started` events for the runs above (append-only store).
9. **Host scratch**: `/tmp/rv/` (evidence JSON, scripts, mcphome/mcpws, vt/ vitest workaround with cache, clihome).
10. **Untracked review docs**: `docs/reviews/full/` (this directory), not committed.

## Deliverables in this directory

INVENTORY.md · CHECKLIST_TECH_STACK.md · CHECKLIST_REQUIREMENTS_LOGIC.md · CHECKLIST_PLUGIN.md · CHECKLIST_TEMPLATE.md · SWEEP_PLUGINS.csv/.md · SWEEP_TEMPLATES.csv/.md · TESTS.md · SUMMARY.md
