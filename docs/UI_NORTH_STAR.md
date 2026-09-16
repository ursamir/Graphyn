# Graphyn Console — North-star UI (100% expectation match)

> **Purpose:** Complete **product** UI plan so Graphyn feels like **one** platform: **n8n + MLflow + orchestrator + Edge Impulse + agentic + full backtrack**.  
> **Status:** Implementation wave 2026-09-15 continued. **Phase 0 path routing shipped** (hash writes banned; legacy `#/` → path redirect only); **Phase A largely shipped**; **Phase B/C/D UI items shipped where APIs exist** (Devices OTA, OTel, Subflows, full HITL, cron, job list-all remain needs-API). See roadmap checkmarks below.
> **Does not replace:** `IA_PROJECT_FIRST.md` for today’s shell notes. This doc is the **target product**.  
> **Interactive:** canvas `graphyn-ui-north-star`.

---

## 0. Scope of “everything”

This document is the **master checklist**. Pillar gaps, API holes, screens, journeys, **path-based routing**, and **production platform** concerns are all in scope. Backend work required for a UI item is marked `needs-API`.

| Bucket | Scale |
|---|---|
| Pillar expectations | ~40 |
| Critical + nice-to-have UI gaps | ~60 |
| API / backend with weak or no UI | ~14 |
| Production platform (routing, auth, quality) | §4–§4.5 · Phase 0 |
| Screen contracts | 14+ surfaces |
| Journeys | J1–J6 |
| Roadmap | **Phase 0** · A · B · C · D |

**Product bar (non-negotiable)**
- Real URLs (`/workspaces/...`), not hash routes — shareable, bookmarkable, proxy-friendly  
- Workspace-scoped paths as the default mental model  
- Auth, authorization, and actor identity as first-class UI  
- Errors, empty, loading, offline — designed states, not alerts only  
- Observability, a11y, testability, release safety as part of the plan  

---

## 1. One product, six jobs

| Job | Analogy | User question (≤2 clicks) | Primary surfaces |
|---|---|---|---|
| **Design** | n8n | “What graph am I editing, and how do I run / trigger it?” | Editor, Templates, Home pipelines |
| **Learn** | MLflow | “Which experiment/model won, and can I promote it?” | Runs Compare, Models |
| **Execute** | Orchestrator | “What is running, where; can I pause/resume/retry?” | Runs Live/History, Workers, Queue |
| **Ship** | Edge Impulse | “Is this package downloadable / on device X?” | Ship (package + devices) |
| **Collaborate with AI** | Agentic | “What did the agent propose, and what if I accept?” | Agent inbox, Editor Agent panel |
| **Prove** | Accountability | “Who/what/where produced this — forever?” | Lineage, Audit, Access |

**Shell rule:** One **workspace** (project). Primary strip is project-scoped when open. Global = Templates, Library, Deploy fleet, Admin, Agent inbox.

**Decision B (locked):** Do not invent a second Project type.

---

## 2. Honest fit today

| Pillar | Fit | Strongest today | Weakest vs expectation |
|---|---:|---|---|
| n8n | ~55% | Canvas, templates, save/envs | Triggers on graph, HITL, always-on |
| MLflow | ~35% | Compare table, run outputs | Registry, charts, prod approve UI |
| Orchestrator | ~60% | Run/pause/cancel, workers list | Queue, waves, reclaim |
| Edge Impulse | ~25% | Package download wizard | Devices, flash/OTA, collect loop |
| Agentic | ~30% | Proposals review/accept | In-UI generate, rich diff, save-apply |
| Accountability | ~50% | Trace payload, replay, thin audit | RBAC, filters, OTel, repro pack |

---

## 3. Noun dictionary (one concept = one name)

| Noun | Means | Is not |
|---|---|---|
| **Workspace / Home** | Project context | Dataset-only folder |
| **Editor** | GraphIR canvas | Do not show `#/builder` or raw route ids in chrome |
| **Runs** | Execution history + Live + Compare | The Editor **Run** button |
| **Run outputs** | Per-run downloadable files | Datasets or Artifacts |
| **Artifacts** | Cross-run registry / ids | Run outputs panel |
| **Datasets** | Shared Inputs/Outputs under `workspace/datasets` | Run downloads |
| **Models** | Registry versions + stages | Raw trainer artifacts until registered |
| **Ship** | Edge package + devices | Worker fleet |
| **Agent inbox** | Proposals + generate | Chat-only LLM product |
| **Lineage** | Backtrack chain (nested under Runs or artifact) | Separate daily-nav peer |
| **Triggers** | Schedule / webhook / event on a graph | Only Ops forms |
| **Always-on** | Enabled triggers for a workspace | One-shot Editor Run |
| **Route** | Path URL under History API | Hash fragment (`#/...`) — **retired** |

---

## 4. Target information architecture

### 4.1 No workspace open

```
Projects              create / open / recent / filter (mine vs examples)
Build
  Templates
  Agent inbox         proposals + Generate (was Proposals-only)
Library
  Datasets
  Plugins
  Models *NEW*        global browse → open filters by project
  Artifacts           cross-run registry (secondary)
Deploy
  Ship / Edge         packages + devices (global device fleet ok)
  Worker fleet
Admin
  Secrets
  Ops                 health, schedules mirror, webhooks mirror, cleanup, audit
  Access *NEW*        tokens / roles / actors (Phase C)
```

