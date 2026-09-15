# Graphyn Console — UI/UX Review

**Date:** 2026-09-15  
**Method:** Live console at `:5173` + `graphyn-ui/src/App.tsx` / feature headers + `docs/PRODUCT_VISION.md` + `docs/IA_PROJECT_FIRST.md`  
**Audience:** Product + frontend agents  
**Goal:** Make every page/tab self-justifying; reduce “which of these three is for me?”

---

## Implemented (2026-09-15)

- **Activity bar (project open):** Home, Editor, Runs (+ Artifacts, Datasets buttons). Lineage / Compare removed as strip peers; `#/trace` and `#/experiments` deep links kept.
- **Labels:** Runs, Home, Artifacts, Datasets, Edge package, Worker fleet, Ops; Library · Plugins under global settings.
- **Proposals:** hidden from global list when pending=0 (unless on proposals view); Editor badge when pending>0.
- **LastRunMenu:** Artifacts / Compare runs…
- **Feature headers / empty states:** Runs hub copy; Trace/Compare redirect-friendly; Artifacts vs Runs→Files; Datasets (not “Data library”); Library Plugins; progressive Proposals empty; Templates as Build entry; Deploy/Ops framing.
- **Projects Overview:** first-run 3-card strip (Editor / template / Datasets) when workspace has no pipelines and no runs.
- **Command palette + keyboard help:** aligned labels; Runs panels group for Lineage/Compare deep links.
- **Mode chip:** click opens Mode A vs B explainer (+ link to Worker fleet).
- **Docs:** `PRODUCT_VISION.md` console map; `IA_PROJECT_FIRST.md` strip peers; steering nav labels.

---

## Verdict

Project-first IA is the right direction (workspace chip → Editor → Run → …). The remaining UX debt is **justification and naming**, not missing screens: several primary tabs still compete, docs still describe an older five-pillar sidebar, and some pages explicitly tell users to go somewhere else.

---

## Mental model to teach (one sentence)

**Open a workspace → design a graph → run it → inspect that run (files / lineage / compare) → package or scale when ready.**

Everything else (Templates, Plugins, Data library, Workers, Secrets) is **support infrastructure**, not the daily loop.

---

## Current IA (as shipped)

### When a workspace is open (activity bar)

| Label | Route id | Job | Label alone enough? |
|---|---|---|---|
| Overview | `projects` | Workspace home / pipelines / linked data | Weak — sounds like “about”, not home |
| Editor | `builder` | Design Graph IR | OK |
| Run | `runs` | Run **history** + detail | Weak — singular; sounds like “press Run” |
| Lineage | `trace` | Artifact/run provenance | Weak — also lives under Run |
| Compare | `experiments` | Metrics/params across runs | Weak — also a tab under Run |
| Files | `artifacts` | Cross-run artifact search | Weak vs Run files / Data |
| Data | `data` | Shared Inputs/Outputs library | OK with description |

### Global / Settings (collapsed by default)

| Label | Job | Label alone enough? |
|---|---|---|---|
| Templates | Start from example graphs | OK |
| Proposals | Review agent GraphIR | Weak for non-agent users |
| Data library | Same Data view, global framing | Confusing next to activity **Data** |
| Edge deploy | Package for device | OK-ish |
| Workers | Distributed workers | OK |
| Plugins | Install node packs | Misplaced under “Admin” |
| Secrets / System | Credentials / health+audit | OK |

`NAV_HINTS` in `App.tsx` already carry good tooltips — they are not visible as page chrome.

---

## Top justification conflicts

### 1. Run vs Lineage vs Compare (P0)

- Activity bar exposes **Run**, **Lineage**, and **Compare** as peers.
- `RunsView` already embeds History / Compare tabs and lineage for the selected run.
- `TraceView` header says: *“For a run, use Run → Lineage. This page is for artifact-id deep links.”* — a top-level tab that demotes itself.

**Improve:** Keep **Run** as the observe hub. Move Lineage + Compare into Run’s tabs only (keep `#/trace` and `#/experiments` as deep links). Or rename strip to make hierarchy obvious: `Run ▾` with sub-routes.

### 2. Files vs Data vs “run outputs” (P0)

- **Files** = artifacts store (cross-run).
- **Data** = `workspace/datasets` Inputs/Outputs.
- Run detail also has per-run files.

Descriptions help (`Data` page is clear), but three nouns for “stuff on disk” burns cognitive load.

**Improve:** Rename **Files → Artifacts**; keep **Data → Datasets**; in Run, call the pane **Run outputs**. Add a one-line “Which storage?” strip on first visit.

### 3. Docs IA ≠ UI IA (P1)

`PRODUCT_VISION.md` still maps **Build / Observe / Library / Deploy / Admin** with Builder, Runs, Trace, Experiments. Live UI is project-first with Editor / Run / Lineage / Compare.

**Improve:** Update vision map to match shipped nav; or reverse — but don’t leave both stories.

### 4. Global nav hidden; Templates hard to find (P0 for new users)

With a workspace open, **Templates / Proposals / Plugins** sit under collapsed **Global / Settings**. First-run path “stamp a template” is mentioned on Overview but the control is buried.

**Improve:** Put **New from template** as a primary CTA on Overview and Editor empty canvas (already partial). Pin Templates in the activity bar or project overflow until first graph is saved.

### 5. Plugins under Admin (P1)

Plugins are the Editor’s catalog, not an admin chore. Empty Editor says “Open Plugins” while Plugins live under Settings.

**Improve:** Move Plugins into Library (global) beside Datasets; keep Secrets/System as Admin.

### 6. Proposals without agent context (P1)

Strong empty/banner copy exists, but the tab appears equal to Templates for everyone. Non-MCP users see a permanent empty inbox.

