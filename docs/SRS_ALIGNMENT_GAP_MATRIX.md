# SRS Alignment Gap Matrix — Graphyn P0

| Field | Value |
|---|---|
| **SRS** | GRAPHYN-SRS-001 **v1.2.0** (`docs/REQUIREMENTS_SPEC.md`, 4953 lines) |
| **Tip probed** | `c3195c58b2dcbd9c6dcde06d3499323d07fff087` on `cursor/usecase-plugins-workflows` (Wave A batch 2: ship REST + MCP P0)
| **Phase** | 2 — Wave A batch 2 implemented (ship packages REST + MCP J1–J3/ship/audit)
| **Author** | Samir Kumar Mishra <samir.nmiet@gmail.com> |
| **Generated** | 2026-09-25 21:12 IST; Wave A batch 2 update 2026-09-25 ~21:50 IST
| **Method** | Static code evidence only (grep/read). Live Server-99 verify = Phase 2 (DESKTOP/CloudAgent not used). |

> **Honesty rule:** Status is **Confirmed** only with file:symbol evidence. Thin/partial contracts → **Partial**. Absent symbols/routes → **Missing**. Product TBD / device APIs → **needs-API**. Not inspected this pass → **Not probed**.

---

## 1. Architecture map (evidence)

### 1.1 Logical layers

```
Console SPA (graphyn-ui/)  ──HTTP Bearer──►  FastAPI /api/v1 (app/api/)
CLI `graphyn` (app/cli)    ──direct/core──►  Runtime (app/core/)
Python SDK (app/core/sdk)  ──get_backend()──► LocalPython | Distributed
MCP stdio (app/mcp/)       ──handlers──────► same core stores
Compose: graphyn-api :8001 + graphyn-ui :5173 (nginx SPA fallback)
```

**ARCH-001 evidence:** `app/core/runtime_backend.py:get_backend` / `RuntimeBackend.execute` — sole execution entry for API/CLI/SDK/MCP.

### 1.2 Console SPA (`graphyn-ui/`)

| Concern | Path | Notes |
|---|---|---|
| Router | `src/main.tsx` | `BrowserRouter` (History API) — not HashRouter |
| Path builders | `src/routes/paths.ts` | Workspace-scoped Models/Ship/Datasets; Library Artifacts/Plugins; Deploy Workers; Admin Secrets/Ops/Access |
| Path↔store | `src/routes/parsePath.ts`, `viewMap.ts` | `pathForView` returns null when workspace required but missing |
| Shell + rail | `src/App.tsx` | Workspace strip (Home/Editor/Runs/Models/Ship/Datasets) + groups Build/Library/Deploy/Admin; one Switch |
| Features | `src/features/*` | builder, runs, models, data, edge/ship, plugins, artifacts, workers, secrets, system, proposals, templates, auth, access |
| SPA fallback | `graphyn-ui/nginx.conf` | `try_files … /index.html` |

### 1.3 API FastAPI (`app/api/`)

Routers mounted in `app/api/main.py` under `/api/v1` (auth deps):

| Router file | Prefix / surface |
|---|---|
| `routers/nodes.py` | `/nodes`, `/types`, compatible |
| `routers/pipelines.py` | `/pipelines` validate/run/run-async/templates/examples |
| `routers/runs.py` | `/runs` + sub-resources |
| `routers/run_control.py` | `/runs/{id}/pause|resume|cancel` |
| `routers/data.py` | `/data/inputs|outputs|merge` |
| `routers/ingest.py` | `/ingest/url|huggingface` |
| `routers/projects.py` | `/projects` (+ pipelines publish/promote/rollback, dataset project APIs) |
| `routers/workers.py` | `/workers`, `/jobs`, `/artifacts/blob` |
| `routers/artifacts.py` | `/artifacts` list/get/lineage/replay |
| `routers/plugins.py` | `/plugins` install/enable/disable/deps/venvs |
| `routers/secrets.py` | `/secrets` |
| `routers/system.py` | health/readiness/auth-status/metrics/cleanup/schedules/webhooks |
| `routers/models.py` | `/models` + request-prod/approve-prod |
| `routers/ship.py` | `/projects/{name}/ship/packages*` |
| `routers/proposals.py` | `/proposals` |
| `routers/trace.py` | `/trace`, `/audit` |
| `routers/experiments.py` | `/experiments` |
| `routers/outputs.py` | `/outputs/file` |

