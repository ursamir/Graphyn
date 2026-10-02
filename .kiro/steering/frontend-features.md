# Frontend features (graphyn-ui)

Persona UX notes for feature screens. Shell/nav labels: `frontend-canvas.md`. Canonical IA: `docs/IA_PROJECT_FIRST.md`.

**Nav labels:** Workspace strip: Home · Editor · Runs · Models · Ship · Datasets. Library and admin: Templates · Agent inbox · Artifacts · Plugins · Workers · Credentials · Ops · Access.

**Client / polling contracts (2026-09-30):**
- `apiFetch` forwards the caller's `AbortSignal` for the whole response lifetime (headers **and** body streaming); `timeoutMs` covers the headers phase only; a caller-aborted request is never retried. `parseError` / `configuredActor` are exported from `api/client.ts`.
- Background polls use `lib/usePolling.ts` (pure loop `startPolling`; in-flight skip; the **immediate first call always runs, even in a hidden tab** — only interval ticks pause while `document.hidden`, catch-up on visible): Runs status (2 s) + Live tab (3 s), Workers (15 s), NotificationBell (45 s), App pending-proposals badge (60 s). Poll failures toast once per outage. Endpoints read by more than one component go through `lib/sharedFetch.ts` so a poll cycle issues one GET (notifications, `proposals?status=pending`).
- **Terminology:** UI says **workspace** for the project concept (API fields stay `project`). Server “Invalid project name …” / “Project 'x' not found|already exists” are rephrased by `lib/workspaceName.ts` `workspaceErrorMessage()`; client validation `workspaceNameError()` mirrors the server rule (letters, digits, `-`, `_`; 1–128).
- `graphyn-ui/nginx.conf` `/api/`: `proxy_buffering off` (NDJSON/SSE), `proxy_read_timeout 3600s`; server `client_max_body_size 2g`.

**Workspace validity (`lib/workspaceValidity.ts`):** every workspace id from the URL or resumed from localStorage is checked with `GET /projects/{id}` (200/404) before it is persisted. The store only writes `graphyn.activeProject` for validated ids (`commitActiveProject`); `noteRecentWorkspace` ignores known-missing ids. A missing URL id (any `/workspaces/<id>/…` route) renders `components/WorkspaceNotFoundView` (links: most recent valid workspace + All workspaces), title "Graphyn · Workspace not found"; the store falls back to the most recent valid recent (`pickFallbackWorkspace`), not "No workspace open". Recents not in `GET /projects` are pruned on boot (`pruneRecentWorkspaces`). While an id is being checked the main pane shows "Opening workspace…".

**Navigation guard (`lib/navigationGuard.ts`):** `registerNavigationGuard(fn: () => boolean | string): () => void` (false/'' = clean; true/message = unsaved). `confirmNavigation()` (window.confirm "You have unsaved changes in the Editor — leave anyway?") is consulted by sidebar/jump keys (`App.go`), header Switch / Back-to chip / Last-run menu, every command-palette item, and `routes/nav.ts` `goView` / `guardedNavigatePath` (both return false when cancelled). The Editor registers its dirty guard.

**Titles:** `Graphyn · <View>[ · <workspace>]` — workspace suffix only on workspace-scoped URLs; picker = "Workspaces"; unknown URL = "Graphyn · Not found"; `/login` = "Graphyn · Sign in".

**Path routes:** `src/routes/paths.ts`, `viewMap.ts`, `nav.ts` (`goView` / `guardedNavigatePath` / `replacePathSearch` / `onPathChange`). Views must not write `#/...`. `stripLegacyAppHash()` in `parsePath.ts` drops a leftover `#/…` fragment. `/admin/secrets` canonicalizes to `/admin/credentials`.

## Models (`ModelsView`)

- `ViewShell` + `MasterDetail` (shared `graphyn.layout.master`); list registered models; request/approve prod; register from name + run_id + slug (primary CTA).
- Detail: **Open run Trace/Lineage** via `openTrace({ runId })`; **Dataset pins** / Home when workspace known.
- Deep-link via path helpers when workspace is open.
- Load error that empties the list clears `selected` / detail (no stale detail pane).

## Projects (`ProjectsView`)

