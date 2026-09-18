# Graphyn — Software Requirements Specification (SRS) / Product Requirements Document

| Field | Value |
|---|---|
| **Title** | Graphyn Product Requirements Specification |
| **Document ID** | GRAPHYN-SRS-001 |
| **Version** | 0.1.0 |
| **Date** | 2026-09-18 (Asia/Calcutta) |
| **Status** | Draft |
| **Owners** | Product — Samir Kumar Mishra; Engineering — Graphyn maintainers |
| **Baseline tip** | `cursor/usecase-plugins-workflows` @ `9fccdd36` |
| **Audience** | Product managers, engineers, QA, agent implementers |

## 1. Document control

Fields above constitute document control for **GRAPHYN-SRS-001**. Change history: v0.1.0 initial draft from product docs + tip `9fccdd36`.

### Related documents

| Doc | Role |
|---|---|
| [PRODUCT_VISION.md](./PRODUCT_VISION.md) | North star: n8n + MLflow + orchestrator + Edge Impulse + agentic + accountability |
| [UI_NORTH_STAR.md](./UI_NORTH_STAR.md) | Target IA, path routes, pillar inventory, journeys J1–J6 |
| [UI_USER_REQUIREMENTS.md](./UI_USER_REQUIREMENTS.md) | User-voice page expectations (legacy hash notes; P0/P1 still valid) |
| [IA_PROJECT_FIRST.md](./IA_PROJECT_FIRST.md) | Workspace-first Decision B; pipeline envs |
| [UI_WORKSPACE_IDE.md](./UI_WORKSPACE_IDE.md) | Stable IDE rail contract |
| [UI_LINKAGE.md](./UI_LINKAGE.md) | Primary job + bridges per surface |
| [UI_FEATURE_AUDIT.md](./UI_FEATURE_AUDIT.md) | Page↔API feature audit structure |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | System layers |
| [API_REFERENCE.md](./API_REFERENCE.md) | REST `/api/v1/` |
| [PIPELINE_EXECUTION.md](./PIPELINE_EXECUTION.md) | Graph IR, waves, cache, checkpoints |
| [DISTRIBUTED_EXECUTION.md](./DISTRIBUTED_EXECUTION.md) | Mode B workers / placement |
| [TRUST_MODEL.md](./TRUST_MODEL.md) | Auth, secrets, egress |
| [MCP_SERVER.md](./MCP_SERVER.md) | Agent tools |
| [PLUGIN_GUIDE.md](./PLUGIN_GUIDE.md) | Plugin authoring |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Compose / production baseline |
| [KNOWN_ISSUES.md](./KNOWN_ISSUES.md) | Current limitations |

**Conventions:** Requirements use RFC 2119 **shall** / **should** / **may**. IDs are unique (`FR-*`, `UX-*`, `NFR-*`, `SEC-*`, `RT-*`, …). **Status** vs tip `9fccdd36`: Implemented · Partial · needs-API · Not started. Priority: **P0** (blocking use) · **P1** (product-feel) · **P2** (polish / later).

---

## 2. Purpose & scope

### 2.1 Purpose

This document is the **master requirements specification** for Graphyn: one control plane where humans and AI agents design typed DAG workflows, train/evaluate models, place work on the right machines, package for edge, and **always** answer *what ran, where, with which data/code, and who/what triggered it?*

It is intended for acceptance by a professional PM/eng team building an **n8n + MLflow + orchestrator + Edge Impulse + agentic** platform with full backtracking.

### 2.2 In scope

- Console (UI): every navigable surface, chrome, routing, Cmd-K, settings
- REST API (`/api/v1/`), CLI, Python SDK, MCP server
- Runtime: Graph IR, LocalPython + Distributed backends, pause/cancel/resume, cache, checkpoints, provenance, artifacts
- Plugins, secrets, schedules/webhooks, model registry, datasets/ingest
- Ship/edge packaging (and device loop when APIs exist)
- Security/trust, observability/audit, non-functionals, quality gates

### 2.3 Out of scope (this SRS still names them as future)

- Generic chat-only LLM product
- Replacing Kubernetes (workers/backends may *use* K8s later)
- Audio-only product identity (audio is a pack)
- Full multi-tenant IdP / SSO (required as future; not shipped)
- Cursor cloud / external cloud-agent product features

### 2.4 Deployment environment note (not a product requirement)

**Server-99**, Docker Compose, and similar lab hosts are **deployment environments**. Requirements shall not hard-code hostnames; they may cite Compose/nginx SPA fallback and Mode A/B as supported topologies.

---

## 3. Definitions / glossary

Aligned with [UI_NORTH_STAR.md](./UI_NORTH_STAR.md) §3 noun dictionary.

| Term | Definition | Not |
|---|---|---|
| **Workspace / Home** | Project context (pipelines + runs + linked data). **UI term is Workspace** (Project = Workspace); API may still say `project`. | Dataset-only folder |
| **Editor** | GraphIR canvas (Builder) | Raw route ids in chrome |
| **Runs** | Execution History + Live + Compare | The Editor **Run** button |
| **Run outputs** | Per-run downloadable files | Datasets or Artifacts library |
| **Artifacts** | Cross-run registry / ids | Run outputs panel |
| **Datasets** | Shared Inputs/Outputs under `workspace/datasets` | Run downloads |
| **Models** | Registry versions + stages | Raw trainer blobs until registered |
| **Ship** | Edge package + devices | Worker fleet |
| **Agent inbox** | Proposals + generate | Chat-only LLM product |
| **Lineage** | Backtrack chain (under Runs or artifact) | Separate daily-nav peer |
| **Triggers / Always-on** | Schedule / webhook / event on a graph | One-shot Editor Run |
| **Graph IR** | Canonical versioned JSON DAG (`schema_version` 1.2) | UI-only canvas state |
| **Mode A** | LocalPython backend — nodes run in API process | Requires workers |
| **Mode B** | `GRAPHYN_BACKEND=distributed` + registered workers | Edge packaging |
| **Actor** | Identity on mutations (`X-Actor`) | Full OIDC user (future) |
| **Route** | Path URL under History API | Hash `#/...` (retired) |