### 4.2 Workspace open — activity strip

```
Home          Situation · pipelines · linked data · always-on · next actions
Editor        Canvas · Triggers dock · Agent drawer · placement (Mode B)
Runs          History | Live | Compare
              panels: Logs · Run outputs · Lineage · Details · Checkpoints
Models *NEW*  Registry for this workspace
Datasets      Linked pins + jump to library
Ship *NEW*    Package wizard · Devices · assign
───────────
Library & admin (collapsed):
  Templates · Agent inbox · Artifacts · Plugins · Workers · Secrets · Ops · Access
```

### 4.3 URL architecture — path routes (production)

**Decision (locked):** The console uses **HTML5 History path routes** (`react-router` or equivalent). **Hash routes (`#/...`) are retired** after a compatibility redirect window. No new feature may navigate via `location.hash`.

#### Principles
1. **Shareable** — paste a URL → same workspace, surface, and entity (run, model, proposal).  
2. **Workspace-first** — primary work lives under `/workspaces/:workspaceId/...`.  
3. **Resource nesting** — child resources are path segments; filters/tabs use query sparingly.  
4. **Stable ids** — prefer opaque ids (`runId`, `proposalId`); workspace id = project name until multi-tenant ids exist.  
5. **No chrome leakage** — users see labels (Editor, Runs); never raw path tokens as titles.  
6. **Server/proxy ready** — SPA fallback (`try_files` / CloudFront 200→`index.html`) is a deploy requirement.  
7. **Legacy** — `#/runs/abc` → `301/replace` → `/workspaces/{active|/}/runs/abc` (see §4.3.4).

#### Global routes (no workspace required)

| Path | Surface | Notes |
|---|---|---|
| `/` | Redirect | → `/workspaces` or last workspace Home |
| `/workspaces` | Projects picker | Create / open / recent / mine·examples |
| `/login` | Auth | Token or SSO entry (`needs-API` for SSO) |
| `/settings` | User settings | API base URL, token, preferences |
| `/templates` | Templates | Stamp requires choosing/creating workspace |
| `/agent/inbox` | Agent inbox | List |
| `/agent/inbox/:proposalId` | Proposal detail | Diff + accept/reject |
| `/library/datasets` | Datasets (global) | |
| `/library/datasets/inputs/:label` | Input detail | |
| `/library/datasets/outputs/:project/:version?` | Output browse | |
| `/library/plugins` | Plugins | |
| `/library/artifacts` | Artifacts registry | Query: `?artifactId=` |
| `/library/models` | Models (global) | Optional; often redirect into workspace |
| `/deploy/ship` | Ship (global) | Package when no workspace; prefer workspace Ship |
| `/deploy/ship/devices` | Device fleet | |
| `/deploy/ship/devices/:deviceId` | Device detail | |
| `/deploy/workers` | Worker fleet | |
| `/deploy/workers/queue` | Job queue | |
| `/admin/secrets` | Secrets | |
| `/admin/ops` | Ops | Health, cleanup, schedules mirror, webhooks mirror |
| `/admin/ops/audit` | Audit | Filters in query: `?actor=&resource=&from=&to=` |
| `/admin/access` | Access / RBAC | Phase C |
| `/404` | Not found | |

#### Workspace-scoped routes (daily product)

| Path | Surface |
|---|---|
| `/workspaces/:workspaceId` | Home |
| `/workspaces/:workspaceId/editor` | Editor (draft / last pipeline) |
| `/workspaces/:workspaceId/editor/pipelines/:pipelineId` | Editor with pipeline loaded |
| `/workspaces/:workspaceId/editor/pipelines/:pipelineId/:env` | `draft` \| `staging` \| `prod` |
| `/workspaces/:workspaceId/runs` | Runs · History |
| `/workspaces/:workspaceId/runs/live` | Runs · Live |
| `/workspaces/:workspaceId/runs/compare` | Runs · Compare · `?ids=a,b,c` |
| `/workspaces/:workspaceId/runs/:runId` | Run detail (default panel) |
| `/workspaces/:workspaceId/runs/:runId/logs` | Logs panel |
| `/workspaces/:workspaceId/runs/:runId/outputs` | Run outputs |
| `/workspaces/:workspaceId/runs/:runId/lineage` | Lineage |
| `/workspaces/:workspaceId/runs/:runId/details` | Details |
| `/workspaces/:workspaceId/runs/:runId/checkpoints` | Checkpoints |
| `/workspaces/:workspaceId/models` | Models registry |
| `/workspaces/:workspaceId/models/:modelName` | Model versions / stages |
| `/workspaces/:workspaceId/models/:modelName/versions/:version` | Version detail |
| `/workspaces/:workspaceId/datasets` | Workspace-linked datasets |
| `/workspaces/:workspaceId/ship` | Ship · Package |
| `/workspaces/:workspaceId/ship/devices` | Ship · Devices |
| `/workspaces/:workspaceId/ship/packages/:packageId` | Package detail |
| `/workspaces/:workspaceId/agent` | Agent panel deep-link (opens Editor + drawer) |

#### Compatibility redirects (retire hash)