- Picker: filter + dense rows; create in explorer header. **Create workspace** validates inline (`workspaceNameError`): message under the input, red border, Create disabled until valid; server errors rephrased via `workspaceErrorMessage`. Row ⋯ menu is Open, View runs, Clone, then Delete. The list does not use `overflow-hidden`, so that menu (including Delete on the last row) paints outside the card. Open a workspace for the same Delete under Workspace settings.
- **Home / Overview:** first-run 2-card strip when empty (Templates · Datasets); header keeps primary **Open Editor**.
- Situation strip; **Pinned inputs** (manual — runs do not auto-link); Versions & taxonomy collapsed.
- Pipeline **pin favorites** via `localStorage` `graphyn.pinnedPipelines.{project}` (star; pinned sort first).
- Pipeline **Rollback** near promote (POST `.../pipelines/{name}/rollback` with required `version`).
- **Always-on** strip: schedules fetched with `?project=` and filtered client-side by `schedule.project === workspace`; “Last error: …” shown; else “No schedules for this workspace” + CTA to Ops.
- **Activity** run rows show relative time (`created_at`, full timestamp on hover) + status badge. Schedule rows: only this workspace's schedules; show `last_error`; click verifies the schedule's `last_run_id` exists (`checkRunExists`) — missing → toast + Ops (Schedules) instead of a dead run link. Recent-run rows open with `{ project: selected }`.
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
- **model_builder architectures:** presets `ds_cnn` / `mobilenet` / `simple_cnn` (paper-style blocks; tunable filters/depth/MobileNet knobs). `architecture=custom` uses a structured **Layers** list editor (add / reorder / typed fields; optional Edit as JSON). Inspector **Load layers from preset** seeds `layers` from a paper body (using current knobs) and sets `architecture=custom`.
- **Inspector collapse:** right inspector panel collapses like the catalog (`graphyn.builder.inspectorOpen`); selecting a node/edge re-expands it.
- **Run-start errors** (503 registry not ready, 4xx validation, …) show an inline run-start error banner with the server detail instead of a generic toast.
- **Unsaved changes** (`graphHistory.ts`): `editorSnapshot` captures only the document (node type/label/config/placement/position, edges, name, seed — never run status/selection), compared by `snapshotSignature` to the last loaded/saved **baseline**. Dirty → amber dot + **Unsaved** chip; `beforeunload` prompt; an app navigation guard (`registerNavigationGuard` from `lib/navigationGuard.ts`) so sidebar / palette / workspace switch / `goView` confirm before leaving; `confirmDiscard` before an in-Editor action replaces the canvas (open pipeline/env, import, external load). Loading a graph resets the baseline and history.
- **Undo / redo:** bounded history (`HISTORY_LIMIT = 50`); rapid edits of the same field coalesce into one step (`changeKey`); Ctrl/Cmd+Z undo, Shift+Ctrl/Cmd+Z or Ctrl+Y redo (`historyShortcut`, ignored while typing in a field — browser text undo wins) plus toolbar buttons.
- **Config validation** (`configValidation.ts`): JSON-schema `minimum`/`maximum`, `exclusiveMinimum`/`exclusiveMaximum` (draft-4 boolean and draft-6 numeric), `multipleOf`, `integer`, `enum`, `minLength`/`maxLength`, `pattern`. Invalid fields get a red border + `aria-invalid`; nodes show an invalid-count badge; a banner lists issues and **Run / Save are blocked** while any exist. Conditional fields: `ui.visible_if = { field = value | [values] }` and `ui.depends_on = "field"` (truthy) or `{ field = value }` hide fields (hidden fields are not validated).
- **Log dedupe** (`logDedupe.ts`): a node `node_error` followed by the pipeline-level `error` with the same core message counts/renders once (Editor log panel + Runs → Logs pretty view; raw view unchanged).
- **Skipped nodes** (`builderRunState.ts`): on a failed/cancelled run, nodes that never started show **skipped (not run)** rather than idle/failed; a started-but-unfinished node is failed (or cancelled).

## Runs (`RunsView`) — unified observe