**Ship packages router:** `app/api/routers/ship.py` → `/projects/{name}/ship/packages*` (Wave A batch 2).

Auth: `app/api/main.py` HTTPBearer + fail-closed when `GRAPHYN_AUTH_REQUIRED` / prod|staging. Actor: `app/api/actor.py` (`X-Actor`).

### 1.4 Runtime (`app/core/`)

| Area | Paths |
|---|---|
| Orchestrator / execute | `orchestrator.py`, `executor.py`, `node_executor.py`, `runtime_backend.py`, `planner.py` |
| IR | `ir/` (loader CURRENT=1.2, models, migrate, secret_policy, yaml_shim) |
| Pipeline envs | `pipeline_environments.py`, `project_pipelines.py` |
| Run durability | `run_journal.py`, `run_manager.py`, `run_control.py`, `checkpoint.py`, `run_cleanup.py` |
| Distributed | `distributed/` (backend, queue, store CAS, registry, placement, transfer) |
| Plugins | `plugins/` (manager, installer, store, isolated_executor+RestrictedUnpickler, dependencies) |
| Models / artifacts / prove | `model_registry.py`, `artifact_store.py`, `provenance.py`, `trace.py`, `audit.py` |
| Data / schedules / secrets | `workspace_paths.py`, `schedules.py`, `webhook.py`, `secrets.py`, `egress.py` |
| Validation | `validation.py` (+ IR loaders) |
| SDK | `sdk.py` (`Pipeline` / `PipelineNode`) |

### 1.5 MCP (`app/mcp/`)

- Transport: `server.py`, auth `auth.py`, registry `tool_registry.py`
- Handlers: discovery, graph, execution, run_control, artifacts, provenance, plugins, secrets, proposals, workspace, optimization, …
- **Registered tools (~29):** list_nodes, generate_graph, validate_graph, get_graph_schema, get_graph_capability_summary, get_event_schema, execute_pipeline, inspect_run, pause/resume/cancel_run, list_artifacts, get_artifact_lineage, replay_run, optimize_execution, install/list/manage_plugin, secrets_list/set, propose/list/get/reject/(accept)_proposal, list_experiments, get_trace, list_projects, list_data_inputs
- **§21 P0 additions:** J1–J3 + ship + audit + readiness **Confirmed** (Wave A batch 2). Residual Missing/Partial: dataset versions MCP, workers/jobs MCP

### 1.6 CLI / SDK

| Surface | Evidence |
|---|---|
| CLI entry | `setup.py` → `graphyn=app.cli.main:main` |
| CLI cmds | validate, run, migrate, inspect, nodes, runs (list/logs/pause/resume/cancel), artifacts, plugin, secrets, mcp, worker |
| SDK | `app/core/sdk.py`; package name `graphyn-sdk` |

### 1.7 Docker Compose

`docker-compose.yml`: `graphyn-api` (8001, AUTH_REQUIRED=1, GRAPHYN_HOME volume, workspace+plugins mounts) + `graphyn-ui` (5173→80). Optional `docker-compose.gpu.yml`. Comment: CPU-safe default so FaceRecognition keeps GPU unless opted in.

---

## 2. Method — status assignment

| Status | Meaning |
|---|---|
| **Confirmed** | Route/symbol exists and key fields/behavior match SRS enough for P0 greenfield use |
| **Partial** | Present but thin vs contract (wrong status names, FastAPI `detail` only, missing envelope/codes, silent no-op vs 409, incomplete schema) |
| **Missing** | No route/handler/tool/module found for the P0 contract |
| **needs-API** | Explicitly deferred in SRS (e.g. device flash/OTA) — honesty stub OK |
| **Not probed** | Not grepped this pass (call out for Phase 2) |

Probes used: router `@router.*` inventory, App rail constants, run_journal status writes, tool_registry `register(`, CLI `add_parser`, ship path grep (empty for REST), Idempotency-Key grep (empty), error envelope shape in `main.py`.


---

## 3. P0 gap tables by domain

### 3.1 UX-NAV / Workspace IDE rail — §10

