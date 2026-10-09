# Inventory — Graphyn (full review, Phase 1)

- Repo: `/home/meritech/Desktop/newAudio3` on Server-99 · branch `test/example-06-plugins` · tip `6978329f529c59567fdfa4397c5bea5a6b1c9099` ("F18.1: security fix agent-disable + credential org gate") · reviewed 2026-10-08 IST.
- Live stack at review time: `graphyn-api` :8001 (healthy, Mode A — `GRAPHYN_BACKEND` local; auth required), `graphyn-ui` :5173 (SPA + /api proxy OK), `graphyn-worker` (s99-ml) container up but **not registered** (API not recreated with `docker-compose.modeb.yml`; worker cannot resolve the API on the modeb network).
- Method: static walk of the tree + live OpenAPI + live registry + live MCP stdio + scripted runs. Scratch evidence in `/tmp/rv` on Server-99.

## Backend (`app/`, 276 .py files)

| Core package | Files | LOC |
|---|---|---|
| agentic | 2 | 483 |
| artifacts | 7 | 3256 |
| credentials | 7 | 1172 |
| distributed | 16 | 8543 |
| execution | 16 | 6016 |
| host | 4 | 587 |
| ir | 8 | 1682 |
| ml | 3 | 878 |
| mlops | 7 | 3740 |
| nodes | 14 | 3216 |
| notify | 4 | 687 |
| paths | 3 | 1389 |
| persist | 4 | 237 |
| pipelines | 6 | 2245 |
| plugins | 17 | 6935 |
| runs | 25 | 10758 |
| templates | 3 | 1206 |
| trust | 14 | 5982 |
| utils | 2 | 88 |
| (kernel *.py) | 5 | 1985 |

## HTTP API

- Live OpenAPI: **214 paths / 259 operations**. Routers: 27 files, 250 route decorators + 2 direct routes in `app/api/main.py` (OpenAPI count is higher because some routes register multiple methods).

| Router | Routes | Prefix/tags | LOC |
|---|---|---|---|
| agents.py | 7 | tags=["agents"] | 186 |
| artifacts.py | 4 | prefix="/artifacts", tags=["artifacts"] | 247 |
| auth.py | 15 | tags=["auth"] | 469 |
| billing.py | 1 | tags=["billing"] | 87 |
| compliance.py | 4 | tags=["compliance"] | 98 |
| credentials.py | 8 | prefix="/credentials", tags=["credentials"] | 208 |
| data.py | 16 | prefix="/data", tags=["data"] | 1230 |
| experiments.py | 3 | prefix="/experiments", tags=["experiments"] | 64 |
| gates.py | 2 | prefix="/runs", tags=["runs"] | 94 |
| hooks.py | 4 | tags=["hooks"] | 288 |
| identity.py | 1 | tags=["identity"] | 64 |
| ingest.py | 4 | prefix="/ingest", tags=["ingest"] | 188 |
| models.py | 6 | prefix="/models", tags=["models"] | 216 |
| nodes.py | 7 | tags=["nodes"] | 196 |
| orgs.py | 12 | tags=["orgs"] | 324 |
| outputs.py | 1 | prefix="/outputs", tags=["outputs"] | 130 |
| pipeline_templates.py | 9 |  | 558 |
| pipelines.py | 3 | prefix="/pipelines", tags=["pipelines"] | 650 |
| plugins.py | 10 | prefix="/plugins", tags=["plugins"] | 526 |
| projects.py | 52 | prefix="/projects", tags=["projects"] | 1079 |
| proposals.py | 5 | prefix="/proposals", tags=["proposals"] | 156 |
| run_control.py | 3 | prefix="/runs", tags=["run-control"] | 281 |
| runs.py | 21 | prefix="/runs", tags=["runs"] | 963 |
| ship.py | 6 | prefix="/projects", tags=["ship"] | 362 |
| system.py | 18 | prefix="/system", tags=["system"] | 575 |
| trace.py | 5 | tags=["trace"] | 178 |
| workers.py | 23 | tags=["distributed"] | 1112 |

