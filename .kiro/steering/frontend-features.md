# Frontend features (graphyn-ui)

Persona UX notes for feature screens. Shell/nav labels: `frontend-canvas.md`. Canonical IA: `docs/IA_PROJECT_FIRST.md`.

**Nav labels:** Workspace strip: Home · Editor · Runs · Models · Ship · Datasets. Library and admin: Templates · Agent inbox · Artifacts · Plugins · Workers · Credentials · Ops · Access.

**Client / polling contracts (2026-09-30):**
- `apiFetch` forwards the caller's `AbortSignal` for the whole response lifetime (headers **and** body streaming); `timeoutMs` covers the headers phase only; a caller-aborted request is never retried. `parseError` / `configuredActor` are exported from `api/client.ts`.
- Background polls use `lib/usePolling.ts` (in-flight skip + pause while `document.hidden`, catch-up on visible): Runs status (2 s) + Live tab (3 s), Workers (15 s), NotificationBell (45 s), App pending-proposals badge (60 s). Poll failures toast once per outage.
- `graphyn-ui/nginx.conf` `/api/`: `proxy_buffering off` (NDJSON/SSE), `proxy_read_timeout 3600s`; server `client_max_body_size 2g`.

**Path routes:** `src/routes/paths.ts`, `viewMap.ts`, `nav.ts` (`goView` / `replacePathSearch` / `onPathChange`). Views must not write `#/...`. `stripLegacyAppHash()` in `parsePath.ts` drops a leftover `#/…` fragment. `/admin/secrets` canonicalizes to `/admin/credentials`.

## Models (`ModelsView`)

- `ViewShell` + `MasterDetail` (shared `graphyn.layout.master`); list registered models; request/approve prod; register from name + run_id + slug (primary CTA).
- Detail: **Open run Trace/Lineage** via `openTrace({ runId })`; **Dataset pins** / Home when workspace known.
- Deep-link via path helpers when workspace is open.
- Load error that empties the list clears `selected` / detail (no stale detail pane).

## Projects (`ProjectsView`)

- Picker: filter + dense rows; create in explorer header. Row ⋯ menu is Open, View runs, Clone, then Delete. The list does not use `overflow-hidden`, so that menu (including Delete on the last row) paints outside the card. Open a workspace for the same Delete under Workspace settings.
- **Home / Overview:** first-run 2-card strip when empty (Templates · Datasets); header keeps primary **Open Editor**.
- Situation strip; **Pinned inputs** (manual — runs do not auto-link); Versions & taxonomy collapsed.
- Pipeline **pin favorites** via `localStorage` `graphyn.pinnedPipelines.{project}` (star; pinned sort first).
- Pipeline **Rollback** near promote (POST `.../pipelines/{name}/rollback` with required `version`).
- **Always-on** strip: schedules filtered by `project`; `last_error` shown; else count + CTA to Ops.
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

## Runs (`RunsView`) — unified observe

- Page title **Runs**; hub for History, Live, **Run outputs**, Lineage, Compare (not separate Lineage tab).
- Opening a run does **not** call `setActiveProject`. The address bar is the workspace; a run whose metadata names another workspace stays a detail selection.
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
- **Run outputs:** API stamps optional `node_id` on each file (ArtifactStore data dir, path refs inside `data.json`, basename hints). UI groups by that id; node focus hides journal-only run files; All shows nodes then dashed **Run-level**; node files split into Outputs / Inputs when detectable. Audio-sample dumps are summarized (manifest + a few clips) so the listing cap stays usable.
- Focus filters Logs by extracting node hints from structured events **and** formatted lines (`Trainer · started`); empty Focus filter says “No logs for …” not “No logs recorded”.
- **Compact sticky detail chrome** (`z-10` inside detail scroll): status · graph name · time · short id · (live only) progress/node · **Editor** (open graph) · **Manage** (pause/resume/cancel/delete — not Admin Ops) · **Promote model** (succeeded only); then tabs. No Focus chip strip / dropdown, no full-width Promote bar.
- **Promote model** = `POST /runs/{id}/promote` with alias `latest|staging|prod` (registry stage pointer — not an LLM prompt). Panel also registers a named model when slug returned.
- Terminal runs hide progress / “Current node”; Focus is not auto-seeded from last node (avoids empty Outputs).
- Tab **Summary**: compact count strip + timing (+ errors when present). No duplicate tab CTAs, no raw JSON dump.
- Detail: **Logs** | **Run outputs** | **Lineage** | **Summary** | **Checkpoints**. Nested outputs splitter: `graphyn.layout.nested`.
- `open(id)` / status poll / `refetchRunDetail` / `loadRunModels` drop results when the selection changed (`selectedRef` + `openSeqRef`). When the polled status turns terminal, detail (logs / outputs / artifacts) is refetched.
- Lineage: detail-only (stack is parent); no duplicate node list / Raw JSON / Graph cards / Editor CTA.
- Failed/cancelled: compact inline banner. Succeeded: **Promote model** → single panel (alias + register).

## Experiments (`ExperimentsView`)

- Standalone title **Compare runs**; prefer Runs → Compare when a workspace is open.
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
- Card primary: **Open** (project gate); version select on card; delete in kebab.
- Gate modal: “Templates stamp into a project” → create/select → Editor.

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

## Runs (`RunsView`)

- (See unified observe section above — FieldSelect, SplitPane, FileViewer, single Promote surface.)

## Plugins (`PluginsView`)

- Description: install node packs for the Editor catalog.
- Header: **Clean unused venvs** → `POST /plugins/venvs/gc` + Refresh.
- Banner: **shared env** (`inprocess`) vs **isolated venv** (`runtime=isolated`); heavy Audio/ML packs ship as isolated.
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

## System (`SystemView`)

- Page title **Ops** — health, schedules, webhooks, cleanup, audit.
- Refresh uses **per-endpoint** `Promise.allSettled` — one failing probe does not blank the whole page; Health/Readiness/Schedules/Webhooks show inline errors when their fetch fails.
- Status: operator facts only. Health is liveness; Readiness shows catalog node count, backend, and storage checks. Metrics chips have no second summary line. Maintenance clears unused plugin venvs. No requirement IDs, threat numbers, or doc paths on this page.
- Schedules: interval in minutes; environment is draft (saved pipeline), staging, or prod. New schedules from Ops default to draft. Add disabled until name/project/pipeline filled; last error labeled clearly. A missing prod/staging version says to publish or switch to draft. A corrupt `schedules.json` returns 503 with the repair message.
- Webhooks: saved endpoint is shown redacted. Save keeps that URL unless a new full URL is typed (`keep_url`). Test waits for delivery and surfaces `{ok:false,reason}`. Clear removes the endpoint.
- Cleanup: confirm with typed CLEANUP; never deletes running runs / examples / dataset inputs. Confirm stays busy until the request finishes (client waits up to 10 minutes; a second click does not start another cleanup). Reconcile on Status uses the same wait. Omitted `delete_cache` on the API defaults to false.
- Audit: actor/resource filters, count, Export JSON of filtered events.

## Access (`AccessView`)

- Actor field saves `graphyn.actor`; note that roles are pending multi-user API.

## Artifacts (`ArtifactsView`)

- Detail: show `consumers`/`downstream` when present; else “Downstream consumers — needs provenance API”.
- Opening an artifact clears prior detail before fetch (no stale cross-id detail).
