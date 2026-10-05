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

**Route aliases** (`resolveRouteAlias(pathname, workspaceId)` in `parsePath.ts`, tested in `routes/routeAliases.test.ts`): short / legacy URLs redirect (replaceState via `canonical`) — `/plugins` `/library` → `/library/plugins`; `/ops` `/admin` `/system` → `/admin/ops`; `/credentials`, `/access`, `/workers` `/deploy` → `/deploy/workers`, `/inbox` `/agent` → `/agent/inbox`, `/library/templates` → `/templates`; workspace pages `/runs` `/editor` `/models` `/ship` `/datasets` `/home` `/compare` (+ tail, e.g. `/runs/<id>/logs`) → `/workspaces/<active>/…` (no workspace → `/workspaces`; `/datasets` → `/library/datasets`); `/workspaces/:id/templates|plugins|ops|…` → the global page, `/workspaces/:id/builder|data|edge|home|compare` → the real segment.

**Unknown URLs** (no route, no alias — `/nonsense`, `/404`, `/workspaces/:id/<junk>`): `parsePathname` returns `notFound: true` and App renders `components/NotFoundView.tsx` (“Page not found” + the path + Home + closest real route from `suggestRouteFor()`). No silent redirect to Home.

## Workspace strip

| Label | Path |
|---|---|
| **Home** | `/workspaces/:id` |
| **Editor** | `/workspaces/:id/editor` · `/workspaces/:id/editor/pipelines/:name[/:env]` (`paths.editor(ws, name, env)`; parsed to `editorPipeline`/`editorEnv`, App calls `openPipelineInEditor` → Editor `openPipelineEnv`, URL replaced with `/editor`) |
| **Runs** | `/workspaces/:id/runs` |
| **Models** | `/workspaces/:id/models` |
| **Ship** | `/workspaces/:id/ship` |
| **Datasets** | `/workspaces/:id/datasets` |

Lineage (`…/runs/:runId/lineage`) and Compare (`…/runs/compare`) are Runs panels, not strip items.

## Sidebar sections (`routes/navSections.ts`)

**Work** (the strip above) · **Library** — Templates · Plugins · **Admin** (collapsible, closed by default, pref `graphyn.nav.adminOpen`; auto-open while an Admin page is active; collapsed header shows the pending-proposal count) — Agent inbox · Worker fleet · Credentials · Ops · Access. Highlight via `navHighlightFor(view)` (Compare → Runs, Devices → Ship; none on a 404). Workspace switcher (name + Switch / Open) sits above Work. Global Library does not host Models, Ship, or Artifacts (removed — use Runs → Run outputs / Lineage).

## Header chrome

- Subtitle: `Home · {project} · {view}` when a workspace is open.
- Header is minimal: brand + workspace name · backend status indicator · Last-run control · ? · notifications · settings.
- **Switch** lives in the sidebar workspace switcher. The header **Back to <workspace>** / **Open workspace** chip shows only while the sidebar is collapsed (otherwise it duplicates the switcher).
- Last-run control label: **Last run · <pipeline name> · <status>** (`runDisplayName` of the latest `GET /runs?project=` row; status via `runStatusLabel`, coloured only for exceptions). A separate amber pill only for an in-flight run without an id yet or a progress message.
- Last-run menu: **Overview** (Lineage path) · **Run outputs** · **Compare runs…** (jumps into Runs panels for the last run from any page).
- Last-run chip is **workspace-scoped**: only with an active workspace; source is `GET /runs?project=` latest, else store `lastRunId` only when `lastRunProject === activeProject`. A fallback id is verified with `lib/runExists.ts` (`GET /runs/{id}` — `/status` answers 200 `unknown` for deleted runs); 404 or a run owned by another workspace clears it. Store `runOutcome` is keyed by `runOutcomeRunId` and ignored for any other run id.
- **Menus / popovers:** `lib/menus.ts` `useMenuDismiss(open, close, rootRef)` — Escape (capture phase), outside pointerdown, and one-open-at-a-time via the `graphyn:menu-open` window event. Used by header Last-run menu, NotificationBell, Templates/Plugins/Workspaces ⋯ menus; `FieldSelect` joins the one-open event. `installGlobalDetailsMenuDismiss()` (App) applies the same rules to ad-hoc `<details class="relative">` popovers with an absolute panel child (Runs **Manage**).
- **Per-view error boundary:** the main pane is wrapped in `components/ViewErrorBoundary` (`resetKey=view`) so a crashing page keeps the sidebar/header (inline “This page failed to load” · Reload page / Try again / Report).
- `EmptyState` takes an optional lucide `icon` (default `Inbox`) rendered in its badge.
- **Shared UI (`components/ui.tsx`)**: `StatusBadge` (generic, sentence-cased) + `kind="run"` / `RunStatusBadge` (shared run vocabulary — coloured only for failed / running / queued / paused / needs action / cancelled; Done / Archived plain muted text); `SectionLabel` (sentence-case heading = `.ide-section-title`, 12px semibold); `Card` (`.ui-card` — border + subtle shadow, 8px radius, `--space-*` padding; `padding="sm"|"none"`); `ShortId` (8-char mono, copy on hover). Status vocabulary lives in `lib/runDisplay.ts`: `runStatusLabel`, `runStatusTone`, `isRunStatusException`, `shortId`.
- **Toasts** (`ToastHost`): 20rem wide, `bottom: var(--toast-bottom-inset, 1rem)`; any bottom-docked element marked `data-toast-avoid` pushes the stack above it; pages can also call `useToastBottomInset(px)` (`lib/toastInset.ts`).
- Editor: proposal badge when `pendingProposalCount > 0`.
- Backend status indicator (dot + **Local** / **Distributed**; exceptions **Sign in** amber, **Offline** rose). Tooltip spells it out (“Local backend · signed in”). Click → Mode A vs B explainer (Mode A primary = Got it); also opens when the API is offline (401 still opens Settings). Other screens open it via `openModeExplainer()` (`lib/menus.ts`, event `graphyn:open-mode-explainer`).
- **Notifications** (`NotificationBell`): titles humanized by `lib/notifications.ts` (“Run succeeded · <graph> · <workspace>”, also `pipeline_failed` / `pipeline_cancelled`), short run ids; opening a run checks existence first and toasts “Run … no longer exists” on 404.
- **Request de-dup:** `lib/sharedFetch.ts` — notifications (`notifications:30`), pending proposals (`proposals:pending`, shared by App badge + Agent inbox), run existence. In-flight joins + short result cache; `fresh: true` after mutations.
- **Layout mode** toggle (Master | Stack): `LayoutModeControl` — persists `graphyn.layout.mode` (`master-detail` side-by-side vs `container-content` stacked).
- **Z-stack (top → bottom):** modals/palette `z-[100+]` → `FieldSelect` portal `z-[80]` → app header + Last-run menu `z-40` → `ViewShell` page chrome `z-10` → run detail strip (Manage menu `z-30` inside) → page body. Header is `relative z-40` so dropdowns paint above the main column.

