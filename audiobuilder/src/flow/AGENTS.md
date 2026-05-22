# audiobuilder/src/flow/ — React Flow Canvas Components

## Files
| File | Purpose |
|------|---------|
| `FlowCanvas.tsx` | Main React Flow canvas — nodes, edges, drag-drop, SSE status updates, undo/redo |
| `FlowCanvasWrapper.tsx` | Thin wrapper that provides ReactFlowProvider |
| `BaseNode.tsx` | Node card component — field rendering, validation tooltips, status indicators |
| `NodePalette.tsx` | Left sidebar — categorized node list with search, collapse state persisted to localStorage |
| `TemplateLibrary.tsx` | Modal — lists templates, loads YAML into canvas, delete user templates |
| `HelpSidebar.tsx` | Right slide-in panel — node reference, auto-highlights selected node |

## FlowCanvas Imperative Handle
`FlowCanvas` exposes these methods via `React.forwardRef` + `useImperativeHandle`:
```tsx
{
  clearCanvas(): void
  loadYAML(yaml: string, schemas: Record<string, unknown>): void
  resetNodeStatuses(): void
  updateNodeStatus(nodeId: string, status: "idle"|"running"|"success"|"error", errorMsg?: string): void
  getNodeIndexMap(edges: Edge[]): Map<number, string>
}
```

## Node Status Flow
1. Before run: `resetNodeStatuses()` → all nodes idle
2. SSE `node_start` event → `updateNodeStatus(id, "running")`
3. SSE `node_end` event → `updateNodeStatus(id, "success")`
4. SSE `node_error` event → `updateNodeStatus(id, "error", message)`

## BaseNode Field Types
Supported `type` values in schema: `"number"`, `"string"`, `"array"`, `"boolean"`
Array fields render as comma-separated input (e.g. `[min, max]` for gain ranges).
