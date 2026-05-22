---
inclusion: fileMatch
fileMatchPattern: "audiobuilder/src/flow/**,audiobuilder/src/store/**,audiobuilder/src/utils/**,audiobuilder/src/App.tsx,audiobuilder/src/main.tsx"
---

# Frontend — Canvas, Store, and Pipeline Execution

You are editing the pipeline canvas, global state, or utility layer.

## Stack

React 18 + TypeScript + Vite + ReactFlow + Zustand + Tailwind CSS.
API base: `VITE_API_BASE_URL` env var (default `http://localhost:8001`). All endpoints under `/api/v1/`.

## Global State: `usePipelineStore` (`store/pipeline.ts`)

| Field | Type | Purpose |
|---|---|---|
| `selectedNodeId` | `string \| null` | Selected canvas node |
| `selectedNodeType` | `string \| null` | Type of selected node |
| `logs` | `LogEntry[]` | Execution log entries |
| `isRunning` | `boolean` | Pipeline executing |
| `error` | `string \| null` | Current error |
| `seed` | `number` | Pipeline seed (default 42) |
| `nodeConfigs` | `Record<string, Record<string, unknown>>` | Per-node config by node ID |
| `flowNodes` | `FlowNode[]` | Canvas nodes snapshot |
| `flowEdges` | `FlowEdge[]` | Canvas edges snapshot |
| `activeProject` | `string \| null` | Active project name |
| `lastRunId` | `string \| null` | Most recent run ID |

## App.tsx — Tab Navigation

Seven views via `view` state: `pipeline`, `projects`, `datasets`, `annotation`, `quality`, `runs`, `registry`.

## Pipeline Execution (`handleRunPipeline`)

1. Read `flowNodes`, `flowEdges`, `nodeConfigs` from store
2. `generateYAML()` → YAML string
3. `POST /api/v1/pipelines/run`
4. Read NDJSON line-by-line, dispatch events:
   - `pipeline_start` → set `totalNodes`
   - `node_start` → node status `"running"`, update progress
   - `node_end` → node status `"success"`, record duration for ETA
   - `node_error` → node status `"error"`
   - `done` → complete, set `lastRunId`
5. Browser `Notification` on completion/failure

## FlowCanvas.tsx — Imperative API (via `canvasRef`)

| Method | Description |
|---|---|
| `clearCanvas()` | Remove all nodes/edges, clear configs |
| `loadYAML(yaml, schemas)` | Parse YAML, create nodes, chain edges |
| `resetNodeStatuses()` | Set all nodes to `"idle"` |
| `updateNodeStatus(nodeId, status, errorMsg?)` | Update visual status |
| `getNodeIndexMap(edges)` | `Map<nodeIndex, nodeId>` for event routing |

Node placement on YAML load: `{x: 200, y: 80 + i * 140}` (vertical stack).

## Connection Validation

On connect: checks `source.output_type === target.input_type`. Incompatible connections silently blocked. During drag: nodes highlight compatible/incompatible via `draggingOutputType`.

## YAML Generation (`utils/yaml.ts`)

`generateYAML(nodes, edges, configs, seed)`:
1. Validate all nodes have type + config
2. Build adjacency map from edges
3. Validate: no cycles, single start node, no multi-in/multi-out
4. Topological sort (linear chain only)
5. Normalize config values: numeric strings → numbers, `"true"`/`"false"` → booleans
6. Serialize with `js-yaml`

**Always produces linear format.** DAG format must be written manually and loaded via "Load Pipeline".

## API Helper (`utils/api.ts`)

`apiUrl(path, query?)` — constructs full URLs from `API_BASE_URL`. Skips null/undefined/empty query params.

## Autosave (`hooks/useAutosave.ts`)

Saves `{nodes, edges, configs, seed}` to `localStorage["audiobuilder_canvas_autosave"]` after 5s inactivity. Only when `nodes.length > 0`. On mount, `App.tsx` checks for saved state and shows restore prompt.

## Keyboard Shortcuts (`hooks/useKeyboardShortcuts.ts`)

| Shortcut | Action |
|---|---|
| `Ctrl/Cmd+S` | Save pipeline (download YAML) |
| `Ctrl/Cmd+F` | Focus node search |
| `Ctrl/Cmd+Enter` | Run pipeline |
| `Ctrl/Cmd+Z` / `+Shift+Z` | Undo / Redo |

## Build

```bash
# from audiobuilder/
npm run dev      # Vite dev server
npm run build    # → audiobuilder/dist/
npm run lint     # ESLint
```
