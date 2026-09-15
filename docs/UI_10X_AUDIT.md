# Graphyn UI 10× Audit

Deep UX audit of the Graphyn console (`graphyn-ui`) against project-first IA. Findings drive Waves 1–4.

## Confusing flows found

| Issue | Symptom | Impact |
| --- | --- | --- |
| Dual chrome: Global **Builder** vs Project **Editor** | Same view (`builder`) labeled differently in global nav vs project strip | Users think Editor and Builder are different products |
| Trace / Compare orphaned | Lineage (`trace`) and Compare (`experiments`) only reachable via Run deep-links or hotkeys; not on project strip | Power features feel hidden; “where did Lineage go?” |
| Circular empty-state CTAs | Empty Artifacts / Runs / Builder / Edge stacked Open Builder + Open Projects + From template + Open Data | Decision paralysis; no clear happy path |
| Promote buried | Model promote lives deep in Run detail Files tab | Operators miss the path from successful train → registry |
| Schedules in System, not project | Cron / schedule UI under Admin → System | Project owners look on Overview and find nothing |
| Model registry API, thin UI | Backend registry exists; console barely surfaces it | “Where are my promoted models?” |
| Naming: **File registry** | `VIEW_LABEL.artifacts` said “File registry” next to Data library | Confused with Data library / Outputs |
| Spec / Taxonomy overload on Overview | Overview packs Spec tabs, taxonomy, pipelines, linked data | Cognitive load; Apple-style declutter needed later |

## Wave 1 (this PR) — nav / naming / CTA

**Goal:** One name for the canvas (**Editor**), project strip includes Lineage + Compare, empty states show one primary (+ optional secondary).

- Remove `builder` from `GLOBAL_NAV_GROUPS` Build group (Templates + Proposals only). Editor appears only in `PROJECT_NAV` when a project is open.
- Expand `PROJECT_NAV_ITEMS`: Overview · Editor · Run · Lineage · Compare. Artifacts remain secondary (Run / Lineage deep links; advanced `#/artifacts`).
- Unify user-visible strings: “Open Builder” / “Open in Builder” → “Open Editor” / “Open in Editor”. Keep internal view id `builder`. `VIEW_LABEL.builder` stays **Editor**.
- `VIEW_LABEL.artifacts`: **Artifacts** (not File registry).
- Empty-state CTA declutter:
  - Runs → primary Open Editor (+ secondary From template)
  - Artifacts → primary Open Run (+ secondary From template)
  - Builder plugins empty → Open Plugins only
  - Builder canvas empty → Open Templates (+ secondary Open Data)
  - Edge → primary Open Templates (+ secondary Projects)

## Wave 2 — project activity & ops surfaces — **SHIPPED**

- Project **Activity** feed on Overview (recent runs + schedule last fires; rows open Run).
- **Promote & models** panel on Run detail (above tabs); reuses `/runs/{id}/promote` + lists `GET /models` for this run_id.
- Schedules card on Overview (`GET /system/schedules`, project filter when possible, Run-now → `POST /system/schedules/{id}/run`; Manage in System).

## Wave 3 — command palette & honesty — **SHIPPED**

- `CommandPalette` owns Cmd/Ctrl+K and `/` (views, projects, recent/last run); KeyboardHelp updated.
- Pipeline env chips in Editor (draft / staging / prod) via project pipeline APIs; hint when none saved.
- Mode A placement: read-only / “ignored until Mode B” with link to Workers when `backendMode !== distributed`.

## Wave 4 — declutter & single source of truth — **SHIPPED**

- Overview **Spec & metadata** Advanced disclosure (closed by default) for Spec / Taxonomy / Contract / Versions / Snapshots / Diff.
- Unified SoT copy: Templates = starters; Project pipelines = canonical saved graphs; Editor = active graph — primers on Overview + Templates.

## Notes

- Internal ids (`builder`, `trace`, `experiments`, `artifacts`) unchanged for hash routes and store.
- Do not kill FaceRecognition / unrelated Docker services; rebuild `graphyn-ui` only when shipping these UI changes.
