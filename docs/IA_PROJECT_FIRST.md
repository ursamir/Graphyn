# Graphyn Console — Project-first information architecture (Phase 1)

> **Status:** Phase 2 project scoping shipped (2026-09-10). Locked product Decision B: do **not** invent a second Project type — evolve current Projects into the full workspace. Dataset versions/snapshots remain a facet of the same project.
>
> **Supersedes for IA:** [UI_USER_REQUIREMENTS.md](./UI_USER_REQUIREMENTS.md) sections 0-1 sidebar / Observe peer layout and the "Projects = dataset workspace only" framing. **P0/P1 controls** (Trace prefill, Runs filters, Compare honesty, Mode A/B chips, etc.) remain valid **inside** this new shell.
>
> Anchors: [PRODUCT_VISION.md](./PRODUCT_VISION.md), Decision B (assistant, Samir 2026-09-10).

---

## 1. Product decisions (locked)

1. **Project = full workspace** — pipelines + runs + experiments + linked data (not datasets-only).
2. **Observe lives primarily inside the open project** — declutter global duplicate Observe peers.
3. **Plugins → Admin**; **Proposals stay global**; **Templates create or enter a project first**.
4. **Global dataset library** (`Data`) + **per-project linked datasets** (versions / snapshots on Project home).
5. **Decision B** — one Project type; versions/snapshots are facets, not a parallel object.

---

## 2. Sidebar: no project vs project open

### 2.1 No active project (global shell)

| Group | Items | Notes |
|---|---|---|
| **Projects** | Projects | Primary entry — picker / create / open |
| **Build** | Templates, Proposals | Builder optional for canvas-only; **Run** path should go through a project |
| **Library** | Data | Global file library (`workspace/datasets/…`) |
| **Deploy** | Edge, Workers | Unchanged |
| **Admin** | Plugins, Secrets, System | **Plugins moved from Library → Admin** |

**Removed as equal top peers when no project:** Runs, Trace, Experiments, Artifacts as a flat Observe group. Deep links (`#/runs/{id}`, `#/trace?run_id=`, …) still work.

### 2.2 Project open (project-local strip + global remainder)

Header shows an **active project chip** (switch / clear). Sidebar prefers:

| Item | Destination | Role |
|---|---|---|
| Overview | `#/projects?project={name}` | Project home |
| Linked data | `#/projects?project={name}&tab=versions` | Versions / snapshots facets |
| Builder | `#/builder` | Pipelines for this workspace |
| Runs | `#/runs` | `GET /runs?project=` hard filter when active project set |
| Experiments | `#/experiments` | `GET /experiments?project=` when active project set |

Global **Build** (Templates, Proposals), **Library** (Data), **Deploy**, **Admin** remain available below or beside the project strip.

**Declutter:** Trace and Artifacts are **not** equal sidebar peers. Reach them from run detail, artifact detail, and the header last-run strip (shortened when a project is active).

---

## 3. What moves (migration from old nav)

| Old (UI_USER_REQUIREMENTS Observe/Library) | New |
|---|---|
| Build: Builder, Templates, Proposals | Templates + Proposals stay global; Builder emphasized under open project |
| Observe: Runs, Trace, Experiments, Artifacts | Runs + Experiments under open project; Trace/Artifacts demoted to detail + last-run |
| Library: Plugins, Data, Projects | Projects → primary entry; Data stays Library; **Plugins → Admin** |
| Admin: Secrets, System | Admin: Plugins, Secrets, System |

**URL strategy (Phase 1):** Keep existing hash routes. Active project persists in `localStorage` (`graphyn.activeProject`) and is reflected on `#/projects?project=…`. Optional `?project=` on other views is progressive; do not break `#/runs/{id}` or Trace/Artifacts query deep links.

---

## 4. Surfaces (Phase 1 behavior)

### 4.1 Active project context (`appStore`)

- `activeProject: string | null`
- `setActiveProject(name | null)` / `openProject(name)` (sets active + navigates to project home)
- Persist to `localStorage`; restore on boot; sync when `#/projects?project=` changes

### 4.2 Project home (`ProjectsView`)

Selected project shows workspace cards (no circular “Open Editor / Run / Experiments” that only duplicate the sidebar):