## App-wide layout system (`src/layout/`)

| Piece | Role |
|---|---|
| `ViewShell` | Dense IDE page chrome (15px title, `px-4 py-2` border-b) + fill body; optional `inlineToolbar` puts title · toolbar · actions on one row (Runs) |
| `WorkbenchPage` | `ViewShell` + `.workbench-scroll` body — Library/Admin screens |
| `MasterDetail` | Shared responsive list\|detail (see **Master–detail rules** below); divider width key `graphyn.layout.master` (`widthKey` overrides); optional `collapsible` — user-only collapse persisted per page at `${storageKey}.collapsed` (default `graphyn.layout.md.<listLabel>`); `MasterDetailToggle` / `useMasterDetail()` for detail-header toggles |
| `ActionBar` / `ResponsiveTable` (`src/components/`) | `primary` / `secondary` / `overflow` action row — wraps, moves `secondary` into a ⋯ menu below `collapseBelow` px (container width); tables get `.responsive-table` horizontal scroll + sticky first column |
| `LayoutPrefsProvider` | Wraps App; mode preference for all `MasterDetail` consumers |
| `LAYOUT_KEYS` | `nav` · `master` · `stack` · `nested` — one divider width synced across History/Live/Compare + Library screens |
| `SplitPane` | Broadcasts `graphyn:layout-split` so same-key panes stay aligned; `paneOverflow="hidden"` when children scroll; clamps primary size to leave ≥240px for the secondary pane (ResizeObserver) so a fat stored width cannot hide detail |

**Shell:** flat workbench (`#f0f2f5` app / `#ebedf0` nav, no mesh). Header `h-11` — brand **Graphyn** + workspace subtitle when open (page title lives in `ViewShell` / `WorkbenchPage`, not duplicated). Nav rows use `.ide-row`. Nav follows `sidebarModeFor(width, pref)` (see **Responsive shell**); the full nav is a resizable `SplitPane` (`graphyn.layout.nav`); the laptop/desktop collapse choice persists (`graphyn.layout.navOpen`). List/detail screens (Runs, Models, Agent inbox, Compare, Datasets, Templates) use `MasterDetail`; other feature pages use `WorkbenchPage`.

**Tabs:** page sections → `IdeTabs` (`.ide-tabs` / `.ide-tab`); mode switches → `SegmentedTabs` (`tab-pill`); catalog/status filters with counts → `catalog-pill`. Master/detail empties prefer `EmptyState` `compact`.

**Viewport containment:** `html/body/#root` use `max-height: 100dvh; overflow: clip` (blocks scrollIntoView/focus scrolling too). App shell + body row + `main` + `ViewShell` root are `min-h-0 overflow-hidden` and carry `data-shell-noscroll` — App snaps any accidental scroll on them back to 0, so the header is always visible. The document never scrolls; each pane scrolls itself.

