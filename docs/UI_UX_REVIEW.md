# Graphyn Console — UI/UX Review

**Date:** 2026-09-16 (deep pass) · prior 2026-09-15  
**North star:** `docs/UI_NORTH_STAR.md` · **IA:** `docs/IA_PROJECT_FIRST.md`  
**Goal:** Each surface has one job; URL, shell, and content agree (workspace vs global).

---

## Pass 3 — Deep review (2026-09-16)

### Root causes users hit

| Symptom | Cause | Fix shipped |
|---|---|---|
| URL like `/workspaces/foo#/projects?…` | Legacy hash left on bar while pathname moved to paths | `navigatePath` strips `#/…`; boot reconcile + `stripLegacyAppHash` |
| Home shows **project list** while sidebar says workspace open | `activeProject` from localStorage ≠ URL; `ProjectsView` `selected` stuck null | Workspace chrome only when URL has `/workspaces/:id`; ProjectsView syncs selected from URL + store |
| Same pip error in every plugin card + toast | Global `installError` + full log copy | Per-plugin one-line error; success-only toasts for deps |

### Shell contract (locked)

| Context | URL | Sidebar | Main content |
|---|---|---|---|
| **Global** | `/workspaces`, `/library/*`, `/deploy/*`, `/admin/*`, `/templates`, `/agent/inbox` | Full global groups | Picker, library, fleet, admin |
| **Workspace** | `/workspaces/:id`, `/workspaces/:id/editor`, `…/runs`, `…/models`, `…/datasets`, `…/ship` | Activity strip: Home · Editor · Runs · Models · Ship · Datasets; **Library & admin** collapsed | Workspace home, editor, runs, etc. |

**Inspiration:** n8n (editor + executions), MLflow (runs/compare/models), Prefect (run detail panels), Edge Impulse (ship wizard) — one workspace context, global library for shared assets.

### Per-surface objectives (implemented vs gap)

| Surface | Objective | Implemented | Gaps / polish |
|---|---|---|---|
| **Home** | Situation dashboard: pipelines, last runs, linked data, always-on | Workspace pane when URL scoped | Picker should never show under scoped URL; spec/taxonomy tabs still power-user heavy |
| **Editor** | Design Graph IR, run, triggers, agent | Canvas, Triggers dock, Agent drawer | Subflows UI needs-API; placement UX Mode B |
| **Runs** | History · Live · Compare; logs/outputs/lineage | Tabs + panels | Queue/reclaim needs-API |
| **Models** | Registry + stages | Workspace models view | Charts/promote flow thin vs MLflow |
| **Ship** | Package + devices | Edge wizard tabs | OTA/devices needs-API |
| **Datasets** | Shared inputs/outputs | Data view + hash-free query sync | Ingest progress OK; merge UX dense |
| **Plugins** | Install packs for catalog | Installed / install tabs | **Pass 3:** shorter errors, plain-language Mode B strip |
| **Artifacts** | Cross-run registry | Library path + `?artifactId=` | Prefer Runs → outputs for single run |
| **Agent inbox** | Proposals + accept | Proposals view | Generate/HITL partial |
| **Ops** | Health, schedules, audit | System view | OTel needs-API |
| **Workers** | Fleet Mode B | Workers view | Job list-all needs-API |

### Redundancy removed (pass 3)

- Duplicate **Templates / Datasets / Artifacts** in both activity strip and Library — strip now: Home, Editor, Runs, Models, Ship, Datasets; Library holds Templates, Agent inbox, Artifacts, Plugins, Workers, Secrets, Ops, Access.
- Header subtitle: `{view} · {workspace}` instead of repeating “Home · project · view”.
- Plugins: no triple pip wall (card + banner + toast).

### Pass 4 — Density & consistency (2026-09-16)

| Fix | Where |
|---|---|
| Global Ship Devices URL sticks (`/deploy/ship/devices`) | `paths.deployShipDevices` + parse + EdgeWizard write |
| Agent inbox always visible; badge only when pending | App shell |
| Proposal badge off Editor nav | App shell |
| Remove duplicate Bridges Lineage/Outputs/Compare | Runs detail |
| Home empty: Template + Dataset only (Editor stays header) | ProjectsView |
| Builder toolbar: Run/Save primary; Validate/Templates/Triggers/Agent in More | BuilderView |
| Empty canvas: Templates only (no Datasets CTA) | BuilderView |
| “Files” → “Run outputs”; Edge → Ship labels | Artifacts, Home, palette, help |
| Secrets Mode A vs B copy | SecretsView |
| Datasets: shorter header; Label lite only in Manage | DataView |
| Live empty → Open Editor; Compare subtitle fixed | RunsView |
| Header: Switch only (dropped Close X duplicate) | App header |
| Models + Artifacts in global Library | App GLOBAL_NAV |

### Pass 5 — Logical state honesty (2026-09-16)

| Fix | Where |
|---|---|
| Datasets: list showed `clean_speech (188)` while detail failed “outside workspace” + “Selection was cleared” + Upload empty | Backend marks `accessible`; UI skips blocked labels; honest error + Clear selection (no Upload-while-error) |
| External symlink labels need `GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS=1` | API error detail + UI copy |
| `openData` ignored mode/label/version | `appStore` |
| Artifacts stale detail on failed open | ArtifactsView |
| Workspace chip on global Library | App chrome URL-only |
| Runs selection hidden by filters | Banner + clear filters |
| Models/Proposals selection vs empty/filter | Clear or snap selection |
| Experiments compare retry | `runCompare` |
| Builder misleading View outputs / Retry | Run failures only |
| Edge wizard skip to step 3/4 | Gated |
| Projects open fail left hollow Home | Clear payload + hide empty strip |
| Plugins optional-install banner always said “PyTorch” / footnotes said “TensorFlow, …” | Progress + toasts name the actual missing packages; footnotes are runtime-generic |
| Plugins optional install failed for `[tflite-runtime, torch]` while TF already ok | Skip tflite when TF present; install optionals one-by-one; surface real pip ERROR lines |
| Ops Status duplicated every field under Raw JSON (+ metrics raw block) | Removed; readiness surfaces node count / backend; Maintenance copy plain-language |

### Still open (product)

- E2E for path-only nav + datasets accessible flags.
- Breadcrumb component matching path.
- `needs-API` (devices OTA, OTel, subflows, cron, job list, env freeze ZIP).

---

## Earlier passes (summary)

Pass 1–2: project-first IA, naming, Run outputs. Pass 3–4: hash ban, density, CTAs. Pass 5: **no contradictory selection vs content**.

**Verdict:** Screenshot class bugs (banner lies / selection kept / wrong empty CTA) are the highest-priority class; Pass 5 targets that across Datasets and peer surfaces.