- Page title **Runs**; hub for History, Live, **Run outputs**, Lineage, Compare (not separate Lineage tab).
- Opening a run does **not** call `setActiveProject`. The address bar is the workspace; a run whose metadata names another workspace stays a detail selection.
- Run selection ↔ URL sync uses `window.history` directly (not `navigatePath`), so the App path sync does not call `store.openRun` and overwrite the header **Last run**. A missing run id renders one not-found state.
- **Run outputs** ordered by execution order, files natural-sorted; “+N more” pages via `?with_meta=1` and `?node_id=&limit=`. The API fills its 400 cap run-level files first, then models/metrics/small summaries, then bulk files, round-robin per node; source-node (ingest) input files are not outputs (`inputs_by_node` counts them). **Promote model** only for runs with a model output.
- **Run outputs grouping:** `guessNodeFromPath` (in `runOutputs.ts`) must never promote a run id / opaque hex to a pipeline step. Journal paths `runs/<run_id>/…` (including `outputs_index.json`) group as **Run-level**. `outputs_index.json` is hidden from the listing (API + UI). File-card subtitles use `shortOutputPath` (drop `workspace/` and `runs/<id>/`). Truncation chips name the step and sit under that step’s file list; a panel banner explains caps when any step is truncated. `PipelineStack` also filters opaque ids at render time.
- **File viewers:** pluggable via `components/viewers/registry.ts` (`registerFileViewer`). Built-ins: image, audio, video, json, text, npy, pickle, model, binary; popup expand on `FileViewer`. MIME fix for audio/video blobs in `api/client.ts` `blobUrlWithMime`. Session notes: `docs/WORKLOG_OUTPUTS_AND_VIEWERS.md`.
- Runs **Manage** is a native `<details>`; Escape / outside click / one-open come from App's `installGlobalDetailsMenuDismiss()`.
- Top tabs: **History | Live | Compare** — shared `ViewShell` / `RunsChrome`; list|detail via app `MasterDetail` (`graphyn.layout.master`, synced with Compare / Models / Artifacts).
- History: status + free-text filters; optional metric name + min (client-side on loaded runs); status/promote alias use `FieldSelect`.
- History/Live run cards use stacked flex (title+badge / meta row) — not viewport `sm:` grids — so narrow master panes (~320px) do not crush names over badges.
- Live: same shell; left live run cards, right progress / node wave / workers + “Open full run”.
- Compare: left checkbox run cards, right params/metrics/charts (not stacked table-over-compare).
- Compare chrome includes the same **Refresh** as History/Live (via `ExperimentsViewHandle`).
- Compare master cards use the same stacked layout as History (name+badge / metric+relative time+short id) with a checkbox.
- App nav collapse persists (`graphyn.layout.navOpen`).
- **Pipeline stack** (numbered circular steps + **All** on top) replaces the Focus dropdown — fixed `min-w` so labels stay readable; status is a dot.
- Tabs sit under the run header; right pane shows content for **tab × stack** selection.
- **Run outputs:** API stamps optional `node_id` on each file (ArtifactStore data dir, path refs inside `data.json`, basename hints). UI groups by that id; node focus hides journal-only run files; All shows nodes then dashed **Run-level**; node files split into Outputs / Inputs when detectable. Audio-sample dumps are summarized (manifest + a few clips) so the listing cap stays usable. Focus filters groups by instance id only (`focusMatchesNode` is exact when focus is `trainer_0` / `trainer_b66a5330` — never soft-match via `humanNodeLabel`, or the hex-suffix Trainer/Evaluator re-merges its sibling).
- Focus filters Logs by extracting node hints from structured events **and** formatted lines (`Trainer · started`); bare type labels still match instances, but instance focus does not reverse soft-match a bare label. Empty Focus filter says “No logs for …” not “No logs recorded”.
- **Compact sticky detail chrome** (`z-10` inside detail scroll): status · graph name · time · short id · (live only) progress/node · **Editor** (open graph) · **Manage** (pause/resume/cancel/delete — not Admin Ops) · **Promote model** (succeeded only); then tabs. No Focus chip strip / dropdown, no full-width Promote bar.
- **Promote model** = `POST /runs/{id}/promote` with alias `latest|staging|prod` (registry stage pointer — not an LLM prompt). Panel also registers a named model when slug returned.
- Terminal runs hide progress / “Current node”; Focus is not auto-seeded from last node (avoids empty Outputs).
- Tab **Summary**: compact count strip + timing (+ errors when present). No duplicate tab CTAs, no raw JSON dump.
- Detail: **Logs** | **Run outputs** | **Lineage** | **Summary** | **Checkpoints**. Nested outputs splitter: `graphyn.layout.nested`.
- `open(id)` / status poll / `refetchRunDetail` / `loadRunModels` drop results when the selection changed (`selectedRef` + `openSeqRef`). When the polled status turns terminal, detail (logs / outputs / artifacts) is refetched.
- Lineage: detail-only (stack is parent); no duplicate node list / Raw JSON / Graph cards / Editor CTA.
- Failed/cancelled: compact inline banner. Succeeded: **Promote model** → single panel (alias + register).
- **Node list** (`runNodes.ts` `pipelineNodesFromRun`): built from the run's graph in execution order (topological; ties by graph order / `node_stats` index), so nodes that never ran still appear, correctly numbered; status from journal events then `node_stats`; no status on a failed/cancelled run → **skipped**.
- **Ask agent to fix:** confirm panel first; creates a pending proposal (the run's unchanged graph + the real failing node / error from `extractRunFailure`, which reads `error` / `error_message` rather than `message`) in the Agent inbox; stays on the page, toast offers **Open proposal**.

## Experiments (`ExperimentsView`)

- Standalone title **Compare runs**; prefer Runs → Compare when a workspace is open.
- **Params from node configs:** after `GET /experiments/compare`, each run's graph is loaded (`fetchRunGraph(runId, null)`) and merged via `compareEnrich.ts` `enrichCompareParams` → `runCompare.ts` `mergeRunParams` (`node_id.field` + `graph.<key>`; experiment params win). `param_keys` is rebuilt from `compareParamRows` (natural key order); differing cells highlighted; CSV export includes node config params. **Export CSV** is disabled when there are no param or metric rows.
- **Embedded** under Runs → Compare: `MasterDetail` (shared master width) — checkbox cards left, compare results right.
- Selection written to `/workspaces/:W/runs/compare?ids=` (path search).
- Compare: metric table + **MetricBars** charts for numeric metric keys; **Export CSV**.
- ErrorBanner **onRetry** → `runCompare()` when 2+ runs selected; else `refresh()`.

## Data (`DataView`)

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
- File table and label list use natural sort (`lib/naturalSort.ts` — digit runs numeric so `nohash_2` before `nohash_10`, but hex-like runs of ≥6 `[0-9a-f]` mixing digits and letters compare as plain strings so `03401e93_…` sorts next to `0a7c…`/`0c54…`).

## Trace (`TraceView`)

- Title **Lineage**; artifact-id / advanced paste deep-link via search params; prefer Runs → Lineage for a selected run. Does not write `#/trace`.
- Empty CTA → Open Runs when possible.

## Artifacts (`ArtifactsView`)

- `ViewShell` + `MasterDetail` (shared master width). Cross-run file registry only; Runs → **Run outputs** for one run; Runs → Lineage for provenance.
- `open()` clears `detail` before fetch so a failed open cannot show the previous artifact.
- `open(id)` clears detail before fetch; on failure keeps selected but never shows prior artifact detail.
- Detail: **Register model** when artifact has `run_id` (POST `/models` staging).

## Templates (`TemplatesView`)

- Page title **Templates** (not “New from template”); starters that stamp GraphIR into a workspace.
- Unified pills with honest counts: **All** = workspace + marketplace totals; **Examples** / **Saved** from `/pipelines/templates`; **Marketplace** from `public/marketplace-catalog.json` (~3032).
- Marketplace browse is client-side filter + pagination (48/page); **Open in Editor** still `POST /pipelines/marketplace/materialize`. “N shown” reflects the active tab (not a stale workspace-only count).
- **OOB materialize:** API seeds bundled datasets, rewrites ingest onto `workspace/datasets/input/speech-commands` (etc.), remaps config aliases, strips forbidden keys — reopen Marketplace templates after materializer fixes.
- Header: Refresh quiet; Sync examples + Save from Builder under More overflow.
- Card primary: **Open in Editor** (workspace gate when none open); version select on card; delete in kebab (Escape / outside click close it).
- Gate modal: “Templates stamp into a workspace” → create/select → Editor; new-name input validated inline (`workspaceNameError`).
- **Project stamp** (`lib/projectStamp.ts` `stampProjectOnGraph`, used by Templates / Marketplace / Builder): always sets `metadata.project` (+ `version_tag`). Exporter/versioner nodes (`audio_exporter`, `dataset_versioner`, `export`) get `project` + `output_dir = workspace/datasets/output/<ws>` **only** when `output_dir` is retargetable (`isRetargetableExportDir`: empty, the plugin default `workspace/datasets/output/audio_export`, or already under `workspace/datasets/output/`). Explicit artifact paths (e.g. Example 06 Phase-1 `workspace/artifacts/speech-commands/dataset/speech_commands` + `v1`) are left alone — the exporter ignores `output_dir` once `project` is set, so stamping it broke the Phase-2 `dataset_ingest` hand-off. Other nodes' `workspace/artifacts/…` `output_dir` is isolated to `workspace/artifacts/<ws>/<node_id>` (falls back to node_type) except `<slug>/dataset/…` trees; no node changes when no workspace is active. Backend `graph_prepare` never rewrites node paths for a project (metadata o
nly). A missing Phase-1 dataset now fails ingest ("has not been produced yet") instead of silently using bundled raw clips (`GRAPHYN_INGEST_EXAMPLE_FALLBACK=1` opts back in). Tests: `projectStamp.test.ts`.
- **Needs plugins:** each card compares `node_types` with the store catalog (`Isolated_` stripped on both sides). Missing node types are mapped to plugin names via `missingPlugins.ts` (`GET /plugins` manifests `node_types` + `GET /plugins/search` entries): mapped → “Needs plugins: <plugin>”, unmapped → “Missing node types: <type>”; tooltip lists every node type (with its plugin). The gate modal repeats it. Card titles prefer the API `title`. Opening anyway is allowed. No warning while the catalog is empty.