---

## 4. Stakeholders & personas

| Persona | Goals | Primary surfaces |
|---|---|---|
| **ML / workflow engineer** | Design graphs, run, compare, promote models | Editor, Runs, Models, Home |
| **Data engineer** | Ingest/upload datasets, version, link to workspace | Datasets, Home links |
| **Edge / embed engineer** | Package models for device runtimes | Ship, Models, Runs lineage |
| **Platform / ops** | Health, workers, schedules, cleanup, secrets | Ops, Workers, Secrets |
| **AI agent (MCP)** | Propose/validate/execute graphs with human gate | MCP + Agent inbox + Editor |
| **Reviewer / auditor** | Backtrack any artifact to graph+run+actor | Lineage, Audit, Access |
| **Product owner** | J1–J6 journeys complete without leaving Graphyn | All |

---

## 5. Product goals & success metrics

### 5.1 Goals

1. One product for Design · Learn · Execute · Ship · Collaborate with AI · Prove (accountability).
2. GraphIR is canonical across UI, API, CLI, MCP.
3. Everything meaningful is a **run** or **artifact** with lineage.
4. Agents are first-class users; secrets never embedded in IR or URLs.
5. Placement is explicit (Mode A honesty vs Mode B workers).

### 5.2 Success metrics (shall be measurable)

| ID | Metric | Target |
|---|---|---|
| SM-001 | Time to first successful run via Templates | ≤ 10 minutes (P0 path) |
| SM-002 | Artifact → graph Trace | ≤ 2 clicks |
| SM-003 | Share run lineage URL | Opens same run lineage (path URL, no hash) |
| SM-004 | Model staging → prod without CLI | 100% via Models UI when APIs available |
| SM-005 | Agent proposal → saved pipeline | ≤ 3 clicks after review |
| SM-006 | Always-on failure → failed run | ≤ 2 clicks from Home |
| SM-007 | E2E smoke login → run → lineage path | Green in CI |
| SM-008 | Journeys J1–J6 | Completable by human **and** MCP agent without leaving Graphyn |

---

## 6. System context

### 6.1 Logical context

```
Humans (Console) ─┐
CLI / SDK ────────┼──► FastAPI /api/v1 ──► RuntimeBackend
MCP agents ───────┘         │                 ├── LocalPython (Mode A)
                            │                 └── Distributed (Mode B + workers)
                            ▼
              Run journal · Artifacts · Provenance · Secrets · Plugins
```

### 6.2 Mode A / Mode B

| | Mode A (default) | Mode B |
|---|---|---|
| Backend | LocalPython | `GRAPHYN_BACKEND=distributed` |
| Who runs nodes | API process / single box | Control plane + workers by labels/GPU/pool |
| Workers UI | Empty is OK (honest copy) | Live heartbeats, stale, labels, GPU |
| Placement IR | Optional; ignored | Routes GPU / pool work |

**FR-CTX-001** The system **shall** expose backend mode honestly in readiness (`backend_mode`) and console Mode chip.  
**FR-CTX-002** Mode A empty Workers **shall not** present as an error state.  
**Priority:** P0 · **Status:** Implemented (partial Mode chip / Workers empty)

### 6.3 Interfaces

- REST `/api/v1/*` (Bearer when configured)
- MCP stdio JSON-RPC (~28–29 tools)
- Console SPA (path routes; nginx SPA fallback)
- Static file mounts for datasets / run files (same bearer policy when token set)

---

## 7. Information architecture & navigation

### 7.1 Stable IDE rail (locked)

**UX-NAV-001** The left sidebar **shall** always present the same structure:
1. **Workspace strip:** Home · Editor · Runs · Models · Ship · Datasets  
2. **Groups:** Build (Templates, Agent inbox) · Library (Plugins, Artifacts) · Deploy (Workers) · Admin (Secrets, Ops, Access)

**UX-NAV-002** Models, Ship, and Datasets **shall** live on the workspace strip only — **not** as Library/Deploy peers.  
**UX-NAV-003** Artifacts **shall not** be a workspace-strip peer; it remains Library-secondary.  
**UX-NAV-004** When no `activeProject`, strip items Editor/Runs/Models/Ship/Datasets **shall** be disabled with “Open a project first”.  
**UX-NAV-005** Lineage and Compare **shall not** be activity-bar peers; they live under Runs (or deep links).  
**UX-NAV-006** Navigation **shall** use path URLs only; new features **shall not** write `location.hash`.  
**UX-NAV-007** Legacy `#/...` **shall** redirect to path equivalents for ≥1 release window.  
**UX-NAV-008** Breadcrumbs **should** mirror path: `Workspaces / {id} / {Surface} / {entityShort}`.  
**UX-NAV-009** Document title **should** be `Graphyn · {surface} · {workspace?}`.

**Priority:** P0 · **Status:** Implemented (rail + path helpers; breadcrumb/title partial)

### 7.2 Path map (required routes)

Workspace: `/workspaces`, `/workspaces/:id`, `.../editor[/pipelines/:p[/:env]]`, `.../runs[/live|/compare|/:runId[/{panel}]]`, `.../models[/:name]`, `.../datasets`, `.../ship[/devices]`.

Global: `/login`, `/settings`, `/templates`, `/agent/inbox[/:id]`, `/library/{datasets,plugins,artifacts}`, `/deploy/workers[/queue]`, `/admin/{secrets,ops[/audit],access}`, `/404`.

Canonicalization: `/library/models`, `/library/datasets`, `/deploy/ship` **should** redirect into workspace flows when product policy requires (see UI_WORKSPACE_IDE).