| ID / cluster | SRS § | Evidence | Status | Notes | Fix pri |
|---|---|---|---|---|---|
| UX-NAV-000 Workspace noun | 10.1 | `App.tsx` strip "Workspace:"; `ui.tsx` labels | Confirmed | API still `project` (allowed) | — |
| UX-NAV-001 rail shape | 10.2 | `App.tsx` WORKSPACE_STRIP + NAV_GROUPS | Confirmed | Build/Library/Deploy/Admin match LOCKED | — |
| UX-NAV-002 one Switch | 10.2 | `App.tsx` ~758–779, header comment ~958 | Confirmed | Header Open only when no URL workspace | — |
| UX-NAV-003/004 Models/Ship/Datasets / Artifacts | 10.2 | strip vs Library items | Confirmed | | — |
| UX-NAV-005 lineage/compare not peers | 10.2 | under Runs paths | Confirmed | | — |
| UX-NAV-006/007 path URLs + cold-boot hash | 10.2–10.4 | `BrowserRouter`; `paths.ts`; parsePath canonical | Confirmed | Hash clear covered by routing mode + canonical | — |
| Path map completeness | 10.3 | `paths.ts` + `parsePath.ts` | Partial | Missing `paths.shipPackage(id, packageId)` for `/ship/packages/:packageId`; model version path thin | A |
| aria-current | 25.2 NFR-A11Y-003 | `App.tsx:816,845` | Confirmed | | — |

**Domain rollup:** Confirmed (strong IA). Residual: ship package detail path builder.

### 3.2 Auth / error envelope — §9.0–9.1, §11.1

| ID / cluster | SRS § | Evidence | Status | Notes | Fix pri |
|---|---|---|---|---|---|
| API-CONV-001 `/api/v1` | 9.0 | `main.py` include_router prefix | Confirmed | | — |
| API-CONV-002 Bearer fail-closed | 9.0 / 9.1 | `main.py` AUTH_REQUIRED / ENV | Confirmed | | — |
| API-CONV-003 X-Actor | 9.0 | `actor.py`; CORS allow `X-Actor` | Confirmed | | — |
| API-CONV-004 Idempotency-Key | 9.0 | `app/api/idempotency.py`; wired on run-async, proposals accept, schedules POST, projects POST | Confirmed | Ship create deferred until Ship REST | A |
| API-CONV-005 If-Match / resource_version | 9.0 | `app/api/concurrency.py`; pipeline PUT, secrets, webhooks, ship promote/transition | Confirmed | 412 If-Match / 409 body; ETag on writers | B |
| API-ERR-001 error envelope | 9.0.1 | `app/api/errors.py` + handlers in `main.py`; dual-emit legacy `detail` | Confirmed | Wave A batch 1 | A |
| FR-AUTH-001/002/005 console | 11.1 | features/auth, Settings, login path | Partial | Login/Settings exist; full honesty banner + returnTo not fully audited this pass | B |
| API-PAGE-001 list envelope | 9.0.2 | `app/api/pagination.py`; nodes/projects/artifacts/data outputs accept `?envelope=1` | Confirmed | Additive; bare arrays default (P1 default-envelope deferred) | B |

**Domain rollup:** Auth gate **Confirmed**; envelope/idempotency **Confirmed** (Wave A batch 1). Residual: If-Match (Wave B).

### 3.3 REST P0 endpoints (§9.2) — sample all P0 route families