- Linked data (link / unlink)
- Pipelines — **list project-owned Graph IR** (`GET /projects/{name}/pipelines`) + open in Editor; **From template** creates/saves under `pipelines/`
- Recent runs (`GET /runs?project=`) — open a run from the list
- Experiments — copy only (“use Experiments sidebar”)
- Empty versions CTA: **From template** (not Open Builder / Open Data triplication)

### 4.3 Templates

Before **Open**: if no `activeProject`, gate modal (“Templates stamp into a project”) → create/select → stamp graph → **PUT project pipeline** → load Editor. If active, stamp, persist, and open. Library search + All/Examples/Saved pills; Sync examples / Save from Builder live under header More; delete stays in card kebab.

### 4.4 Declutter chrome

- **Cold start:** default hash view is **Projects** when `activeProject` is null (not Editor behind a gate).
- **Mode honesty:** header chip **Local** / **Distributed** from `GET /system/readiness` (`backend_mode`).
- **Hash `go()`:** only preserves query keys the destination understands (no `#/trace?run_id=` → `#/edge?run_id=` smear). Edge may keep `project`, `version`, `run_id`.
- **Runs detail:** Trace + Artifacts + Open in Editor + Compare (no dead Projects/Data buttons — Run is project-gated).
- **Header last-run strip:** Run + Lineage + Artifacts visible on mobile too (not `sm:`-only).
- **Run status vocabulary:** UI normalizes `completed` / `succeeded` / `success` for filters and Edge poll.
- **Edge:** sticky lineage bar (project + source `run_id`); optional artifact pick on Configure; persist `source_run_id` / `source_artifact_id` on the package run meta; step owns actions (header Artifacts only when package exists); skip-to-download gated on package artifact; failure → Open run / Trace.
- **Artifacts detail:** keep Trace + Replay; soften Open run / Editor duplication without removing utility

### 4.5 Project pipelines (Wave 1)

Durable graphs for a workspace: `workspace/datasets/output/{project}/pipelines/{name}.graph.json`.

### 4.5.1 Pipeline versions + environments (Wave 7)

| Concept | Storage |
|---|---|
| **Draft** | `{name}.graph.json` (Editor save) |
| **Versions** | `{name}/versions/vN.graph.json` |
| **Envs** | `{name}/environments.json` → `staging` / `prod` pointers |

Flow: edit draft → **Publish → staging** → **Request prod** → **Approve prod**. Schedules default to `env=prod`.

API: `POST .../publish`, `POST .../promote` (`approve: true` for prod), `GET .../versions`, `GET ...?env=staging|prod`.
Editor **Save to project**; Overview lists and reopens them. Global templates remain a stamp source, not the system of record.
---

## 5. Phase 2 shipped (backend scoping)

| Capability | Behavior |
|---|---|
| Persist project on runs | Builder / Templates→Builder stamp `metadata.project` (+ optional `version_tag`); `POST /pipelines/run[-async]` writes `project` / `version_tag` into run `meta.json` (and orchestrator re-stamps from graph / node configs). |
| Hard `GET /runs?project=` | Exact match on `meta.project`, with soft upgrade: if missing, infer from journal `graph.json` metadata / dataset node `config.project`. |
| Experiments | `GET /experiments?project=` filters run rows by the same resolved project field. |
| Project-linked datasets | `GET/POST/DELETE /projects/{name}/links` persists `{ inputs: string[], outputs?: {version}[] }` in `links.json` (mirrored on `project.json`). Project home: Link from Data picker + unlink; Browse files still opens Data with project context. |
| Templates → project → Builder → Run | Active project required (Phase 1 gate); stamp on graph; **persist under `pipelines/`**; run writes `meta.project`; project home recent runs uses `GET /runs?project=`. |
| Project pipelines | `GET/PUT/DELETE /projects/{name}/pipelines[/{pipeline}]` — Graph IR system of record for the workspace. |

Disk layout unchanged: projects live under `workspace/datasets/output/{project}/`.

---

## 6. Success criteria

### Phase 1 (done)
- doc shipped
- Working shell: project chip, sidebar, home cards, Templates gate, declutter
- build must pass
- no charts work this phase

### Phase 2 (this ship)
- `GET /runs?project=` hard filter + unit tests
- links API + unit tests
- experiments scoped via `?project=`
- `graphyn-ui` build passes
- no P2 charts / device flash / RBAC

---

## 7. Phase 3 remaining / deferred