---

## 8. Cross-cutting functional requirements

### 8.1 Auth, token, actor

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-AUTH-001 | Unauthenticated users **shall** be directed to `/login` or Settings with `returnTo` when API returns 401 | P0 | Partial |
| FR-AUTH-002 | Console **shall** store API Bearer token (Settings); values **shall not** appear in URLs or GraphIR | P0 | Implemented |
| FR-AUTH-003 | When `GRAPHYN_API_TOKEN` set, API **shall** require Bearer; fail-closed when auth required / prod|staging | P0 | Implemented |
| FR-AUTH-004 | Mutations **shall** accept `X-Actor` for audit; console **shall** allow editing actor (Access / localStorage) | P1 | Implemented |
| FR-AUTH-005 | Auth honesty banner **shall** distinguish Connected / Sign in required / Can't reach API | P0 | Implemented |
| FR-AUTH-006 | Full RBAC (roles, per-project ACL, SSO) **shall** be deferred; Access UI **may** stub until APIs exist | P2 | Partial / needs-API |

### 8.2 Errors, empty, loading

| ID | Requirement | Pri | Status |
|---|---|---|---|
| UX-STATE-001 | Every primary surface **shall** define loading, empty, and error states (no blank white) | P0 | Partial |
| UX-STATE-002 | Empty states **shall** offer a next-click CTA | P0 | Implemented (most) |
| UX-STATE-003 | Destructive actions **shall** require confirm (armed button / typed CLEANUP for cleanup) | P0 | Implemented |
| UX-STATE-004 | Toasts **shall** cover success/error/info; dismissible | P0 | Implemented |
| UX-STATE-005 | Per-route error boundary **should** provide recovery CTA | P1 | Partial |
| UX-STATE-006 | Offline / API-down **should** show retry wall | P1 | Partial |

### 8.3 Routing & deep links

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-ROUTE-001 | Deep links **shall** survive refresh for workspace, run, panel, proposal, artifact query | P0 | Implemented |
| FR-ROUTE-002 | Cross-links **shall** pass context (`run_id`, project, artifact_id) — users **shall not** re-paste IDs for primary flows | P0 | Implemented |
| FR-ROUTE-003 | URL **shall** be source of truth for workspace id; store mirrors URL | P0 | Partial |
| FR-ROUTE-004 | Copy-link **should** exist on run, model, proposal, lineage | P1 | Partial |
| FR-ROUTE-005 | Open-in-new-tab **shall** work for primary resources | P1 | Partial |

### 8.4 Command palette & shortcuts

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-CMDK-001 | ⌘/Ctrl+K (and `/` where scoped) **shall** open Command palette | P1 | Implemented |
| FR-CMDK-002 | Jump keys **shall** match sidebar destinations (incl. Secrets, Models, Access) | P1 | Implemented |
| FR-CMDK-003 | `?` **shall** open keyboard help overlay; Esc closes | P1 | Implemented |

### 8.5 Linkage rule

**UX-LINK-001** Each surface **shall** have one primary job and explicit bridges (see §9 and UI_LINKAGE). Observe duplication (Trace/Compare as strip peers) **shall not** return.

---

## 9. Per-surface functional requirements

Status assessed against tip `9fccdd36` and feature audit honesty.

---

### 9.1 Login (`/login`)

**Purpose:** Enter Bearer token and continue to `returnTo`.  
**Actors:** Human operator.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-LOGIN-001 | System **shall** provide token input and Continue that persists token client-side | P0 | Implemented |
| FR-LOGIN-002 | After save, system **should** verify token (e.g. readiness/nodes) before claiming success | P1 | Not started |
| FR-LOGIN-003 | Enter key **shall** submit the form | P2 | Partial |
| FR-LOGIN-004 | 401 remediation **may** use Settings drawer; `/login` **shall** remain a valid path | P1 | Partial |

**Acceptance:** Given valid token When Continue Then subsequent catalog calls succeed. Given invalid token When verified Then user sees clear failure (when FR-LOGIN-002 shipped).

**Data/API:** Client-only today; optional `GET /system/auth-status` or `GET /nodes`.

---

### 9.2 Workspaces / Home (`/workspaces`, `/workspaces/:id`)

**Purpose:** Pick/create workspace; situation strip; pipelines + envs; always-on; linked datasets; next actions.  
**Actors:** Engineer, agent (via project APIs).

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-HOME-001 | User **shall** create, open, filter (mine/examples), rename, clone, delete projects | P0 | Implemented |
| FR-HOME-002 | Home **shall** list project pipelines with draft/staging/prod and open Editor | P0 | Implemented |
| FR-HOME-003 | User **shall** Publish→staging, Request prod, Approve prod, Rollback draft when APIs allow | P0 | Implemented |
| FR-HOME-004 | Home **shall** show recent runs scoped by `?project=` and open run detail | P0 | Implemented |
| FR-HOME-005 | Home **shall** show Always-on schedules for the workspace with Run now + link to Ops | P1 | Implemented |
| FR-HOME-006 | User **shall** link/unlink dataset inputs; Browse library/Artifacts | P0 | Implemented |
| FR-HOME-007 | User **should** pin favorite pipelines | P2 | Implemented |
| FR-HOME-008 | Spec/taxonomy/contract/versions/snapshots/diff **shall** remain available (collapsed OK) | P1 | Implemented |
| FR-HOME-009 | Situation strip **should** show Mode, last run, pending proposals, always-on count, failed schedule | P1 | Partial |
| FR-HOME-010 | Partial API failure on Home load **shall not** silently blank successful sections | P1 | Partial (known gap) |

**UI/UX:** First-run cards when empty; CTAs Template / Editor / Register model / Ship.  
**Data/API:** `/projects*`, `/runs?project=`, `/system/schedules`, `/data/inputs`, pipeline publish/promote/rollback.  
**Acceptance:** Given project with pipeline When Publish staging Then env badge updates. Given no versions When open Versions Then honest empty + CTAs.