| Route cluster | SRS § | Evidence | Status | Notes | Fix pri |
|---|---|---|---|---|---|
| `GET/POST /projects` | 9.2.1 | `projects.py` list/create | Confirmed | | — |
| `GET /projects/{name}` | 9.2.1 | `projects.py` GET + `ProjectManager.get` | Confirmed | Wave A batch 1 | A |
| `PUT /projects/{name}` | 9.2.1 | `PUT` metadata update; legacy `PATCH` rename retained | Confirmed | Wave A batch 1 | A |
| Pipelines CRUD + versions/envs | 9.2.2 | `projects.py` + `pipeline_environments.py` | Confirmed | publish/promote/rollback present; approve flag on promote | — |
| `POST /pipelines/validate|run|run-async` | 9.2.3 | `pipelines.py` | Confirmed | | — |
| Templates / examples / nodes / types | 9.2.3 | `pipelines.py`, `nodes.py` | Confirmed | | — |
| Runs list/get + sub-resources | 9.2.4 | `runs.py` graph/status/checkpoints/artifacts/outputs/zip/provenance/debug-report/promote | Confirmed | Wire status uses `completed` not `succeeded` (see §13.2) | — |
| Run pause/resume/cancel | 9.2.4 | `run_control.py` + `run_status.py` matrix | Confirmed | 409 invalid_transition; cancel-on-cancelled idempotent | A |
| Artifacts list/lineage/blob | 9.2.5 | `artifacts.py`, `workers.py` blob | Confirmed | | — |
| Models + request/approve prod | 9.2.6 | `models.py`, `model_registry.py` | Confirmed | | — |
| Data inputs/outputs/merge + ingest | 9.2.7 | `data.py`, `ingest.py` | Confirmed | Ingest P1 in DATA-SYS-002 but routes exist | — |
| Plugins lifecycle APIs | 9.2.8 | `plugins.py` | Confirmed | | — |
| Secrets | 9.2.9 | `secrets.py` names-only; If-Match / resource_version on PUT/DELETE | Confirmed | Wave B | B |
| Schedules + webhooks | 9.2.10 | `system.py` | Confirmed | Idempotency-Key missing | A |
| Workers + jobs claim/complete | 9.2.11 | `workers.py` + distributed queue | Confirmed | | — |
| Proposals CRUD/accept/reject | 9.2.12 | `proposals.py` + agentic | Confirmed | Idempotency-Key missing on accept | A |
| System health/readiness/auth/metrics/cleanup/audit/trace/experiments | 9.2.13 | system/trace/experiments; `ready` + store_corrupt/disk_full | Confirmed | Wave B `app/core/readiness.py` | B |
| **Ship packages REST** | 9.2.14 | `app/api/routers/ship.py` + `app/core/ship_packages.py` | Confirmed | list/create/get/download/promote/transition; Idempotency-Key on create/promote; 409 invalid_transition | A |

**Domain rollup (route-level):** GET/PUT project + run control + Ship packages REST **Confirmed** (Wave A).

### 3.4 Run state machine — §13.2

| ID / cluster | SRS § | Evidence | Status | Notes | Fix pri |
|---|---|---|---|---|---|
| Canonical states pending/running/paused/succeeded/failed/cancelled | 13.2 | writers: `pending`→`running`→`succeeded`; reads map `completed`→`succeeded` | Confirmed | Wave A: migrate writes; alias legacy journals on read | A |
| Current×Action matrix + 409 invalid_transition | RT-SM-001/003 | `app/core/run_status.py` + API gates | Confirmed | SDK silent no-ops still Wave B | A |
| Resume failed/cancelled/succeeded = NO | 13.2 locked | enforced via `next_status` → 409 | Confirmed | Wave A batch 1 | A |
| Cancel durable + forbid artifact commit | RT-CANCEL-* | `ArtifactCommitForbidden` in `run_journal.register_artifact` + unit test | Confirmed | Wave B | B |
| graph_hash on resume | RT-RESUME-001 | `orchestrator.py` hash check | Confirmed | | — |
| Crash reconcile stale running | RT-CRASH / NFR-REL-002 | `run_cleanup.py` reconcile → failed | Confirmed | | — |
| get_backend sole entry | RT-002 | `runtime_backend.py` | Confirmed | | — |

### 3.5 Graph validation — §14

| ID / cluster | SRS § | Evidence | Status | Notes | Fix pri |
|---|---|---|---|---|---|
| VAL-001 validate before execute / API | 14 | `pipelines.py` validate; IR load; secret_policy | Confirmed | | — |
| Check IDs VAL-DUP/CYCLE/SECRET/… | 14.2 | `validate_graph_ir_result` emits VAL-* + severity | Confirmed | Wave A batch 1 | A |
| Result schema valid/errors[]/warnings[] | 14.3 | full §14.3 shape from validate endpoint | Confirmed | Wave A batch 1 | A |
| IR-006 secret fail-closed | 8.7 | `ir/secret_policy.py` | Confirmed | | — |
| schema_version 1.2 | IR-001/002 | `ir/loader.py` CURRENT_IR_VERSION=1.2 | Confirmed | | — |

### 3.6 Distributed — §15

| ID / cluster | SRS § | Evidence | Status | Notes | Fix pri |
|---|---|---|---|---|---|
| Register/heartbeat/list/deregister | 15.1 | `workers.py`, `distributed/registry.py` | Confirmed | | — |
| CAS claim + lease_generation | 15.3–15.5 | `queue.py`, `store.py` mutate/CAS | Confirmed | | — |
| At-least-once + fencing complete | 15.4 | complete checks lease | Confirmed | | — |
| artifact:// + RestrictedUnpickler | 15.6 | transfer + `isolated_executor.RestrictedUnpickler` | Confirmed | | — |
| Durable store default Mode B | DIST-035 | disk/redis store present | Confirmed | memory-only for tests — honesty OK | — |
| DIST-AUTH honesty (shared bearer) | 15.2 | docs/compose comments; SEC-001 | Partial | Product copy in UI/Ops not fully probed | C |