| Legacy | Target |
|---|---|
| `#/projects` | `/workspaces` |
| `#/projects?project=W` | `/workspaces/W` |
| `#/builder` | `/workspaces/{W\|last}/editor` or `/workspaces` |
| `#/runs` | `/workspaces/{W}/runs` |
| `#/runs/{id}` | `/workspaces/{W}/runs/{id}` (resolve W from run API if needed) |
| `#/runs?tab=compare` | `/workspaces/{W}/runs/compare` |
| `#/experiments` | `/workspaces/{W}/runs/compare` |
| `#/trace?run_id=` | `/workspaces/{W}/runs/{id}/lineage` |
| `#/trace?artifact_id=` | `/library/artifacts?artifactId=` → lineage sheet |
| `#/data` | `/library/datasets` or `/workspaces/{W}/datasets` |
| `#/artifacts` | `/library/artifacts` |
| `#/templates` | `/templates` |
| `#/proposals` | `/agent/inbox` |
| `#/edge` | `/workspaces/{W}/ship` or `/deploy/ship` |
| `#/workers` | `/deploy/workers` |
| `#/secrets` | `/admin/secrets` |
| `#/system` | `/admin/ops` |
| `#/plugins` | `/library/plugins` |

Keep redirects ≥1 release; log hit counts; then remove.

#### Router implementation contract (Phase 0)
- `BrowserRouter` / `createBrowserRouter` — **not** `HashRouter`  
- Layout routes: `AppShell` → `WorkspaceLayout` (`:workspaceId`) → feature outlets  
- Navigation **only** via router (`Link`, `navigate`, typed helpers) — ban ad-hoc `history.replaceState` to hashes  
- `appStore` deep-link helpers rewrite to path builders (`paths.runs.outputs(workspaceId, runId)`)  
- Vite/nginx/Compose: SPA fallback for all non-`/api` paths  
- Document title: `Graphyn · {surface} · {workspace?}`  
- Breadcrumb mirrors path: `Workspaces / {id} / Runs / {shortId}`  

---

### 4.4 Production platform (all aspects)

Building a **product**, not a console demo. These are first-class plan items (Phase 0 + ongoing).

#### Auth & session
| ID | Requirement |
|---|---|
| P1 | Route guards: unauthenticated → `/login` with `returnTo` |
| P2 | Settings: API base URL, token storage (httpOnly cookie preferred when API supports; localStorage interim with clear threat model) |
| P3 | Auth honesty banner (shipped) stays; 401 globally redirects once |
| P4 | Actor header (`X-Actor`) editable for humans; agents set automatically |
| P5 | Access / RBAC UI (Phase C / C4) gates admin and prod approve |

#### Layout, state, data
| ID | Requirement |
|---|---|
| P6 | Shell layouts + nested outlets (no monolithic `view` enum as router) |
| P7 | Workspace context from URL param (source of truth); sync store ← URL, not the reverse as primary |
| P8 | TanStack Query (or equiv.) for server state: runs, models, workers — cache, retry, stale |
| P9 | Optimistic UI only where rollback is safe (pins, rejects) |
| P10 | Dirty Editor guard on route leave (`useBlocker`) |

#### Reliability & UX states
| ID | Requirement |
|---|---|
| P11 | Per-route error boundary + recovery CTA |
| P12 | Skeleton/loading for list+detail; never blank white |
| P13 | Offline / API down wall with retry (catalog already branches) |
| P14 | 404 and 403 pages (resource missing vs forbidden) |
| P15 | Toast + inline errors; destructive confirms (armed button shipped) |

#### Observability & ops
| ID | Requirement |
|---|---|
| P16 | Client error reporting hook (Sentry or equiv. — env-flagged) |
| P17 | Correlation: show `run_id` / `request_id` on failures |
| P18 | Feature flags for Phase C/D surfaces |
| P19 | Environment badge (local / staging / prod API) in shell |

#### Accessibility & i18n
| ID | Requirement |
|---|---|
| P20 | Keyboard nav for shell + Runs tables; focus traps in dialogs |
| P21 | WCAG AA for core flows (contrast, labels, live regions) — track UI-A11Y |
| P22 | i18n-ready strings (no new user-facing literals without key discipline) |

#### Security
| ID | Requirement |
|---|---|
| P23 | CSP-friendly build; no inline secret logging |
| P24 | Sanitize rendered artifact/JSON previews |
| P25 | Secrets never in URLs or GraphIR (validate fail-closed) |

#### Performance
| ID | Requirement |
|---|---|
| P26 | Route-level code splitting (`React.lazy` per feature) |
| P27 | Virtualize long run/artifact lists |
| P28 | Editor bundle isolated; observe routes stay light |

#### Testing & quality gates
| ID | Requirement |
|---|---|
| P29 | Router unit tests for legacy hash redirects |
| P30 | Playwright (or Cypress) smoke: login → workspace → run → lineage URL |
| P31 | Visual/a11y CI checks on shell + Runs |
| P32 | Contract tests: path helpers ↔ API ids |

#### Deploy & config
| ID | Requirement |
|---|---|
| P33 | Compose/nginx SPA fallback + `/api` proxy unchanged |
| P34 | `GRAPHYN_UI_BASE_PATH` support if served under subpath |
| P35 | Version/build SHA in Ops and `?` help |