---

### 9.3 Editor (`/workspaces/:id/editor...`)

**Purpose:** Design Graph IR, validate, run, save, triggers, agent propose.  
**Actors:** Engineer, agent (proposals).

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-ED-001 | Canvas **shall** add/wire nodes from catalog with typed ports, config from schema, zoom/pan | P0 | Implemented |
| FR-ED-002 | Validate **shall** surface errors; Run disabled on empty canvas | P0 | Implemented |
| FR-ED-003 | Run **shall** stream events (NDJSON); Cancel **shall** cancel backend run (`POST /runs/{id}/cancel`) and abort stream | P0 | Partial (UI cancel vs backend gap) |
| FR-ED-004 | Save to project pipeline **shall** persist Graph IR under workspace pipelines | P0 | Implemented |
| FR-ED-005 | Import/export graph and save-as-template **shall** work | P0 | Implemented |
| FR-ED-006 | Triggers dock **shall** manage schedules for current pipeline and show webhook honesty | P1 | Implemented |
| FR-ED-007 | Agent drawer **shall** create proposals into Agent inbox | P1 | Implemented |
| FR-ED-008 | Credential picker **shall** select secret **names** only | P1 | Implemented |
| FR-ED-009 | Mode A **shall** show placement-ignored badge; Mode B **shall** expose placement fields | P1 | Implemented |
| FR-ED-010 | Load/save **shall** preserve edge conditions, event triggers, labels, graph parameters (no silent strip) | P0 | Partial (known strip bug) |
| FR-ED-011 | Dirty Editor **should** block route leave with confirm | P1 | Partial |
| FR-ED-012 | HITL / wait node UX **should** guide operators; full HITL node **may** be needs-API | P2 | Partial |
| FR-ED-013 | Subflows **may** be deferred | P2 | Not started / needs-API |

**Bridges:** Run → Runs panels; Templates stamp → Editor; Accept proposal → Editor; dataset chip → Datasets.  
**Acceptance:** Given valid graph Mode A When Run Then `run_id` + last-run strip. Given Projects Open in Builder Then dataset chip shows project/version.

---

### 9.4 Runs — History / Live / Compare + panels

**Paths:** `/workspaces/:id/runs`, `.../live`, `.../compare`, `.../:runId/{logs|outputs|lineage|details|checkpoints}`  
**Purpose:** Execution ops, live waves, compare experiments, lineage — not a second Editor.  
**Actors:** Engineer, auditor, agent (inspect/control).

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-RUN-001 | History **shall** list runs (project-scoped when workspace open) with status, time, id, filters | P0 | Implemented |
| FR-RUN-002 | Detail **shall** support Pause / Resume / Cancel (stale-aware) / Delete terminal | P0 | Implemented |
| FR-RUN-003 | Panels **shall** include Logs, Outputs (Run outputs), Lineage, Details/Debug, Checkpoints | P0 | Implemented |
| FR-RUN-004 | Live **shall** poll running/pending with node/worker visibility | P1 | Implemented |
| FR-RUN-005 | Compare **shall** select 2–5 runs; params/metrics table; honest empty metrics; charts/CSV when available | P1 | Implemented |
| FR-RUN-006 | Promote aliases and Register model **shall** be available from succeeded runs | P1 | Implemented |
| FR-RUN-007 | Mode B **shall** show `node → worker` chips when placement map exists | P1 | Implemented |
| FR-RUN-008 | Explain/fix failure **shall** create an agent proposal | P1 | Implemented |
| FR-RUN-009 | Lineage panel **shall** show hop chain, graph hash/plugin versions header, repro pack (lite OK) | P0 | Implemented |
| FR-RUN-010 | Standalone Trace page **shall not** be required for daily nav; run lineage path is canonical | P0 | Implemented (TraceView demoted) |
| FR-RUN-011 | Error `detail` objects from run_control **should** surface precise messages in UI | P1 | Partial |

**Acceptance:** Given completed run When open lineage Then chain loads without pasting id. Given stale RUNNING When Cancel Then leaves running. Given ≥2 metric runs When Compare Then diffs highlight.

---

### 9.5 Models (`/workspaces/:id/models`)

**Purpose:** Registry list/stages; request/approve prod; register from runs; link Trace/datasets/Ship.  
**Actors:** ML engineer, auditor.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-MOD-001 | List/filter models; show stages latest/staging/prod and pending_prod | P0 | Implemented |
| FR-MOD-002 | Request prod / Approve prod **shall** call registry APIs from UI | P0 | Implemented |
| FR-MOD-003 | Register model from run id/slug **shall** work | P0 | Implemented |
| FR-MOD-004 | Model card **shall** deep-link Trace/run and **should** link datasets | P1 | Partial |
| FR-MOD-005 | Use in Ship CTA **should** prefill package wizard | P1 | Partial |
| FR-MOD-006 | Workspace scope vs all-registries **shall** be clear | P1 | Implemented |

**Acceptance:** Given staging model When Approve prod Then stage updates and audit can record actor.  
**Data/API:** `GET/POST /models`, `.../request-prod`, `.../approve-prod`.

---

### 9.6 Ship (+ Devices) (`/workspaces/:id/ship`, `.../ship/devices`)

**Purpose:** Optimize + package trained model; devices when API exists.  
**Actors:** Edge engineer.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-SHIP-001 | Package wizard **shall** support template → configure → run-async → download | P0 | Implemented |
| FR-SHIP-002 | Missing model path **shall** warn with CTAs (Templates/Editor/Artifacts) | P0 | Implemented |
| FR-SHIP-003 | Tabs Package \| Devices **shall** exist; Devices **may** be needs-API stub | P1 | Implemented (Devices stub) |
| FR-SHIP-004 | Auto-pick model from registry **should** work | P1 | Partial |
| FR-SHIP-005 | Package diagnostics + lineage bar **shall** link source run | P1 | Implemented |
| FR-SHIP-006 | Device inventory, flash, OTA **shall** require device registry API | P2 | needs-API |
| FR-SHIP-007 | On-device metrics → Runs/Models **shall** require API | P2 | needs-API |