### 3.7 Persistence — §16

| ID / cluster | SRS § | Evidence | Status | Notes | Fix pri |
|---|---|---|---|---|---|
| Atomic meta / os.replace+fsync | 16.1–16.2 | run_journal, secrets, schedules, artifact_store, distributed/store | Confirmed | | — |
| Quarantine corrupt index | PERS-020 | quarantine + readiness `store_corrupt` signal | Partial | Signal in readiness; not every API returns 503 store_corrupt yet | B |
| Readiness false on corrupt | PERS-021 | `ready=false` when store_corrupt/disk_full/unwritable | Confirmed | Wave B | B |
| PERS-001 pending before run_id ack | 16.1 | `RunManager` writes `pending`; `mark_running` at execute start | Confirmed | Wave A batch 1 | A |

### 3.8 Plugins — §17

| ID / cluster | SRS § | Evidence | Status | Notes | Fix pri |
|---|---|---|---|---|---|
| Install/enable/disable/uninstall/deps/isolated | 17.2 | `plugins/manager.py`, installer, isolated_executor | Confirmed | | — |
| Allowlist remote install | PLG-TRUST-002 | installer + plugins router comments | Confirmed | | — |
| Lifecycle wire states installing/failed_install | 17.2 | install jobs map in router | Partial | Full SM naming vs SRS states | C |
| Domain types in plugin types.py | PLG-SYS-008 | PluginPackage layout | Confirmed | | — |

### 3.9 Models / pipeline envs — §18

| ID / cluster | SRS § | Evidence | Status | Notes | Fix pri |
|---|---|---|---|---|---|
| Independent axes | MR-ENV-001 | separate modules | Confirmed | | — |
| Pipeline approve:true for prod | MR-ENV-003 | `promote_environment(..., approve=)` | Confirmed | | — |
| Model request/approve prod + audit | MR-003 | models router + registry | Confirmed | | — |
| UX linkage run↔pipeline↔dataset | MR-ENV-002 | Trace/Models UI | Partial | Not fully audited | C |

### 3.10 Ship — §19

| ID / cluster | SRS § | Evidence | Status | Notes | Fix pri |
|---|---|---|---|---|---|
| Package REST create/list/get/download/promote | 9.2.14 / SHIP-001 | `ship.py` + `ship_packages.py` | Confirmed | Wave A batch 2; archive+manifest sha256 | A |
| Lifecycle states draft…deployed | 19.2 | `ship_packages.next_status` matrix | Confirmed | aliases creating→draft, ready→built on read/wire | A |
| Edge wizard template path | EDGE-001 | `features/edge/EdgeWizardView.tsx` | Partial | Wizard still runs packager pipeline; also lists/creates via ship REST | A |
| Devices honesty stub | SHIP-006 / EDGE-007 | `DevicesView.tsx` honesty copy | needs-API | Correct stub | — |
| Checksum display in UI | SHIP-002 | EdgeWizard checksum state | Partial | Depends on artifact path not package API | B |

### 3.11 Datasets — §20

| ID / cluster | SRS § | Evidence | Status | Notes | Fix pri |
|---|---|---|---|---|---|
| Input/output layout + APIs | DATA-SYS-001 | `data.py`, workspace_paths | Confirmed | | — |
| Version immutability + merge new version | DATA-VER-001/008 | `dataset_versions.py` manifest sha256; DELETE 409 unless force | Confirmed | Wave B | B |
| Upload sanitize | DATA-SYS-005 | upload route | Partial | Need Phase 2 | C |
| Ingest URL/HF | DATA-SYS-002 | `ingest.py` | Confirmed | P1 priority in SRS; routes exist | — |

### 3.12 MCP parity — §21

| ID / cluster | SRS § | Evidence | Status | Notes | Fix pri |
|---|---|---|---|---|---|
| Core ~29 tools | 21.3 core | `tool_registry.py` | Confirmed | | — |
| P0 J1–J6 additions | 21.3 table | + `data_ops.py` / `workers_ops.py` | Confirmed | Wave B: dataset versions + upload + list_workers/list_jobs | A/B |
| MCP-001 secrets names only | 21.1 | secrets_list handler | Confirmed | | — |
| MCP-005 structured tool errors | 21.4 | mixed | Partial | | B |
| accept_proposal gated | MCP-002 | conditional register | Confirmed | | — |