## Proposals (`ProposalsView`)

- Header **Agent inbox**; Generate proposal form → POST `/proposals` (empty-graph stub + summary).
- List|detail via app `MasterDetail` (shared master width with Runs / Models / Artifacts).
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

- Page title **Ship**; tabs **Package | Devices** (Devices embeds `DevicesView`).
- Wizard step **Package run** (not “Run” — avoids nav collision).
- Step pills: cannot jump to 3/4 without project + source run; step 4 also needs package `runId`.
- **Dropdowns** use shared `FieldSelect` (portal menu, width matches the trigger). A short list opens under the control; when the viewport is tight it grows upward from that same control. Native `<select>` was clipped by the sticky lineage bar.
- Configure: registry / artifact pickers **probe-resolve** real model paths via `resolveModelPathCandidates` + `GET /outputs/file` (canonical `…/runs/<id>/saved_model` then `.keras`, then alias). Prefer model-like artifacts; never invent `${project}/saved_model`.
- Download path: prefer package URI from run artifacts, else `guessPackagePath` under run `artifacts_dir` or `edge-deploy/latest/packages`.
- Failure diagnostics: run id + Open run / lineage / outputs / Editor.
- Download: checksum from package artifacts when present; else honesty copy.
- Step owns actions; header Artifacts only when package artifact exists.
- Lineage (project / run) sticky secondary bar once (not duplicated per step).
- Skip-to-download only if package exists; else “Run package step first.”
- **Empty state (step 1):** no workspace → “Workspace + source run required”; workspace open but no model run → “No runs with a model in <ws> yet — run a training pipeline (e.g. Speech commands E2E) first” with Templates / Runs buttons.
- **Source run:** offered/preselected only from runs known to have a model — registry stage `run_id`s (ModelsView logic) plus an artifact probe (`isModelLikeArtifact`) of the 5 newest successful workspace runs. A selected run without model artifacts shows an amber note. The model path auto-adopts the source run's first model artifact.
- No blind probes: the placeholder `workspace/artifacts/models/saved_model` is never fetched, and the guessed package path is only probed when a run produced it or the workspace has ship packages.