- **RBAC per project** (authz on Observe / links / Builder run)
- Optional server-side active-project session
- charts / device flash
- DB-backed `project_id` indexes (filesystem journals remain source of truth for now)
- second Workspace type (Decision B still locks one Project type)

---

## 8. UX visibility (Web IDE analogy)

Shipped after Phase 2 to make **global vs project** and **viewer vs editor** obvious — think **VS Code / Cursor**, not a flat SaaS nav.

| Graphyn surface | IDE analogue |
|---|---|
| **Project (active)** | Opened folder / workspace |
| **Overview** | Workspace home / welcome |
| **Editor (Builder)** | Main editor (center stage) |
| **Explorer (Linked data + Data Browse)** | File explorer (viewer) |
| **Data Manage** | Explorer actions (upload / delete / ingest) — secondary |
| **Run** | History + Files + Lineage + Compare (one surface; Prefect/W&B pattern) |
| **Trace / Artifacts** | Deep-link only (artifact ids / cross-run registry) — not sidebar peers |
| **Templates** | New from template wizard (creates/opens workspace first) |
| **Proposals** | PR review (global) |
| **Plugins / Secrets / System** | Settings / Extensions (Admin) |
| **Edge / Workers** | Remote deploy targets |

### Chrome rules (Web IDE hierarchy)

Modeled on VS Code + Prefect run tabs + W&B/MLflow compare-in-runs:

1. **Activity bar (project open):** Overview / Editor / **Run** / **Data** (library Outputs for this project — *not* Overview). Global/Settings collapsed.
2. **Header:** project chip + Switch / Close; last-run menu: **Lineage** | **Files** | **Compare…** (land on Run panels).
3. **Projects picker** (`#/projects`): dense explorer + filter; welcome pane only.
4. **Workspace Overview** (`#/projects?project=`): situation strip + Open Editor / From template / Last run; **Pinned inputs** are manual links (runs do not auto-link); Versions & taxonomy collapsed.
5. **Editor:** Run | Validate | Save; placement only in Distributed mode.
6. **Run (unified observe):**
   - Top: **History | Compare**.
   - Detail panels: **Logs** (execution printout) | **Files** (downloadable outputs, type previews, grouped by node) | **Lineage** (executed nodes + provenance — enriched `/trace?run_id=`) | **Details** (counts, node_stats, errors) | **Checkpoints**.
   - `openTrace({ runId })` → Run → Lineage; `openArtifacts({ runId })` → Run → Files.
7. **Data vs Overview:** sidebar **Data** = Data library Outputs for the project; Overview keeps workspace home only.
8. **Hash sync:** `replaceHash` / `go` dispatch `hashchange`; Switch clears `?project=`.
9. **Auth:** 401 → Settings CTA.

### 5.0 Data / lineage / onboard (Waves 2–3)

| Surface | Primary job | IA notes |
|---|---|---|
| **Data** | Shared dataset library | Browse\|Manage; honesty: Outputs ≠ Run Files |
| **Trace** | Artifact-id lineage deep-link | Prefer Run → Lineage for runs |
| **Artifacts** | Cross-run file registry | Prefer Run → Files for one run; Lineage for provenance |
| **Templates** | Stamp into project → Editor | Search + pills; quieter header; gate copy |
| **Proposals** | Approve agent GraphIR | MCP discovery banner; search; diff first |
| **Edge** | Package for device | Step-owned actions; openRun for fail/lineage |

### 5.1 Admin / ops surfaces (Wave 4 persona IA)

| Surface | Primary job | IA notes |
|---|---|---|
| **Plugins** | Install packs; fix deps so Builder catalog works | Tabs **Installed** (default) / **Install / Search**; status filter (ok / missing deps / disabled); one dep CTA per row; empty → Install tab |
| **Workers** | Monitor Mode B workers | Summary strip (count, mode hint, refresh); client filter by label/pool/status; row → detail drawer; empty = short Mode B + copyable `graphyn worker start` |
| **Secrets** | Create / rotate / delete named credentials | Searchable name list (values never shown); POST same name → **Replace value** confirm; note that usage index is not available yet |
| **System** | Health, schedules, webhooks, cleanup, audit | Status: facts first, Raw JSON collapsed, no filler Projects card, Workers link when distributed; Schedules: project/pipeline selects from `/projects` + `/projects/{name}/pipelines` (text fallback); denser Audit table; shorter Cleanup prose + CLEANUP confirm |