### 3.13 Audit / provenance — §22

| ID / cluster | SRS § | Evidence | Status | Notes | Fix pri |
|---|---|---|---|---|---|
| Append-only JSONL audit | AUD-001 | `audit.py` events.jsonl | Confirmed | | — |
| Schema fields request_id/result/actor_kind/timestamp | 22.1 | `audit.record_audit` writes timestamp+ts, result, request_id, actor_kind | Confirmed | Wave B; `ts`/`meta` aliases kept | B |
| Required audited actions | AUD-005 | cancel, rollback, model, plugin, ship, dataset.version_delete | Confirmed | Schema aligned Wave B | B |
| ProvenanceRecord fields | 22.2 | `provenance.py` ProvenanceRecord | Confirmed | plugin_versions optional thin | C |
| GET /trace | OBS-002 | `trace.py` | Confirmed | | — |
| Prove capture set completeness | 22.2 | Not probed end-to-end | Not probed | Phase 2 | C |

### 3.14 Security — §23

| ID / cluster | SRS § | Evidence | Status | Notes | Fix pri |
|---|---|---|---|---|---|
| SEC-010/011 secrets perms + names only | 23.3 | `secrets.py` | Confirmed | file mode: Phase 2 live verify | — |
| SEC-012 / IR-006 | 23.2 | secret_policy | Confirmed | | — |
| SEC-023 webhook SSRF | 23.2 | `egress.py` + `webhook.py` | Confirmed | | — |
| SEC-030 path jail | 23.3 | workspace_paths / outputs file jail | Confirmed | | — |
| SEC-040/041 RestrictedUnpickler | 23.2 | isolated_executor | Confirmed | | — |
| SEC-042 plugin allowlist | 23.3 | installer | Confirmed | | — |
| SEC-XSS / CSP / token honesty | THREAT-001/002 | Not fully probed UI CSP meta | Partial / Not probed | | C |
| SEC-020 python_code AST | 23.3 | conditions AST; python_code node | Partial | Not deep-probed | C |

### 3.15 Ops — §24

| ID / cluster | SRS § | Evidence | Status | Notes | Fix pri |
|---|---|---|---|---|---|
| Health vs readiness | OPS-014 | `/health` + `/system/readiness` | Confirmed | | — |
| Cleanup armed | OPS-009 | `POST /system/cleanup` | Confirmed | | — |
| Stale RUNNING reconcile | NFR-REL-002 | run_cleanup | Confirmed | | — |
| Backup/restore docs procedure | OPS-001/002 | Not in code (ops doc) | Partial | Treat Partial until ops runbook in-tree | C |
| Shutdown drain SIGTERM | OPS-005/011 | lifespan exists; drain not proven | Partial | | C |
| Disk-full 503 | OPS-007 | Not probed | Not probed | | C |
| Compose SPA fallback | NFR-REL-001 | nginx try_files | Confirmed | | — |

### 3.16 CLI / SDK — §9.4

| ID / cluster | SRS § | Evidence | Status | Notes | Fix pri |
|---|---|---|---|---|---|
| Entry `graphyn` | CLI-000 | setup.py console_scripts | Confirmed | | — |
| Global `--api-url/--token/--actor/--json` | CLI-000 | root parser in `app/cli/main.py` + env fallback | Confirmed | Optional remote `nodes` | B |
| Exit codes 0/1/2/3/4/5/130 | CLI-000 | `app/cli/exit_codes.py` + main mapping | Confirmed | Wave B | B |
| validate / run / migrate | 9.4.1 | present | Confirmed | | — |
| runs pause/resume/cancel | 9.4.1 | present | Confirmed | same SM gaps as API | A |
| plugin / secrets / artifacts / worker | 9.4.1 | present | Confirmed | | — |
| SDK Pipeline API | 9.4 | `sdk.py` | Confirmed | pause/resume silent no-op vs 409 | B |
| Remote CLI via REST for all resources | 9.4 | thin | Partial | Many cmds hit local core, not API | B |

---

## 4. Counts (this pass, P0 rows above)

| Status | Approx count |
|---|---|
| **Confirmed** | ~72 |
| **Partial** | ~30 |
| **Missing** | ~14 |
| **needs-API** | ~2 |
| **Not probed** | ~4 |