#### Collaboration & deep links
| ID | Requirement |
|---|---|
| P36 | Copy-link on run, model, proposal, lineage |
| P37 | Open-in-new-tab works for all primary resources |
| P38 | MCP/docs cite **path URLs**, not hashes |

---

### 4.5 Breadcrumbs

Always derived from the route:

`Workspaces / {workspaceId} / {Surface} / {entityShort}`

Examples:
- `Workspaces / demo / Runs / a1b2c3d4`  
- `Workspaces / demo / Models / wake-word / v3`  
- `Agent / Inbox / prop_019`  

---

## 5. Pillar inventories (expect · have · gaps)

### 5.1 n8n — Design

**Expect**
1. Visual canvas: add/wire nodes, typed ports, config  
2. Templates / import / export  
3. Triggers: schedule, webhook, event; always-on  
4. Human-in-the-loop / wait  
5. Execution history tied to graph; re-run; pin versions  
6. Credentials/secrets not in graph JSON  
7. Subflows / reusable components  
8. Error routing / retry UX  

**Have today**
- Editor: React Flow, catalog, ports, schema config, validate, sync/async run, cancel, import/export, save template, save to project, load pipelines, placement (Mode B), env publish/request/approve  
- Templates stamp; Secrets name store; Ops schedules (interval) + one webhook; Runs history + open in Editor  

**Critical gaps → roadmap**
| ID | Gap |
|---|---|
| A6 | Triggers designer on canvas (not only Ops) |
| B4 | Home Always-on strip |
| B6 | HITL / wait node UX |
| B8 | Credential picker in node config (secret names) |
| C6 | Subflows / reusable graph components |
| B9 | Visual error-branch / retry policy editor |
| A9 | Cron UI (not interval-only) + bind schedule to project pipeline |
| A10 | Per-workflow webhook wiring (not one global URL only) |

**Nice-to-have → roadmap**
| ID | Gap |
|---|---|
| D1 | Version diff of two pipeline drafts on canvas |
| D2 | Richer live node overlay (n8n parity) |
| D3 | Multi-workflow always-on dashboard (cross-project) |
| B10 | Pin / favorite pipelines on Home |

### 5.2 MLflow — Learn

**Expect**
1. Experiment tracking: params, metrics, tags, nested runs  
2. Compare runs (table + charts)  
3. Artifact browser per run  
4. Model registry with stages + approval  
5. Promote / stage transitions with audit  
6. Metric history / plots over steps  
7. Search/filter by metric/param  
8. Link model ↔ training run ↔ code/data  

**Have today**
- Runs Compare / experiments aggregate; params/metrics table (no charts)  
- Run outputs + Artifacts download/replay  
- Promote aliases `latest|staging|prod` on run; pipeline env UI on Home  
- Model `request-prod` / `approve-prod` **API-only**  

**Critical gaps → roadmap**
| ID | Gap |
|---|---|
| A1 | Models screen: list/register/stages + request/approve prod |
| A3 | Compare metric charts (across runs + step curves when present) |
| A4 | Register model from Run outputs / Artifacts |
| A11 | Experiment create/rename/tag management UI |
| A12 | Search/filter runs by metric threshold / param facet |
| B11 | “Register as model X” primary flow (not only promote side-effect) |
| B12 | Model card → Trace + dataset version links (first-class) |

**Nice-to-have → roadmap**
| ID | Gap |
|---|---|
| D4 | Nested runs / parent-child |
| D5 | Artifact type icons + model blob preview |
| D6 | Compare code hash + data version columns |
| D7 | Export compare CSV |

### 5.3 Orchestrator — Execute

**Expect**
1. DAG plan / waves; parallel visibility  
2. Pause / resume / cancel  
3. Checkpoints / resume from failure  
4. Distributed workers, placement, queues  
5. Schedules + event triggers at scale  
6. Retries, timeouts, SLA alerts  
7. Job/task drill-down across workers  

**Have today**
- Editor run stream + cancel; Runs pause/resume/cancel, checkpoints, logs, stale warning  
- Workers list/detail; Mode chip; Ops schedules/tick/cleanup  
- Placement editor Mode B  

**Critical gaps → roadmap**
| ID | Gap |
|---|---|
| A8 | Job queue UI (`/jobs/*` visibility) + worker deregister |
| B3 | Runs Live: wave Gantt / node states / worker map |
| B13 | Mid-flight per-node reclaim / reassignment UX |
| A13 | In-graph “placement ignored in Mode A” badge + Mode explainer link |
| B14 | Retry / timeout policy surface (node or graph) |
| A2 | Pipeline rollback control on Home (`.../rollback`) |
| B15 | Schedule durability status + last error on Always-on |

**Nice-to-have → roadmap**
| ID | Gap |
|---|---|
| D8 | Alerting on failed schedules / SLA breach |
| D9 | Cache hit/miss indicators on nodes/runs |
| C7 | Worker labels/pools editor UX beyond copy-paste CLI |

### 5.4 Edge Impulse — Ship

**Expect**
1. Collect → label → train → optimize → package → flash/OTA  
2. Device list, firmware, on-device metrics  
3. Target backends with size/latency tradeoffs  
4. Dataset → model → package lineage  
5. Download + deploy one-click  
6. Continuous monitoring from edge  