**Acceptance:** Given valid model When Run then Download Then package file downloads. Given Devices tab When no API Then honest needs-API empty (not fake devices).

---

### 9.7 Datasets (`/workspaces/:id/datasets`, `/library/datasets`)

**Purpose:** Files in / files out under `workspace/datasets/` — not project metadata editor.  
**Actors:** Data engineer.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-DATA-001 | Browse Inputs/Outputs; Manage Upload/Ingest/Merge | P0 | Implemented |
| FR-DATA-002 | Paths **shall** stay jailed inside workspace (symlink policy per TRUST_MODEL) | P0 | Implemented |
| FR-DATA-003 | Merge **shall** create target project/version consumable by Home/Projects | P1 | Implemented |
| FR-DATA-004 | Ingest (URL/HF) **shall** show progress/log; SSE when available | P1 | Implemented |
| FR-DATA-005 | Mode B **should** warn about shared storage for workers | P2 | Partial |
| FR-DATA-006 | Collect/label lite **may** use project annotations APIs | P2 | Partial / needs-UI |

**Acceptance:** Given upload When complete Then label lists file. Given output version When browse Outputs Then only version dirs shown as versions.

---

### 9.8 Templates (`/templates`)

**Purpose:** Stamp known-good graphs into a workspace then open Editor.  
**Actors:** Engineer.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-TPL-001 | List Examples/Saved; search; sync examples; open stamps into project | P0 | Implemented |
| FR-TPL-002 | Without active project, gate create/select before stamp | P0 | Implemented |
| FR-TPL-003 | Save from Editor **shall** create Saved card | P1 | Implemented |
| FR-TPL-004 | Category tags on cards **should** improve gallery | P2 | Not started |

**Acceptance:** Given Sync examples When Open Then IR loads in Editor under chosen workspace.

---

### 9.9 Agent inbox (`/agent/inbox`, `/:proposalId`)

**Purpose:** Review agent graph proposals — Accept → Editor; not a second Builder.  
**Actors:** Human reviewer, MCP agent.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-AGT-001 | List/filter by status; detail with structural diff; Accept/Reject | P0 | Implemented |
| FR-AGT-002 | Accept **shall** load graph into Editor with toast | P0 | Implemented |
| FR-AGT-003 | Generate in UI **shall** create proposals (API/MCP parity) | P1 | Partial |
| FR-AGT-004 | Accept & save to pipeline + dirty-draft guard **should** exist | P1 | Partial |
| FR-AGT-005 | Actor chips **shall** show human vs agent | P1 | Implemented |
| FR-AGT-006 | Partial apply **may** stay stub until API | P2 | Partial (stub) |
| FR-AGT-007 | MCP connection status **should** appear in console (Ops honesty OK) | P2 | Partial |

**Acceptance:** Given pending proposal When Accept Then Editor has graph. Given Reject Then leaves pending; audit event.

---

### 9.10 Artifacts (`/library/artifacts`)

**Purpose:** Cross-run registry browse/download/replay/Trace — prefer Run outputs for one run.  
**Actors:** Engineer, auditor.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-ART-001 | Filter by run/type; detail Trace/Download/Open run/Replay | P0 | Implemented |
| FR-ART-002 | Copy **shall** clarify Runs→Outputs vs Artifacts library | P1 | Implemented |
| FR-ART-003 | Register model CTA **should** appear when applicable | P1 | Partial |
| FR-ART-004 | Repro pack **should** download from lineage | P1 | Partial |

**Acceptance:** Given `artifactId` query When open Then detail focuses that artifact.

---

### 9.11 Plugins (`/library/plugins`)

**Purpose:** Install node packs so Editor catalog fills.  
**Actors:** Platform eng, engineer.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-PLG-001 | Install from path/package/git/https; enable/disable/uninstall | P0 | Implemented |
| FR-PLG-002 | Deps install **shall** show real package names + progress | P0 | Implemented |
| FR-PLG-003 | After install, catalog refresh **shall** be visible to user | P1 | Partial |
| FR-PLG-004 | Venv GC **should** be available from Ops/Plugins | P2 | Implemented |
| FR-PLG-005 | Mode B **should** document worker plugin parity | P2 | Partial |

**Acceptance:** Given valid plugin When Install Then appears Installed and nodes list in Editor after refresh.

---

### 9.12 Workers (`/deploy/workers`, `/queue`)

**Purpose:** Monitor Mode B workers — not Edge flash.  
**Actors:** Ops, engineer.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-WRK-001 | Mode A empty **shall** explain local mode + copyable CLI | P0 | Implemented |
| FR-WRK-002 | Mode B table **shall** show heartbeat, stale, labels, GPU/VRAM, refresh | P0 | Implemented |
| FR-WRK-003 | Deregister worker **shall** be available | P1 | Implemented |
| FR-WRK-004 | Job queue visibility **should** list jobs (honesty if list-all limited) | P1 | Partial |
| FR-WRK-005 | Reclaim / labels PATCH **may** need API/UI completion | P2 | Partial / needs-API |

**Acceptance:** Given no workers When open Then not an error. Given live worker When heartbeat old Then Stale chip.

---

### 9.13 Secrets (`/admin/secrets`)

**Purpose:** Named credentials for runs — never in Graph IR.  
**Actors:** Ops, engineer.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-SEC-001 | Store/list/delete **names**; values never re-displayed | P0 | Implemented |
| FR-SEC-002 | Replace same name **shall** confirm | P1 | Implemented |
| FR-SEC-003 | Docs/UI **shall** state workers resolve names via platform (not IR) | P1 | Partial |

