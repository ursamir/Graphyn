# graphyn-ui shell & canvas

Canonical IA (Phase 1): `docs/IA_PROJECT_FIRST.md`.  
**North-star UI:** `docs/UI_NORTH_STAR.md` — path routes; Phase 0–D UI wave (Devices/OTA, OTel, Subflows, cron, job list-all still needs-API). Canvas: `graphyn-ui-north-star`.

## Path routing foundation (Phase 0 · partial)

| Module | Role |
|---|---|
| `src/routes/paths.ts` | Typed History API builders (`paths.editor`, `paths.runPanel`, …) |
| `src/routes/legacyHash.ts` | `#/...` → path map (`resolveLegacyHash`) |
| `src/routes/HashRedirect.tsx` | Mount under router; `replace` navigate + clear hash |
| `src/routes/viewMap.ts` | `AppView` → path (`pathForView`) for gradual migration |
| `src/main.tsx` | Wraps app in `BrowserRouter` |

`App.tsx` syncs pathname ↔ store via `parsePathname` / `navigatePath`. Workspace sidebar chrome only when URL is `/workspaces/:id` (not localStorage alone). Mount `<HashRedirect />` for one-way legacy `#/...` bookmarks; `navigatePath` strips orphan `#/…` fragments.

## Activity bar (workspace open)

| Label | Target path (north-star) | Legacy hash |
|---|---|---|
| **Home** | `/workspaces/:id` | `#/projects?project=…` |
| **Editor** | `/workspaces/:id/editor` | `#/builder` |
| **Runs** | `/workspaces/:id/runs` | `#/runs` |
| **Artifacts** | `/library/artifacts` | `#/artifacts` |
| **Datasets** | `/workspaces/:id/datasets` | `#/data` |
| **Templates** | `/templates` | `#/templates` |

**Not activity-bar peers:** Lineage (`…/runs/:runId/lineage`, legacy `#/trace`), Compare (`…/runs/compare`, legacy `#/experiments`) — deep links or Runs panels only.

## Global / Settings (collapsed)

Templates · **Agent inbox** · Artifacts · **Library · Plugins** · **Ship** · **Worker fleet** · Secrets · **Ops** · Access

## Header chrome

- Subtitle: `Home · {project} · {view}` when a workspace is open.
- Workspace chip **only** when URL is `/workspaces/:id` (`workspaceOpen`); **Switch** clears then opens picker.
- Global Library with `activeProject` in localStorage but no workspace URL → **Open workspace** (restore), not the chip (avoids chip+global-nav contradiction).
- Last-run menu: **Run outputs** · **Compare runs…**
- Editor: proposal badge when `pendingProposalCount > 0`.
- Mode chip (Local / Distributed): click → Mode A vs B explainer (Mode A primary = Got it).

## Command palette / keyboard help

Primary jumps: Home, Editor, Runs, Datasets, Artifacts, Templates, Library · Plugins, Ship (Package|Devices), Worker fleet, Ops.

Secondary **Runs panels:** Runs → Lineage (`/workspaces/:id/runs/:runId/lineage`, legacy `#/trace`), Runs → Compare (`/workspaces/:id/runs/compare`, legacy `#/runs?tab=compare`).
