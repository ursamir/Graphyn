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

`App.tsx` syncs pathname ↔ store via `parsePathname` / `navigatePath`. Workspace chrome follows the URL `/workspaces/:id`. On a **global** route (Templates, Library, Admin, Agent inbox, …) a cold load resumes the last active workspace from `localStorage` `graphyn.activeProject` (`readInitialProject` in `appStore.ts`; never on `/` or `/workspaces`, and Switch / the picker clear it); App validates it against `GET /projects` and drops it (plus `graphyn.recentWorkspaces` entry) if deleted. Views must not write `#/...`. `/admin/secrets` bookmarks land on `/admin/credentials`.

**Unknown URLs** (`/plugins`, `/credentials`, `/404`, …): `parsePathname` returns `notFound: true` and App renders `components/NotFoundView.tsx` (“Page not found” + the path + Home + closest real route from `suggestRouteFor()` — e.g. `/plugins` → `/library/plugins`, `/credentials` → `/admin/credentials`; workspace routes only when a workspace is known). No silent redirect to Home. `/workspaces/:id/<junk>` still canonicalizes to `/workspaces/:id`.

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

Templates · Agent inbox · Plugins · Worker fleet · Credentials · Ops · Access. Global Library does not host Models, Ship, or Artifacts (removed — use Runs → Run outputs / Lineage).

## Header chrome

- Subtitle: `Home · {project} · {view}` when a workspace is open.
- Workspace chip **only** when URL is `/workspaces/:id` (`workspaceOpen`); **Switch** clears then opens picker.
- Global Library with `activeProject` in localStorage but no workspace URL → **Open workspace** (restore), not the chip (avoids chip+global-nav contradiction).
- Last-run menu: **Overview** (Lineage path) · **Run outputs** · **Compare runs…** (jumps into Runs panels for the last run from any page).
- Last-run chip is **workspace-scoped**: only with an active workspace; source is `GET /runs?project=` latest, else store `lastRunId` only when `lastRunProject === activeProject`. A fallback id is verified with `lib/runExists.ts` (`GET /runs/{id}` — `/status` answers 200 `unknown` for deleted runs); 404 or a run owned by another workspace clears it. Store `runOutcome` is keyed by `runOutcomeRunId` and ignored for any other run id.
- **Menus / popovers:** `lib/menus.ts` `useMenuDismiss(open, close, rootRef)` — Escape (capture phase), outside pointerdown, and one-open-at-a-time via the `graphyn:menu-open` window event. Used by header Last-run menu, NotificationBell, Templates/Plugins/Workspaces ⋯ menus; `FieldSelect` joins the one-open event. `installGlobalDetailsMenuDismiss()` (App) applies the same rules to ad-hoc `<details class="relative">` popovers with an absolute panel child (Runs **Manage**).
- `EmptyState` takes an optional lucide `icon` (default `Inbox`) rendered in its badge.
- **Toasts** (`ToastHost`): 20rem wide, `bottom: var(--toast-bottom-inset, 1rem)`; any bottom-docked element marked `data-toast-avoid` pushes the stack above it; pages can also call `useToastBottomInset(px)` (`lib/toastInset.ts`).
- Editor: proposal badge when `pendingProposalCount > 0`.
- Mode chip (Local / Distributed): click → Mode A vs B explainer (Mode A primary = Got it); also opens when the API is offline (401 still opens Settings). Other screens open it via `openModeExplainer()` (`lib/menus.ts`, event `graphyn:open-mode-explainer`).
- **Notifications** (`NotificationBell`): titles humanized by `lib/notifications.ts` (“Run succeeded · <graph> · <workspace>”, also `pipeline_failed` / `pipeline_cancelled`), short run ids; opening a run checks existence first and toasts “Run … no longer exists” on 404.
- **Request de-dup:** `lib/sharedFetch.ts` — notifications (`notifications:30`), pending proposals (`proposals:pending`, shared by App badge + Agent inbox), run existence. In-flight joins + short result cache; `fresh: true` after mutations.
- **Layout mode** toggle (Master | Stack): `LayoutModeControl` — persists `graphyn.layout.mode` (`master-detail` side-by-side vs `container-content` stacked).
- **Z-stack (top → bottom):** modals/palette `z-[100+]` → `FieldSelect` portal `z-[80]` → app header + Last-run menu `z-40` → `ViewShell` page chrome `z-10` → run detail strip (Manage menu `z-30` inside) → page body. Header is `relative z-40` so dropdowns paint above the main column.