**Acceptance:** Given store OPENAI_API_KEY When list Then name only.

---

### 9.14 Ops (`/admin/ops`, `/admin/ops/audit`)

**Purpose:** Health, schedules/webhooks mirrors, cleanup, audit, metrics.  
**Actors:** Ops, auditor.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-OPS-001 | Health/readiness/metrics cards **shall** load; Raw JSON collapsed | P0 | Implemented |
| FR-OPS-002 | Schedules CRUD + tick; webhook URL save/test | P0 | Implemented |
| FR-OPS-003 | Cleanup **shall** default non-destructive; require typed CLEANUP; never delete running runs / examples / datasets/input | P0 | Implemented |
| FR-OPS-004 | Audit table **shall** show when/actor/action/resource; filters/export **should** | P1 | Partial |
| FR-OPS-005 | Backend mode + worker count **should** surface when distributed | P1 | Partial |
| FR-OPS-006 | Build SHA / version **should** appear | P2 | Partial |

**Acceptance:** Given accepted proposal When refresh Audit Then event row. Given CLEANUP confirm Then toast summarizes deletions.

---

### 9.15 Access (`/admin/access`)

**Purpose:** Actors, tokens, future roles.  
**Actors:** Admin.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-ACS-001 | Edit actor identity for `X-Actor` | P1 | Implemented |
| FR-ACS-002 | Link to API token Settings | P1 | Implemented |
| FR-ACS-003 | Roles matrix (admin/prod-approve/secret-write) **shall** wait for multi-user API | P2 | needs-API |

**Acceptance:** Given actor set When mutate Then audit shows actor.

---

### 9.16 Command palette

**Purpose:** Fast jump across surfaces/entities.  
**Actors:** All humans.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-PAL-001 | Palette **shall** navigate to primary views and recent resources when listed | P1 | Implemented |
| FR-PAL-002 | Keyboard nav ↑↓ Enter Esc **shall** work | P1 | Implemented |

---

### 9.17 Settings

**Purpose:** API base URL / Bearer token / preferences.  
**Actors:** All humans.

| ID | Requirement | Pri | Status |
|---|---|---|---|
| FR-SET-001 | Settings panel **shall** edit/clear API token and refresh catalog | P0 | Implemented |
| FR-SET-002 | `/settings` path **should** exist as first-class route (drawer OK interim) | P1 | Partial |
| FR-SET-003 | Env badge (local/staging/prod API) **should** appear in shell | P2 | Partial |

---

## 10. Runtime / pipeline requirements

| ID | Requirement | Pri | Status |
|---|---|---|---|
| RT-001 | Graph IR **shall** be canonical (`schema_version` 1.2); UI/API/CLI/MCP speak same IR | P0 | Implemented |
| RT-002 | `get_backend().execute(graph)` **shall** be the execution entry | P0 | Implemented |
| RT-003 | Planner **shall** topo-sort into waves; parallel execution within wave | P0 | Implemented |
| RT-004 | Pause / resume / cancel **shall** work for active runs | P0 | Implemented |
| RT-005 | Per-node checkpoints **shall** support resume/inspect samples | P0 | Implemented |
| RT-006 | Pipeline cache **shall** key by content hash; skip on hit when enabled | P1 | Implemented |
| RT-007 | Edge conditions **shall** skip/branch safely (evaluator) | P1 | Implemented (runtime); UI strip Partial |
| RT-008 | ProvenanceStore **shall** record lineage for artifacts | P0 | Implemented |
| RT-009 | ArtifactStore **shall** content-address artifacts; download/replay | P0 | Implemented |
| RT-010 | Schedules **shall** fire runs (interval; cron honesty); default env=prod for scheduled | P1 | Partial |
| RT-011 | Outbound webhooks **shall** fire on terminal run states when configured | P1 | Implemented |
| RT-012 | Run journal **shall** persist meta, graph, logs under run dir | P0 | Implemented |
| RT-013 | Secret resolution in nodes **shall** use names; fail closed if required secret missing | P0 | Implemented |
| RT-014 | Retry policies **should** be configurable per node | P2 | Partial |

**Acceptance:** Given Graph IR with two parallel nodes When execute Then both complete in same wave when independent. Given cancel When in-flight Then no further side effects after cancel acknowledged.

---

## 11. Model registry & promote requirements

| ID | Requirement | Pri | Status |
|---|---|---|---|
| MR-001 | Register model from run artifact/slug | P0 | Implemented |
| MR-002 | Promote aliases `latest` \| `staging` \| `prod` on runs | P0 | Implemented |
| MR-003 | `request-prod` / `approve-prod` gate with audit | P0 | Implemented (API+UI) |
| MR-004 | Pipeline env pointers (draft/versions/staging/prod) separate from model stages but linked in UX | P0 | Implemented |
| MR-005 | Model → training run → dataset version links **should** be first-class | P1 | Partial |

---

## 12. Distributed / Mode B requirements

| ID | Requirement | Pri | Status |
|---|---|---|---|
| DIST-001 | Workers register/heartbeat/deregister with bearer | P0 | Implemented |
| DIST-002 | Job claim/complete/events/cancel APIs **shall** exist | P0 | Implemented |
| DIST-003 | IR placement (auto/worker/pool/gpu) **shall** route work in Mode B | P0 | Implemented |
| DIST-004 | Run detail **shall** expose `distributed_node_workers` map | P1 | Implemented |
| DIST-005 | Blob transfer for artifacts across workers **shall** work | P1 | Implemented |
| DIST-006 | Mid-flight reclaim / reassignment UX **may** follow API | P2 | Partial |
| DIST-007 | OTel spans per node/job across workers **may** be Phase C+ | P2 | needs-API |

---

## 13. Plugin system requirements

