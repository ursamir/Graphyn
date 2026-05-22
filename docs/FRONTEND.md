# Frontend — Detailed Reference - Deprecated (new frontend is yet to build)

**Stack:** React 18 + TypeScript + Vite + ReactFlow + Zustand + Tailwind CSS  
**Entry point:** `audiobuilder/src/main.tsx`  
**API base URL:** `VITE_API_BASE_URL` env var (defaults to `http://localhost:8001`)

> **API note:** All backend endpoints are under `/api/v1/`. The old root-path endpoints (`/schemas`, `/runs`, `/validate`, `/run-stream`, etc.) no longer exist. The frontend's `apiUrl()` helper constructs full URLs using `API_BASE_URL`.

---

## Application Structure

```
audiobuilder/src/
├── main.tsx                    # React root, wraps App in ReactFlowProvider
├── App.tsx                     # Root component
├── store/pipeline.ts           # Zustand global state
├── flow/                       # Pipeline canvas
│   ├── FlowCanvas.tsx          # ReactFlow canvas + node palette
│   ├── FlowCanvasWrapper.tsx   # Thin wrapper around FlowCanvas
│   ├── BaseNode.tsx            # Custom ReactFlow node renderer
│   ├── NodePalette.tsx         # Draggable node list (left panel)
│   ├── TemplateLibrary.tsx     # Template browser modal
│   ├── SaveTemplateDialog.tsx  # Save-as-template dialog
│   └── HelpSidebar.tsx         # Node reference sidebar
├── features/
│   ├── projects/               # Project management UI
│   ├── datasets/               # Dataset browser UI
│   ├── quality/                # Quality dashboard UI
│   ├── runs/                   # Run history + checkpoint preview
│   ├── annotation/             # Annotation UI
│   └── registry/               # Dataset registry UI
├── components/                 # Shared UI primitives
│   ├── Alert.tsx
│   ├── Button.tsx
│   ├── Card.tsx
│   ├── Input.tsx
│   ├── LoadingSpinner.tsx
│   ├── LogViewer.tsx
│   ├── Select.tsx
│   ├── ThemeToggle.tsx
│   └── index.ts
├── hooks/
│   ├── useAutosave.ts          # Debounced localStorage autosave
│   ├── useKeyboardShortcuts.ts # Global keyboard shortcut registration
│   └── usePreferences.ts       # Persistent user preferences
└── utils/
    ├── api.ts                  # apiUrl() helper, API_BASE_URL constant
    ├── yaml.ts                 # generateYAML() — canvas → YAML string
    ├── pipelineFile.ts         # downloadYAML(), openYAMLFile()
    └── cn.ts                   # Tailwind class merging utility
```

---

## Global State: `usePipelineStore`

**File:** `audiobuilder/src/store/pipeline.ts`  
**Library:** Zustand

| State Field | Type | Purpose |
|---|---|---|
| `selectedNodeId` | `string \| null` | Currently selected node on canvas |
| `selectedNodeType` | `string \| null` | Node type of selected node |
| `logs` | `LogEntry[]` | Execution log entries for LogViewer |
| `isRunning` | `boolean` | Pipeline execution in progress |
| `error` | `string \| null` | Current error message |
| `seed` | `number` | Pipeline random seed (default: 42) |
| `nodeConfigs` | `Record<string, Record<string, unknown>>` | Per-node configuration keyed by node ID |
| `flowNodes` | `FlowNode[]` | Snapshot of canvas nodes (synced from FlowCanvas) |
| `flowEdges` | `FlowEdge[]` | Snapshot of canvas edges (synced from FlowCanvas) |
| `activeProject` | `string \| null` | Currently active project name |
| `lastRunId` | `string \| null` | Run ID of the most recent execution |

---

## App.tsx — Root Component

`App.tsx` is the single-page application shell. It manages:

### Tab Navigation

Seven views rendered via a `view` state variable:
- `pipeline` — FlowCanvas + LogViewer
- `projects` — ProjectManager
- `datasets` — DatasetManager
- `annotation` — AnnotationUI
- `quality` — QualityDashboard
- `runs` — RunHistory
- `registry` — DatasetRegistry

### Pipeline Execution Flow (`handleRunPipeline`)

1. Reads `flowNodes`, `flowEdges`, `nodeConfigs` from store
2. Calls `generateYAML()` to build YAML string
3. POSTs to `POST /api/v1/pipelines/run`
4. Reads NDJSON response line-by-line
5. Dispatches structured events:
   - `pipeline_start` → sets `totalNodes` for progress bar
   - `node_start` → updates node visual status to "running", updates progress bar
   - `node_end` → updates node visual status to "success", records duration for ETA
   - `node_error` → updates node visual status to "error"
   - `done` → marks stream complete
6. Shows browser `Notification` on completion or failure (if permission granted)
7. Sets `lastRunId` to enable CheckpointPreview

### Other Handlers

- `handleSavePipeline` — generates YAML and triggers browser download
- `handleLoadPipeline` — opens file picker, loads YAML into canvas
- `handleClearCanvas` — clears canvas after confirmation dialog
- `handleValidatePipeline` — POSTs to `POST /api/v1/pipelines/validate`, shows result in log
- `handleAutosaveRestore` / `handleAutosaveDismiss` — manages autosave restore prompt

### Autosave

On mount (after schemas load), checks `localStorage["audiobuilder_canvas_autosave"]`. If non-empty nodes exist, shows a restore prompt banner.

### Keyboard Shortcuts

