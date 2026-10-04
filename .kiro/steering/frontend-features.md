# Frontend features (graphyn-ui)

Persona UX notes for feature screens. Shell/nav labels: `frontend-canvas.md`. Canonical IA: `docs/IA_PROJECT_FIRST.md`.

**Nav labels:** Workspace strip: Home · Editor · Runs · Models · Ship · Datasets. Library and admin: Templates · Agent inbox · Plugins · Workers · Credentials · Ops · Access.

**Client / polling contracts (2026-09-30):**
- `apiFetch` forwards the caller's `AbortSignal` for the whole response lifetime (headers **and** body streaming); `timeoutMs` covers the headers phase only; a caller-aborted request is never retried. `parseError` / `configuredActor` are exported from `api/client.ts`.
- Background polls use `lib/usePolling.ts` (pure loop `startPolling`; in-flight skip; the **immediate first call always runs, even in a hidden tab** — only interval ticks pause while `document.hidden`, catch-up on visible): Runs status (2 s) + Live tab (3 s), Workers (15 s), NotificationBell (45 s), App pending-proposals badge (60 s). Poll failures toast once per outage. Endpoints read by more than one component go through `lib/sharedFetch.ts` so a poll cycle issues one GET (notifications, `proposals?status=pending`).
- **Terminology:** UI says **workspace** for the project concept (API fields stay `project`). Server “Invalid project name …” / “Project 'x' not found|already exists” are rephrased by `lib/workspaceName.ts` `workspaceErrorMessage()`; client validation `workspaceNameError()` mirrors the server rule (letters, digits, `-`, `_`; 1–128).
- `graphyn-ui/nginx.conf` `/api/`: `proxy_buffering off` (NDJSON/SSE), `proxy_read_timeout 3600s`; server `client_max_body_size 2g`.

**Workspace validity (`lib/workspaceValidity.ts`):** every workspace id from the URL or resumed from localStorage is checked with `GET /projects/{id}` (200/404) before it is persisted. The store only writes `graphyn.activeProject` for validated ids (`commitActiveProject`); `noteRecentWorkspace` ignores known-missing ids. A missing URL id (any `/workspaces/<id>/…` route) renders `components/WorkspaceNotFoundView` (links: most recent valid workspace + All workspaces), title "Graphyn · Workspace not found"; the store falls back to the most recent valid recent (`pickFallbackWorkspace`), not "No workspace open". Recents not in `GET /projects` are pruned on boot (`pruneRecentWorkspaces`). While an id is being checked the main pane shows "Opening workspace…".

**Navigation guard (`lib/navigationGuard.ts`):** `registerNavigationGuard(fn: () => boolean | string): () => void` (false/'' = clean; true/message = unsaved). `confirmNavigation()` (window.confirm "You have unsaved changes in the Editor — leave anyway?") is consulted by sidebar/jump keys (`App.go`), header Switch / Back-to chip / Last-run menu, every command-palette item, and `routes/nav.ts` `goView` / `guardedNavigatePath` (both return false when cancelled). The Editor registers its dirty guard.

**Titles:** `Graphyn · <View>[ · <workspace>]` — workspace suffix only on workspace-scoped URLs; picker = "Workspaces"; unknown URL = "Graphyn · Not found"; `/login` = "Graphyn · Sign in".

**Path routes:** `src/routes/paths.ts`, `viewMap.ts`, `nav.ts` (`goView` / `guardedNavigatePath` / `replacePathSearch` / `onPathChange`). Views must not write `#/...`. `stripLegacyAppHash()` in `parsePath.ts` drops a leftover `#/…` fragment. `/admin/secrets` canonicalizes to `/admin/credentials`.

**Shared UX helpers (2026-10-03, UX overhaul):** `lib/metrics.ts` — `formatMetric(0.5611)` → `0.561` (`{percent:true}` → `56.1%`), `metricLabel`, `isRatioMetric`, `pickPrimaryMetric` / `primaryMetric(run)` (`summary.primary_metric` → flat `metrics` by preference test_accuracy > accuracy > val_accuracy > f1), `regressionOf`, `formatDelta`. `lib/runDisplay.ts` `runDisplayName(run)` — backend `display_name` (top level or `meta`), else humanized non-generic `graph_name`, else `Run <short id>`; never the bare "pipeline". `api/errorCode.ts` `apiErrorCode(err)` / `apiErrorDetail(err)` read `{error:{code}}` / `{detail:{code}}`. Every list consumer normalizes with `unwrapList` (bare array or `{items}`) — never `Array.isArray(x) ? x : []` on `/runs`, `/projects/*/pipelines`, `/data/*`.

**Per-view crash boundary:** `components/ViewErrorBoundary` wraps only the main pane in `App` (`resetKey=view`) — a crashing page shows “This page failed to load” with **Reload page** / **Try again** / **Report** (copies `lib/crashReport.ts` text) while the sidebar/header keep working; switching view clears it. The app-level `ErrorBoundary` remains the last resort.

**Copy rules:** primary UI copy never shows env var names, API routes, raw workspace paths or internal ids — those go in `title` tooltips or an **Advanced** disclosure. “Model stage” (staging / production of a trained model, Models page) and “Pipeline version” (published graph versions, Home) are always named that way.

## Models (`ModelsView`)

- `ViewShell` + `MasterDetail` (shared `graphyn.layout.master`); list registered models; request/approve production; register from name + training run (+ model file picker when `GET /runs/{id}/models` exists → sends `model_path`, name prefilled from `suggested_name`; 422 `compiled_untrained` → confirm then `allow_untrained:true`; `model_not_in_run` explained). Old APIs fall back to `slug`.
- Scope: `SegmentedTabs` in toolbar (**This workspace** | **All workspaces**) when a workspace is open; master rows show `modelDisplayName` (backend `display_name`, else node-id-like names such as `edge_optimizer_0` → “Edge Optimizer model”; raw name in tooltip) + headline metric; detail empty → compact `EmptyState`.
- Detail stage cards (“Model stage · staging/production/latest”, help tooltip per stage): facts from resolved registry stage fields (`features/models/modelDisplay.ts` `stageFacts`: primary metric, format, size, classes), **From run** = `source_run_display_name` / `runDisplayName`, path label + producing node (from stage or matching `GET /runs/{id}/models` row), created time, `exists:false` warning. **Request production** carries a plain-language explanation (approver must confirm). Note under the cards distinguishes model stages from pipeline versions.
- **Use in Ship** navigates `…/ship?run_id=&model=&stage=` (staging first) so Ship preselects that model.
- Detail: **How it was made** via `openTrace({ runId })`; **Datasets** / Home when workspace known.
- Deep-link via path helpers when workspace is open.
- Load error that empties the list clears `selected` / detail (no stale detail pane).

## Projects (`ProjectsView`)