## Runs (`RunsView`)

- (See unified observe section above — FieldSelect, SplitPane, FileViewer, single Promote surface.)

## Plugins (`PluginsView`)

- Description: install node packs for the Editor catalog.
- Header: **Clean unused venvs** → `POST /plugins/venvs/gc` + Refresh.
- Banner: **shared env** (`runtime=inprocess`) vs **isolated venv** (`runtime=isolated`) — same wording/chip style as the row badges; heavy Audio/ML packs ship as isolated.
- Isolated boot installs required + TF/Keras/ONNX allowlist by default (`GRAPHYN_ISOLATED_BOOT_HEAVY=1`); set `=0` to defer. Exotic optionals (TTS, audiocraft, tflite-runtime, …) via **Install optional (venv)**.
- Badge text: `shared env` / `isolated venv`; Install optional labeled accordingly.
- After shared-env pip failure, hint to upgrade plugin for isolated runtime then Install optional (venv).
- Install progress / toasts name the **actual missing packages** (never a hardcoded “PyTorch” / “TensorFlow” stub); footnotes stay runtime-generic.
- Optional install is per-package: one bad wheel (e.g. `tflite-runtime` when TensorFlow is already present) must not block others (`torch`). UI shows concrete pip ERROR lines.
- Tabs Installed (default) | Install / Search; status filter; one dep CTA per row; empty → Install tab.
- Per-plugin one-line install errors (no duplicate toast walls).
- Remote install poll (`GET /plugins/{name}`): job stub has `status: installing|failed`; the finished PluginRecord has **no** `status`, so installed = record with `version`/`installed_at` (upgrade: `installed_at` differs from pre-install baseline). In-flight guard, 10 min cap, 3× 404 → error.