Registered via `useKeyboardShortcuts`:
- `Ctrl/Cmd+S` → save pipeline
- `Ctrl/Cmd+F` → focus node search
- `Ctrl/Cmd+Enter` → run pipeline

---

## FlowCanvas.tsx

**File:** `audiobuilder/src/flow/FlowCanvas.tsx`

ReactFlow-based canvas. Exposed to `App.tsx` via `React.forwardRef` + `useImperativeHandle`.

### Imperative API (via `canvasRef`)

| Method | Description |
|---|---|
| `clearCanvas()` | Remove all nodes and edges, clear node configs |
| `loadYAML(yaml, schemas)` | Parse YAML, create nodes with default+loaded configs, chain edges |
| `resetNodeStatuses()` | Set all nodes to `status: "idle"` |
| `updateNodeStatus(nodeId, status, errorMsg?)` | Update a node's visual status |
| `getNodeIndexMap(edges)` | Build `Map<nodeIndex, nodeId>` for event routing |

### Node Placement

When loading YAML, nodes are placed at `{x: 200, y: 80 + i * 140}` — a vertical stack. Drag-and-drop places nodes at the cursor position.

### Connection Validation

When connecting two nodes, the canvas checks `source.output_type === target.input_type`. Incompatible connections are silently blocked. During a drag, nodes highlight as compatible/incompatible based on `draggingOutputType`.

### Autosave Integration

`useAutosave({ nodes, edges, configs, seed })` is called with current canvas state. Saves to `localStorage["audiobuilder_canvas_autosave"]` after 5 seconds of inactivity.

### State Sync

Canvas state is synced to the Zustand store via `setFlowState()` on every change (debounced by snapshot comparison).

---

## YAML Generation: `generateYAML()`

**File:** `audiobuilder/src/utils/yaml.ts`

Converts canvas state to a pipeline YAML string:
1. Validates all nodes have a type and config
2. Builds adjacency map from edges
3. Validates: no cycles, single start node, no multi-in/multi-out nodes
4. Topologically sorts nodes (linear chain only)
5. Normalizes config values: numeric strings → numbers, `"true"`/`"false"` → booleans
6. Serializes with `js-yaml`

The frontend always generates the linear YAML format. DAG format pipelines must be written manually.

---

## API Integration

**File:** `audiobuilder/src/utils/api.ts`

`apiUrl(path, query?)` constructs full URLs using `API_BASE_URL` (from `VITE_API_BASE_URL` env var, defaulting to `http://localhost:8001`). Handles query parameter serialization, skipping null/undefined/empty values.

Key API calls made by the frontend:

| Action | Endpoint |
|---|---|
| Load node schemas on startup | `GET /api/v1/nodes` |
| Run pipeline (streaming) | `POST /api/v1/pipelines/run` |
| Validate pipeline | `POST /api/v1/pipelines/validate` |
| List templates | `GET /api/v1/pipelines/templates` |
| Get template | `GET /api/v1/pipelines/templates/{name}` |
| Save template | `POST /api/v1/pipelines/templates` |
| List runs | `GET /api/v1/runs` |
| Get run | `GET /api/v1/runs/{run_id}` |
| List checkpoints | `GET /api/v1/runs/{run_id}/checkpoints` |
| List input datasets | `GET /api/v1/data/inputs` |
| List output datasets | `GET /api/v1/data/outputs` |
| Upload file | `POST /api/v1/data/inputs/upload` |
| Health check | `GET /api/v1/system/health` |

---

## Feature Modules

### `features/projects/ProjectManager.tsx`

Full project lifecycle UI: create, rename, delete, clone, set status. Tabs: Spec, Taxonomy, Contract, Versions, Annotations (via AnnotationUI), Quality, Curation.

### `features/datasets/DatasetManager.tsx`

Browse output datasets. Shows audio files with waveform preview (wavesurfer.js). Supports filtering by split and label.

### `features/quality/QualityDashboard.tsx`

Displays quality check findings. Sub-tabs: Quality Checks, Statistics, Curation Queue. Includes `ExportGateBanner` (shows blocking issues), `QualityReportExport` (download report), charts.

### `features/runs/RunHistory.tsx`

Table of past pipeline runs. Clicking a run shows config YAML and logs. "Re-run" button loads the config back into the canvas.

### `features/runs/CheckpointPreview.tsx`

Shown in the pipeline view after a run completes. Lists checkpoints per node, shows sample audio with waveform player. Fetches from `GET /api/v1/runs/{run_id}/checkpoints`.

### `features/annotation/AnnotationUI.tsx`

Audio annotation interface. Allows labeling samples, adding time-range annotations, bulk annotation.

### `features/registry/DatasetRegistry.tsx`

Searchable/filterable list of all projects. "Open" button navigates to the Projects tab with the selected project pre-selected.

---

## Hooks

### `useAutosave`

Debounced (5s) save of `{nodes, edges, configs, seed}` to `localStorage["audiobuilder_canvas_autosave"]`. Only saves when `nodes.length > 0`.

### `useKeyboardShortcuts`

Registers `keydown` listener on `window`. Handles Ctrl/Cmd+S, F, Enter, Z, Shift+Z.

### `usePreferences`

Persists user preferences to `localStorage["audiobuilder_preferences"]`:
- `theme`: `"dark" | "light" | "system"`
- `nodePaletteCollapsed`: per-category collapse state
- `recentProjects`: last 5 project names
- `logViewerFilters`: level, nodeFilter, searchText
