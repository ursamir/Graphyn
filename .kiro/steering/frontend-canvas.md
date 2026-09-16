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
- Last-run menu: **Lineage** · **Run outputs** · **Compare runs…** (jumps into Runs panels for the last run from any page).
- Editor: proposal badge when `pendingProposalCount > 0`.
- Mode chip (Local / Distributed): click → Mode A vs B explainer (Mode A primary = Got it).
- **Layout mode** toggle (Master | Stack): `LayoutModeControl` — persists `graphyn.layout.mode` (`master-detail` side-by-side vs `container-content` stacked).
- **Z-stack (top → bottom):** modals/palette `z-[100+]` → `FieldSelect` portal `z-[80]` → app header + Last-run menu `z-40` → `ViewShell` page chrome `z-10` → sticky run chrome `z-10` (Manage menu `z-30` inside) → page body. Header is `relative z-40` so dropdowns paint above the main column.

## App-wide layout system (`src/layout/`)

| Piece | Role |
|---|---|
| `ViewShell` | Container (title / actions / toolbar, `z-10`) + Content body for every feature screen |
| `MasterDetail` | Shared list\|detail splitter; follows layout mode; default key `graphyn.layout.master`; optional `collapsible` (Runs) hides master to a rail |
| `LayoutPrefsProvider` | Wraps App; mode preference for all `MasterDetail` consumers |
| `LAYOUT_KEYS` | `nav` · `master` · `stack` · `nested` — one divider width synced across History/Live/Compare + Library screens |
| `SplitPane` | Broadcasts `graphyn:layout-split` so same-key panes stay aligned; `paneOverflow="hidden"` when children scroll |

**Shell:** desktop nav is a resizable `SplitPane` (`graphyn.layout.nav`); collapse persists (`graphyn.layout.navOpen`). List/detail screens (Runs, Models, Artifacts, Agent inbox, Compare) use `MasterDetail` — not page-local fixed grids.

**Viewport containment:** `html/body/#root` use `max-height: 100dvh; overflow: hidden`. App shell + body row + `main` are `min-h-0 overflow-hidden` so pages never grow past the window; scroll lives inside panes. Rebuild UI only: `docker compose build graphyn-ui && docker compose up -d --no-deps graphyn-ui` (never recreate API for UI changes).
## Command palette / keyboard help

Primary jumps: Home, Editor, Runs, Datasets, Artifacts, Templates, Library · Plugins, Ship (Package|Devices), Worker fleet, Ops.

Secondary **Runs panels:** Runs → Lineage (`/workspaces/:id/runs/:runId/lineage`, legacy `#/trace`), Runs → Compare (`/workspaces/:id/runs/compare`, legacy `#/runs?tab=compare`).
