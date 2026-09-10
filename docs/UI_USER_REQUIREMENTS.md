# Graphyn Console — User Requirements (detailed)

> Written **as the user** (“I expect…”). Goal: lock what each page must do before more UI churn.  
> Anchors: [PRODUCT_VISION.md](./PRODUCT_VISION.md) (n8n + MLflow + orchestrator + Edge Impulse + agents + accountability).  
> Industry norms: [n8n editor/executions](https://docs.n8n.io/), [MLflow tracking UI](https://mlflow.org/docs/latest/ml/tracking/), [Edge Impulse data→deploy](https://docs.edgeimpulse.com/), [Prefect run detail/assets](https://docs.prefect.io/).  
> Mode A/B: [GETTING_STARTED.md](./GETTING_STARTED.md).  
> Grounded in real console NAV (`graphyn-ui/src/App.tsx`) and feature views under `graphyn-ui/src/features/*`.  
> Widgets listed with **(shipped)** when the control already exists in TSX; **MISSING — I need …** when the product should have it and it isn’t there yet.  
> **Do not treat this doc as an implementation ticket list for CloudAgent** — requirements only.

---

## 0. North-star loop (what I expect as a user)

```
Upload / ingest data  →  Create or open Project  →  Open Template in Builder
    →  Run  →  Watch Runs / Logs  →  Open Trace or Artifacts
    →  Manage version in Projects  →  Compare in Experiments
    →  Package in Edge  (Workers only if Mode B / distributed)
```

**Rules I expect everywhere**

1. Every page has **one job** (no dumping the same metadata under new labels).
2. Every empty state tells me **the next click**, not jargon.
3. Deep links survive refresh (`#/runs/{id}`, `#/trace?run_id=`, `#/data?mode=inputs`, `#/projects?project=&tab=`, `#/experiments?run_id=a,b`, …).
4. Cross-links pass context (run_id, project, version, artifact_id) — I never re-paste IDs.
5. Destructive actions need confirm; Docker paths stay inside workspace.
6. Mode A vs Mode B is honest: Workers is Mode B placement; Edge is packaging; local runs still work without workers.

### Mode A vs Mode B (global)

| | **Mode A** (default) | **Mode B** (`GRAPHYN_BACKEND=distributed` + workers) |
|---|---|---|
| Who runs nodes | This API process / single Docker box | Control plane + registered workers by labels/GPU/pool |
| Workers page | Empty is **OK** — copy explains local mode; CTA Open System / Edge | List must show heartbeats, stale, labels, GPU/VRAM |
| Runs detail | No `distributed_node_workers` chips (or empty) | Chips `node → worker_id` when placement map exists |
| Builder IR placement | Optional; ignored for local backend | Placement on nodes routes GPU work |
| First-run path | Templates → Builder → Run → Runs | Same, plus Workers must show ≥1 live worker before GPU jobs finish |

---

## 1. Global chrome

**One-job statement:** I expect the shell to tell me where I am, whether the API trusts me, and how to jump into the observe loop for my last run — without stealing focus from the page’s job.

### Mode A

I expect Connected when the catalog loads; Settings only for the Bearer token; Workers empty is fine and should not scare me.

### Mode B

I expect the same chrome. Last-run strip still works. If a run was placed on workers, Trace / Runs still open with `run_id` — I should not need to visit Workers first unless I’m debugging placement.

### Widgets / UI elements

| Element | Expected behavior |
|---|---|
| **Brand + current view subtitle** (shipped) | Shows “Graphyn” + active page label (Builder, Runs, …). |
| **Menu / collapse sidebar** (shipped) | Mobile: hamburger opens drawer + backdrop. Desktop: collapses sidebar. |
| **Sidebar groups** (shipped) | Build / Observe / Library / Deploy / Admin — labels match jobs. |
| **Nav items** (shipped) | Builder, Templates, Proposals, Runs, Trace, Experiments, Artifacts, Plugins, Data, Projects, Edge deploy, Workers, Secrets, System. Active = white pill + `aria-current`. Tooltip = NAV hint + jump key. |
| **Proposals badge** (shipped) | Amber count when pending > 0; polls ~60s. |
| **Connected / Sign in / Can’t reach** (shipped) | Green-ish “Connected” when OK; “Sign in required” on 401; “Can't reach the API” otherwise. Boot banner with **Open Settings**. |
| **Running chip** (shipped) | Amber pill while `isRunning`; else optional status chip. |
| **Last-run strip** (shipped) | When `lastRunId` set: **Run {short}**, **Lineage**, **Artifacts**, **Compare**, **Projects**. Passes `run_id` into Trace/Artifacts/Runs; Compare seeds experiments with that id; Projects opens list (no project auto-select unless known). |
| **?** help (shipped) | Opens Keyboard shortcuts overlay (jump keys + Builder tips). Esc closes. |
| **Settings (gear)** (shipped) | Dialog: **API Bearer token** field (show/hide), Cancel, Save. Toast “API token saved/cleared”; refreshes catalog. Stored only in this browser (= `GRAPHYN_API_TOKEN`). |
| **Toast host** (shipped) | Success / error / info toasts; dismissible. |
| **MISSING — I need** | Last-run **Compare** chip should not pretend a single-run compare is ready: either disable with “select a second run” or open Experiments with that run pre-checked and clear copy. |
| **MISSING — I need** | Jump key for **Secrets** (today: b/t/p/r/o/e/a/d/j/g/w/l/s — no secrets key). |
| **MISSING — I need** | Re-clicking the same Observe/Library nav item must **keep** query (`#/trace?run_id=…`) — already intended for preserve-query views; I expect that contract documented and tested. |

### Links & transitions

| From | To | Context |
|---|---|---|
| Last-run → Run | `#/runs/{id}` | `run_id` |
| Last-run → Lineage | `#/trace?run_id=` | `run_id` |
| Last-run → Artifacts | `#/artifacts?run_id=` | `run_id` |
| Last-run → Compare | `#/experiments?run_id=` | ≥1 seeded id |
| Last-run → Projects | `#/projects` | none (or project if stamped later) |
| Jump keys | same as sidebar | none |
| Boot banner → Settings | modal | token focus |

### Acceptance checks

- **Given** API reachable and token OK, **When** I load the console, **Then** I see Connected and the Builder catalog can load.
- **Given** 401, **When** boot fails, **Then** Settings opens / banner offers Open Settings and I can paste `GRAPHYN_API_TOKEN`.
- **Given** a successful Builder run, **When** I look at the header, **Then** last-run chips open Runs/Trace/Artifacts with that `run_id` without pasting.
- **Given** I press `?`, **When** the overlay opens, **Then** jump keys match sidebar destinations and Esc closes.

---

## 2. Build

### 2.1 Builder (`#/builder`) — *n8n canvas*

**One-job statement:** I expect to design Graph IR on a canvas and run it — one place for nodes, wires, validate, and execute.

#### Mode A

Run executes in-process on the API host. I do not need Workers. Catalog comes from locally installed plugins.

#### Mode B

Same canvas. Nodes with IR `placement` (auto/worker/pool/gpu) wait for matching workers. I expect Run to still start; stuck nodes show in Runs/logs; Workers page shows who is alive.

#### Widgets / UI elements

| Element | Expected behavior |
|---|---|
| **Node catalog search** (shipped) | Placeholder “Search nodes…”; `/` or ⌘/Ctrl+K focuses it on Builder. |
| **Category filter** (shipped) | Select “All categories (N)” + per-category counts. |
| **Catalog list** (shipped) | Grouped by category; click adds node; `iso` chip for isolated runtime. |
| **Empty catalog** (shipped) | Auth: “Sign in to load nodes” → **Open Settings**. Else “No plugins installed” → **Open Plugins** / **Open Data** / **Open Projects**. |
| **No nodes match** (shipped) | Soft empty when filter too narrow. |
| **Pending proposals chip** (shipped) | Amber “N proposal(s)” → Proposals. |
| **Dataset chip** (shipped) | When opened from Projects: `Dataset: {project} / {version}`; **Open Data** (outputs+project); clear (X). |
| **Run** (shipped) | Primary; disabled when canvas empty; starts run; becomes **Cancel** while running. |
| **Validate** (shipped) | Surfaces errors (banner/toast); no silent fail. |
| **Graph name** (shipped) | Slug field; used as artifact slug on Run. |
| **Errors chip** (shipped) | After failed run; jumps to log errors. |
| **More menu** (shipped) | Save template (+ name), Import graph, Export graph, secondary actions. |
| **Canvas** (shipped) | Zoom/pan/fit; connect ports; delete wire (**Remove connection**); select node; empty canvas CTAs. |
| **Empty canvas CTAs** (shipped) | **Open Templates** (and related next-click help). |
| **Inspector** (shipped) | Graph settings or selected node/edge fields from plugin schema; **Clear selection**; **No config fields** when schema empty. |
| **Node chrome** (shipped) | Configure / Remove; port types on hover; status. |
| **Execution log** (shipped) | Collapsible; “No events yet.”; resize handle; Open run when `lastRunId`. |
| **Action error banner** (shipped) | Retry / Open run. |
| **MISSING — I need** | Explicit “Run in background” vs foreground if product wants both modes labeled (secondary action exists in code paths — keep one clear primary story). |
| **MISSING — I need** | Placement inspector fields called out when Mode B (mode/tags/require_gpu/pool) so I don’t invent them in raw IR only. |

#### Links & transitions

| From | To | Context |
|---|---|---|
| Templates → Builder | canvas | Full graph IR loaded |
| Projects → Builder | canvas + dataset chip | `output_dir=datasets/output/{project}`, `version_tag` |
| Proposals Accept → Builder | canvas | Proposed graph |
| Catalog empty → Plugins | `#/plugins` | — |
| Dataset chip → Data | `#/data?mode=outputs&project=&version=` | project/version |
| Run success → Runs | `#/runs/{id}` + last-run strip | `run_id` |
| Pending chip → Proposals | `#/proposals` | — |

#### Acceptance checks

- **Given** a non-empty valid graph, **When** I click Run (Mode A), **Then** a run_id appears, last-run strip updates, and I can open Runs detail.
- **Given** empty canvas, **When** I look at Run, **Then** it is disabled and empty state offers Templates.
- **Given** empty catalog without token, **When** I open Builder, **Then** Open Settings is the primary CTA.
- **Given** Projects “Open in Builder”, **When** canvas loads, **Then** dataset chip shows project/version and clears without breaking the graph.

---

### 2.2 Templates (`#/templates`) — *n8n workflow library / Edge Impulse starter*

**One-job statement:** I expect to start from a known-good graph (examples + saved) and open it in Builder — not re-author IR from scratch.

#### Mode A / Mode B

Same UI. Mode B only matters after I Run a template that needs GPU placement.

#### Widgets / UI elements

| Element | Expected behavior |
|---|---|
| **PageHeader** (shipped) | “Starter graphs and saved pipelines…” |
| **Refresh** (shipped) | Reloads list. |
| **Sync examples** (shipped) | Copies repo examples; shows Syncing…; banner if partial errors. |
| **Save from Builder** (shipped) | Expands name field → **Save** / **Upload** / **Cancel**. |
| **Filter pills** (shipped) | All / Examples / Saved with counts. |
| **Cards** (shipped) | Humanized name, Example chip, version select, overflow menu, **Open in Builder**, **Open Data** when inputs needed. |
| **Empty** (shipped) | “No templates” / “No example templates” → Sync examples. |
| **MISSING — I need** | Text search by name/description (All/Examples/Saved alone is not enough when the library grows). |
| **MISSING — I need** | Category tags on cards (wakeword, edge-deploy, distributed, …) matching industry template galleries. |

#### Links & transitions

| From | To | Context |
|---|---|---|
| Open in Builder | `#/builder` | Full IR |
| Open Data | `#/data?mode=inputs` (or label) | Template input hints |
| Save from Builder | stays / refresh | New saved card |

#### Acceptance checks

- **Given** Sync examples succeeds, **When** I filter Examples, **Then** I see starter cards and Open in Builder loads IR.
- **Given** a canvas graph, **When** I Save from Builder with a name, **Then** it appears under Saved.
- **Given** empty library, **When** I land here, **Then** Sync examples is the next click.

---

### 2.3 Proposals (`#/proposals`, `#/proposals?id=`) — *agentic human-in-the-loop*

**One-job statement:** I expect to review agent/API graph proposals here — Accept loads Builder; this is not a second Builder.

#### Mode A / Mode B

Same. Agents/MCP create proposals regardless of backend; execution mode applies after Accept → Run.

#### Widgets / UI elements

| Element | Expected behavior |
|---|---|
| **Status filter** (shipped) | Pending / accepted / rejected (and related). |
| **Refresh** (shipped) | Reloads; updates pending badge. |
| **List rows** (shipped) | Summary, status, proposed-by, time; select opens detail. |
| **Empty** (shipped) | “No proposals yet” — agents/MCP create them; CTA **Open Builder** + docs link. |
| **Detail** (shipped) | Summary, Diff summary (nodes/edges added/removed/changed), **Accept → Builder**, **Reject**. |
| **No diff / not found** (shipped) | Honest empty states. |
| **Deep link** (shipped) | `?id=` selects one. |
| **MISSING — I need** | Richer visual IR diff (side-by-side canvas) — P2; until then structured summary must stay truthful (“No structural diff”). |

#### Links & transitions

| From | To | Context |
|---|---|---|
| Accept | Builder | Proposed graph loaded |
| Reject | list | Status → rejected; badge decrements |
| Empty → Builder | `#/builder` | — |
| Sidebar badge | `#/proposals` | Pending filter preferred |

#### Acceptance checks

- **Given** a pending proposal, **When** I Accept, **Then** Builder opens with that graph and toast confirms.
- **Given** Reject, **When** confirmed, **Then** it leaves pending and audit can show the mutation (System).
- **Given** `#/proposals?id=…`, **When** I refresh, **Then** the same proposal is selected.

---

## 3. Observe

### 3.1 Runs (`#/runs`, `#/runs/{id}`) — *n8n Executions + Prefect run detail*

**One-job statement:** I expect execution ops here — status, logs, pause/cancel, open outputs — not full Trace dumps.

#### Mode A

List + detail for local runs. No worker placement chips (or empty). Stale RUNNING still possible after crash.

#### Mode B

Detail shows **Workers** chips from `distributed_node_workers` (`node → worker_id`). Stale runs may mean dead worker; Cancel stale run is critical.

#### Widgets / UI elements

| Element | Expected behavior |
|---|---|
| **List** (shipped) | Graph name (humanized) or “Pipeline”, StatusBadge, metric snippet, relative time, short run id. |
| **Stale chip** (shipped) | On long RUNNING; title explains zombie journal. |
| **Prev / Next** (shipped) | Pagination. |
| **Empty list** (shipped) | “No runs yet” → Open Builder / Browse Templates. |
| **Select a run empty** (shipped) | Open latest run / Open Builder. |
| **Detail header** (shipped) | Status, Stale RUNNING, progress, current node, worker chips (Mode B). |
| **Actions** (shipped) | View lineage, Browse artifacts, Compare, Projects, Data (outputs), Open in Builder, Pause, Resume, Cancel run / Cancel stale run (confirm), Delete run (confirm when terminal). |
| **Stale callout** (shipped) | Explains zombie; points to Cancel. |
| **Tabs** (shipped) | Logs / Debug / Checkpoints / Artifacts (files). |
| **Logs** (shipped) | Mono console; “No logs.”; errors highlighted. |
| **Debug** (shipped) | KeyValue; “No debug report.” |
| **Checkpoints** (shipped) | List → load samples JSON. |
| **Artifacts tab** (shipped) | Path, Latest badge, Use as latest, Download all, per-file Download + preview, Open in Artifacts, Trace lineage. |
| **MISSING — I need** | Filter list by status and graph name (draft P1; not in UI yet). |
| **MISSING — I need** | Never show a useless “Pipeline” label when graph_name exists in journal — prefer humanized name always. |

#### Links & transitions

| From | To | Context |
|---|---|---|
| List → detail | `#/runs/{id}` | `run_id` |
| View lineage | Trace | `run_id` |
| Browse artifacts / Open in Artifacts | Artifacts | `run_id` |
| Compare | Experiments | `run_id` seeded |
| Projects / Data | Projects / Data outputs | — |
| Open in Builder | Builder | Graph IR when resolvable |

#### Acceptance checks

- **Given** a completed run, **When** I open `#/runs/{id}`, **Then** logs/files load and lineage/artifacts links carry `run_id`.
- **Given** stale RUNNING, **When** I Cancel (confirm), **Then** status leaves running.
- **Given** Mode B placement map, **When** I open detail, **Then** I see node→worker chips.
- **Given** no runs, **When** I open Runs, **Then** CTAs point to Builder/Templates.

---

### 3.2 Trace (`#/trace?run_id=&artifact_id=`) — *accountability / Prefect asset lineage*

**One-job statement:** I expect one-hop backtrack: artifact → node → run → graph → worker — curated fields and deep links, not a raw JSON dump.

#### Mode A

Worker hop may be empty/local — say so honestly. Still show artifact/run/graph.

#### Mode B

Worker hop should name the worker_id when provenance has it; link to Workers.

#### Widgets / UI elements

| Element | Expected behavior |
|---|---|
| **Artifact ID / Run ID fields** (shipped) | Placeholders; optional paste fallback. |
| **Refresh / Clear** (shipped) | Reload chain; clear selection. |
| **Empty** (shipped) | “Start a backtrack” — pick run or artifact; CTAs **Open Runs** / **Open Artifacts** (no paste required if I came from them). |
| **Chain** (shipped) | Steps with curated fields; per-hop actions: Open Run, Open Artifacts, Open Builder, Open Workers as relevant. |
| **Lineage inputs** (shipped) | Upstream list with jump buttons; “No upstream inputs recorded.” |
| **MISSING — I need** | Prefer hiding raw UUID paste when navigated from Runs/Artifacts (fields prefilled + readonly-or-subtle). |

#### Links & transitions

| From | To | Context |
|---|---|---|
| Runs / Artifacts / last-run | Trace | `run_id` and/or `artifact_id` |
| Chain → Run | Runs detail | `run_id` |
| Chain → Artifacts | Artifacts | `run_id` / `artifact_id` |
| Chain → Builder | Builder | graph when available |
| Chain → Workers | Workers | Mode B |

#### Acceptance checks

- **Given** I click View lineage on a run, **When** Trace opens, **Then** chain loads for that `run_id` without me pasting.
- **Given** partial provenance, **When** hops are missing, **Then** I see honest “No details for this hop” — not a crash.
- **Given** Mode B worker in chain, **When** I click Workers, **Then** I land on Deploy → Workers.

---

### 3.3 Experiments (`#/experiments?run_id=a,b`) — *MLflow compare*

**One-job statement:** I expect to compare params/metrics across runs — MLflow-shaped, without pretending metrics exist when they don’t.

#### Mode A / Mode B

Same board. Metrics come from experiment_tracker / experiment.json regardless of where nodes ran.

#### Widgets / UI elements

| Element | Expected behavior |
|---|---|
| **Compare (N)** (shipped) | Enabled when 2–5 selected; runs compare API. |
| **Clear / Refresh** (shipped) | Clears compare result; reloads. |
| **Experiment sidebar** (shipped) | Named experiment buckets when present. |
| **Run table** (shipped) | Checkbox select, graph, status, created, Open, Trace lineage. |
| **Compare table** (shipped) | Side-by-side params & metrics; differing cells highlighted. |
| **Honest empty metrics** (shipped) | “No metrics recorded…” explains experiment.json / metrics.json need. |
| **Empty page** (shipped) | Open Runs / Open Builder. |
| **URL write-back** (shipped) | Selection in hash for share/refresh. |
| **MISSING — I need** | Charts (MLflow-style) — P2. |
| **MISSING — I need** | Header last-run Compare honesty when only one id (see chrome). |

#### Links & transitions

| From | To | Context |
|---|---|---|
| Runs Compare / last-run | Experiments | `run_id` list |
| Row Open | Runs | `run_id` |
| Trace lineage | Trace | `run_id` |

#### Acceptance checks

- **Given** ≥2 runs with metrics, **When** I Compare, **Then** params/metrics table highlights diffs.
- **Given** runs without metrics, **When** I Compare, **Then** I see the honest empty — not a fake chart.
- **Given** `#/experiments?run_id=a,b`, **When** I refresh, **Then** selection restores and auto-compare can run.

---

### 3.4 Artifacts (`#/artifacts?run_id=&artifact_id=`) — *MLflow Artifacts + Prefect artifacts*

**One-job statement:** I expect to browse / preview / download / replay outputs across runs — library, not a second Runs Files dump.

#### Mode A / Mode B

Same. Replay starts a new run locally or distributed per backend.

#### Widgets / UI elements

| Element | Expected behavior |
|---|---|
| **Filters** (shipped) | Run ID, Node, Type + **Apply**. |
| **List** (shipped) | Human node label, short run id, artifact type, id. |
| **Empty** (shipped) | Open Builder / Open Runs. |
| **Detail** (shipped) | Preview, **Download**, **Copy path**, **Replay**, **Trace lineage**, **Open run**, **Open in Builder**; “No linked run” when absent. |
| **Select empty** (shipped) | Open first artifact CTA when list non-empty. |
| **MISSING — I need** | Stronger human titles (model name / filename) when metadata exists — not only node type. |

#### Links & transitions

| From | To | Context |
|---|---|---|
| Runs / last-run | Artifacts | `run_id` |
| Trace lineage | Trace | `artifact_id` + `run_id` |
| Replay | new Run | new `run_id` |
| Open run | Runs | `run_id` |

#### Acceptance checks

- **Given** `run_id` from Runs, **When** Artifacts opens, **Then** list is filtered to that run.
- **Given** an artifact with path, **When** I Download / Copy path / Replay, **Then** each action toasts success or a clear error.
- **Given** Trace lineage, **When** clicked, **Then** Trace opens with artifact context.

---

## 4. Library

### 4.1 Plugins (`#/plugins`)

**One-job statement:** I expect to install node packs and see dependency progress so the Builder catalog fills — no silent 30s abort.

#### Mode A

Plugins install on this machine; catalog refresh is immediate for local backend.

#### Mode B

Control plane plugins ≠ worker plugins. **MISSING — I need** copy that Mode B workers must install the same packs they claim (link Getting Started Mode B) — today the page is control-plane-centric.

#### Widgets / UI elements

| Element | Expected behavior |
|---|---|
| **Install source** (shipped) | path / package / https / git+; optional SHA256; Upgrade if installed; **Install**. |
| **Search index** (shipped) | package name + Search; results Use / install. |
| **Installed list** (shipped) | Name, status, deps chips; Actions menu: Manage dependencies, Enable/Disable, Uninstall (confirm). |
| **Deps panel** (shipped) | Install required / optional; progress text while installing. |
| **Empty** (shipped) | “No plugins installed” → focus Install. |
| **No directory** (shipped) | Honest message to install from path/git/package. |
| **Toasts** (shipped) | Installing… / Installed / Enabled / Disabled / Uninstalled / errors. |
| **MISSING — I need** | After install, explicit “Builder catalog refreshed” confirmation (refreshCatalog is called — surface it). |

#### Links & transitions

| From | To | Context |
|---|---|---|
| Builder empty catalog | Plugins | — |
| After install | Builder | Catalog includes new nodes |

#### Acceptance checks

- **Given** a valid plugin source, **When** I Install, **Then** it appears under Installed and Builder catalog can list its nodes after refresh.
- **Given** optional deps, **When** I install them, **Then** I see progress — not a hung button with no feedback.
- **Given** Uninstall confirm, **When** done, **Then** nodes leave the catalog on next refresh.

---

### 4.2 Data (`#/data?mode=&project=&version=&label=`) — *Edge Impulse Data acquisition (filesystem)*

**One-job statement:** I expect files in / files out under `workspace/datasets/` — **not** project metadata (that’s Projects).

#### Mode A

Uploads and outputs on the same box / Docker mount. Paths must stay inside workspace (no “outside workspace” for normal mounts).

#### Mode B

Same filesystem API on the control plane workspace. Workers reading datasets need shared storage or copied inputs — **MISSING — I need** a one-line Mode B warning on Ingest/Outputs when backend is distributed.

#### Widgets / UI elements

| Element | Expected behavior |
|---|---|
| **Mode tabs** (shipped) | Inputs / Outputs / Ingest / Merge. |
| **Upload / Refresh** (shipped) | Header actions. |
| **First-run copy** (shipped) | Upload → Templates → run → Outputs / Projects. |
| **Inputs** (shipped) | Label list; Upload a file; open files; delete label (confirm); empty → Upload. |
| **Outputs** (shipped) | Projects + **version dirs**; Open project → Projects; delete version (confirm); empty CTAs: Upload audio, Create project, Open Projects, Browse Templates, Browse existing outputs. |
| **Ingest** (shipped) | URL textarea + Start URL ingest; HF repo + Start HF ingest; log stream (“No ingest events yet.”). |
| **Merge** (shipped) | Sources (`project:version,…`), target project/version, **Merge**; creates project.json + labels. |
| **Path recovery empty** (shipped) | “Dataset path reset” vs “No output datasets yet”. |
| **MISSING — I need** | Progress % for large uploads (toast alone is weak for big audio sets). |

#### Links & transitions

| From | To | Context |
|---|---|---|
| Upload success | Inputs | `label=uploads` (or chosen) |
| Open project | Projects | `project` (+ version) |
| Create project / Open Projects | Projects | — |
| Browse Templates | Templates | — |
| Merge success | Projects / Outputs | project + version |

#### Acceptance checks

- **Given** I Upload on Inputs, **When** complete, **Then** the label folder lists the file and toast names it.
- **Given** a pipeline wrote `output/{project}/v1`, **When** I open Outputs, **Then** I see that version only (not random non-version dirs as versions).
- **Given** Merge with valid sources, **When** I Merge, **Then** target appears and Projects can open it.

---

### 4.3 Projects (`#/projects?project=&tab=`) — *Edge Impulse project workspace*

**One-job statement:** I expect a dataset workspace over the same `output/{project}`: spec, versions, snapshots, lineage — not a second file browser.

#### Mode A / Mode B

Same. Versions appear only after pipelines/exports write them.

#### Widgets / UI elements

| Element | Expected behavior |
|---|---|
| **Create** (shipped) | Name → Create; draft `project.json`; versions:[] — copy says so. |
| **Browse files / Refresh** (shipped) | → Data outputs; reload. |
| **Empty** (shipped) | “No dataset projects” → Open Data. |
| **List + detail** (shipped) | Select project; status buttons; Browse files; **Open in Builder**; Experiments; **Use in Edge**; Rename; Clone; Delete (confirm). |
| **Tabs** (shipped) | Versions / Spec / Taxonomy / Contract / Snapshots / Diff / lineage. |
| **Versions** (shipped) | Version select; Load stats / samples; Restore version (confirm); empty → Templates / Builder / Data. |
| **Spec / Taxonomy / Contract** (shipped) | Editors + Save. |
| **Snapshots** (shipped) | Name + Create snapshot; Restore; empty “No snapshots”. |
| **Diff / lineage** (shipped) | Diff vs; **Open Trace** when `run_id`; **Open Artifacts**. |
| **MISSING — I need** | Open in Builder must always stamp `datasets/output/{project}` + `version_tag` when a version is selected — acceptance-critical. |

#### Links & transitions

| From | To | Context |
|---|---|---|
| Browse files | Data outputs | project/version |
| Open in Builder | Builder | IR path stamps + dataset chip |
| Use in Edge | Edge | project/version query |
| Experiments | Experiments | — |
| Open Trace | Trace | `run_id` when known |
| Data Merge / Outputs | Projects | project |

#### Acceptance checks

- **Given** Create “demo”, **When** I open Versions, **Then** I see “No versions yet” with Templates/Builder/Data CTAs — not an error.
- **Given** version v1 exists, **When** I Open in Builder, **Then** dataset chip shows demo/v1 and export path is stamped.
- **Given** lineage with run_id, **When** I Open Trace, **Then** Trace loads that run.

---

## 5. Deploy

### 5.1 Edge deploy (`#/edge?...`) — *Edge Impulse Deployment*

**One-job statement:** I expect to optimize + package a **trained model** for a device/runtime — not to manage distributed workers.

#### Mode A

Wizard runs the edge-deploy graph locally; download package from artifacts.

#### Mode B

Same packaging job may place optimizer nodes on GPU workers if IR says so — still Edge’s job, not Workers’ UI.

#### Widgets / UI elements

| Element | Expected behavior |
|---|---|
| **Stepper** (shipped) | Choose graph → Configure → Run → Download. |
| **Dataset chip / Open Data / Open Projects** (shipped) | Context only unless wiring is real. |
| **Step 1** (shipped) | Use edge template; Open Data/Projects; Browse Templates; empty “No graph selected”. |
| **Step 2 Configure** (shipped) | Model path, package target, quantization, optimizer backend, labels, package name; **Model path not found** warning + CTAs Templates/Builder/Artifacts. |
| **Step 3 Run** (shipped) | Start run-async; Open run; View lineage / artifacts; Back. |
| **Step 4 Download** (shipped) | Download package; Skip to download; Open run / Builder. |
| **MISSING — I need** | Full device flash / device feedback loop (vision P2) — until then, download-only is honest. |

#### Links & transitions

| From | To | Context |
|---|---|---|
| Projects Use in Edge | Edge | project/version |
| Missing model CTAs | Templates / Builder / Artifacts | — |
| Run started | Runs | `run_id` |
| View lineage | Trace | `run_id` |

#### Acceptance checks

- **Given** missing model path, **When** I configure, **Then** I see a clear warning and CTAs — no silent fail on Run.
- **Given** edge template + valid model, **When** I Run then Download, **Then** a package file downloads.
- **Given** I confuse Edge with Workers, **When** I read the page description, **Then** it points Workers for Mode B placement.

---

### 5.2 Workers (`#/workers`) — *orchestrator placement (Mode B)*

**One-job statement:** I expect to see registered distributed workers (labels, GPU, heartbeats) — not Edge flash.

#### Mode A

Empty state is success: “Local Mode A… needs no workers”; copyable `GRAPHYN_BACKEND=distributed` + worker start CLI; **Open System**; **Edge deploy instead**; docs link.

#### Mode B

Table of workers with auto-refresh ~15s; Stale after ~45s; labels/pool chips; GPU/VRAM; status; active jobs.

#### Widgets / UI elements

| Element | Expected behavior |
|---|---|
| **Refresh** (shipped) | Manual reload. |
| **Empty** (shipped) | Mode A copy + CopyableMono env/CLI + Open System + Edge deploy instead + Getting Started Mode B. |
| **Table** (shipped) | Worker, Status, Labels, GPU/VRAM, Last heartbeat; Stale chip; plugins subtitle. |
| **MISSING — I need** | Drain / disable worker action (ops) — P2. |
| **MISSING — I need** | Deep link from Trace worker hop highlighting that row. |

#### Links & transitions

| From | To | Context |
|---|---|---|
| Empty → System | `#/system` | health |
| Empty → Edge | `#/edge` | clarify packaging ≠ workers |
| Trace → Workers | `#/workers` | optional worker_id later |

#### Acceptance checks

- **Given** Mode A (no workers), **When** I open Workers, **Then** empty state explains local mode and does not look like an error.
- **Given** Mode B with a live worker, **When** I refresh, **Then** I see id, labels, heartbeat, and Stale only when heartbeat is old.
- **Given** I need packaging, **When** I click Edge deploy instead, **Then** I leave Workers for the wizard.

---

## 6. Admin

### 6.1 Secrets (`#/secrets`)

**One-job statement:** I expect named credentials for runs — never pasted into Graph IR.

#### Mode A / Mode B

Same store on control plane; workers must receive secrets via the platform — not via IR. **MISSING — I need** one sentence on the page that Mode B workers resolve secret names from the control plane (or document the limit).

#### Widgets / UI elements

| Element | Expected behavior |
|---|---|
| **Add form** (shipped) | Name (e.g. OPENAI_API_KEY), Value with show/hide, **Store secret**. |
| **List** (shipped) | Names only (values never shown after store); Delete with confirm. |
| **Empty** (shipped) | “No secrets stored” → Add a secret. |
| **Refresh** (shipped) | Reloads names. |
| **MISSING — I need** | Jump key / sidebar discoverability parity (help overlay lists System but not Secrets). |

#### Links & transitions

None required beyond Builder nodes referencing secret **names**.

#### Acceptance checks

- **Given** I store OPENAI_API_KEY, **When** list refreshes, **Then** I see the name only and toast says value not shown.
- **Given** Delete confirm, **When** done, **Then** the name disappears.

---

### 6.2 System (`#/system`)

**One-job statement:** I expect ops health, webhooks, audit, and safe cleanup — accountability for mutations.

#### Mode A / Mode B

Health/readiness reflect this API. Mode B: **MISSING — I need** readiness to surface distributed backend + worker count (or link Workers) so I don’t guess.

#### Widgets / UI elements

| Element | Expected behavior |
|---|---|
| **Health / Readiness cards** (shipped) | StatusBadge + facts + Raw JSON. |
| **Metrics** (shipped) | Summary line + Raw JSON when present. |
| **Audit table** (shipped) | When / Actor / Action / Resource; empty → Open Proposals. |
| **Projects pointer** (shipped) | Copy + Open Projects (no duplicate project UI). |
| **Webhooks** (shipped) | URL; checkboxes Pipeline complete / failed; Save; Test. |
| **Cleanup** (shipped) | Older than days; **Delete cache** / **Delete workspace artifacts** unchecked by default; Run cleanup… → type `CLEANUP` → Confirm cleanup / Cancel. Never deletes running runs; keeps latest by default; never examples/ or datasets/input. |
| **MISSING — I need** | Optional “reconcile abandoned runs” control (draft mentioned; not in UI). |
| **MISSING — I need** | Backend mode chip: LocalPython vs distributed. |

#### Links & transitions

| From | To | Context |
|---|---|---|
| Audit empty → Proposals | `#/proposals` | — |
| Projects CTA | `#/projects` | — |
| Workers empty → System | `#/system` | health |

#### Acceptance checks

- **Given** cleanup options unchecked, **When** I open Cleanup, **Then** nothing destructive is prechecked.
- **Given** I type CLEANUP, **When** I Confirm, **Then** finished journals older than N days are removed per options and toast summarizes.
- **Given** an accepted proposal, **When** I refresh Audit, **Then** an event row appears.

---

## 7. Cross-page transition matrix

| From → To | Must pass context | Notes |
|---|---|---|
| Templates → Builder | Full graph IR | Open in Builder |
| Projects → Builder | `output_dir=datasets/output/{project}`, `version_tag`, dataset chip | Open in Builder |
| Proposals Accept → Builder | Proposed graph | Toast + load |
| Builder Run → Runs | `run_id`, last-run strip | Deep link `#/runs/{id}` |
| Builder / Runs → Trace | `run_id` | View lineage / Lineage chip |
| Runs / last-run → Artifacts | `run_id` | Browse artifacts |
| Runs → Experiments | `run_id` (≥1; compare needs ≥2) | Compare |
| Artifacts → Trace | `artifact_id`, `run_id` | Trace lineage |
| Artifacts → Replay → Runs | new `run_id` | |
| Data Upload → Inputs | `label` | |
| Data Merge → Projects | project (+ version) | |
| Data / Projects Browse files | mode=outputs, project, version | Shared filesystem |
| Projects → Edge | project/version query | Use in Edge |
| Projects → Experiments | optional | |
| Edge Run → Runs / Trace / Artifacts | `run_id` | |
| Trace → Workers | — (Mode B) | Placement debug |
| Trace → Builder | graph when resolvable | |
| Plugins install → Builder catalog | refreshed nodes | |
| Chrome last-run → Run/Lineage/Artifacts/Compare/Projects | `run_id` where applicable | Compare honesty gap |
| Workers empty → System / Edge | — | Mode A education |
| System → Projects / Proposals | — | Pointers only |
| Boot 401 → Settings | token | |

---

## 8. Priority buckets (P0 / P1 / P2)

### P0 — I cannot use the product without these

- Data Inputs upload + Outputs browse (Docker-safe paths)
- Templates → Builder → Run → Runs detail (Mode A)
- Projects create + Open in Builder path stamps + dataset chip
- Trace / Artifacts from a run **without** pasting IDs
- Global Connected / Settings token / last-run strip basics
- Workers empty state honesty for Mode A (no false alarm)
- Destructive confirms (cancel/delete/cleanup CLEANUP)

### P1 — Makes it feel like MLflow / Edge Impulse / n8n Executions

- Experiments compare with real params/metrics when logged; honest empty otherwise
- Projects versions / snapshots / lineage ↔ Trace
- Edge wizard with honest model-missing state + download
- Runs filter by status/name + consistent human graph names
- Mode B: Runs worker chips + Workers live table + Builder placement fields visibility
- Last-run Compare chip honesty (≥2 or clear next step)
- Plugins deps progress + catalog refresh feedback
- Data Merge → Projects round-trip

### P2 — Polish / later

- Templates text search + category tags
- MLflow-style experiment charts
- HF ingest label polish
- Full Edge device flash / device feedback
- Workers drain/disable; Trace→worker row highlight
- System reconcile abandoned runs; backend mode chip
- Secrets jump key; richer proposal IR diff canvas
- RBAC / promotion / environments (vision — out of this console pass)
- OTel spans across workers

---

## 9. Out of scope for this requirements pass

- Implementing the above in UI code
- CloudAgent / automated coding agents applying these changes
- FaceRecognition product surface
- Inventing promotion / RBAC UIs beyond noting them as vision gaps
- Replacing Kubernetes or becoming a generic chat LLM product

---

## 10. Source map (for reviewers)

| Console area | Primary source |
|---|---|
| NAV, chrome, jump keys, Settings | `graphyn-ui/src/App.tsx`, `components/KeyboardHelp.tsx` |
| Builder | `features/builder/BuilderView.tsx` (+ GraphynNode, DeletableEdge) |
| Templates / Proposals | `features/templates/*`, `features/proposals/*` |
| Runs / Trace / Experiments / Artifacts | `features/runs/*`, `trace/*`, `experiments/*`, `artifacts/*` |
| Plugins / Data / Projects | `features/plugins/*`, `data/*`, `projects/*` |
| Edge / Workers | `features/edge/*`, `features/workers/*` |
| Secrets / System | `features/secrets/*`, `features/system/*` |
| Mode A/B | `docs/GETTING_STARTED.md`, `docs/DISTRIBUTED_EXECUTION.md` |
| Vision | `docs/PRODUCT_VISION.md` |