| ID | Requirement | Pri | Status |
|---|---|---|---|
| PLG-SYS-001 | Plugins **shall** install via PluginManager (path/pkg/git/https) with optional SHA256 | P0 | Implemented |
| PLG-SYS-002 | Manifest + registry registration **shall** expose nodes to catalogue | P0 | Implemented |
| PLG-SYS-003 | Isolated runtime (`iso`) **should** be indicated in catalog | P1 | Implemented |
| PLG-SYS-004 | Remote install allowlist **shall** fail closed when auth required | P0 | Implemented |
| PLG-SYS-005 | Enable/disable/uninstall **shall** update catalog on refresh | P0 | Implemented |

---

## 14. MCP / agent requirements

| ID | Requirement | Pri | Status |
|---|---|---|---|
| MCP-001 | MCP **shall** expose discovery, graph validate/generate, execute, run control, artifacts/lineage/replay, plugins, secrets (names), proposals, experiments, trace, projects/data list | P0 | Implemented (~28–29 tools) |
| MCP-002 | Auth **shall** mirror API token policy; `accept_proposal` gated by `GRAPHYN_MCP_HUMAN_APPROVAL` | P0 | Implemented |
| MCP-003 | Agents **shall not** receive secret values via list tools | P0 | Implemented |
| MCP-004 | Propose → human Accept in UI **shall** be the default apply path | P0 | Implemented |
| MCP-005 | Schedules/workers/ingest **may** remain REST-only (documented) | P1 | Implemented (intentional) |
| MCP-006 | Docs/MCP **shall** cite path URLs not hashes | P1 | Partial |

---

## 15. Edge / Ship / device requirements

| ID | Requirement | Pri | Status |
|---|---|---|---|
| EDGE-001 | edge_optimizer + deployment_packager path via template/wizard | P0 | Implemented |
| EDGE-002 | Download package artifact from completed ship run | P0 | Implemented |
| EDGE-003 | Promote package env staging/prod when supported | P1 | Partial |
| EDGE-004 | Device registry / flash / OTA | P2 | needs-API |
| EDGE-005 | Signed package / checksum display | P2 | Partial |
| EDGE-006 | Multi-target batch packages | P2 | Not started |

---

## 16. Data / datasets / ingest requirements

| ID | Requirement | Pri | Status |
|---|---|---|---|
| DATA-SYS-001 | Inputs under `datasets/input/{label}`; outputs under `datasets/output/{project}/...` | P0 | Implemented |
| DATA-SYS-002 | URL + HuggingFace ingest | P1 | Implemented |
| DATA-SYS-003 | Project versions, snapshots, lineage, quality APIs **may** exceed UI coverage | P2 | Partial (API > UI) |
| DATA-SYS-004 | Annotations / curation / quality-check **should** gain UI when product prioritizes label lite | P2 | needs-UI |

---

## 17. Security & trust requirements

| ID | Requirement | Pri | Status |
|---|---|---|---|
| SEC-001 | Shared-bearer single-tenant model **shall** be documented; no fake RBAC claims | P0 | Implemented (TRUST_MODEL) |
| SEC-002 | Secrets: 0700/0600 files; API names only; resolve in-process | P0 | Implemented |
| SEC-003 | Secrets **shall never** appear in Graph IR, URLs, or logs | P0 | Implemented (validate fail-closed) |
| SEC-004 | `python_code` **shall** use AST filters; **shall not** be marketed as a sandbox | P0 | Implemented |
| SEC-005 | HTTP egress restricted mode + allowlist **shall** be available | P1 | Implemented |
| SEC-006 | Platform webhooks **shall** block private/loopback | P0 | Implemented |
| SEC-007 | Sanitize artifact/JSON previews in UI | P1 | Partial |
| SEC-008 | CSP-friendly build; no inline secret logging | P1 | Partial |
| SEC-009 | Future: cross-project ACL default-deny when multi-user ships | P2 | Not started |

---

## 18. Observability & audit

| ID | Requirement | Pri | Status |
|---|---|---|---|
| OBS-001 | Append-only audit events for mutations (proposals, envs, etc.) | P0 | Implemented |
| OBS-002 | `GET /trace` unified backtrack payload | P0 | Implemented |
| OBS-003 | Audit filters (actor/resource/time) + export | P1 | Partial |
| OBS-004 | Client error reporting hook (env-flagged) | P2 | Not started |
| OBS-005 | Correlation ids on failure UI | P1 | Partial |
| OBS-006 | OTel span viewer | P2 | needs-API |

---

## 19. Non-functional requirements

### 19.1 Performance

| ID | Requirement | Pri | Status |
|---|---|---|---|
| NFR-PERF-001 | Route-level code splitting for features | P1 | Partial |
| NFR-PERF-002 | Virtualize long run/log/artifact lists | P1 | Partial |
| NFR-PERF-003 | Editor bundle isolated from observe routes | P1 | Partial |
| NFR-PERF-004 | Catalog/list endpoints **should** respond < 2s on lab hardware for ≤1k nodes/runs page | P2 | Not measured |

### 19.2 Accessibility

| ID | Requirement | Pri | Status |
|---|---|---|---|
| NFR-A11Y-001 | Keyboard nav for shell + tables; focus traps in dialogs | P1 | Partial |
| NFR-A11Y-002 | WCAG AA for core flows (contrast, labels, live regions) | P1 | Partial |
| NFR-A11Y-003 | `aria-current` on active nav | P0 | Implemented |

### 19.3 i18n

| ID | Requirement | Pri | Status |
|---|---|---|---|
| NFR-I18N-001 | New user-facing strings **should** be key-disciplined (i18n-ready) | P2 | Partial |
| NFR-I18N-002 | Full locale packs **may** be deferred | P2 | Not started |

### 19.4 Browser support