**Have today**
- Edge wizard: template → configure → run-async → download; promote staging/prod; lineage bar  

**Critical gaps → roadmap**
| ID | Gap |
|---|---|
| C1 | Devices inventory + flash/OTA status (`needs-API` device registry) |
| C2 | Collect/label lite into Datasets for edge projects |
| B5 | Auto-pick model from registry; target size/latency comparison |
| C3 | On-device inference metrics → Runs/Models |
| A14 | Ship IA: rename Edge → Ship tabs Package | Devices |
| B16 | Failure path: package run diagnostics panel (not only open Trace) |

**Nice-to-have → roadmap**
| ID | Gap |
|---|---|
| D10 | Multi-target batch packages |
| D11 | Signed package / checksum display |
| C8 | Impulse-style guided path UI (still GraphIR under the hood) |

### 5.5 Agentic — Collaborate

**Expect**
1. Copilot generates/edits graphs in UI  
2. Propose → review diff → accept/reject → apply  
3. Chat / iterate with constraints  
4. Auto-debug failed runs → suggested fixes  
5. MCP parity; agents as first-class actors  
6. Guardrails: no secrets in IR; approval for apply  

**Have today**
- Proposals list/filter, structural diff, accept→Editor, reject+reason; badge; MCP banner  
- No create form; MCP `generate_graph` / `propose_graph` outside UI  

**Critical gaps → roadmap**
| ID | Gap |
|---|---|
| A5 | Agent inbox **Generate** + richer IR/text diff |
| B1 | Editor Agent side panel (propose/iterate) |
| B2 | Accept & **save to pipeline** + dirty-draft conflict |
| A15 | “Explain / fix this failure” from failed run → proposal |
| B17 | Actor chips (human vs agent id) on proposals + audit |
| C9 | MCP connection status in console |
| A16 | Partial apply (accept subset of node changes) — if API allows; else Phase D |

**Nice-to-have → roadmap**
| ID | Gap |
|---|---|
| D12 | Proposal auto-tied to project/pipeline |
| C10 | Optimize_execution suggestions surfaced in UI |
| B18 | Chat transcript retained per proposal thread |

### 5.6 Accountability — Prove

**Expect**
1. From any artifact: who/what/where/when/code/data  
2. Chain: artifact → node → run → graph → worker → actor  
3. Immutable audit of mutations  
4. Replay / re-execute from provenance  
5. Compare what changed between runs  
6. RBAC / multi-tenant actor identity  
7. Cross-worker OTel traces  

**Have today**
- Runs Lineage under `/workspaces/:id/runs/:runId/lineage`; Artifacts Trace + replay; Ops audit ~25 events; proposal/env audits  

**Critical gaps → roadmap**
| ID | Gap |
|---|---|
| A7 | Audit filters (actor/resource/time) + export; lineage path `/runs/:id/lineage` |
| B7 | Repro pack download (env + plugin versions freeze) |
| C4 | Access / RBAC UI + actor identity everywhere |
| C5 | OTel span viewer (optional; `needs-API`) |
| A17 | Lineage header: graph hash + plugin versions always visible |
| B19 | Model prod approval appears in Audit with deep links |
| C11 | Downstream consumers of an artifact |

**Nice-to-have → roadmap**
| ID | Gap |
|---|---|
| D13 | Blame view for pipeline file edits |
| D14 | Signed / append-only audit verification UX |
| D15 | Mobile observe-only (Runs + Lineage) |

---

## 6. Backend / API with weak or no UI (must appear in plan)

| Capability | API (indicative) | Plan ID | Notes |
|---|---|---|---|
| Model registry prod gate | `POST /models/.../request-prod`, `approve-prod`; `GET/POST /models` | A1, A4, B11 | Highest leverage |
| Pipeline rollback | `POST .../pipelines/.../rollback` | A2 | |
| Job queue / lease | `/jobs/claim\|complete\|events\|cancel\|{id}` | A8, B3 | Observe-only UI first |
| Worker deregister | `DELETE /workers/{id}` | A8 | |
| Plugin venv GC | `POST /plugins/venvs/gc` | C12 | Ops · Plugins maintenance |
| Create proposals | `POST /proposals` + MCP | A5, B1 | |
| MCP generate / optimize | `generate_graph`, `optimize_execution` | A5, C10 | |
| System metrics | `GET /system/metrics` | C13 | Ops metrics product strip |
| Artifact blob internals | `/artifacts/blob` | — | Keep internal; no console |
| Auth / RBAC | Bearer + future roles | C4 | Access screen |
| Durable cron / multi-webhook | schedules + webhooks | A9, A10, B15 | |
| Device registry / OTA | **missing** | C1 | `needs-API` |
| Ingest SSE | `/ingest/.../stream` | C14 | Datasets job progress UX |
| Project annotations / quality | projects router | C2 | Label lite, not full studio |

---

## 7. Journeys (100% definition)

### J1 — Human builds and runs
Open workspace → Template or Editor → Validate → Run → **View outputs** → Save pipeline → Publish staging → Request/Approve prod → Rollback if needed (A2).