## App-wide layout system (`src/layout/`)

| Piece | Role |
|---|---|
| `ViewShell` | Dense IDE page chrome (15px title, `px-4 py-2` border-b) + fill body; optional `inlineToolbar` puts title · toolbar · actions on one row (Runs) |
| `WorkbenchPage` | `ViewShell` + `.workbench-scroll` body — Library/Admin screens |
| `MasterDetail` | Shared list\|detail splitter; follows layout mode; default key `graphyn.layout.master`; optional `collapsible` (Runs) hides master to a rail |
| `LayoutPrefsProvider` | Wraps App; mode preference for all `MasterDetail` consumers |
| `LAYOUT_KEYS` | `nav` · `master` · `stack` · `nested` — one divider width synced across History/Live/Compare + Library screens |
| `SplitPane` | Broadcasts `graphyn:layout-split` so same-key panes stay aligned; `paneOverflow="hidden"` when children scroll; clamps primary size to leave ≥240px for the secondary pane (ResizeObserver) so a fat stored width cannot hide detail |

**Shell:** flat workbench (`#f0f2f5` app / `#ebedf0` nav, no mesh). Header `h-11` — brand **Graphyn** + workspace subtitle when open (page title lives in `ViewShell` / `WorkbenchPage`, not duplicated). Nav rows use `.ide-row`. Desktop nav is a resizable `SplitPane` (`graphyn.layout.nav`); collapse persists (`graphyn.layout.navOpen`). List/detail screens (Runs, Models, Agent inbox, Compare, Datasets, Templates) use `MasterDetail`; other feature pages use `WorkbenchPage`.

**Tabs:** page sections → `IdeTabs` (`.ide-tabs` / `.ide-tab`); mode switches → `SegmentedTabs` (`tab-pill`); catalog/status filters with counts → `catalog-pill`. Master/detail empties prefer `EmptyState` `compact`.

**Viewport containment:** `html/body/#root` use `max-height: 100dvh; overflow: hidden`. App shell + body row + `main` are `min-h-0 overflow-hidden` so pages never grow past the window; scroll lives inside panes.

**Docker — UI changes only:** `docker compose build graphyn-ui && docker compose up -d --no-deps graphyn-ui`. Never `compose up` / recreate `graphyn-api` for frontend work — full plugin reinstall is **15+ minutes**.
## Command palette / keyboard help

Primary jumps: Home, Editor, Runs, Datasets, Templates, Library · Plugins, Ship (Package|Devices), Worker fleet, Ops.

Secondary **Runs panels:** Runs → Overview (`…/lineage`, key **O**), Runs → Run outputs (`…/outputs`, key **A**), Runs → Compare (`…/runs/compare`).

While a workspace is open, Home / Models / Ship / Datasets appear only in the **Workspace** section (the Views section skips them). The Compare hint is the real `paths.runsCompare(ws)` path (“Open a workspace first” otherwise). Every item runs through `confirmNavigation()` (Editor unsaved-changes guard, `lib/navigationGuard.ts`).

## Editor document state (see `frontend-features.md` → Builder)

Unsaved tracking is vs. a baseline signature (document only, never run status); **Unsaved** chip + `beforeunload` + `lib/navigationGuard.ts` guard for app navigation; confirm before a load replaces the canvas. Undo/redo: 50 steps, same-field edits coalesce, Ctrl/Cmd+Z · Shift+Ctrl/Cmd+Z / Ctrl+Y (not while typing). Schema validation (min/max/exclusive/multipleOf/integer/enum/length/pattern) blocks Run/Save and badges invalid nodes; `visible_if` / `depends_on` hide conditional fields. Catalog add is click or drag-drop (hint only on empty canvas); connect tip only when nodes exist without edges; Open vs Name are distinct (load vs document slug, Save synced); draft/staging/prod switches only for existing pointers.