**Improve:** Hide Proposals until `list_proposals` is non-empty **or** show under Editor as a badge (“3 proposals”) instead of a global peer.

### 7. Edge deploy vs Workers (P1)

Both sit under Deploy; both are “targets,” but one is packaging and one is fleet ops.

**Improve:** Group labels: **Package for edge** vs **Worker fleet**. On Overview, show “Mode: local | distributed” with link to Workers only when Mode ≠ local.

### 8. Overview label (P2)

When project is open, nav says Overview; when closed, group says Projects. Same view, two names.

**Improve:** Always **Projects** in global; inside workspace call it **Home** or keep **Overview** but use the same noun in breadcrumbs: `Projects / {name}`.

---

## Page-level notes (high signal)

| Page | What’s working | Gap |
|---|---|---|
| Projects / Overview | “Open a workspace” + 3-step list | Dense e2e-* list with no purpose chips; soft landing for real users |
| Editor | Clear empty CTAs (Templates / Data / Plugins) | Catalog can show 0 nodes (auth/plugins) without a single “why empty” diagnosis |
| Run | History + Compare tabs; good empty states | Title “Run” + peer Lineage/Compare confuse |
| Lineage | Deep-link capable | Self-dismissing purpose; duplicate of Run → Lineage |
| Data | Excellent “not Run → Files” description | Browse / Manage + Inputs / Outputs = two axes; justify on first paint |
| Templates | “New from template” | Buried when Global collapsed |
| Proposals | Honest MCP/API banner | Always-visible empty for most users |
| Edge | Wizard steps | Requires project + source run — gate should be the first screen story |
| Workers | Empty state with register hint | No “you only need this if Mode=distributed” |
| System / Secrets | Clear Admin jobs | Audit buried; fine for v1 |

---

## Prioritized UX recommendations

### P0 — Convey the loop

1. **Collapse observe peers into Run** — activity bar: `Overview · Editor · Run · Datasets` (+ Artifacts optional). Lineage/Compare as Run subtabs; deep links preserved.  
2. **Rename Run → Runs** (or **History**) so it doesn’t collide with the Editor **Run** button.  
3. **First-run strip on Overview** — three cards: Template → Editor → Runs (with status). Don’t rely on collapsed Global for day-1.  
4. **Align PRODUCT_VISION console map** with shipped project-first nav.

### P1 — Justify support surfaces

5. **Rename Files → Artifacts**; **Data → Datasets** in nav (page title can stay “Data library”).  
6. **Move Plugins** out of Admin into Library.  
7. **Proposals**: badge on Editor or hide-when-empty.  
8. **Workers / Edge**: subtitle under Deploy group (“Package” vs “Fleet”).  
9. **Surface NAV_HINTS** as one-line page intros (many PageHeaders already do this — make the strip consistent, max 1 sentence).  
10. **Editor catalog empty**: branch copy — no token / plugins failed / none installed — with one CTA each.

### P2 — Polish

11. Breadcrumb: `Workspace · {project} · Runs · {shortId}`.  
12. Command palette groups mirror activity vs global (already partly there).  
13. Soften e2e project noise (filter “examples” / “mine”).  
14. Mode chip: click → short explainer modal (local vs distributed).  
15. Keep desktop-first; don’t fake mobile Builder.

---

## Addendum — label mismatches & copy bugs (from deep explore)

Concrete chrome inconsistencies to fix with the P0/P1 renames:

| Current | Problem | Fix |
|---|---|---|
| Nav **Files** → page title **Artifacts** | Same view, two names | One label everywhere (prefer **Artifacts**) |
| Nav **Templates** → page **New from template** | Same product, two titles | Match both |
| Hash `#/builder` / `#/trace` / `#/experiments` | Chrome says Editor / Lineage / Compare | Keep hashes for deep links; never show raw ids in UI |
| Compare empty: *“Select two runs from History, then return here”* | Peer nav opens Compare without History context | CTA → Run → History with multi-select, or auto-land History |
| Proposals empty CTA **Open Editor** | Editor does not create proposals | Point to MCP/docs (banner already cites `propose_graph`) |
| Data empty *“Upload audio…”* | Audio-pack bias | Domain-agnostic *“Upload files or ingest URLs…”* |
| Edge wizard step **Run** | Collides with nav **Run** | Prefer **Execute package** / **Package run** |
| `IA_PROJECT_FIRST.md` (Trace/Artifacts deep-link-only) | Activity bar still lists Lineage | Demote Lineage from `PROJECT_NAV_ITEMS` to match IA doc |

`docs/IA_PROJECT_FIRST.md` is the intended Web IDE map; `PRODUCT_VISION.md` § Console map is the stale flat Observe map — sync vision to IA, not the reverse.

---

## Suggested copy cheat-sheet

| Instead of | Prefer |
|---|---|
| Run (nav) | Runs |
| Lineage (peer tab) | (inside Runs) Provenance |
| Compare (peer tab) | (inside Runs) Compare runs |
| Files | Artifacts |
| Data (activity) | Datasets |
| Data library | Datasets (library) |
| Global / Settings | Library & admin |
| Overview | Home (or Projects home) |

---

## Out of scope for this review

- Visual redesign / new design system  
- Full WCAG pass (see KNOWN_ISSUES UI-A11Y-1)  
- Implementing RBAC or multi-user IA  

---

## Agent implementation order

1. Nav rename + collapse Lineage/Compare into Runs (routes stay)  
2. Overview first-run cards + Templates CTA  
3. Plugins move + Artifacts/Datasets naming  
4. Docs vision map sync  
5. Proposals progressive disclosure  

Interactive summary: open the canvas `graphyn-ui-ux-review` beside chat.