> Counts are row-clusters (not every atomic FR ID). Treat as directional for Wave planning.

---

## 5. Iteration plan

### Wave A — highest-impact P0 Missing/Partial, code-searchable, no product TBD

1. **API-ERR-001** — ✅ Closed (Wave A batch 1): `app/api/errors.py` + handlers.
2. **API-CONV-004** — ✅ Closed for run-async / proposals accept / schedules POST / projects POST (ship create when Ship REST lands).
3. **RT-SM / run wire** — ✅ Closed: `succeeded` writes + `completed`→`succeeded` on read; `pending` ack; 409 matrix.
4. **Ship packages REST** — ✅ Closed (Wave A batch 2): `ship_packages.py` + `routers/ship.py`; Edge wizard list/create wired.
5. **MCP P0 additions (J1–J3 first)** — ✅ Closed (Wave A batch 2): journey handlers + registry.
6. **GET /projects/{name}** (+ PUT) — ✅ Closed (Wave A batch 1).
7. **VAL result schema** — ✅ Closed: VAL-* + warnings[]; execute refuses on errors.
8. **MCP Ship + audit tools** — ✅ Closed (Wave A batch 2): ship_ops + audit_ops.
9. **Run control from durable meta** — ✅ Closed (idempotent cancel; terminal resume 409).
10. **PERS-001** — ✅ Closed (`pending` before async ack; `mark_running` on execute).

### Wave B — contract depth / concurrency / schema polish

- ✅ If-Match / resource_version on pipeline draft, secrets, webhooks, ship promote/transition.
- ✅ Audit schema field rename/align (`timestamp`, `result`, `request_id`, `actor_kind`; `ts`/`meta` aliases).
- ✅ List `?envelope=1` additive on key list endpoints (P1 default-envelope deferred).
- ✅ CLI global flags + exit code matrix; optional remote `nodes`.
- ✅ Dataset version force-delete 409 + manifest sha256 enforcement.
- ✅ Readiness `ready` boolean + store_corrupt / disk_full signals.
- ✅ Artifact-commit-after-cancel hard forbid + unit test.
- ✅ MCP leftovers: list/get dataset versions, upload_dataset_file, list_workers, list_jobs.

### Wave C — honesty, ops, security polish, needs-API follow-through

- Devices API when product ready (keep stub until then).
- CSP / token-in-localStorage honesty banner.
- Backup/restore runbook in-tree; SIGTERM drain.
- DIST-AUTH / SEC-WORKER product copy on Workers/Ops.
- Prove capture set end-to-end audit (Phase 2 live).
- Perf TBD-PERF-* measurement (GA gate — not Wave A).

---

## 6. Phase 2 note (live verify)

**Server-99 / DESKTOP live verification is blocked in this Phase 1 agent turn** (no CloudAgent; no DESKTOP session attached for runtime probe). Next: run API contract tests + Docker IDE smoke on Server-99 against tip after Wave A items land.

---

## 7. Related machine-readable summary

See `docs/SRS_ALIGNMENT_GAP_MATRIX.json`.


### Wave A batch 1 landing

- Tip: `038c38a570b933523b536c589dece1f70a90389c`
- Closed: API-ERR-001, API-CONV-004 (key routes), RT-SM/PERS-001, GET/PUT projects, VAL schema.
- Remaining after batch 2: dataset-version / workers MCP (Wave B); Edge checksum UI polish.

### Wave A batch 2 landing

- Tip: `c3195c58b2dcbd9c6dcde06d3499323d07fff087`
- Closed: Ship packages REST §9.2.14/§19; MCP P0 J1–J3 + ship + audit + readiness.
- Residual Wave A→B: dataset version MCP tools, list_workers/list_jobs MCP, checksum UI polish.

### Wave B landing

- Tip: see commit on `cursor/usecase-plugins-workflows` after this docs update (filled in JSON).
- Closed: API-CONV-005, API-PAGE-001 (`?envelope=1`), audit §22.1 fields, CLI-000 globals+exits, DATA-VER-002/006, readiness ready/signals, API-FORBID-005 cancel-artifact, MCP dataset versions + workers/jobs.
- Deferred to Wave C: default-envelope migration (P1), universal 503 store_corrupt on all reads, Devices OTA, CSP/token honesty, backup runbook, SIGTERM drain, Perf TBD.