### J2 — Train, compare, promote
Training run → Compare table+charts (A3) → Register model (A4) → Models stages (A1) → Request/Approve prod → Trace to data+run (B12).

### J3 — Always-on
Canvas Triggers (A6/A9/A10) → Enable → Home Always-on (B4) → failure opens run → schedule error visible (B15).

### J4 — Edge ship
Models → Ship auto-pick (B5) → target compare → package → Download and/or Device assign (C1) → on-device metrics (C3) → Lineage.

### J5 — Agent + human gate
Generate (A5) or Editor Agent (B1) → rich diff → Accept & save (B2) / Reject → audit actors (B17) → optional fix-from-failure (A15).

### J6 — Backtrack
Any artifact/model/package/device build → Lineage (A7/A17) → Replay → Repro pack (B7) → Audit filter/export (A7) → Access when multi-user (C4).

**Done means:** J1–J6 by a new human **and** an MCP agent without leaving Graphyn.

---

## 8. Screen contracts (complete)

### 8.1 Home
- Situation strip: Mode, last run, pending agent items, always-on count, model prod pending, failed schedule badge  
- First-run cards (shipped) when empty  
- Pipelines: env badges, open Editor, **Rollback**, publish/request/approve  
- Linked datasets; Browse Artifacts  
- Always-on strip (B4)  
- Next actions: Template, Editor, Register model, Ship  
- Optional: pin favorites (B10); examples/mine filter (U1)

### 8.2 Editor
- Catalog (auth/offline/plugins empty — shipped) · canvas · inspector · log  
- Toolbar: Run, Validate, Save, Templates (shipped), Triggers (shipped), Agent (shipped)
- Triggers dock (A6) — interval schedules + global webhook honesty (A9/A10)
- Agent drawer (B1)
- HITL node UX (B6) — wait_delay callout
- Placement + Mode A ignored badge (A13)
- Credential picker (B8)
- Error/retry policy note (B9/B14)
- Narrow honesty banner (shipped)  
- Success toast View outputs (shipped)

### 8.3 Runs
- Tabs: History | **Live** (B3) | Compare  
- History: filters by metric/param (A12); multi-select callout before Compare (U2)  
- Compare: table + charts (A3); export CSV (D7)  
- Panels: Logs · Run outputs · Lineage · Details · Checkpoints  
- Actions: promote aliases, Register model (A4), Ship, Open Editor, Explain failure (A15)  
- Breadcrumb entity = short run id (U3)

### 8.4 Models *NEW*
- List/filter by project; versions; stages None/Staging/Production  
- Request prod / Approve prod (A1)  
- Register from run (A4/B11)  
- Trace + dataset links (B12)  
- Use in Ship CTA  

### 8.5 Datasets
- Browse/Manage; Which storage? strip (shipped)  
- Pins from Home  
- Label/collect lite (C2)  
- Ingest job progress / SSE (C14)

### 8.6 Artifacts
- Cross-run registry; prefer Run outputs for one run  
- Register model CTA (A4)  
- Trace / Replay / Repro (B7)

### 8.7 Ship (Edge)
- Tabs: Package | Devices  
- Package wizard (shipped) + auto model + target compare (B5)  
- Devices (C1); diagnostics (B16); metrics (C3)  
- Checksum/sign (D11)

### 8.8 Agent inbox
- List/filter (shipped); Generate (A5); rich diff  
- Accept / Accept & save (B2) / Reject  
- Partial apply (A16/D)  
- Actor chips (B17); MCP status (C9)

### 8.9 Templates
- Stamp into workspace (shipped); pinned on strip (shipped)

### 8.10 Plugins
- Install/catalog (shipped); venv GC (C12)

### 8.11 Worker fleet
- List/detail (shipped); deregister + Queue tab (A8)  
- Reclaim (B13); labels/pools (C7)

### 8.12 Secrets
- Name CRUD (shipped); used by credential picker (B8)

### 8.13 Ops
- Health/readiness/cleanup (shipped)  
- Schedules/webhooks = admin mirrors of Triggers  
- Audit filters/export (A7)  
- Metrics strip (C13)  
- Plugin GC entry (C12)

### 8.14 Access *NEW*
- Tokens, roles, actors (C4)  
- Maps to X-Actor honesty everywhere  

---

## 9. Cross-cutting UI rules

1. One noun per concept (§3).  
2. Every success has a next CTA.  
3. **Path URLs only** — deep link = same UX as nav; no hash navigation.  
4. Agents are users — actor chips; secrets never in IR or URLs.  
5. Backtrack is a primary verb on artifacts/models/packages/devices.  
6. Mode honesty — Local vs Distributed changes visible panels.  
7. URL is source of truth for workspace + entity; store mirrors URL.  
8. Production states: loading / empty / error / forbidden — every screen.  
9. Switch clears workspace (shipped); ConfirmButton armed feedback (shipped).  
10. Desktop-first Editor; observe-only mobile later (D15).

---

## 10. Usability pass-2 leftovers (include in plan)

| ID | Item | Phase |
|---|---|---|
| U1 | Soften e2e/examples noise — filter mine vs examples on Projects | A (with Home) |
| U2 | History multi-select affordance before Compare | A (with Runs) |
| U3 | Breadcrumbs derived from path routes | Phase 0 |

