# graphyn-ui shell & canvas

Canonical IA (Phase 1): `docs/IA_PROJECT_FIRST.md`.  
**North-star UI:** `docs/UI_NORTH_STAR.md` — path routes; Phase 0–D UI wave (Devices/OTA, OTel, Subflows, cron, job list-all still needs-API). Canvas: `graphyn-ui-north-star`.

## Path routing

| Module | Role |
|---|---|
| `src/routes/paths.ts` | Typed History API builders (`paths.editor`, `paths.runPanel`, …) |
| `src/routes/parsePath.ts` | Pathname → view. `stripLegacyAppHash()` drops a leftover `#/…` fragment. |
| `src/routes/viewMap.ts` | `AppView` → path (`pathForView`) |
| `src/routes/nav.ts` | `goView`, jump keys, nav labels |
| `src/main.tsx` | Wraps the app in `BrowserRouter` |

`App.tsx` syncs pathname ↔ store via `parsePathname` / `navigatePath`. Workspace chrome follows the URL `/workspaces/:id`, not localStorage alone. Views must not write `#/...`. `/admin/secrets` bookmarks land on `/admin/credentials`.

## Workspace strip

| Label | Path |
|---|---|
| **Home** | `/workspaces/:id` |
| **Editor** | `/workspaces/:id/editor` |
| **Runs** | `/workspaces/:id/runs` |
| **Models** | `/workspaces/:id/models` |
| **Ship** | `/workspaces/:id/ship` |
| **Datasets** | `/workspaces/:id/datasets` |

Lineage (`…/runs/:runId/lineage`) and Compare (`…/runs/compare`) are Runs panels, not strip items.

## Library and admin

Templates · Agent inbox · Artifacts · Plugins · Worker fleet · Credentials · Ops · Access. Global Library does not host Models or Ship.

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

**Viewport containment:** `html/body/#root` use `max-height: 100dvh; overflow: hidden`. App shell + body row + `main` are `min-h-0 overflow-hidden` so pages never grow past the window; scroll lives inside panes.

**Docker — UI changes only:** `docker compose build graphyn-ui && docker compose up -d --no-deps graphyn-ui`. Never `compose up` / recreate `graphyn-api` for frontend work — full plugin reinstall is **15+ minutes**.
## Command palette / keyboard help

Primary jumps: Home, Editor, Runs, Datasets, Artifacts, Templates, Library · Plugins, Ship (Package|Devices), Worker fleet, Ops.

Secondary **Runs panels:** Runs → Lineage (`/workspaces/:id/runs/:runId/lineage`), Runs → Compare (`/workspaces/:id/runs/compare`).
