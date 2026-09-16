# Graphyn Console — Page-by-Page Feature Audit

**Snapshot:** commit `dc1d42f` + uncommitted work on top (working tree at review time; see [Caveat](#caveat-in-flight-changes) below) · **Date:** 2026-09-16
**Scope:** all 18 console pages (`graphyn-ui/src/features/**`), each feature traced to its backend endpoint and checked for a request/response match.

**How to use this document.** Each page is a self-contained unit: purpose, exhaustive feature list, a table mapping every feature to its backend route, then UI feedback and backend feedback — only real, reproduced defects, cited by `file:line`. Pick any page and fix it without re-reading the rest of this doc. A "Cross-cutting" section near the end covers issues that recur across pages instead of repeating them per-page. Every claim below was verified by opening the actual file; several were independently re-verified by a second pass (marked where relevant).

**Method:** one agent read all 22 UI files + their mapped backend routers in full, self-verified every claim before finalizing (dropping ~7 candidates that didn't reproduce), then a second, independent pass spot-checked the four highest-impact claims directly against source — all four held.

---

## Caveat: in-flight changes

At the moment this audit was compiled, the working tree had **uncommitted changes on top of `dc1d42f`** touching most of the files below (`BuilderView.tsx`, `RunsView.tsx`, `ArtifactsView.tsx`, `ModelsView.tsx`, `TraceView.tsx`, `EdgeWizardView.tsx`, and others), plus new not-yet-integrated files (`components/FieldSelect.tsx`, `components/FileViewer.tsx`, `components/SplitPane.tsx`, `features/runs/PipelineStack.tsx`, a new `layout/` directory). This looks like an active refactor in progress, separate from this audit.

Two of this report's highest-severity findings were re-verified directly against that exact in-flight state and confirmed still open (§12 Artifacts, §5 Trace — `appStore.ts` and `routes/parsePath.ts` are unmodified; `ArtifactsView.tsx`'s `findCopyablePath` is untouched). Treat the rest of the report as accurate as of `dc1d42f`, but **re-check any specific finding against current `HEAD` before acting on it** if significant time has passed or a commit has landed since.

---

## 1. Login (`/login`)
**File:** `graphyn-ui/src/features/auth/LoginView.tsx` · **Size:** 44 lines
**Purpose:** Paste a Bearer token into `localStorage` and continue to `returnTo`.

**Features:**
- Token input (password field) — `LoginView.tsx:22-29`
- Continue button — writes token via `setApiToken`, navigates to `returnTo` — `LoginView.tsx:31-40`

**Backend mapping:**
| Feature | Method + path | Handler | Match? |
|---|---|---|---|
| Continue | *(none — client-side only)* | — | N/A — no verification call is made |

**UI feedback:**
- [P3] No token verification on submit — `LoginView.tsx:34-37` calls `setApiToken(token)` and navigates unconditionally; an invalid token still "succeeds" here, and failure only surfaces later as a 401 elsewhere.
- [P3] Enter key does not submit — the token `<input>` isn't wrapped in a `<form>` and has no `onKeyDown`; only the mouse-click "Continue" works.
- [P3] Page is effectively orphaned — no sidebar nav links to it; `App.tsx:1029` renders it only for `/login*` paths, reachable only via a legacy `#/login` hash redirect or a typed URL. The real 401 remediation flow (`App.tsx:410-412`) opens the Settings drawer instead of navigating here.

**Backend feedback:** none — no backend calls exist to break.

---

## 2. Projects / Home (`/workspaces`, `/workspaces/:id`)
**File:** `graphyn-ui/src/features/projects/ProjectsView.tsx` · **Size:** 1401 lines
**Purpose:** Project picker + per-workspace home (pipelines, runs, schedules, linked datasets, spec/taxonomy/contract/versions/snapshots/diff, settings).

**Features:**
- Sidebar: create project (name + New), filter/search, project list, Refresh — `86-136`, `716-787`
- Workspace header: Open Editor, From template, Last run, Refresh — `827-841`
- Activity feed: recent runs + schedule-fired rows, click-to-open — `909-957`
- Pipelines: open pipeline (+ env draft/staging/prod), pin/unpin favorite, Publish→staging, Request prod, Approve prod, Rollback draft — `959-1082`
- Always-on schedules: list, Run now, link to Ops — `1084-1148`
- Linked inputs: pick+Link, Unlink, open in Datasets, Browse library/Artifacts — `1150-1223`
- Spec & metadata (collapsible): Versions (stats, Restore), Spec/Taxonomy/Contract (edit+Save), Snapshots (create/Restore), Diff (pick A/B, Diff, Open Lineage/Artifacts) — `1225-1364`
- Project settings: status select, Rename, Clone, "Use in Ship", Delete — `1366-1396`

**Backend mapping:**
| Feature | Method + path | Handler | Match? |
|---|---|---|---|
| List/Create project | `GET`/`POST /projects` | `projects.py:129-138` | yes |
| Rename/Delete/Status/Clone | `PATCH`/`DELETE`/`PATCH .../status`/`POST .../clone` | `projects.py:141-163` | yes |
| Versions/stats/samples/restore | `GET .../versions[/…]`, `POST …/restore` | `projects.py:358-398, 376` | yes |
| Spec/Taxonomy/Contract | `GET`/`PUT .../{spec,taxonomy,contract}` | `projects.py:193-238` | yes |
| Snapshots | `POST`/`GET .../snapshots`, `POST …/restore` | `projects.py:453-470` | yes |
| Diff/latest lineage | `GET .../diff`, `GET .../lineage` | `projects.py:429-446` | yes |
| Links | `GET`/`POST`/`DELETE .../links` | `projects.py:171-186` | yes |
| Pipelines list/get/put/delete | `GET`/`PUT`/`DELETE .../pipelines[...]` | `projects.py:513-694` | yes |
| Publish/Promote/Rollback | `POST .../publish\|promote\|rollback` | `projects.py:574-649`, `pipeline_environments.py:159-330` | yes — status fields match exactly |
| Recent runs | `GET /runs?project=&limit=8` | `runs.py:153-222` | yes |
| Schedules | `GET /system/schedules`, `POST .../{id}/run` | `system.py:268, 372` | yes |
| Input labels | `GET /data/inputs` | `data.py:86-112` | yes |

**UI feedback:**
- **[P2]** `open()`'s secondary `Promise.all` (recent runs / links / input labels / pipelines / schedules, `ProjectsView.tsx:201-224`) has a `.catch()` on every call **except** `/runs`. If `/runs` alone fails, the whole `Promise.all` rejects and the catch block (`251-256`) blanks all five states — even ones that already answered successfully — with no error banner or retry. Consequence: transient failure on one endpoint renders "No pipelines yet / No schedules yet / No inputs pinned yet" as if that were true, silently.
- [P3] A large fraction of `projects.py`'s surface (annotations, curation decisions, quality-check trigger/status, quality-report export, dataset-card generation, export-gate) has **zero** UI presence anywhere in the console (grep-confirmed).

**Backend feedback:** none — every called route exists with matching shapes.

---

## 3. Builder / Editor (`/workspaces/:id/editor`)
**Files:** `BuilderView.tsx` (2195), `GraphynNode.tsx` (547), `DeletableEdge.tsx` (49), `AgentDrawer.tsx` (150), `TriggersDock.tsx` (266)
**Purpose:** Canvas editor for Graph IR — build, validate, run, save, template, schedule/webhook triggers, propose via agent.

**Features:**
- Node catalog: search, category filter, collapse/expand, click-to-add — `1148-1273`
- Canvas: drag/connect (soft port-type check on connect), delete, selection, snap-to-grid, minimap, pan-on-scroll — `1665-1699`, `474-502`
- Workspace chip / Open Home, project-pipeline picker (draft/staging/prod), Request/Approve prod inline — `1286-1399`
- Pending-proposals chip → Agent inbox; linked-dataset chip — `1400-1445`
- Run / Cancel (streaming NDJSON with live per-node status painting) — `643-845`
- Save, graph-name field, Errors chip → jump to log — `915-937, 1460-1487`
- More menu: Validate, Templates, Triggers dock toggle, Agent drawer toggle, Save-as-template, Import/Export graph, Clear canvas, Run in background, Seed field — `1499-1587`
- Inspector: Graph mode (name/seed/counts/linked run), Edge mode (from/to/port, remove), Node mode (status badge, failure detail w/ jump-to-log/open-run/retry, Placement editor, config fields Basic/Advanced incl. named-secret picker) — `1729-2081`
- Execution log panel: raw/pretty toggle, resizable, error-jump, virtualized — `2088-2182`
- Agent drawer: propose-a-graph textarea → stub proposal — `AgentDrawer.tsx:42-78`
- Triggers dock: interval schedules per pipeline, webhook URL show/copy — `TriggersDock.tsx:50-256`

**Backend mapping:**
| Feature | Method + path | Handler | Match? |
|---|---|---|---|
| Secrets picker | `GET /secrets` | `secrets.py:35-36` | yes |
| Project pipelines | `GET /projects/{p}/pipelines` | `projects.py:513-520` | yes |
| Validate node config | `POST /nodes/{type}/validate-config` | `nodes.py:150-167` | yes |
| Port compatibility | `GET /nodes/compatible` | `nodes.py:69-96` | yes |
| Validate graph | `POST /pipelines/validate` | `pipelines.py:265-334` | yes |
| Run (stream) | `POST /pipelines/run` | `pipelines.py:339-434` | yes — `X-Run-Id` header + NDJSON events match |
| Run in background | `POST /pipelines/run-async` | `pipelines.py:439-503` | yes |
| Save as template | `POST /pipelines/templates` | `pipelines.py:635-692` | yes |
| Save to project | `PUT /projects/{p}/pipelines/{name}` | `projects.py:670-684` | yes |
| Promote from Builder | `POST /projects/{p}/pipelines/{pipe}/promote` | `projects.py:596-616` | yes |
| Hydrate node status | `GET /runs/{id}` | `runs.py:227-263` | yes |
| Agent propose | `POST /proposals` | `proposals.py:36-49` | yes |
| Triggers | `GET/POST /system/schedules`, `GET /system/webhooks` | `system.py:268-323, 182-186` | yes |

**UI feedback:**
- **[P1] Edge conditions, node labels, event triggers, and graph-level `parameters` are silently discarded on both load and save.** `types/graph.ts:130-148` (`buildGraphFromCanvas`) hard-codes `label: null`, `capability_metadata: null`, `event_trigger: null` per node and `condition: null` per edge, and always emits `parameters: {}`; `BuilderView.tsx:570-577`'s `loadGraph` never reads `e.condition` into edge state either. **Consequence:** opening any graph with a conditional branch, event trigger, custom label, or graph-level parameters and clicking Save silently strips all of it — a conditional graph becomes unconditionally linear on disk with no warning.
- **[P1] Cancel does not cancel the run on the backend, and the stream is never aborted on unmount.** `handleCancel` (`BuilderView.tsx:625-634`) only aborts the local fetch reader — no call to `POST /runs/{id}/cancel` exists (grep-confirmed), and there is no unmount cleanup. **Consequence:** (a) the backend keeps executing — and performing any side effects — after the UI shows "cancelled"; (b) navigating away mid-run and starting a new one lets the old stream's callbacks (global Zustand setters) race with and overwrite the new run's state.
- [P3] `onValidateConfig` is fully wired end-to-end (`GraphynNode.tsx:24`, `BuilderView.tsx:369-386`) but no UI control calls it — dead per-node "validate this node" feature.

**Backend feedback:** none — every called endpoint exists and matches.

---

## 4. Runs (`/workspaces/:id/runs`, `/runs/:runId[/panel]`, `/runs/live`, `/runs/compare`)
**Files:** `RunsView.tsx` (1884), `RunLineagePanel.tsx` (386)
**Purpose:** History/Live/Compare tabs; per-run detail (Logs/Debug/Checkpoints/Outputs/Lineage); run control; promote-to-model.

**Features:**
- Top tabs: History / Live / Compare (embeds Experiments) — `259-283`, `1076-1096`
- History: status/name/metric filters, paginated list, open run — `1114-1294`
- Run header: status badge, stale-running warning, progress %, current node, source-run link, worker map — `1330-1384`
- Ops: Open in Editor, Pause/Resume/Cancel (stale-aware confirm), Delete run — `1386-1456`
- Failure/cancel banner: Open Editor, View logs, Explain/propose fix (→ agent proposal) — `1473-1514`
- Promote & register model panel: alias select + Promote, name/slug + Register, per-run models list — `1541-1625`
- Panel tabs: Logs (virtualized, raw/pretty, error-jump), Debug (metrics, recent errors, per-node stats, raw JSON), Checkpoints (load samples), Outputs (grouped, preview, Download/Download-all, Promote), Lineage — `1627-1878`
- Live tab: 3s-polled running/pending list, node-status wave, worker map, "Open in History" — `910-1073`
- Compare tab: embeds ExperimentsView — `1076-1096`
- `RunLineagePanel`: hop list, per-node artifacts → Artifacts, upstream inputs, repro-pack button, Open in Editor

**Backend mapping:**
| Feature | Method + path | Handler | Match? |
|---|---|---|---|
| List runs | `GET /runs` | `runs.py:153-222` | yes |
| Run detail/status/debug/checkpoints/outputs/artifacts | `GET /runs/{id}[...]` | `runs.py:227-411, 496-502, 523-583` | yes |
| Pause/Resume/Cancel | `POST /runs/{id}/{pause,resume,cancel}` | `run_control.py:69-138` | yes for the call — see backend feedback |
| Promote | `POST /runs/{id}/promote` | `runs.py:441-491` | yes |
| Register/list models | `POST`/`GET /models` | `models.py:35-68` | yes |
| Delete run | `DELETE /runs/{id}` | `runs.py:265-286` | yes |
| Checkpoint samples | `GET /runs/{id}/checkpoints/{node}/samples` | `runs.py:400-411` | yes |
| Explain failure → proposal | `POST /proposals` | `proposals.py:36-49` | yes |
| Lineage | `GET /trace?run_id=` | `trace.py:20-40` | yes |

**UI feedback:** none found — this page is in good shape.

**Backend feedback:**
- **[P2] Dict-shaped error `detail` breaks the shared error parser on exactly the failures users hit most.** `run_control.py:36,55,62` raises `HTTPException(detail={"error": "run_not_found", ...})` — an object, not a string. `client.ts`'s `parseError` (`client.ts:79-98`) only unwraps a string or array `detail`; an object falls through to a generic `"HTTP 404"`/`"HTTP 503"`. **Consequence:** clicking Cancel on a run that just finished, or Pause/Resume on a run pinned to another Mode B worker, shows a bare status-code toast instead of the precise reason the backend already computed. (Same root cause recurs on Plugins — see §10 — affecting exactly these two pages, not a systemic issue.)

---

## 5. Trace / Lineage (`view: 'trace'` — no navigable path)
**File:** `graphyn-ui/src/features/trace/TraceView.tsx` · **Size:** 660 lines
**Purpose:** Standalone artifact/run backtrace deep-link page (hop chain, recent-runs picker, lineage inputs).

**Features (as coded — all currently unreachable, see below):** recent-runs picker, artifact/run ID paste, hop-chain visualization, per-hop actions (Open run, Artifacts, Trace this, Editor, Workers), lineage-inputs list, raw JSON view.

**Backend mapping:** `GET /trace` (`trace.py:20-40`) — shapes match `app/core/trace.py:138-337`'s `assemble_trace` exactly. Not the problem.

**UI feedback:**
- **[P1] This entire page is dead code — there is no way for a user to reach it.** Independently re-verified: `routes/parsePath.ts` never returns `{view: 'trace'}` for any recognized path (`grep -n "'trace'"` → zero hits); `appStore.ts:223-246`'s `openTrace()` sets `view: 'trace'` only in the fallback branch reached when **neither** `runId` nor `artifactId` is passed — but every one of the 8 real call sites (`App.tsx` ×2, `CommandPalette.tsx`, `ModelsView.tsx`, `ArtifactsView.tsx`, `ProjectsView.tsx`, `EdgeWizardView.tsx` ×2) passes a `runId`, which routes to `view: 'runs'` with the lineage panel instead. `App.tsx:63-99`'s sidebar has no Trace/Lineage entry at all — a comment there confirms this is deliberate: "Lineage / Compare live under Runs." **Net effect:** 660 lines of a fully built page are shipped and labeled live in `VIEW_LABEL`/`NAV_HINTS`, but functionally superseded by `RunLineagePanel` and never rendered for any real user action.

**Backend feedback:** none — the endpoint this page would use is fine; the page just never calls it.

---

## 6. Experiments / Compare runs (`/workspaces/:id/runs/compare`)
**File:** `graphyn-ui/src/features/experiments/ExperimentsView.tsx` · **Size:** 784 lines
**Purpose:** Select 2–5 runs, compare params/metrics side by side, export CSV, bar-chart metrics.

**Features:**
- Deep-link banner → Runs → Compare — `310-345`
- Selection: per-row checkboxes (max 5), sticky bar, Compare, Clear — `244-253, 365-379`
- Groups sidebar (by experiment name) — `423-451`
- Run table: metric columns, code_hash/data_version when present, Open/Open Lineage — `455-567`
- Compare panel: Parameters/Metrics/Repro-metadata tables with diff highlight, per-metric bar charts, Export CSV — `569-707`
- Auto-compare on deep-link with ≥2 ids — `288-296`

**Backend mapping:**
| Feature | Method + path | Handler | Match? |
|---|---|---|---|
| List experiments | `GET /experiments?project=` | `experiments.py:18-28` | yes |
| Compare | `GET /experiments/compare?run_ids=` | `experiments.py:31-46` | yes |

**UI feedback:** none found. **Backend feedback:** none found.

---

## 7. Templates (`/templates`)
**File:** `graphyn-ui/src/features/templates/TemplatesView.tsx` · **Size:** 727 lines
**Purpose:** Browse/import example + saved templates, open into a project, save/upload new templates, manage versions.

**Features:**
- Header: Refresh, Sync examples, Save from Editor (name + Upload) — `344-419`
- Search + All/Examples/Saved filter — `434-464`
- Per-card: description/tags, version picker, Open (project-gated), "Open Datasets", per-card menu (Delete version, Delete) — `493-655`
- Project gate modal: pick/create project, load stamped graph, save as pipeline — `658-724`

**Backend mapping:**
| Feature | Method + path | Handler | Match? |
|---|---|---|---|
| List templates | `GET /pipelines/templates` | `pipelines.py:528-548` | yes |
| Template versions | `GET /pipelines/templates/{name}/versions` | `pipelines.py:551-586` | yes |
| Get template (+version) | `GET /pipelines/templates/{name}?version=` | `pipelines.py:589-632` | yes |
| Save/Upload | `POST /pipelines/templates` | `pipelines.py:635-692` | yes |
| Delete (version) | `DELETE /pipelines/templates/{name}[?version=]` | `pipelines.py:695-743` | yes |
| Sync examples | `POST /pipelines/templates/sync-examples?force=` | `pipelines.py:508-517` | yes |
| Project create/list, save pipeline | `GET`/`POST /projects`, `PUT /projects/{p}/pipelines/{n}` | `projects.py:129-138, 670-684` | yes |

**UI feedback:** none found. **Backend feedback:** none found.

---

## 8. Proposals / Agent inbox (`/agent/inbox[/:id]`)
**File:** `graphyn-ui/src/features/proposals/ProposalsView.tsx` · **Size:** 771 lines
**Purpose:** Review agent/MCP-authored graph proposals; accept (→ Editor, optional save) or reject; generate a proposal from a prompt.

**Features:**
- Header: Generate proposal (prompt → stub GraphIR), Refresh — `386-445`
- Docs/inbox banner (dismissible) — `446-467`
- Search + status filter — `468-491`
- Master list: summary, status badge, actor chip, diff counts — `535-570`
- Detail: Reject / Accept→Editor / Accept-then-save, diff summary, side-by-side base/proposed GraphIR, local chat transcript, raw JSON — `585-742`

**Backend mapping:**
| Feature | Method + path | Handler | Match? |
|---|---|---|---|
| List/create proposals | `GET`/`POST /proposals` | `proposals.py:36-63` | yes |
| Get one | `GET /proposals/{id}` | `proposals.py:71-79` | yes |
| Accept/Reject | `POST /proposals/{id}/{accept,reject}` | `proposals.py:82-107` | yes — `accept_proposal` returns `proposed_graph` (`app/core/agentic/proposals.py:271,342`) matching `resolveAcceptedGraph` |
| Save accepted graph | `PUT /projects/{p}/pipelines/{n}` | `projects.py:670-684` | yes |

**UI feedback:** none found. **Backend feedback:** none found.

---

## 9. Data / Datasets (`/workspaces/:id/datasets`, `/library/datasets`)
**File:** `graphyn-ui/src/features/data/DataView.tsx` · **Size:** 1246 lines
**Purpose:** Browse Inputs/Outputs, upload, URL/HuggingFace ingest with streaming progress, delete, merge datasets.

**Features:**
- Browse/Manage toggle; Inputs/Outputs mode; project/version or label pickers — `125-324`
- File browser (jailed blob fetch), filter — `413-429`
- Upload audio file — `431-455`
- Ingest: URL list + label → streamed job log, HuggingFace repo → same — `457-535`
- Delete input label / output version — `537-565`
- Merge: `project:version` sources → target project/version — `567-593`
- Browse-templates shortcut — `595-598`

**Backend mapping:**
| Feature | Method + path | Handler | Match? |
|---|---|---|---|
| List inputs/outputs | `GET /data/{inputs,outputs}` | `data.py:86-112, 236-256` | yes |
| Detail | `GET /data/inputs/{label}`, `GET /data/outputs/{p}/{v}[/stats]` | `data.py:151-178, 259-346` | yes |
| Upload | `POST /data/inputs/upload` | `data.py:198-231` | yes |
| Delete | `DELETE /data/inputs/{label}`, `DELETE /data/outputs/{p}/{v}` | `data.py:181-191, 304-321` | yes |
| Ingest + stream | `POST /ingest/{url,huggingface}`, `GET /ingest/{kind}/{job}/stream` | `ingest.py:51-124` | yes — egress-validated at `:62-68` |
| Merge | `POST /data/merge` | `data.py:357-481` | yes |

**UI feedback:**
- **[P2] Merge result parsing checks the wrong field names, and reports success even when sources failed.** `lib/format.ts:301-307`'s `formatMergeToast` looks for `res.merged`/`res.count`/`res.files`/`res.entries`; the real response is `{target, files_copied, errors, labels_written}` (`data.py:476-481`) — none match, so it always falls back to the generic `"Merge complete"` string. `DataView.tsx:585` fires that toast with tone `'success'` regardless of whether `res.errors` is non-empty. **Consequence:** the real `files_copied` count is silently discarded, and a partially-failed merge (e.g. `"Source not found: proj/v2"` in the dropped `errors` array) is reported as an unqualified success.

**Backend feedback:** none beyond the above (a frontend contract mismatch, not a backend bug).

---

## 10. Plugins (`/library/plugins`)
**File:** `graphyn-ui/src/features/plugins/PluginsView.tsx` · **Size:** 906 lines
**Purpose:** Install/search plugins, manage per-plugin dependencies, enable/disable/uninstall, venv GC.

**Features:**
- Header: Clean unused venvs, Refresh — `459-490`
- Tabs: Installed / Install-Search — `442-526`
- Install: source input (+Advanced: SHA256, upgrade) → Install; search-index query → Use — `528-601`
- Installed: status filter pills, per-plugin card (runtime badge, missing-dep counts, primary dep CTA, Manage dependencies), per-card menu (Dependencies, Enable/Disable, Uninstall), dependency panel (per-requirement satisfied/missing, install buttons), live install-progress naming actual packages, terminal-only success/failure toasts — `605-902`

**Backend mapping:**
| Feature | Method + path | Handler | Match? |
|---|---|---|---|
| List plugins | `GET /plugins` | `plugins.py:137-163` | yes |
| Install | `POST /plugins/install` | `plugins.py:201-273` | yes — sync/async branching matches |
| Poll install | `GET /plugins/{name}` | `plugins.py:341-365` | yes |
| Dependencies status/install | `GET`/`POST /plugins/{name}/dependencies[/install]` | `plugins.py:371-467` | yes — see backend feedback |
| Enable/Disable/Uninstall | `POST /plugins/{name}/{enable,disable}`, `DELETE /plugins/{name}` | `plugins.py:279-335` | yes |
| Search | `GET /plugins/search` | `plugins.py:171-186` | yes |
| Venv GC | `POST /plugins/venvs/gc` | `plugins.py:189-195` | yes |

**UI feedback:**
- [P3] `installDeps()`'s branch at `PluginsView.tsx:398-401` (synchronous `dependencies` array path) is dead code — `POST /plugins/{name}/dependencies/install` **always** returns `{"status": "installing", ...}` (`plugins.py:463-467`, unconditional `background_tasks.add_task`), never triggering that branch.

**Backend feedback:**
- **[P2] Same dict-shaped-`detail` gap as §4.** `plugins.py`'s `_plugin_http_error` (`:109-115`) raises object `detail` for `PluginAlreadyInstalledError` (409), `PluginCompatibilityError`/`PluginDependencyError` (422), `PluginInstallError`/`PluginIndexError` (502) — exactly the errors a user hits clicking Install. Shows as bare `"HTTP 409"`/`"HTTP 422"` instead of the real reason (e.g. "already installed at version 1.2.0", or the pip conflict summary).

**Rework status (commit `dc1d42f` + follow-on work):** This is a genuine, **complete** fix for a real problem — isolated TensorFlow/ONNX plugin installs used to block the API from binding for 10–30+ minutes.
- Registry init now runs in a background thread inside a FastAPI `lifespan`, so `:8001` binds immediately; `/system/readiness` gained `registry_ready`/`node_type_count`/`registry_init_error`.
- `loader.py`'s `isolated_venv_requirements()` now defers heavy optional ML packages at load time by default (only installed when `GRAPHYN_ISOLATED_BOOT_HEAVY=1`), and falls back to required-deps-only if the optional install fails, rather than blocking registration.
- `dependencies.py`'s `DependencyChecker.install(..., one_by_one=True)` installs optional extras one at a time so one bad wheel doesn't abort the rest.
- `PluginsView.tsx` now names the actual packages being installed instead of hard-coded text, matching the new on-demand-install default.

The one rough edge it doesn't touch is the dict-shaped-error gap above, which predates this commit.

---

## 11. Models (`/workspaces/:id/models[/:name]`)
**File:** `graphyn-ui/src/features/models/ModelsView.tsx` · **Size:** 331 lines
**Purpose:** Registry of promoted run artifacts — stages (staging/prod/latest), request/approve prod, register new model.

**Features:**
- Header: Refresh, Register model (toggle form) — `139-152`
- Register-from-run form — `156-177`
- Master list: rows with prod/staging badge — `198-223`
- Detail: per-stage row (staging/prod/latest) with linked run, Request prod, Approve prod, Open Lineage / Dataset pins / Open Home / Use in Ship — `225-333`

**Backend mapping:**
| Feature | Method + path | Handler | Match? |
|---|---|---|---|
| List/get models | `GET /models[/{name}]` | `models.py:35-51` | yes |
| Register | `POST /models` | `models.py:54-68` | yes |
| Request/Approve prod | `POST /models/{name}/{request-prod,approve-prod}` | `models.py:71-92` | yes for the call itself — see UI feedback |

**UI feedback:**
- **[P1] "Approve prod" renders unconditionally whenever the stage loop reaches `'prod'`, regardless of whether anything is pending approval.** Independently re-verified: `ModelsView.tsx:268-278` guards the button on nothing but `stage === 'prod'` — no check on `entry`, no check on a pending flag. The backend's actual pending state (`pending_prod: {run_id, slug, requested_at, requested_by}`, `app/core/model_registry.py:170-175`) is a **sibling field of `stages`**, not nested inside `stages.prod` the way the frontend's own type declares (`ModelRow.stages: Record<string, {..., pending_prod?: boolean}>`, `ModelsView.tsx:13`) — and `detail.pending_prod` is never read anywhere in the file. **Consequence:** any model with only a staging stage and no prod request ever made still shows an active "Approve prod" button; clicking it always fails with the backend's `ValueError("No pending_prod to approve")` (422), with no visual cue it will fail.

**Backend feedback:** none — the backend contract is fine; the mismatch is entirely the frontend's read of `pending_prod`'s location.

---

## 12. Artifacts (`/library/artifacts`)
**File:** `graphyn-ui/src/features/artifacts/ArtifactsView.tsx` · **Size:** 718 lines
**Purpose:** Cross-run artifact registry — filter, inspect, download, replay, lineage, register model.

**Features:**
- Run/Type filters (+ advanced run-id/node-type), Apply, Clear — `340-425`
- Master list: title/run/type — `464-487`
- Detail: title/type/run-link/graph/size/created, image preview, Lineage, Download, Open run, Replay, Editor, Copy path, downstream-consumers, Register model — `492-717`

**Backend mapping:**
| Feature | Method + path | Handler | Match? |
|---|---|---|---|
| List artifacts | `GET /artifacts` | `artifacts.py:49-66` | yes, but see UI feedback on pagination |
| Get artifact | `GET /artifacts/{id}` | `artifacts.py:71-90` | yes |
| Replay | `POST /artifacts/{id}/replay` | `artifacts.py:114-204` | yes |
| Download/preview | `GET /outputs/file` | `outputs.py:40-54` | yes for transport — see UI feedback on `path` |
| Register model | `POST /models` | `models.py:54-68` | yes |

**UI feedback:**
- **[P1] `findCopyablePath()` never checks the field the backend actually returns.** Independently re-verified against the current working tree: `ArtifactsView.tsx:50-63` only checks keys `'model_path'`/`'path'` (recursing into nested objects). The real `ArtifactRecord` field is `data_path` (`app/core/artifact_store.py:147`), a **top-level string** — not nested under anything the recursive search descends into. **Consequence:** for ordinary node-output artifacts (the common case), `path` is always `null`, so the **Download button, Copy-path button, and image preview never appear**. `RunsView.tsx:59,78,158` and `RunLineagePanel.tsx` both correctly check `data_path` first — this page is the outlier.
- [P2] `load()` (`ArtifactsView.tsx:149-176`) never passes `limit`/`offset` to `GET /artifacts` (server default `limit=100`, `artifacts.py:54`), and there is no pagination control anywhere in the file. Any project with >100 artifacts silently shows only the newest 100.

**Backend feedback:** none — `artifacts.py` is correct and already supports pagination the UI doesn't use.

---

## 13. Edge / Ship (`/workspaces/:id/ship`, `/deploy/ship`)
**File:** `graphyn-ui/src/features/edge/EdgeWizardView.tsx` · **Size:** 1088 lines
**Purpose:** 4-step wizard (Graph → Configure → Package → Download) to package a trained model for edge deployment, with train→package lineage.

**Features:**
- Step 1: link project + source run/artifact/registry-model pickers, load edge-deploy template — `98-427`
- Step 2: configure model path (live existence probe), labels CSV, backend/quantization/target selects, package name — `54-57, 164-233`
- Step 3: Package run (`POST /pipelines/run-async` with `source_run_id`/`source_artifact_id` lineage fields), live status poll, failure diagnostics — `434-547, 587-616`
- Step 4: Download (existence-probed), Promote (staging/prod alias) — `549-583`
- Ship/Devices tab switch

**Backend mapping:**
| Feature | Method + path | Handler | Match? |
|---|---|---|---|
| Registry models | `GET /models` | `models.py:35-39` | yes |
| Path probes | `GET /outputs/file` | `outputs.py:40-54` | yes |
| Source artifacts/runs | `GET /artifacts?run_id=`, `GET /runs?project=` | `artifacts.py:49-66`, `runs.py:153-222` | yes |
| Package run | `POST /pipelines/run-async` | `pipelines.py:439-503` | yes — `source_run_id`/`source_artifact_id`/`project` explicitly supported for this wizard (`app/core/run_project.py:81-91`) |
| Poll status/artifacts | `GET /runs/{id}[/status]`, `GET /artifacts?run_id=` | `runs.py:227-263, 312-349`; `artifacts.py:49-66` | yes |
| Download | `GET /outputs/file` | `outputs.py:40-54` | yes |
| Promote | `POST /runs/{id}/promote` | `runs.py:441-491` | yes |

**UI feedback:**
- [P2] `applySourceArtifact()` (`:383-401`) and the post-run package-detection loop (`~496-521`) compute a candidate path via `a.uri || a.path || metaPath` — the same missing-`data_path` gap as §12. Lower severity here because a broader fallback chain (`resolveModelPathCandidates` probing guessed paths) means the feature degrades rather than breaks — but the "pick model path from a linked source artifact" shortcut is quietly less precise than intended.

**Backend feedback:** none.

---

## 14. Devices (`/workspaces/:id/ship/devices`, `/deploy/ship/devices`)
**File:** `graphyn-ui/src/features/ship/DevicesView.tsx` · **Size:** 45 lines
**Purpose:** Placeholder for device inventory/flash/OTA, pending a backend device-registry API.

**Features:** a single, explicitly-labeled `EmptyState` ("No device registry yet") — no inputs, no backend calls.
**UI feedback:** none — an honestly-labeled stub, not a defect. **Backend feedback:** N/A.

---

## 15. Workers / Worker fleet (`/deploy/workers`, `/deploy/workers/queue`)
**File:** `graphyn-ui/src/features/workers/WorkersView.tsx` · **Size:** 549 lines
**Purpose:** Mode B worker registry — list, filter, inspect, deregister; honest "Queue" tab (no list-jobs API exists).

**Features:**
- Summary strip (count, mode hint, last-refreshed, Refresh) — `162-174`
- Workers/Queue tabs — `178-193`
- Queue tab: explicit "no list-all-jobs API" notice + recent-run-statuses proxy — `195-274`
- Workers tab: label/pool/status filters, table — `307-421`
- Worker detail: status, labels/pools (display-only), resources, heartbeat, plugins, Deregister — `424-546`

**Backend mapping:**
| Feature | Method + path | Handler | Match? |
|---|---|---|---|
| List workers | `GET /workers?include_stale=` | `workers.py:124-127` | yes — fields match `WorkerInfo` (`app/core/distributed/models.py:50-63`) exactly |
| Deregister | `DELETE /workers/{id}` | `workers.py:130-136` | yes |
| Recent runs (queue proxy) | `GET /runs?limit=12` | `runs.py:153-222` | yes |

**UI feedback:** none found — the Queue tab is careful to label itself a proxy, matching reality. **Backend feedback:** none found.

---

## 16. Secrets (`/admin/secrets`)
**File:** `graphyn-ui/src/features/secrets/SecretsView.tsx` · **Size:** 211 lines
**Purpose:** Named-secret store — list names (never values), store/rotate, delete, search.

**Features:**
- Store/rotate form: name, value (show/hide), replace-confirmation — `103-154`
- Search names — `156-164`
- List: click-to-reuse, per-row Delete (confirm) — `188-208`

**Backend mapping:**
| Feature | Method + path | Handler | Match? |
|---|---|---|---|
| List names | `GET /secrets` | `secrets.py:34-36` | yes |
| Store/rotate | `POST /secrets` | `secrets.py:39-57` | yes |
| Delete | `DELETE /secrets/{name}` | `secrets.py:81-101` | yes |

**UI feedback:** none found. **Backend feedback:** none found (`PUT /secrets/{name}` exists server-side but is simply unused — not a defect).

---

## 17. System / Ops (`/admin/ops[/audit]`)
**File:** `graphyn-ui/src/features/system/SystemView.tsx` · **Size:** 1176 lines
**Purpose:** Health/readiness, metrics, schedules, webhooks, cleanup, audit — the operator console.

**Features:**
- Status: backend/mode chip, MCP info, Reconcile-abandoned-runs, live metrics tiles, Health card, Readiness card, Maintenance (clean venvs) — `372-610`
- Schedules: create (name/project/pipeline/interval), Add, Run due now, per-schedule Run now/Enable-Disable/Delete — `709-936`
- Webhooks: URL + event checkboxes, Save, Send test — `938-1025`
- Cleanup: older-than-days, delete-cache/artifacts/reconcile checkboxes, type-to-confirm destructive action — `1027-1173`
- Audit: actor/resource filters, Export JSON, event table — `613-707`
- Global: auth-required-but-no-token banner — `364-370`

**Backend mapping:**
| Feature | Method + path | Handler | Match? |
|---|---|---|---|
| Health/Readiness/Metrics | `GET /system/{health,readiness,metrics}` | `system.py:42-94` | yes |
| Webhooks | `GET`/`PUT /system/webhooks`, `POST .../test` | `system.py:182-230` | yes |
| Audit | `GET /audit?limit=` | `trace.py:54-58` | yes |
| Auth status | `GET /system/auth-status` | `system.py:235-250` | yes |
| Schedules CRUD/tick/run/enable | `GET/POST/DELETE /system/schedules[...]` | `system.py:253-394` | yes |
| Cleanup/Reconcile | `POST /system/cleanup` | `system.py:108-155` | yes |
| Venv GC | `POST /plugins/venvs/gc` | `plugins.py:189-195` | yes |
| Project/pipeline pickers | `GET /projects`, `GET /projects/{p}/pipelines` | `projects.py:129-138, 513-520` | yes |

**UI feedback:**
- **[P2] `registry_init_error` is fetched but never rendered.** It's part of the same `/system/readiness` payload the page already reads into `readyObj`, but grep-confirmed there's no reference to it in `SystemView.tsx`. `registryReady` collapses "still starting" and "permanently failed" into one boolean, and the Readiness card shows the same "Still loading plugins… refresh in a moment" message for both. **Consequence:** if AutoDiscovery hard-fails (duplicate `node_type`, import error), an operator is told to "refresh in a moment" — which will never resolve — instead of seeing the actual error string the backend already computed.

**Backend feedback:** none — the backend side is correct and complete (see Rework status).

**Rework status (commit `dc1d42f` + follow-on work):** two independent, verified fixes.
1. **P2-30 (one failing endpoint blanking the whole page) fixed, completely.** `refresh()` switched to `Promise.allSettled` with a `panelErrors` map tracked per-endpoint; each section renders independently. Verified end-to-end: `panelErrors.{metrics,health,readiness,schedules,webhooks}` are all actually rendered at their sections, not just computed and discarded. Minor residual: the auth-status panel has no visible failure indicator (fine, not a regression).
2. **DEEP_REVIEW's readiness-`finally`-block bug fixed, completely, on the backend.** `app/core/nodes/__init__.py` now tracks `_init_error` / `registry_init_error()`; `is_registry_ready()` returns `False` on init failure; `/system/readiness` correctly reports `"status": "failed"` with the error populated. **The frontend rework fell short of the backend fix here** — the new field the backend now correctly computes isn't consumed by the one page that needs it (see UI feedback above), a real if minor residual gap directly adjacent to what this rework targeted.

---

## 18. Access (`/admin/access`)
**File:** `graphyn-ui/src/features/access/AccessView.tsx` · **Size:** 53 lines
**Purpose:** Placeholder — actor identity (feeds `X-Actor` header) + link to Settings; explicit "Roles coming with multi-user API" stub.

**Features:** actor-name field (persists to `localStorage`, consumed by `client.ts:authHeaders()` as `X-Actor` on every mutation) — `9-33`; "API token & Settings" button — `38-40`; explicit "Roles coming…" stub — `42-50`.
**Backend mapping:** N/A — no HTTP calls; `X-Actor` is read downstream by every router's `resolve_actor(request)` for audit trails.
**UI feedback:** none — another honestly-labeled stub. **Backend feedback:** N/A.

---

## Cross-cutting

- **No global 401 handling.** `client.ts`'s `parseError` prefixes a 401 with "Unauthorized — set API token in Settings," but nothing app-wide reacts to a 401 by opening Settings. Only Projects (`authBlocked` detection) and Builder (catalog 401 check) special-case it. Every other page — Runs, Trace, Experiments, Templates, Proposals, Data, Plugins, Models, Artifacts, Edge, Workers, Secrets, System, Access — just shows the generic error banner with Retry. One shared-plumbing fix (an app-level 401 interceptor) would resolve this everywhere at once.
- **Artifact "path" field naming is inconsistent across the UI.** `RunsView.tsx` and `RunLineagePanel.tsx` correctly check `data_path` first; `ArtifactsView.tsx` (§12, page-breaking) and `EdgeWizardView.tsx` (§13, degraded) do not. Same underlying cause, one fix: teach both call sites to check `data_path` first.
- **Dict-shaped `HTTPException.detail` breaks the shared error parser.** Exactly two routers — `run_control.py` (§4) and `plugins.py` (§10) — raise object `detail` instead of a string; `client.ts`'s `parseError` doesn't unwrap it. Fixing `parseError` to also handle `{error, ...}` objects (or fixing both routers to raise strings) closes both at once.

## Page health summary

| Page | Features | UI defects | Backend defects | Verdict |
|---|---|---|---|---|
| Login | 2 | 3 (P3) | 0 | needs work (minor, low-traffic) |
| Projects / Home | ~30 | 1 (P2) + 1 (P3 coverage) | 0 | solid |
| Builder / Editor | ~30 | 2 (P1) + 1 (P3) | 0 | **needs work** |
| Runs | ~35 | 0 | 1 (P2) | solid |
| Trace / Lineage | ~10 (unreachable) | 1 (P1 — page is dead) | 0 | **broken** |
| Experiments | ~10 | 0 | 0 | solid |
| Templates | ~10 | 0 | 0 | solid |
| Proposals | ~12 | 0 | 0 | solid |
| Data | ~15 | 1 (P2) | 0 | solid |
| Plugins | ~20 | 1 (P3) | 1 (P2) | solid (recently reworked) |
| Models | ~10 | 1 (P1) | 0 | **needs work** |
| Artifacts | ~12 | 2 (P1 + P2) | 0 | **needs work** |
| Edge / Ship | ~20 | 1 (P2) | 0 | solid |
| Devices | 1 (stub) | 0 | 0 | solid (honest stub) |
| Workers | ~15 | 0 | 0 | solid |
| Secrets | 5 | 0 | 0 | solid |
| System / Ops | ~25 | 1 (P2) | 0 | solid (recently reworked) |
| Access | 3 (stub) | 0 | 0 | solid (honest stub) |

**Priority order for a fixing agent:** Trace (P1, dead page — either wire it up or delete it and its nav labels), Artifacts `data_path` (P1, breaks Download/Copy/Preview for most artifacts), Builder edge-condition/label data loss (P1) and Cancel-doesn't-cancel (P1), then Models "Approve prod" guard (P1), then the P2s in any order.

---

## Appendix — test suite currently crashes, unconditionally

Not a page-level finding, but relevant to anyone picking up work here: `venv/bin/pytest unit_test/ -q` **segfaults (exit 139)**, reproducibly, on this environment — confirmed on two separate runs, and unaffected by `GRAPHYN_SKIP_PLUGIN_LOAD=1`. The crash happens ~92%+ through the run, in a background `ThreadPoolExecutor` worker mid-import of `triton` (pulled in transitively by `transformers` → `torch._dynamo`). Installed: `torch==2.12.0`, `transformers==5.9.0`, `cuda-bindings==13.3.1`, against driver `580.178.04` (CUDA 13.0). This is very likely a package-version/CUDA-binding mismatch rather than an app bug, but it means the documented dev command (and the CI job that now runs the full suite per `dc1d42f`) cannot complete on this machine today. Worth pinning down before relying on CI green/red here.