---

## 11. Full phased roadmap

### Phase 0 — Production foundation (before / with early A) — Shipped: BrowserRouter + path helpers; hash writes banned (legacy `#/` → path redirect only)

| ID | Deliverable | Area |
|---|---|---|
| R1 | `createBrowserRouter` path routes; ban hash writes | Routing — **Shipped**: `BrowserRouter` + `goView`/`navigatePath`; views no longer write `#/` |
| R2 | Typed path helpers; migrate `appStore` open* navigators | Routing — **helpers shipped** (`src/routes/paths.ts`, `viewMap.ts`); store migrate open |
| R3 | Layout routes: AppShell · WorkspaceLayout · outlets | Routing |
| R4 | Legacy `#/...` → path redirects + hit telemetry | Routing — **redirect map + `HashRedirect` shipped**; telemetry open |
| R5 | SPA fallback (nginx/Compose); optional `BASE_PATH` | Deploy |
| R6 | Document title + copy-link on run/model/proposal/lineage | Routing |
| P1–P5 | Auth guard, `/login?returnTo=`, settings, actor, 401 | Auth |
| P6–P10 | URL-owned workspace, server-state cache, dirty leave | State |
| P11–P15 | Error boundaries, skeletons, offline, 404/403 | Reliability |
| P16–P19 | Error reporting, correlation ids, flags, env badge | Ops |
| P20–P22 | Keyboard, a11y baseline, i18n string discipline | Quality |
| P23–P25 | CSP-friendly, sanitize previews, no secrets in URLs | Security |
| P26–P28 | Route code-split, virtualize lists, isolate Editor | Perf |
| P29–P32 | Redirect tests, E2E smoke, a11y CI, path contracts | QA |
| P33–P35 | Deploy fallback, base path, build SHA in Ops | Release |
| P36–P38 | Copy-link, open-in-new-tab, MCP/docs use path URLs | Collab |

### Phase A — Product surfaces over existing APIs

| ID | Deliverable | Pillar |
|---|---|---|
| A1 | Models screen: list + stages + request/approve prod — Shipped (partial) | MLflow |
| A2 | Pipeline rollback on Home — Shipped (partial) | n8n / Orch |
| A3 | Compare metric charts — Shipped (partial) | MLflow |
| A4 | Register model from Run outputs / Artifacts — Shipped | MLflow |
| A5 | Agent inbox Generate + richer IR/text diff — Shipped (partial) | Agentic |
| A6 | Canvas Triggers panel → schedules/webhooks APIs — Shipped | n8n |
| A7 | Audit filters + export; lineage via `/runs/:id/lineage` — Shipped (partial) | Account. |
| A8 | Worker deregister + job queue list — Shipped (partial; deregister + Queue honesty) | Orch |
| A9 | Cron UI + schedule bound to project pipeline — Shipped (partial; interval + cron honesty) | n8n |
| A10 | Per-workflow webhook wiring UI — Shipped (global URL honesty in Triggers) | n8n |
| A11 | Experiment create/rename/tag UI | MLflow |
| A12 | Run search by metric/param facet — Shipped (client-side) | MLflow |
| A13 | Mode A placement-ignored badge in Editor — Shipped | Orch |
| A14 | Ship IA: Edge → Ship tabs Package \| Devices — Shipped (lite) | Edge |
| A15 | Fix/explain failure → create proposal from run — Shipped | Agentic |
| A16 | Partial proposal apply (or stub → D) — Shipped (stub: disabled UI) | Agentic |
| A17 | Lineage header: graph hash + plugin versions — Shipped | Account. |
| U1 | Projects mine/examples filter | UX |
| U2 | History multi-select before Compare | UX |
| U3 | Breadcrumbs from path (with R3) | UX |

### Phase B — Journeys feel native

| ID | Deliverable | Pillar |
|---|---|---|
| B1 | Editor Agent side panel — Shipped | Agentic |
| B2 | Accept & save to pipeline + dirty-draft guard — Shipped (partial: Accept then save) | Agentic |
| B3 | Runs Live wave/worker view — Shipped | Orch |
| B4 | Home Always-on strip — Shipped | n8n |
| B5 | Ship auto-pick model + target comparison — Shipped (partial; registry auto-pick) | Edge |
| B6 | HITL / wait node UX — Shipped (wait_delay callout; HITL node needs-API) | n8n |
| B7 | Repro pack from Lineage — Shipped (client JSON pack; full freeze needs-API) | Account. |
| B8 | Credential picker in node config — Shipped | n8n |
| B9 | Error-branch / retry policy editor | n8n |
| B10 | Pin favorite pipelines on Home — Shipped | n8n |
| B11 | Explicit Register-as-model primary flow — Shipped (partial) | MLflow |
| B12 | Model card → Trace + dataset pins — Shipped (partial) | MLflow |
| B13 | Per-node reclaim / reassignment | Orch |
| B14 | Retry/timeout policy surface | Orch |
| B15 | Always-on schedule durability + last error — Shipped (partial) | n8n |
| B16 | Ship package diagnostics panel — Shipped (lite) | Edge |
| B17 | Actor chips on proposals + audit — Shipped (proposals) | Agentic / Account. |
| B18 | Proposal chat transcript retention — Shipped (localStorage) | Agentic |
| B19 | Model prod approval in Audit deep links | Account. |