Operations by OpenAPI tag: projects 52, runs 23, distributed 23, auth 20, system 18, data 16, pipelines 12, orgs 12, plugins 10, credentials 8, nodes 7, agents 7, models 6, ship 6, trace 5, proposals 5, hooks 5, ingest 4, artifacts 4, compliance 4, run-control 3, experiments 3, billing 2, untagged 2, outputs 1, identity 1.

## Distributed (Mode B) — `app/core/distributed/` (16 modules, 8,543 LOC)

| Module | LOC |
|---|---|
| __init__.py | 68 |
| backend.py | 1483 |
| blob_crypto.py | 212 |
| enrollment.py | 243 |
| models.py | 163 |
| mtls.py | 596 |
| placement.py | 243 |
| queue.py | 2089 |
| quotas.py | 402 |
| registry.py | 464 |
| security.py | 173 |
| slots.py | 85 |
| store.py | 792 |
| transfer.py | 1042 |
| worker_progress.py | 108 |
| worker_spool.py | 380 |

## MCP server

- `register` calls: 80; live stdio `tools/list` returned **79** tools (`accept_proposal` is gated/conditional). `list_nodes` call verified live.
- Docs drift: README says 77 tools, AGENTS.md/MCP_SERVER.md say 79.
- Tools: `list_nodes`, `generate_graph`, `validate_graph`, `get_graph_schema`, `get_graph_capability_summary`, `get_event_schema`, `execute_pipeline`, `inspect_run`, `pause_run`, `resume_run`, `cancel_run`, `list_artifacts`, `get_artifact_lineage`, `replay_run`, `optimize_execution`, `install_plugin`, `list_plugins`, `manage_plugin`, `list_credentials`, `create_credential`, `get_credential`, `update_credential`, `revoke_credential`, `propose_graph`, `list_proposals`, `get_proposal`, `accept_proposal`, `reject_proposal`, `list_experiments`, `get_trace`, `list_projects`, `list_data_inputs`, `list_pipelines`, `get_pipeline`, `save_pipeline`, `publish_pipeline`, `promote_pipeline`, `rollback_pipeline`, `list_runs`, `get_run`, `get_run_outputs`, `list_templates`, `get_template`, `instantiate_template`, `search_templates`, `materialize_template`, `get_node_spec`, `list_packs`, `describe_pack`, `register_model`, `list_models`, `get_model`, `request_model_prod`, `approve_model_prod`, `compare_runs`, `list_schedules`, `upsert_schedule`, `enable_schedule`, `delete_schedule`, `run_schedule_now`, `get_webhooks`, `put_webhooks`, `test_webhook`, `list_notifications`, `mark_notifications_read`, `get_readiness`, `create_ship_package`, `get_ship_package`, `list_ship_packages`, `download_ship_package`, `promote_ship_package`, `get_audit_events`, `export_audit`, `list_dataset_versions`, `get_dataset_version`, `upload_dataset_file`, `list_workers`, `list_jobs`, `list_pending_gates`, `decide_gate`

## CLI (`graphyn`)

- Top-level commands (live `--help`): inspect, nodes, migrate, run, validate, runs, artifacts, plugin, secrets, users, data, mcp, worker. 44 `add_parser` calls in total (sub-commands: runs list/logs/pause/resume/cancel; artifacts list/get/lineage/replay; plugin install/list/enable/disable/remove/search/info; secrets list/set/delete; data ls/upload/snapshot/download; worker start/join).
- Note: even `graphyn --help` boots the plugin manager first (host install reports 48 node types from a stale `~/.graphyn` — differs from the 36 in the container).

## Plugins (`PluginPackage/`)

