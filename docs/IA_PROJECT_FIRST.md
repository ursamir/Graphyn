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

Selected project shows workspace cards:

- Linked / versions data (existing tabs condensed)
- Pipelines / Open Builder
- Recent runs (`GET /runs?project=` — Phase 2 hard filter)
- Experiments entry
- Empty CTAs: Link data (Data), Open Templates, Open Builder

Status pills (active / archived / draft / ready) kept, less button-heavy where easy.

### 4.3 Templates

Before **Open in Builder**: if no `activeProject`, prompt Create/select project → set active → stamp graph → load Builder. If active, stamp and open.

### 4.4 Declutter chrome

- **Runs detail:** primary Trace + Artifacts + Open in Builder; Projects/Data only when no active project context
- **Header last-run strip:** when project active → Run + Lineage + Artifacts (drop duplicate Projects chip; Compare soft-pedaled when it duplicates sidebar Experiments)
- **Artifacts detail:** keep Trace + Replay; soften Open run / Builder duplication without removing utility

---

## 5. Phase 2 shipped (backend scoping)

| Capability | Behavior |
|---|---|
| Persist project on runs | Builder / Templates→Builder stamp `metadata.project` (+ optional `version_tag`); `POST /pipelines/run[-async]` writes `project` / `version_tag` into run `meta.json` (and orchestrator re-stamps from graph / node configs). |
| Hard `GET /runs?project=` | Exact match on `meta.project`, with soft upgrade: if missing, infer from journal `graph.json` metadata / dataset node `config.project`. |
| Experiments | `GET /experiments?project=` filters run rows by the same resolved project field. |
| Project-linked datasets | `GET/POST/DELETE /projects/{name}/links` persists `{ inputs: string[], outputs?: {version}[] }` in `links.json` (mirrored on `project.json`). Project home: Link from Data picker + unlink; Browse files still opens Data with project context. |
| Templates → project → Builder → Run | Active project required (Phase 1 gate); stamp on graph; run writes `meta.project`; project home recent runs uses `GET /runs?project=`. |

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