### Phase C — Edge Impulse bar + multi-user

| ID | Deliverable | Pillar |
|---|---|---|
| C1 | Devices inventory + flash/OTA (`needs-API`) | Edge |
| C2 | Collect/label lite in Datasets — Shipped (callout / pins path) | Edge |
| C3 | On-device metrics → Runs/Models | Edge / MLflow |
| C4 | Access / RBAC UI + actors everywhere — Shipped (partial; actor + roles pending) | Account. |
| C5 | OTel span viewer (`needs-API`) | Account. |
| C6 | Subflows / reusable components | n8n |
| C7 | Worker labels/pools editor — Shipped (partial; display-only, no PATCH) | Orch |
| C8 | Guided impulse-style Ship path — Shipped (lite; Package\|Devices tabs) | Edge |
| C9 | MCP connection status in console — Shipped (honesty chip in Ops) | Agentic |
| C10 | optimize_execution suggestions in UI | Agentic |
| C11 | Downstream artifact consumers — Shipped (lite; field or needs-API note) | Account. |
| C12 | Plugin venv GC in Ops/Plugins — Shipped | Ops |
| C13 | System metrics product strip in Ops — Shipped | Orch |
| C14 | Ingest SSE / job progress in Datasets — Shipped | Datasets |

### Phase D — Polish to 100% feel

| ID | Deliverable | Pillar |
|---|---|---|
| D1 | Pipeline draft version diff on canvas | n8n |
| D2 | Richer live node execution overlay | n8n |
| D3 | Cross-project always-on dashboard | n8n |
| D4 | Nested runs / parent-child | MLflow |
| D5 | Artifact type icons + model preview — Shipped (partial) | MLflow |
| D6 | Compare code hash + data version — Shipped (when fields present) | MLflow |
| D7 | Export compare CSV — Shipped | MLflow |
| D8 | Schedule/SLA alerting — Shipped (lite; failed schedule row highlight) | Orch |
| D9 | Cache hit/miss indicators | Orch |
| D10 | Multi-target batch packages | Edge |
| D11 | Signed package / checksum UI — Shipped (lite; hash or honesty copy) | Edge |
| D12 | Proposal auto-bound to pipeline — Shipped (partial: project bind on Generate) | Agentic |
| D13 | Pipeline blame / edit history | Account. |
| D14 | Signed audit verification UX | Account. |
| D15 | Mobile observe-only | UX |
| D16 | Complete A16 if deferred | Agentic |

---

## 12. What not to build

- Separate MLflow or Edge apps with different IA  
- Chat-only LLM product without GraphIR  
- Second Project type  
- Fake Devices UI without registry API (stub + `needs-API` only)  
- Duplicating Trace/Compare as activity-bar peers  
- **Any new hash-based navigation**  
- Demo-only shortcuts that skip auth, audit, or shareable URLs  

---

## 13. Migration from current console

| Today | Target |
|---|---|
| Hash `#/...` + `view` enum | Path router + layout outlets |
| Home · Editor · Runs · … | Same IA under `/workspaces/:id/...` + global library/admin |
| Edge package | **Ship** at `/workspaces/:id/ship` |
| Proposals | **Agent inbox** at `/agent/inbox` |
| `#/trace`, `#/experiments` | `/workspaces/:id/runs/:runId/lineage`, `.../runs/compare` |
| Ad-hoc `replaceState` hashes | Typed `paths.*` helpers only |

---

## 14. Success metrics

| Metric | Target |
|---|---|
| Share run lineage URL with teammate | Opens same run lineage without hash |
| Time to first successful run | &lt; 10 min via Templates |
| Artifact → graph Trace | ≤ 2 clicks |
| Model staging → prod without CLI | 100% in Models UI |
| Agent proposal → saved pipeline | ≤ 3 clicks after review |
| Edge package → device assigned | Possible in Ship (Phase C) |
| Always-on failure → failed run | ≤ 2 clicks from Home |
| E2E smoke (login → run → lineage path) | Green in CI |
| J1–J6 without docs | Required for “100%” |

---

## 15. Implementation order (recommended)

0. **Phase 0 (R1–R6 + P\*)** — path router, layouts, auth guard, SPA fallback, redirects from `#/`  
1. **A1 + A4 + A3** — Models + register + charts  
2. **A2 + U1 + U2** — Home trust + picker filter + Compare affordance  
3. **A5 + A15** — Agentic create path  
4. **A6 + A9 + A10 + B4** — Triggers → Always-on  
5. **A7 + A17 + A8** — Accountability + queue  
6. **A14 + B5** then **C1** when device API exists  
7. Phase B Agent panel + Live + HITL  
8. Phase C Access + Devices + OTel  
9. Phase D polish  

---

## Related

- Vision: [PRODUCT_VISION.md](./PRODUCT_VISION.md)  
- Phase 1 IA (legacy notes): [IA_PROJECT_FIRST.md](./IA_PROJECT_FIRST.md) — **URL strategy superseded by §4.3 here**  
- Usability log: [UI_UX_REVIEW.md](./UI_UX_REVIEW.md)  
- Canvas: `graphyn-ui-north-star`