- Picker: filter + dense rows; create in explorer header. Workspace list / filter empties and Home list panels (Activity, Continue, Always-on, linked inputs) use shared `EmptyState` (`compact` in side cards). Spec & metadata drawer uses `SegmentedTabs` (Versions · Spec · … · Diff). **Create workspace** validates inline (`workspaceNameError`): message under the input, red border, Create disabled until valid; server errors rephrased via `workspaceErrorMessage`. Row ⋯ menu is Open, View runs, Clone, then Delete. The list does not use `overflow-hidden`, so that menu (including Delete on the last row) paints outside the card. Open a workspace for the same Delete under Workspace settings.
- **Home / Overview:** first-run 2-card strip when empty (Templates · Datasets); header keeps primary **Open Editor**.
- Header subtitle: “Status: Getting started / In progress / Ready / Archived” (+ “Dataset version vN” when focused) — not the raw `draft · v1`. Metrics strip: Pipelines · **Datasets in use** (was Pinned inputs) · Last run (`runDisplayName` · status, id in tooltip) · **Pipeline versions** (was Envs; staging / production of saved graphs).
- **Latest result** card (`features/projects/latestResult.ts` `pickLatestResult`): newest non-failed run with a primary metric → big formatted metric, regression badge from `regression.delta` (Regression / Improved / No change vs best earlier run), **Open run** and **Open model** (registered model whose stage points at the run, from `GET /models`).
- **Datasets in use** card (was Linked inputs): choose dataset folders (`/projects/{id}/links`); runs don't add folders automatically. Versions & taxonomy collapsed.
- Workspaces picker stat **With recent runs** = listed workspaces that have a run in the recent `/runs` page (“of N workspaces”) — previously “Active” counted every project id on runs, so it could exceed the workspace count.
- Pipeline **pin favorites** via `localStorage` `graphyn.pinnedPipelines.{project}` (star; pinned sort first).
- Pipeline **Rollback** near promote (POST `.../pipelines/{name}/rollback` with required `version`).
- **Always-on** strip: schedules fetched with `?project=` and filtered client-side by `schedule.project === workspace`; “Last error: …” shown; else “No schedules for this workspace” + CTA to Ops.
- **Activity** run rows (Home and the cross-workspace feed) show `runDisplayName` + primary metric (`Test accuracy 56.1%`), relative time (`created_at`, full timestamp on hover) + status badge. Schedule rows: only this workspace's schedules; show `last_error`; click verifies the schedule's `last_run_id` exists (`checkRunExists`) — missing → toast + Ops (Schedules) instead of a dead run link. Recent-run rows open with `{ project: selected }`.
- `open(name)` failure: keep selection, clear Home payload, show ErrorBanner (no empty-home pretend-success).
- `open(name)` has a request-sequence guard (`openSeqRef`): a slower open(A) never paints A's data under B. Spec / taxonomy / contract fall back to empty **only on 404**; other errors show inline and disable that tab's Save (also disabled while loading or when the editor holds another workspace's content).

## Builder (`BuilderView`)

- Primary **Run / Cancel · Save · graph name**; Validate / Templates / Triggers / Agent live under **More**.
- **Triggers dock (A6/A9/A10):** interval schedules via `GET/POST /system/schedules` (filtered by project); webhook preview from `GET /system/webhooks` (redacted; copy does not include the secret path); link to Ops. Label “Interval (minutes)”.
- **Agent drawer (B1/B2):** prompt → `POST /proposals` stub graph; pending count + Open inbox; optional “Save to project after load” preference (`graphyn.builder.saveAfterProposalLoad`) — Accept remains inbox-side.
- **Mode A badge (A13):** when Local and graph has placement fields → “Placement ignored in Mode A” toast pointing at header Mode chip.
- **Credential picker:** `connection_id` fields use a `<select>` filled from `GET /credentials` (Admin → Credentials). Empty falls through to the workspace default, then env.
- **HITL/wait (B6):** selected `wait*` node shows callout (dedicated HITL TBD).
- **Retry/timeout (B9/B14):** graph settings note — per-node fields live in Config when plugin exposes them.
- `actionError`: **View outputs** / Retry only for run failures (or last run succeeded); not for validate / missing-path errors.
- Success toast **View outputs** → Runs → Run outputs; fail → Open failed run / logs.
- Catalog empty: auth / API offline / no plugins (distinct CTAs). Narrow viewport honesty banner.
- Catalog load (`App.refreshCatalog`) pages `GET /nodes` via `fetchAllPages` (API default `limit=50`; max page 500) so “All categories (N)” matches the full registry, not the first page.
- **Run stream:** exec status matches events by `node_id` only; backend `node_index` is the *execution-order* index, so the index fallback (events without `node_id`) maps through a client topological order, never the canvas array index. Terminal = `type=done` (success) or `type=error`; a stream ending without either shows “Stream disconnected — checking run status” and polls `/runs/{id}/status` to a terminal state. Only the current run (`abortRef.current === controller`) may clear `isRunning` / write run state. The `lastRunId` hydrate on mount is skipped when the run's `graph_name` differs from the canvas or it references node ids not on the canvas.
- Catalog rows whose config schema has `stub.default === true` show a **stub** badge. Proposed-pack nodes default `stub` to false, so they do not carry that badge.
- **Execution badge** (`builderRunState.ts`): derived from the server run status (or this session's own terminal stream event for that exact run id, kept in a module-level per-run outcome map) — never defaulted to “succeeded”, never from component-local flags that reset on remount.
- **Cancel** reads the server's result: per-node statuses come from the run's journal events, not from painting every running/pending node cancelled.
- **Late catalog:** a graph loaded before `/nodes` arrived is re-decorated (category, runtime, schema, ports, defaults under `config`) once the catalog loads.
- **Catalog ports:** `NodeRegistry.register` fills empty `NodeMetadata` ports from the class (isolated stubs historically omitted them). Builder `catalogPorts` / `portsNeedResync` / `decorateNodeData` re-sync canvas handles when the catalog advertises real named ports — catalog-drag and template-import show the same handles for every node type.
- **Copy node:** each canvas node has a Copy action (beside Configure / Remove) that clones type, config, placement, and ports with a new id offset on the canvas; edges are not copied. Write sinks (`output_path` / `output_dir`) are rebound to the new id.
- **Unique write paths:** catalog-add and graph load uniquify shared `workspace/artifacts/…` sinks per node id (trainer/evaluator/model_builder no longer collide on plugin defaults). Pipeline focus matches instance ids only — two Trainers stay distinct.
- **model_builder architectures:** presets `ds_cnn` / `mobilenet` / `simple_cnn` (paper-style blocks; tunable filters/depth/MobileNet knobs). `architecture=custom` uses a structured **Layers** list editor (add / reorder / typed fields; optional Edit as JSON). Inspector **Load layers from preset** appears only when architecture is `custom`.
- **JSON UX (Builder config):** treat JSON as three jobs — (A) known-shape structured config → form/list editor with **Edit as JSON** secondary; (B) freeform documents (artifacts, proposals, lineage) → tree/pretty viewer only; (C) escape hatch always available for A. `ConfigFieldEditor` wires Job A editors by `fieldKey`: `layers` → `LayersEditor`, `augmentations` → `AugmentationsEditor`, `split_ratios` → `SplitRatiosEditor` (train/val/test + sum check; custom keys if present), `allowed_paths` → `StringListEditor`. Other `widget=json` / object|array fields keep the compact textarea fallback.
- **Inspector collapse:** right inspector panel collapses like the catalog (`graphyn.builder.inspectorOpen`); selecting a node/edge re-expands it. Single header row (collapse + Node/Edge/Graph title); Local mode shows a one-line placement note instead of a dashed box. Field descriptions are brief under the control (full text on hover). Trainer `patience` is forced into Basic next to Epochs.
- **Editor toolbar:** three clusters — **Document** (workspace chip · **Open** saved pipeline · env `SegmentedTabs`/Publish · **Name**), **Run** (Run/Cancel · Save with amber dirty dot · Undo/Redo · invalid/error jump chips), **Overflow** (More: Validate, Templates, Triggers, Agent, **Save as…**, Save as template, import/export, clear). **Open** loads a workspace pipeline; **Name** is the single document slug (synced into Save’s `templateName` — no second NAME field in More). Env chips only for existing pointers; draft-only shows **Draft** + **Publish → staging**. Catalog filter label is **All nodes (N)**; “Click or drag…” subheader only when the canvas is empty.
- **Catalog add:** click **or** HTML5 drag onto the canvas (`application/graphyn-node`); drop uses `screenToFlowPosition` so the node lands under the cursor. Empty-canvas copy says “Click or drag…”.
- **Connect tip:** shown only when the canvas has nodes but **no edges** yet; dismissible (`graphyn.builder.connectTipDismissed`). Hidden once any edge exists — not a permanent overlay.
- **Canvas nodes:** subtitle shows visible field count (not schema length), `model_builder` architecture cue, and instance id suffix (`#0` / `#c3f15543`) so dual-branch copies are distinguishable.
- **Run-start errors** (503 registry not ready, 4xx validation, …) show an inline run-start error banner with the server detail instead of a generic toast.
- **Unsaved changes** (`graphHistory.ts`): `editorSnapshot` captures only the document (node type/label/config/placement/position, edges, name, seed — never run status/selection), compared by `snapshotSignature` to the last loaded/saved **baseline**. Dirty → amber dot on **Save** (no separate Unsaved chip); `beforeunload` prompt; an app navigation guard (`registerNavigationGuard` from `lib/navigationGuard.ts`) so sidebar / palette / workspace switch / `goView` confirm before leaving; `confirmDiscard` before an in-Editor action replaces the canvas (open pipeline/env, import, external load). Loading a graph resets the baseline and history.
- **Undo / redo:** bounded history (`HISTORY_LIMIT = 50`); rapid edits of the same field coalesce into one step (`changeKey`); Ctrl/Cmd+Z undo, Shift+Ctrl/Cmd+Z or Ctrl+Y redo (`historyShortcut`, ignored while typing in a field — browser text undo wins) plus toolbar buttons.
- **Config validation** (`configValidation.ts`): JSON-schema `minimum`/`maximum`, `exclusiveMinimum`/`exclusiveMaximum` (draft-4 boolean and draft-6 numeric), `multipleOf`, `integer`, `enum`, `minLength`/`maxLength`, `pattern`. Invalid fields get a red border + `aria-invalid`; nodes show an invalid-count badge; a banner lists issues and **Run / Save are blocked** while any exist. Conditional fields: `ui.visible_if = { field = value | [values] }` and `ui.depends_on = "field"` (truthy) or `{ field = value }` hide fields (hidden fields are not validated).
- **Log dedupe** (`logDedupe.ts`): a node `node_error` followed by the pipeline-level `error` with the same core message counts/renders once (Editor log panel + Runs → Logs pretty view; raw view unchanged).
- **Skipped nodes** (`builderRunState.ts`): on a failed/cancelled run, nodes that never started show **skipped (not run)** rather than idle/failed; a started-but-unfinished node is failed (or cancelled).

## Runs (`RunsView`) — unified observe

- Page title **Runs**; one list + detail (no History|Live|Compare peer tabs). Compare is a multi-select action; Active status filter replaces the old Live tab.
- Opening a run does **not** call `setActiveProject`. The address bar is the workspace; a run whose metadata names another workspace stays a detail selection.
- Run selection ↔ URL sync uses `window.history` directly (not `navigatePath`), so the App path sync does not call `store.openRun` and overwrite the header **Last run**. A missing run id renders one not-found state.
- **Run outputs** ordered by execution order, files natural-sorted; “+N more” pages via `?with_meta=1` and `?node_id=&limit=`. The API fills its 400 cap run-level files first, then models/metrics/small summaries, then bulk files, round-robin per node; source-node (ingest) input files are not outputs (`inputs_by_node` counts them). **Promote model** only for runs with a model output.
- **Run outputs grouping:** `guessNodeFromPath` (in `runOutputs.ts`) must never promote a run id / opaque hex to a pipeline step. Journal paths `runs/<run_id>/…` (including `outputs_index.json`) group as **Run-level**. `outputs_index.json` is hidden from the listing (API + UI). File-card subtitles use `shortOutputPath` (drop `workspace/` and `runs/<id>/`). Truncation chips name the step and sit under that step’s file list; a panel banner explains caps when any step is truncated. `PipelineStack` also filters opaque ids at render time.
- **File viewers:** pluggable via `components/viewers/registry.ts` (`registerFileViewer`). Built-ins: image, audio, video, json, text, npy, pickle, model, binary; popup expand on `FileViewer`. MIME fix for audio/video blobs in `api/client.ts` `blobUrlWithMime`. Session notes: `docs/WORKLOG_OUTPUTS_AND_VIEWERS.md`.
- Live runs: **Manage** is a native `<details>` (Pause / Resume / Cancel); Escape / outside click / one-open come from App's `installGlobalDetailsMenuDismiss()`. Terminal runs show **Archive** (confirm) and a `⋯` Advanced menu with **Delete permanently…** (typed full-run-id confirmation) — see *Run audit* below.
- **One layout always:** no `ViewShell` title strip on the list (sidebar already says Runs). MasterDetail edge-to-edge; master filter strip + detail run chrome share the same top edge whether or not a run is selected. Selecting a run must not change outer chrome.
- **List filter strip:** one dense row (status + search + metric toggle + refresh). Metric/min only expand when the slider control is on — avoids a ~250px stacked filter block in a narrow master pane. List status badges use short labels (`Done` / `Failed` / …).
- **Selected run chrome:** status · name · time · id · Editor · Manage(live) · **Register model**(when succeeded+model) · Delete(terminal) — success path before destructive. Register is chrome-only (no duplicate Overview banner); toggles a Close-able stage/register form on Overview (scrollable branch list; closes on tab leave). Label becomes **Close register** while open. Live in-flight runs also show a compact `LiveRunMonitor` (node wave / workers).
- Status filter includes **Active** (`running|queued|paused` via `statusMatchesFilter`); list polls every 3s while Active or a live status is selected; Active + empty selection auto-follows the newest active run. `/runs/live` aliases to `/runs?status=active`.
- List rows: dense stacked `ide-row` + checkbox for Compare (2–5); selection bar Clear / Compare → `openExperiments`. Metric name + min filters client-side; status/promote alias use `FieldSelect`.
- **Compare mode** (`focusRunsTab === 'compare'` / `/runs/compare`): `ViewShell` **Compare** + Back to runs + Refresh; embedded `ExperimentsView` (checkbox cards + params/metrics/charts).
- App nav collapse persists (`graphyn.layout.navOpen`).
- **Pipeline stack** (numbered circular steps + **All** on top) replaces the Focus dropdown — fixed `min-w` so labels stay readable; status is a dot. Dual-instance copies that share a base label get `#0` / `#c3f15543` cues (same as the builder canvas). When `computePipelineShape` is `fork`/`parallel` (multi-sink), the rail groups Shared → Path A → Path B (execution numbers preserved). Linear runs stay a plain numbered list.
- Detail panels use underline **IdeTabs** (not a heavy pill strip). Right pane shows content for **tab × stack** selection. Empty copy is focus-aware (Checkpoints / Logs / Outputs name the selected step).
- **Run outputs:** API stamps optional `node_id` on each file (ArtifactStore data dir, path refs inside `data.json`, basename hints). UI groups by that id; node focus hides journal-only run files; All shows nodes then dashed **Run-level**; node files split into Outputs / Inputs when detectable. Preview selection is scoped to files visible for the current focus (no stale `7.wav` while another step says in-memory). Nested file|preview `SplitPane` uses `graphyn.layout.nested` with `secondaryMinSize={320}` so the preview cannot be crushed. Audio-sample dumps are summarized (manifest + a few clips) so the listing cap stays usable. Focus filters groups by instance id only (`focusMatchesNode` is exact when focus is `trainer_0` / `trainer_b66a5330` — never soft-match via `humanNodeLabel`, or the hex-suffix Trainer/Evaluator re-merges its sibling). WAV preview converts IEEE-float / wide PCM to 16-bit via `lib/wavPlayable.ts` for browser playback. Console CSP (`index.html`) must include `media-src 'self' blob: data:` — without it Chromium rejects blob `<audio>`/`<video>` (`default-src 'self'` only).
- Focus filters Logs by extracting node hints from structured events **and** formatted lines (`Trainer · started`); bare type labels still match instances, but instance focus does not reverse soft-match a bare label. Empty Focus filter says “No logs for …” not “No logs recorded”.
- Run outputs meta is one thin row (truncated path · Latest · focus · **Download zip**), not a full header block. Zip packs files under `<node_id>/` (API); toast warns when listing/byte-capped. `FileViewer` chrome is one line (name · size · kind · Expand/Download; full path in tooltip). Pipeline stack + panel fill the remaining height.
- **Register model** (chrome only) when the run produced a model file/artifact (or already registered one) — `runHasModelOutput` / `listRunModelCandidates`. Dual branches listed to **register each by name**; **Stage artifact pack** is run-wide (`POST /runs/{id}/promote` → latest|staging|prod). **Artifact pack** = workspace slug from `artifacts/<slug>/runs/…` (`artifactSlugFromPath`). Registered list links **Open Models**. Preprocess / export runs never show Register.
- **Compare** tables (`CompareTable`): each table has its own `overflow-auto` (not a shared scroller — param tables with 100+ rows buried the H-bar). Cells `max-w` + truncate + `title` tooltip; sticky Key + sticky thead. Parameters caps body height (`maxBodyHeight`) so sideways scroll stays on-screen; hint when >3 runs. Embedded Compare master list scrolls inside MasterDetail.
- **Checkpoints** tab is omitted when the terminal run has none (optional resume points). Empty copy explains that many workflows never write them. Overview hides zero Checkpoints / Errors / Lineage-links counts; shows Metrics + collapsible Hot spots (duration) when present.
- Terminal runs hide progress / “Current node”; Focus is not auto-seeded from last node (avoids empty Outputs).
- Detail: **Overview** | **Run outputs** | **Logs** | **Checkpoints** (when present). Default: Overview when succeeded, Logs when live/failed/cancelled. Nested outputs splitter: `graphyn.layout.nested`. Legacy `/details` → Overview (`…/lineage`).
- `open(id)` / status poll / `refetchRunDetail` / `loadRunModels` drop results when the selection changed (`selectedRef` + `openSeqRef`). When the polled status turns terminal, detail (logs / outputs / artifacts) is refetched.
- Overview (= former Summary + Lineage): adaptive **Run story** — verdict + domain-agnostic **Got** outcome + duration **spine pills** for linear graphs (including single-sink train_ml / diamonds); **fork** map (Shared + Path A/B tracks with relative duration bars + per-path Got) when ≥2 sinks share a prefix; **parallel** tracks (no Shared) when sinks share nothing. Timeline is chronological for linear; sectioned Shared/Path only for fork/parallel. Wrote counts use `truncated_by_node.total` when the UI sample-caps audio dumps. No Browse-files button. **Export meta** downloads run+trace+readiness JSON. Saved-files/provenance fold into the map footer; Checkpoints/Errors strip only when non-zero. **Hot spots** closed `<details>`. Empty Wrote: “no files (data stayed in memory)”. Logs: clocks + line count (+ “N paths” when multi-track). Step click → Step story → **Run outputs**. Registry IDs under Advanced. Run outputs **Whole run** files use plain titles (Pipeline graph, Run summary, Event log, Reproducibility record).
- Failed/cancelled: compact inline banner. Succeeded: **Register model** → Overview (stage pack + register).
- **Node list** (`runNodes.ts` `pipelineNodesFromRun`): built from the run's graph in execution order (topological; ties by graph order / `node_stats` index), so nodes that never ran still appear, correctly numbered; status from journal events then `node_stats`; no status on a failed/cancelled run → **skipped**.
- **Ask agent to fix:** confirm panel first; creates a pending proposal (the run's unchanged graph + the real failing node / error from `extractRunFailure`, which reads `error` / `error_message` rather than `message`) in the Agent inbox; stays on the page, toast offers **Open proposal**.

## Experiments (`ExperimentsView`)

- Standalone shell: `WorkbenchPage` (**Compare runs**); embedded Runs → Compare keeps `MasterDetail` only.
- Prefer Runs → Compare when a workspace is open.
- **Params from node configs:** after `GET /experiments/compare`, each run's graph is loaded (`fetchRunGraph(runId, null)`) and merged via `compareEnrich.ts` `enrichCompareParams` → `runCompare.ts` `mergeRunParams` (`node_id.field` + `graph.<key>`; experiment params win). `param_keys` is rebuilt from `compareParamRows` (natural key order); differing cells highlighted; CSV export includes node config params. **Export CSV** is disabled when there are no param or metric rows.
- **Embedded** under Runs → Compare: `MasterDetail` (shared master width) — checkbox cards left, compare results right.
- Selection written to `/workspaces/:W/runs/compare?ids=` (path search).
- Compare: metric table + **MetricBars** charts for numeric metric keys; **Export CSV**.
- ErrorBanner **onRetry** → `runCompare()` when 2+ runs selected; else `refresh()`.

## Data (`DataView`)

- Shell: `WorkbenchPage`; Browse/Manage file browser uses `MasterDetail` (`listLabel="datasets"`, collapsible) — workspace/version or input label pickers live in the master list; detail holds toolbars, stats, file table, and compact `EmptyState`s (no duplicate pickers when the master list is shown).
- Page title **Datasets**; Browse | Manage; Inputs|Outputs ≠ Runs → Run outputs.
- `openData({ mode, project, version, label })` navigates `paths.datasets(W)` / `paths.libraryDatasets()` with search params (`manage=1` for ingest/merge).
- First-visit dismissible “Which storage?” strip (Datasets vs Run outputs vs Artifacts).
- Label lite only under Manage.
- Input labels with `accessible: false` (external symlink) are never auto-selected; options marked “external (blocked)”; failed browse clears selection and never shows Upload-as-primary while an error banner is up.
- Quiet amber note when blocked labels exist and nothing is selected; Compose defaults `GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS=1`.
- Outputs invalid-path recovery clears selection and avoids re-seeding from `/workspaces/:id/datasets` path id.
- Ingest: EventSource or authed fetch on `GET /ingest/{url|huggingface}/{job_id}/stream` → progress log. A `type:error` event is job-fatal (stream closes with no summary) — the toast shows its message. The stream is closed / reader cancelled on unmount.
- Upload (`POST /data/inputs/upload`) uses a 1 h `timeoutMs` and surfaces the backend detail via `parseError` (413 → “too large for server/proxy limit”).
- `FileViewer` checks the 3 MB text/JSON preview cap against the `size` prop and `Content-Length` **before** downloading the body; Download failures toast.
- Empty upload copy domain-agnostic (“Upload files or ingest URLs…”).
- Workspace Datasets (`/workspaces/:id/datasets`) reads `GET /projects/{id}/links`: when inputs are pinned (Home → Linked inputs) only those labels are listed, with a **Show all shared inputs** toggle; with none pinned, all shared labels are listed with an explanatory note. Header copy says which.
- `GET /data/outputs/{project}/{version}` is an **object** (`{project, version, files, content_hash, created_at, samples}`); `features/data/datasetRows.ts` `normalizeDatasetRows` turns it (or a bare array / `{items}`) into table rows — `samples` preferred (split/label), sizes joined from `files`, else manifest `files` qualified as `<project>/<version>/<path>`. This fixed the “S.filter is not a function” Datasets → Outputs crash. `/data/outputs` and `/data/inputs` lists go through `unwrapList` with shape guards. Blocked external-symlink copy says “ask an admin”; the env var lives in tooltips/detail only.
- File table and label list use natural sort (`lib/naturalSort.ts` — digit runs numeric so `nohash_2` before `nohash_10`, but hex-like runs of ≥6 `[0-9a-f]` mixing digits and letters compare as plain strings so `03401e93_…` sorts next to `0a7c…`/`0c54…`).

## Overview (Runs panel — was Summary + Lineage)

- Prefer Runs → **Overview** (`openTrace({ runId })` → `…/lineage`).
- Legacy `/library/artifacts?artifactId=` / artifact-id-only deep links resolve via `GET /artifacts/{id}` → Overview or Run outputs.
- Does not write `#/trace`. Library Artifacts UI removed.

## Templates (`TemplatesView`)

- Shell: `WorkbenchPage` (search + All/Examples/Saved/Marketplace pills in `toolbar`; sort + plugin facets below banners). Fill-height body for every tab. Workspace + Marketplace browse use `MasterDetail` (`listLabel="templates"`, collapsible, default master ~300px) — dense `ide-row` list (title + mono slug), detail pane holds description/nodes/plugins/Open in Editor/overflow; no selection → compact `EmptyState`. **All** shows workspace starters in the same split + a “Browse Marketplace” CTA (no stacked second splitter that crushed the detail pane). `SplitPane` clamps master width so a fat shared `graphyn.layout.master` value cannot hide the detail.
- Page title **Templates** (not “New from template”); starters that stamp GraphIR into a workspace.
- Unified pills with honest counts: **All** = workspace + marketplace totals; **Examples** / **Saved** from `/pipelines/templates`; **Marketplace** from `public/marketplace-catalog.json` (~3032).
- Marketplace browse is client-side filter + pagination (48/page); **Open in Editor** still `POST /pipelines/marketplace/materialize`. “N shown” reflects the active tab (not a stale workspace-only count).
- **OOB materialize:** API seeds bundled datasets, rewrites ingest onto `workspace/datasets/input/speech-commands` (etc.), remaps config aliases, strips forbidden keys — reopen Marketplace templates after materializer fixes.
- Header: Refresh quiet; Sync examples + Save from Builder under More overflow.
- Card primary: **Open in Editor** (workspace gate when none open); version select on card; delete in kebab (Escape / outside click close it).
- Gate modal: “Templates stamp into a workspace” → create/select → Editor; new-name input validated inline (`workspaceNameError`).
- **Project stamp** (`lib/projectStamp.ts` `stampProjectOnGraph`, used by Templates / Marketplace / Builder): always sets `metadata.project` (+ `version_tag`). Exporter/versioner nodes (`audio_exporter`, `dataset_versioner`, `export`) get `project` + `output_dir = workspace/datasets/output/<ws>` **only** when `output_dir` is retargetable (`isRetargetableExportDir`: empty, the plugin default `workspace/datasets/output/audio_export`, or already under `workspace/datasets/output/`). Explicit artifact paths (e.g. Example 06 Phase-1 `workspace/artifacts/speech-commands/dataset/speech_commands` + `v1`) are left alone — the exporter ignores `output_dir` once `project` is set, so stamping it broke the Phase-2 `dataset_ingest` hand-off. Other nodes' `workspace/artifacts/…` `output_dir` is isolated to `workspace/artifacts/<ws>/<node_id>` (falls back to node_type) except `<slug>/dataset/…` trees; no node changes when no workspace is active. Backend `graph_prepare` never rewrites node paths for a project (metadata o
nly). A missing Phase-1 dataset now fails ingest ("has not been produced yet") instead of silently using bundled raw clips (`GRAPHYN_INGEST_EXAMPLE_FALLBACK=1` opts back in). Tests: `projectStamp.test.ts`.
- **Runnable here** checkbox (default on, persisted `graphyn.templates.runnableOnly`): hides templates whose backend `runnable` is false (fallback: no missing node types vs catalog; unknown → never hide). “(N hidden — show all)” link; empty state offers **Show all templates**. Default selection = first runnable template in list order. Non-runnable rows show a “Needs plugins” chip when visible. Backend `missing_node_types` wins over the client diff (`templateGroups.ts` `templateMissing`).
- **Guided series** (`templateGroups.ts` `groupTemplates`): templates sharing `group` collapse into one master card (“Speech commands E2E · Guided · 2 steps”) with steps ordered by `phase` and titled by `step_title` (Example 06: Step 1 · Prepare dataset → Step 2 · Train model). Detail shows a step strip; Step 1 points to the next step; later steps check readiness by probing their declared `inputs` (`GET /outputs/file`, then `/data/inputs` labels) → “Step 1 output found” or “Run Step 1 first …” + **Open Step 1**.
- **Needs plugins:** each card compares `node_types` with the store catalog (`Isolated_` stripped on both sides). Missing node types are mapped to plugin names via `missingPlugins.ts` (`GET /plugins` manifests `node_types` + `GET /plugins/search` entries): mapped → “Needs plugins: <plugin>”, unmapped → “Missing node types: <type>”; tooltip lists every node type (with its plugin). The gate modal repeats it. Card titles prefer the API `title`. Opening anyway is allowed. No warning while the catalog is empty.

## Proposals (`ProposalsView`)

- Shell: `WorkbenchPage` (search + status filter chips in `toolbar`); list|detail in scroll body.
- Header **Agent inbox**; Generate proposal form → POST `/proposals` (empty-graph stub + summary).
- List|detail via app `MasterDetail` (shared master width with Runs / Models / Artifacts); master rows use `ide-row` / `is-active`; master/detail empties use compact `EmptyState`.
- Generate appends user prompt to `localStorage` `graphyn.proposal.chat.{id}`; transcript under detail.
- Auto-bind: when `activeProject` set, include in graph metadata/tags and summary `[project:…]`.
- Dismissible discovery banner (MCP/API create; review here); persist `graphyn.proposals.bannerDismissed`.
- Empty pending inbox: Generate CTA + MCP docs note.
- Filter chips + search (actor / summary / id); **actor chips** on list + detail.
- When search filters out `selectedId`, snap to first visible row (or clear).
- Detail: structural diff; side-by-side base/proposed JSON when `base_graph` + graph present.
- Accept → Editor; **Accept then save…** PUTs draft under `activeProject` using summary slug — first free slug (`slug`, `slug-2`, …) via `GET .../pipelines/{slug}` 404, never silently overwriting.
- Accept/Reject bodies never hardcode an actor: configured `graphyn.actor` if set, else omitted (server derives from `X-Actor`/auth).
- Disabled **Partial apply (coming)** checkbox (API not supported).
- Accept toast confirms load into Editor; Accept/Reject remain primary mutations.

## Edge (`EdgeWizardView`)

- Shell: `WorkbenchPage` with `SegmentedTabs` toolbar (**Package** | **Devices**). Devices embeds `DevicesView` without its own shell; standalone `/devices` uses `WorkbenchPage`.
- Wizard step **Package run** (not “Run” — avoids nav collision).
- Step pills: cannot jump to 3/4 without project + source run; step 4 also needs package `runId`.
- **Dropdowns** use shared `FieldSelect` (portal menu, width matches the trigger). A short list opens under the control; when the viewport is tight it grows upward from that same control. Native `<select>` was clipped by the sticky lineage bar.
- **Step 1 is optional:** once workspace + source run are known the edge template loads and the wizard jumps to Configure (once; Back still works). Step 1 is labelled “Source run”; the run picker shows `runDisplayName`.
- **Configure → Model to ship** (`features/edge/runModels.ts`): radio list of the run's models from `GET /runs/{id}/models` (fallback: model-like files in `GET /runs/{id}/outputs` — `.keras/.h5/.tflite/.onnx/saved_model`), each with kind/format/size/metric/created/classes; untrained (`compiled_untrained`) and already-converted (`tflite`/`onnx`) rows are disabled. Default = `?model_path`, else the carried registry stage's `artifact_path` (from Models → Use in Ship `?model=&stage=`, only if it belongs to the run and `exists !== false`), else the best path's trained model (`summary.best_path_id`), else the first trained one. **No path is ever prefilled** (old `workspace/artifacts/models/saved_model` placeholder removed); registry auto-pick only adopts a probe-verified path and uses stage `artifact_path` as-is (never appends `/saved_model`).
- **Labels** prefill from the model's `labels` (labels.txt order) until the user edits; `checkLabelsAgainstModel` flags *order* vs *set* mismatches (“Model class order is down, go, no, stop, up, yes” + **Use model order**). Mismatch / empty labels / no model block **Next** and **Run** (`configBlocker`). Server `labels_mismatch` (422) is explained and, for package create, re-fills labels from `detail.expected`.
- **Advanced** disclosure holds the registered-model picker, **Package as-is (no conversion)** (`POST /projects/{p}/ship/packages` with `model_path`, `run_id`, `labels`; response `warnings` toasted), artifact picker and raw path input.
- Download path: prefer package URI from run artifacts, else `guessPackagePath` under run `artifacts_dir` or `edge-deploy/latest/packages`.
- Failure diagnostics: run id + Open run / lineage / outputs / Editor.
- Download: checksum from package artifacts when present; else honesty copy.
- Step owns actions; header Artifacts only when package artifact exists.
- Lineage (project / run) sticky secondary bar once (not duplicated per step).
- Skip-to-download only if package exists; else “Run package step first.”
- **Empty state (step 1):** no workspace → “Pick a workspace and a training run”; workspace open but no model run → “No runs with a model in <ws> yet — run a training pipeline (e.g. Speech commands E2E) first” with Templates / Runs buttons.
- **Source run:** offered/preselected only from runs known to have a model — registry stage `run_id`s (ModelsView logic) plus an artifact probe (`isModelLikeArtifact`) of the 5 newest successful workspace runs. A selected run without model artifacts shows an amber note. The legacy artifact auto-adopt (first model-like `/artifacts` row) only runs when the run has no model list.
- No blind probes: an empty model path is never fetched, and the guessed package path is only probed when a run produced it or the workspace has ship packages.

## Runs (`RunsView`)

- (See unified observe section above — FieldSelect, SplitPane, FileViewer, single Promote surface.)

## Plugins (`PluginsView`)

- Description: install node packs for the Editor catalog.
- Shell: `WorkbenchPage` with `IdeTabs` toolbar (**Installed** | **Install · Search**); status filters use `catalog-pill` / `catalog-pill-on`; runtime filter uses `SegmentedTabs` (Any / Isolated / Shared).
- Header: **Clean unused venvs** → `POST /plugins/venvs/gc` + Refresh.
- **Deps & runtime** callout is a foldable `<details>`; row badges still use **shared env** / **isolated venv** chip style; heavy Audio/ML packs ship as isolated.
- Installed list: `divide-y` + `ide-row` rows (dependency panel expands inline below the row); empty filter → compact `EmptyState`; row ⋯ menu `rounded-lg`.
- Install tab: `surface-card p-3` + `field-control` inputs.
- Isolated boot installs required + TF/Keras/ONNX allowlist by default (`GRAPHYN_ISOLATED_BOOT_HEAVY=1`); set `=0` to defer. Exotic optionals (TTS, audiocraft, tflite-runtime, …) via **Install optional (venv)**.
- Badge text: `shared env` / `isolated venv`; Install optional labeled accordingly.
- After shared-env pip failure, hint to upgrade plugin for isolated runtime then Install optional (venv).
- Install progress / toasts name the **actual missing packages** (never a hardcoded “PyTorch” / “TensorFlow” stub); footnotes stay runtime-generic.
- Optional install is per-package: one bad wheel (e.g. `tflite-runtime` when TensorFlow is already present) must not block others (`torch`). UI shows concrete pip ERROR lines.
- Tabs Installed (default) | Install / Search; status filter; one dep CTA per row; empty → Install tab.
- Per-plugin one-line install errors (no duplicate toast walls).
- Remote install poll (`GET /plugins/{name}`): job stub has `status: installing|failed`; the finished PluginRecord has **no** `status`, so installed = record with `version`/`installed_at` (upgrade: `installed_at` differs from pre-install baseline). In-flight guard, 10 min cap, 3× 404 → error.

## Workers (`WorkersView`)

- Shell: `WorkbenchPage` with `SegmentedTabs` toolbar (**Workers** | **Queue**); Mode B hint only when distributed. Empty = Mode B + copyable `graphyn worker start`.
- Queue explains no list-all `/jobs` API + Mode A/B copy; recent runs as proxy. Summary strip has no duplicate Refresh (header actions own it).
- Detail drawer: labels/pools display-only (no PATCH); **Deregister** ConfirmButton → `DELETE /workers/{id}`.
- Workers use the same API token as this console. No requirement IDs on the page.

## Credentials (`CredentialsView`)

- Shell: `WorkbenchPage`; create form + filter use `field-control`; list is dense `ide-row` rows in a bordered list.
- **Revoke** = soft revoke (`DELETE /credentials/{id}`); separate danger **Delete permanently** ConfirmButton uses `?delete=true`.
- Named secret values are not a console page. Ops bootstrap stays on CLI `graphyn secrets`.
- List renders fields as a key/value list. Secret fields (kind schema `secret`, else `secret_fields_set` keys, else key-name heuristic) show **set / not set** badges — from the API's `secret_fields_set` when present, otherwise `""` = not set, any other value (the `***` marker) = set. Values are never printed.

## System (`SystemView`)

- Shell: `WorkbenchPage` with `IdeTabs` toolbar (Status · Schedules · Webhooks · Cleanup · Audit).
- Page title **Ops** — health, schedules, webhooks, cleanup, audit.
- Refresh uses **per-endpoint** `Promise.allSettled` — one failing probe does not blank the whole page; Health/Readiness/Schedules/Webhooks show inline errors when their fetch fails.
- Status: operator facts only. Health is liveness; Readiness shows catalog node count, backend, and storage checks. Metrics chips have no second summary line. Maintenance clears unused plugin venvs. No requirement IDs, threat numbers, or doc paths on this page.
- Schedules: interval in minutes; environment is draft (saved pipeline), staging, or prod. New schedules from Ops default to draft. Add disabled until name/workspace/pipeline filled; last error labeled clearly. Add form: all five fields labeled with one height (`h-9`); Pipeline is a select of `GET /projects/{name}/pipelines` once a workspace is picked (disabled “Select a workspace first” / “No saved pipelines”); free text only if the workspaces or pipelines API fails. Server errors rephrased via `workspaceErrorMessage`. **Orphaned** schedules (`orphaned: true`, workspace deleted) show an amber “Orphaned — workspace deleted” badge + `disabled_reason`; env select / Run now / Enable are hidden (Delete only). Next run is shown only for enabled, non-orphaned schedules. A missing prod/staging version says to publish or switch to draft. A corrupt `schedules.json` returns 503 with the repair message.
- Webhooks: saved endpoint is shown redacted. Save keeps that URL unless a new full URL is typed (`keep_url`). Test waits for delivery and surfaces `{ok:false,reason}`. Clear removes the endpoint.
- Cleanup: confirm with typed CLEANUP; never deletes running runs / examples / dataset inputs. Confirm stays busy until the request finishes (client waits up to 10 minutes; a second click does not start another cleanup). Reconcile on Status uses the same wait. Omitted `delete_cache` on the API defaults to false.
- Audit: search box (run id / resource, incl. `metadata.run_id`), actor + type/action filters, count, Export JSON of filtered events. Resource ids are shown **in full** and link to the run (Overview) / model / pipeline (Editor) / proposal; related `metadata.run_id` gets its own run link. Run lifecycle actions read as labels with tones (`run.start/finish/fail/cancel/archive/restore/purge/replay` → “Run finished” …; `features/system/auditEvents.ts`). Actor + `actor_kind` shown. **Load more** re-requests `GET /audit?limit=` in +100 steps up to the API cap 1000 (no offset param in the contract).

## Access (`AccessView`)

- Shell: `WorkbenchPage`; actor form in a surface card; roadmap empty uses compact `EmptyState`.
- Actor field saves `graphyn.actor`; note that roles are pending multi-user API.

<!-- BEGIN Runs/Editor UX (results-first) — owned by the Runs/Builder agent -->
## Runs/Editor UX (results-first)

Supersedes the `#0` / `#c3f15543` label cue notes above for dual-branch graphs.

- **Results banner** (`RunResultsBanner`): **Overview tab only** (not Outputs/Logs). Headline metric when present; Path A/B comparison only when `isMultiTrackShape` (never invent Path chrome on linear). Dataset line is phase-aware (`datasetSentence`: train → “Trained on … clips”; preprocess → “Processed …”; else “Used … items/clips”). Regression badge vs best earlier run when detail API attaches `regression`. Sources: backend `summary` / `regression` / `display_name`; fallback evaluator `metrics.json` (`useEvaluatorOutputs`). Linear Overview story stays **Got + duration spine** (no metric chip on the Got line).
- **Paths, not ids:** fork/parallel only — duplicated steps "Trainer · Path B" (`disambiguateByPath`; `#cue` when still ambiguous). Stack lane headers / timeline sections use path descriptions; fork tracks show description + metric chip (best highlighted). Linear runs: plain numbered stack, no Path headers.
- **Evaluator step story:** headline metrics, per-class precision/recall/F1 table, confusion-matrix heat grid (PNG thumbnail fallback). Timeline rows of metric-producing steps show a metric chip. Overview Metrics list shows scalar metrics only, `formatMetric` (0.561, never 0.5611111).
- **List rows:** `lib/runDisplay` title (`display_name`; generic `pipeline` → "Run <id>"), primary metric for multi-path runs ("Test accuracy 0.561 · 2 paths" from `summary.paths`), red ↓delta when `regression.delta < 0`.
- **Progress:** `runs/runProgress.ts` parses `node_progress`. Runs → Logs has **Readable / Raw** toggle — Readable collapses each node's progress into one live line (bar + sparkline + "N updates"); Raw shows every event JSON. Live runs: journal re-fetched every other 2 s status tick; progress also merged from `status.node_progress` / detail `node_progress`; running steps show a bar in the Pipeline stack and the LiveRunMonitor.
- **Register model** (chrome button unchanged; panel "Save a model from this run"): options from `GET /runs/{id}/models` (parsed via `edge/runModels.normalizeRunModels`), else model files in outputs. Each option: path label, kind (Trained / Optimized for devices / Untrained), file, format, size, path metric. Default = best path's trained model (`defaultModelOption`) — **never** `compiled_untrained` (hidden unless "Also list untrained models" under More options). Name prefilled from `suggested_name` or `<graph>-<architecture>` slug. POST `/models` sends `model_path` + `node_id` (+ `allow_untrained` only for an explicitly chosen untrained model); 422 `compiled_untrained` → plain toast. "Storage folder" (slug) and "Mark all of this run's outputs as Latest / Testing / Production" (`/runs/{id}/promote`) live under More options.
- **Editor link:** the run chrome **Editor** button sets the Editor's linked run (`setLastRunId`) to that run.

### Editor
- **Fit view:** `FIT_VIEW_OPTIONS = { padding 0.12, minZoom 0.55, maxZoom 1 }` on mount and after every `loadGraph` (`loadGen`); canvas `minZoom 0.15` for manual zoom-out.
- **Nodes:** 15px label (graph `label`), 12px subtitle (status word · architecture · category); no `#hex` suffix (id in tooltip). Fork branches (`builder/canvasPaths.ts`) get a coloured **Path A/B** badge + left border; path-aware labels feed the log. Running nodes with `node_progress` show a progress bar + "epoch n/N · val acc …". All view-only (`pathBadge`, `displayLabel`, `progress` on display nodes; never saved, not in `editorSnapshot`).
- **Execution log:** `node_progress` lines collapse (Pretty) into one live row per node with bar + sparkline; Raw keeps all. Node lines are relabelled with the path label (`journalLog.relabelLine`). Opening a graph whose linked run matches the canvas hydrates the log from that run's journal (`journalToLogEntries`; "Log of run xxxx"), refreshing while the run is live; it only replaces an empty log, its own hydrated log, or the log right after a graph load. Empty-state copy says what to do.
- **Pipeline version** label in front of the draft/staging/prod chips; "Publish pipeline version → staging", "Request / Approve prod version" — distinct from model stages on Models.
<!-- END Runs/Editor UX (results-first) -->

<!-- BEGIN Run audit / traceability — owned by the Runs/Builder agent -->
## Run audit / traceability (2026-10-04)

Backend contract: `audit_api_contract.md` (backend agent) / `docs/API_REFERENCE.md`. Pure parsing in `features/runs/runRecord.ts` (+ tests); every field is optional so legacy runs and older API containers degrade, never crash.

- **Run record card** (`runs/RunRecord.tsx` `RunRecordCard`, Overview tab, hidden while a step is focused): actor · trigger, exact start/finish (absolute local; UTC + ISO in tooltip), duration, graph hash (short + copy; executed/materialized hash in tooltip), pipeline version (name · env · version/revision, “edited before run” for `pipeline_source: saved_modified`, “Ad-hoc graph” for `adhoc`), seed, Graphyn/runtime, record hash + chain `#seq`, **Replay of** link. Folds: **Code** (per node type: version, runtime, code hash), **Inputs** (`external_inputs` path + content hash + manifest/file count + dataset version; else legacy `input_artifact_hashes`; `dataset_versions`), **Environment** (python, os/machine, image digest, git, libraries). Missing / placeholder values (node version `builtin`, empty `plugin_version`, null `pipeline_version` without `pipeline_source`, empty `dataset_versions`, null `environment`, no `record_hash`, generic actor `system`/`api`) show amber **not recorded** chips; header shows “N not recorded” / “complete” / “sealed when the run finishes” (`record_status: pending`). **Copy all** (plain text) and **View raw record** (prove.json in Run outputs’ viewer). Source: `GET /runs/{id}` `record` (or `prove`); fallback `runs/<id>/prove.json` (+ `meta.json` when the detail lacks `meta`) via `GET /outputs/file` (`useRunRecord.ts`).
- **Audit API detection:** `record_status`/`record` key on the run detail. Without it (old container) Replay / Verify / Archive are hidden and the only removal is **Delete permanently** (old `DELETE` = hard delete) — never offer “Archive” that would hard-delete.
- **Replay exactly** (header): confirm panel explains same graph snapshot (hash) + seed, not the Editor’s current pipeline; `POST /runs/{id}/replay {check_inputs:true, force:false}`. 409 `inputs_changed` → diff list (path, status, recorded → current hash) + **Replay anyway** (`force:true`). Success opens the new run (Logs). Runs with `replay_of` show “Replay of run …” (full-id link) in the header and the record card.
- **Verify** (header): `GET /runs/{id}/verify` → checklist grouped Graph snapshot / Inputs / Outputs / Record hash / Record chain (worst state wins: failed > changed > not checked > pass); non-passing targets listed with node label, path and “recorded x · now y” / “2 added · 1 modified”. Long timeout (5 min).
- **Archive instead of delete:** header **Archive** (ConfirmButton; toast with Undo → `POST /runs/{id}/restore`), archived runs show an Archived badge + **Restore**. List hides archived by default; the Archive icon toggle in the filter strip requests `GET /runs?include_archived=1` (also filtered client-side). **Delete permanently…** lives only in the `⋯` Advanced menu: typed full run id → `DELETE /runs/{id}?purge=true` + `X-Confirm-Purge: <id>` (428 `confirm_required` explained).
- **Step labels:** backend `node_label` on events / `meta.node_labels` / `record.node_labels` / `node_stats[].node_label` win (description in parentheses dropped: `compactNodeLabel`), else the path-aware stack label. Runs → Logs relabel lines (`journalLog.relabelLine`: “Trainer · started” → “Trainer · Path C · started”), Pipeline stack, step stories, Verify rows and **Advanced — registry IDs** (ids in tooltips). Editor execution log + progress lines prefer `node_label` too.
- **Cache provenance:** cached steps show “from run <display name / short id> (open)” in the Step story and `cached · <short id>` on the timeline chip (full id in tooltip) from `node_stats[].cache_source_run_id` / `record.cache[].source_run_id`; else “source run not recorded”.
- **Failures:** header failure banner and step stories render `ErrorType: message` + collapsible **Traceback** (`FailureDetails`; framework frames — orchestrator/node_executor/asyncio/anyio/starlette — hidden with a count). Sources: `node_error` `error`/`error_type`/`traceback`, meta `error`/`error_type`/`error_traceback`/`failed_node_id` (`extractRunFailure`, `failuresByNode`).
- **Short ids:** links/navigation always use the full id (`linkableRunId` refuses truncated hex); short ids are display only, with the full id in tooltip / copy button (run header now has a copy-full-id button).
- **Editor drift** (`builder/graphDrift.ts`, `RunDriftBanner.tsx`): when the linked run (`lastRunId`, or the snapshot’s run) has the same graph name as the canvas, the canvas is diffed against the run’s recorded `graph.json` (node add/remove/type, config keys, placement, edges, seed; catalog-default fills and run-scoped write paths `…/runs/<id>/…` ignored). Differences → amber “This pipeline changed since run X — N differences” with **Open run’s exact graph** and **Compare** (list of changes). Backend `pipeline_drift.drifted` (not `layout_only`) shows “The saved pipeline changed since run X” when the canvas itself matches. **Open run’s exact graph** loads the run graph with run-scoped output folders removed (`unscopeRunPaths`) as a **read-only snapshot** (sky banner): Save routes to **Save as new…** (suggested `<name>-run-<short>`, same name refused) and never overwrites the pipeline; **Close snapshot** ends the mode. Runs → **Editor** also loads the unscoped graph with `loadGraphIntoBuilder(graph, { fromRunId })` (store `editorRunContext`).
- **Run start:** Editor posts `{graph, trigger: "ui", pipeline?, pipeline_env?}` (wrapper accepted by every API version) so records carry the UI trigger and declared saved pipeline.
- **Metric format (one rule, `lib/metrics.formatMetricValue`):** ratio metrics (accuracy/precision/recall/F1/AUC in 0..1) as “75.6%”, others `formatMetric` (“0.412”); deltas of ratio metrics in points (“−30.6 pts”, `formatMetricDelta`). Used by Home, Runs (list, banner, stories, register form, progress lines), Models, Ship, Compare tables (CSV keeps raw values).
- **Compare:** param rows that differ only by each run’s own `runs/<id>` folder (`output_path`/`output_dir`…; `runCompare.isRunScopedPathParam`) are hidden behind “Show run-specific paths (N)”; param keys read “Trainer · Path C · epochs” (`paramKeyLabel` + `canvasPathView` over each run’s graph), raw key in tooltip.
- **Workspaces cards:** last-run line is `w-full` + truncate inside `min-w-0` grid items (long activity text no longer runs into the neighbour card).
<!-- END Run audit / traceability -->