- Enabled live: **35 plugins → 36 node types** (compose `BUNDLED_PLUGIN_ALLOWLIST`). Packs present: Audio (7 plugins), Common (23 incl. ML chain), Agents (5).
- Runtime: isolated (own venv) = dataset_builder, model_builder/trainer, evaluator, edge_optimizer, realtime_inference; inprocess = the rest; 8 manifests omit `runtime`.
- Removed on this branch (but still referenced by templates, tests, docs): RAG, Vision, Video, TinyML, WakeWord, MLOps packs and Audio annotator/classifier/ASR/enhancer/versioner/stream_ingest etc.
- Docs vs reality: NODES.md & PluginPackage/ARCHITECTURE.md say **49** node types; AGENTS.md says **9 packs / 156 plugin.toml**; PLUGIN_GUIDE says 20/48; PLUGIN_NODE_PLATFORM_CATALOG.json lists 146 (43 existing / 7 alter / 96 proposed); NODE_CATALOGUE.md says 14 + workflow set. **Live: 36.**

## Templates

- File templates: 129 (`examples/**` 98, `workspace/configs/templates/**` 31). Live `GET /pipelines/templates`: 31 (16 flagged runnable=false via missing_node_types). `GET /pipelines/examples`: 31. Marketplace catalog: 3,032 entries.

## UI (`graphyn-ui/`)

- Vite + React + TS; 70 .tsx files (~63k LOC), 16 feature dirs, ~28 route builders in `src/routes/paths.ts`.
- Routes: /workspaces, /workspaces/:id[/editor|/runs|/runs/live|/runs/compare|/models|/datasets|/ship|/ship/devices], /templates, /agent/inbox, /library/datasets, /library/plugins, /deploy/workers[/queue], /admin/credentials, /admin/ops[/audit], /admin/access, /settings, /login, /404.
- `libraryArtifacts`, `libraryModels`, `deployShip`, `deployShipDevices` route builders are typed `never` (declared but intentionally unroutable).

## Tests

- Backend test files: 295 — by dir: unit_test 1, unit_test/models 11, unit_test/plugins 16, unit_test/plugins/common 36, unit_test/plugins/audio 22, unit_test/plugins/agents 2, unit_test/cli 2, unit_test/api 47, unit_test/core 99, unit_test/core/nodes 13, unit_test/core/plugins 16, unit_test/core/ir 6, unit_test/core/execution 1, unit_test/core/distributed 6, unit_test/mcp 17
- UI: 260 vitest suites / 528 tests.

## Docs

- 34 top-level markdown files under docs/ (lines): API_REFERENCE.md 1792, ARCHITECTURE.md 548, DATA_FLOW_AND_WORKSPACE.md 306, DEPLOYMENT.md 247, DISTRIBUTED_EXECUTION.md 600, ENTERPRISE_READINESS.md 206, EXAMPLE_06_COVERAGE.md 371, GETTING_STARTED.md 203, HANDOFF_UI_REVIEW_PROMPT.md 130, IA_PROJECT_FIRST.md 230, KNOWN_ISSUES.md 456, MCP_AGENT_PACK_COVERAGE.md 142, MCP_SERVER.md 365, NODE_CATALOGUE.md 244, OPS_BACKUP_RESTORE.md 76, PIPELINE_EXECUTION.md 661, PIPELINE_TEMPLATE_MARKETPLACE.md 98, PLUGIN_GUIDE.md 463, PLUGIN_NODE_PLATFORM_CATALOG.md 2223, PLUGIN_NODE_REFINEMENTS.md 61, PRODUCT_VISION.md 142, README.md 42, REQUIREMENTS_SPEC.md 4955, SDK_AND_CLI.md 745, SRS_ALIGNMENT_GAP_MATRIX.md 420, TRUST_MODEL.md 237, UI_LINKAGE.md 21, UI_NORTH_STAR.md 859, UI_USER_REQUIREMENTS.md 774, UI_WORKSPACE_IDE.md 52, WORKLOG_OUTPUTS_AND_VIEWERS.md 106, CREDENTIAL_STORE.md 108, F18_REQUIREMENTS_LOGICAL_CHECKLIST.md 195, F18_TECH_STACK_CHECKLIST.md 181
- Requirements: `docs/REQUIREMENTS_SPEC.md` 339 ID rows / 330 unique IDs (P0 208 rows, P1 100, P2 31).