**Responsive shell** (`lib/viewport.ts` — `BREAKPOINTS` phone <768 · tablet 768–1023 · laptop 1024–1439 · desktop ≥1440; `useViewport`, `useElementWidth`; pure helpers unit-tested):
- **Sidebar** (`sidebarModeFor`): ≥1024 full by default, header toggle collapses to the icon rail and persists; 768–1023 always the icon rail (icons + tooltips, workspace initials button, Admin as an icon popover) — a stored "open" never forces full below 1024; <768 hidden, header ☰ opens the full nav as an overlay drawer (closes on navigation, backdrop, Esc). Below 1024 the header button opens that drawer (not persisted).
- **Header:** never clips at 360px — right cluster is `shrink-0`; below 1024 the Last-run chip collapses to a history icon + status dot (name/status in the tooltip, ▾ menu kept), the run-progress pill shows ≥1024 only, "Back to workspace" hides; logo mark hides <400px. Help / notifications / settings always visible.

**Master–detail rules** (`masterDetailModeFor`): ≥1024 `split` — list | detail; the list is collapsible **by the user only** (pages never auto-collapse on tab switches). 768–1023 `overlay` — detail full width, list is a drawer opened by the "Runs ▾" toggle; closes on selection (`selectedKey` change or a click on `[data-md-select]` / `li button` / `li a` / `[role=option]`; opt out with `data-md-keep-open`), backdrop or Esc. <768 `stack` — list OR detail: list first when `selectedKey` is null, "‹ Runs" back button in the detail (`onBack` e.g. clears the selection). Pages put `<MasterDetailToggle />` in their detail header; without one MasterDetail renders a fallback rail/bar. Panes stay mounted across drawer open/close (scroll + state preserved).

**Docker — UI changes only:** `docker compose build graphyn-ui && docker compose up -d --no-deps graphyn-ui`. Never `compose up` / recreate `graphyn-api` for frontend work — full plugin reinstall is **15+ minutes**.
## Command palette / keyboard help

Primary jumps: Home, Editor, Runs, Datasets, Templates, Library · Plugins, Ship (Package|Devices), Worker fleet, Ops.

Secondary **Runs panels:** Runs → Overview (`…/lineage`, key **O**), Runs → Run outputs (`…/outputs`, key **A**), Runs → Compare (`…/runs/compare`).

While a workspace is open, Home / Models / Ship / Datasets appear only in the **Workspace** section (the Views section skips them). The Compare hint is the real `paths.runsCompare(ws)` path (“Open a workspace first” otherwise). Every item runs through `confirmNavigation()` (Editor unsaved-changes guard, `lib/navigationGuard.ts`).

## Editor document state (see `frontend-features.md` → Builder)

Unsaved tracking is vs. a baseline signature (document only, never run status); amber dot on **Save** + `beforeunload` + `lib/navigationGuard.ts` guard for app navigation; confirm before a load replaces the canvas. Undo/redo: 50 steps, same-field edits coalesce, Ctrl/Cmd+Z · Shift+Ctrl/Cmd+Z / Ctrl+Y (not while typing). Schema validation (min/max/exclusive/multipleOf/integer/enum/length/pattern) blocks Run/Save and badges invalid nodes; `visible_if` / `depends_on` hide conditional fields. Catalog add is click or drag-drop (hint only on empty canvas); connect tip only when nodes exist without edges; pipeline name and switching are one control (editable name + ▾ saved-pipeline list; name = document slug, Save synced); draft/staging/prod switches only for existing pointers.

**Canvas minimap (2026-10-04):** anchored **bottom-right** (zoom Controls and the Triggers dock are bottom-left; tips/badges top), sized from the canvas box by `features/builder/canvasMinimap.ts` `minimapLayout` (140–200 px wide, 3:2, ≤ ¼ canvas height, 12 px margin) and **hidden below 720×420 px** canvas. A small **Map / Hide map** toggle sits just above it (pref `graphyn.builder.minimapOpen`).

**Workflow canvas (2026-10-05):** `buildGraphFromCanvas` / `eventTriggerToIr` derives a timer `event_trigger` for `schedule_trigger` from config `cron` / `interval_s` when the canvas has no explicit trigger (same shape as MCP `_schedule_event_trigger`). `GraphynNode` draws a red `graphyn-handle-error` output when the step's `on_error.mode` is `route` and captions branch outputs (true/false, approved/rejected, output/error; tones from `workflowIr.portCaptions`) just outside the card above each handle. `DeletableEdge` shows an amber `if <condition>` chip for edges with an IR `condition` (chip click → `SELECT_EDGE_EVENT` → edge inspector) and draws wires out of a routed error port dashed red. On load the routed error port is not added to catalog outputs (it comes from `on_error`). `categoryLook(category, nodeType)` gives `*_trigger` nodes (webhook / schedule, catalog category “Input”) a neutral slate Zap icon instead of the red audio look. The Triggers dock (bottom-left, `min(100%−1.5rem, 24rem)` wide, ≤ 85 % canvas height) and `RunInputsDialog` (portal modal, `max-h: 100dvh − 2rem`) stay usable at 360 px.