## Workers (`WorkersView`)

- Page title **Worker fleet**; PageHeader Mode B hint only when distributed. Empty = Mode B + copyable `graphyn worker start`.
- Tabs: **Workers | Queue**. Queue explains no list-all `/jobs` API + Mode A/B copy; recent runs as proxy.
- Detail drawer: labels/pools display-only (no PATCH); **Deregister** ConfirmButton → `DELETE /workers/{id}`.
- Workers use the same API token as this console. No requirement IDs on the page.

## Credentials (`CredentialsView`)

- **Revoke** = soft revoke (`DELETE /credentials/{id}`); separate danger **Delete permanently** ConfirmButton uses `?delete=true`.
- Named secret values are not a console page. Ops bootstrap stays on CLI `graphyn secrets`.
- List renders fields as a key/value list. Secret fields (kind schema `secret`, else `secret_fields_set` keys, else key-name heuristic) show **set / not set** badges — from the API's `secret_fields_set` when present, otherwise `""` = not set, any other value (the `***` marker) = set. Values are never printed.

## System (`SystemView`)

- Page title **Ops** — health, schedules, webhooks, cleanup, audit.
- Refresh uses **per-endpoint** `Promise.allSettled` — one failing probe does not blank the whole page; Health/Readiness/Schedules/Webhooks show inline errors when their fetch fails.
- Status: operator facts only. Health is liveness; Readiness shows catalog node count, backend, and storage checks. Metrics chips have no second summary line. Maintenance clears unused plugin venvs. No requirement IDs, threat numbers, or doc paths on this page.
- Schedules: interval in minutes; environment is draft (saved pipeline), staging, or prod. New schedules from Ops default to draft. Add disabled until name/workspace/pipeline filled; last error labeled clearly. Add form: all five fields labeled with one height (`h-9`); Pipeline is a select of `GET /projects/{name}/pipelines` once a workspace is picked (disabled “Select a workspace first” / “No saved pipelines”); free text only if the workspaces or pipelines API fails. Server errors rephrased via `workspaceErrorMessage`. **Orphaned** schedules (`orphaned: true`, workspace deleted) show an amber “Orphaned — workspace deleted” badge + `disabled_reason`; env select / Run now / Enable are hidden (Delete only). Next run is shown only for enabled, non-orphaned schedules. A missing prod/staging version says to publish or switch to draft. A corrupt `schedules.json` returns 503 with the repair message.
- Webhooks: saved endpoint is shown redacted. Save keeps that URL unless a new full URL is typed (`keep_url`). Test waits for delivery and surfaces `{ok:false,reason}`. Clear removes the endpoint.
- Cleanup: confirm with typed CLEANUP; never deletes running runs / examples / dataset inputs. Confirm stays busy until the request finishes (client waits up to 10 minutes; a second click does not start another cleanup). Reconcile on Status uses the same wait. Omitted `delete_cache` on the API defaults to false.
- Audit: actor/resource filters, count, Export JSON of filtered events.

## Access (`AccessView`)

- Actor field saves `graphyn.actor`; note that roles are pending multi-user API.

## Artifacts (`ArtifactsView`)

- Detail: show `consumers`/`downstream` when present; else “Downstream consumers — needs provenance API”.
- Opening an artifact clears prior detail before fetch (no stale cross-id detail).