| ID | Requirement | Pri | Status |
|---|---|---|---|
| NFR-BRW-001 | Desktop Chrome/Edge/Firefox latest-2 **shall** be supported | P0 | Implemented (target) |
| NFR-BRW-002 | Mobile observe-only **may** be Phase D | P2 | Not started |
| NFR-BRW-003 | Desktop-first Editor (wide canvas) | P0 | Implemented |

### 19.5 Reliability

| ID | Requirement | Pri | Status |
|---|---|---|---|
| NFR-REL-001 | SPA fallback for non-`/api` paths in Compose/nginx | P0 | Implemented |
| NFR-REL-002 | Stale RUNNING detection + cancel path | P0 | Implemented |
| NFR-REL-003 | Schedule durability across process restart **should** improve | P1 | Partial |
| NFR-REL-004 | Optional `GRAPHYN_UI_BASE_PATH` | P2 | Partial |

---

## 20. Quality gates

| ID | Requirement | Pri | Status |
|---|---|---|---|
| QA-001 | Unit tests for path helpers and legacy hash redirects | P0 | Partial |
| QA-002 | API/router unit tests for project scoping, runs filter, pipelines | P0 | Implemented (areas) |
| QA-003 | E2E smoke: login → workspace → run → lineage path in CI | P1 | Partial |
| QA-004 | `graphyn-ui` production build **shall** pass on tip | P0 | Assumed CI |
| QA-005 | Contract tests path helpers ↔ API ids | P1 | Partial |
| QA-006 | a11y CI checks on shell + Runs | P2 | Not started |
| QA-007 | Docker IDE loop smoke script **should** remain green | P1 | Implemented (script) |

---

## 21. Out of scope / future

- SSO / OIDC / full RBAC / multi-tenant isolation (Access stub only)
- Device flash/OTA hardware loop without registry API
- Nested MLflow parent-child runs; full MLflow package dependency
- K8s-native executor as primary backend
- Chat LLM product without GraphIR
- Second Project type (Decision B locked)
- Fake Devices UI without API
- Observe Trace/Compare as activity-bar peers
- New hash-based navigation
- FaceRecognition product surface
- Cursor cloud product features

---

## 22. Traceability matrix (pillar → requirement IDs)

| Pillar | Primary requirement IDs |
|---|---|
| **n8n — Design** | FR-ED-*, FR-TPL-*, FR-HOME-002..005, RT-001, RT-007, RT-010 |
| **MLflow — Learn** | FR-RUN-005..006, FR-MOD-*, MR-*, FR-ART-* |
| **Orchestrator — Execute** | RT-*, FR-RUN-001..004,007, FR-WRK-*, DIST-*, FR-OPS-002 |
| **Edge Impulse — Ship** | FR-SHIP-*, EDGE-*, FR-DATA-* |
| **Agentic** | FR-AGT-*, MCP-*, FR-ED-007, FR-RUN-008 |
| **Accountability** | FR-RUN-009..010, OBS-*, SEC-001..003, FR-ACS-*, FR-OPS-004 |
| **Platform / IA** | UX-NAV-*, FR-ROUTE-*, FR-AUTH-*, UX-STATE-*, NFR-*, QA-* |

Journeys: **J1** FR-TPL + FR-ED + FR-RUN + FR-HOME · **J2** FR-RUN-005 + FR-MOD · **J3** FR-ED-006 + FR-HOME-005 · **J4** FR-MOD + FR-SHIP · **J5** FR-AGT · **J6** FR-RUN-009 + OBS + FR-ART.

---

## 23. Open questions

1. **Settings route vs drawer:** Promote `/settings` to full page or keep modal as permanent pattern?
2. **TraceView:** Keep dead-code standalone for artifact-only deep links, or delete and fold entirely into Artifacts + Runs Lineage?
3. **Cron durability:** Persist scheduler across API restarts — file ticker vs external cron?
4. **Device API shape:** Minimal registry (id, target, last package, OTA status) before UI investment?
5. **RBAC roles:** Exact role set for prod-approve vs secret-write vs admin Ops?
6. **Compare charts:** Server aggregates vs client-only from existing compare payload?
7. **FR-ED-010 silent strip:** Treat as P0 bug fix vs IR feature freeze until canvas supports conditions?
8. **Worker plugin sync:** Require identical packs on workers — enforce in heartbeat or document-only?
9. **BASE_PATH:** First-class subpath hosting requirement for current customers?
10. **Audit retention / signing:** Append-only verification UX timeline?

---

## Appendix A — Console surface checklist (self-check)

| Surface | Section | Covered |
|---|---|---|
| Login | §9.1 | ✓ |
| Workspaces/Home | §9.2 | ✓ |
| Editor | §9.3 | ✓ |
| Runs History/Live/Compare + panels | §9.4 | ✓ |
| Models | §9.5 | ✓ |
| Ship + Devices | §9.6 | ✓ |
| Datasets | §9.7 | ✓ |
| Templates | §9.8 | ✓ |
| Agent inbox | §9.9 | ✓ |
| Artifacts | §9.10 | ✓ |
| Plugins | §9.11 | ✓ |
| Workers | §9.12 | ✓ |
| Secrets | §9.13 | ✓ |
| Ops | §9.14 | ✓ |
| Access | §9.15 | ✓ |
| Command palette | §9.16 | ✓ |
| Settings | §9.17 | ✓ |
| Runtime / Models / Dist / Plugins / MCP / Edge / Data / Security / Obs / NFR / QA | §10–20 | ✓ |

## Appendix B — API router areas mapped

`artifacts`, `data`, `experiments`, `ingest`, `models`, `nodes`, `outputs`, `pipelines`, `plugins`, `projects`, `proposals`, `run_control`, `runs`, `secrets`, `system`, `trace`, `workers` — requirements allocated across §§8–18. Project annotations/quality endpoints noted as API>UI gaps (DATA-SYS-003/004).

---

*End of GRAPHYN-SRS-001 v0.1.0 — Draft 2026-09-18*
