---
inclusion: fileMatch
fileMatchPattern: "audiobuilder/src/features/**,audiobuilder/src/hooks/**,audiobuilder/src/components/**"
---

# Frontend — Feature Modules, Hooks, and Components

You are editing a feature module, hook, or shared component.

## Feature Modules (`src/features/`)

### `projects/ProjectManager.tsx`
Full project lifecycle: create, rename, delete, clone, set status.
Tabs: Spec, Taxonomy, Contract, Versions, Annotations (→ AnnotationUI), Quality, Curation.
API: `/api/v1/projects/*`

### `datasets/DatasetManager.tsx`
Browse output datasets. Audio files with waveform preview (wavesurfer.js). Filter by split and label.
API: `GET /api/v1/data/outputs`, `GET /api/v1/data/inputs`

### `quality/QualityDashboard.tsx`
Quality check findings. Sub-tabs: Quality Checks, Statistics, Curation Queue.
Includes `ExportGateBanner` (blocking issues) and `QualityReportExport` (download report).

### `runs/RunHistory.tsx`
Table of past runs, newest first. Click → config YAML + logs. "Re-run" loads config back into canvas.
API: `GET /api/v1/runs`, `GET /api/v1/runs/{run_id}`

### `runs/CheckpointPreview.tsx`
Shown after a run completes (`lastRunId` set). Lists checkpoints per node with waveform audio player.
API: `GET /api/v1/runs/{run_id}/checkpoints`, `GET /api/v1/runs/{run_id}/checkpoints/{node_id}/samples`

### `annotation/AnnotationUI.tsx`
Audio annotation: label samples, add time-range annotations, bulk annotation.

### `registry/DatasetRegistry.tsx`
Searchable/filterable project list. "Open" navigates to Projects tab with project pre-selected.
API: `GET /api/v1/system/projects-registry`

## Hooks (`src/hooks/`)

### `useAutosave.ts`
`useAutosave({ nodes, edges, configs, seed })` — debounced (5s) save to `localStorage["audiobuilder_canvas_autosave"]`. Only saves when `nodes.length > 0`.

### `useKeyboardShortcuts.ts`
Registers `keydown` on `window`. Handles Ctrl/Cmd+S, F, Enter, Z, Shift+Z.

### `usePreferences.ts`
Persists to `localStorage["audiobuilder_preferences"]`:
- `theme`: `"dark" | "light" | "system"`
- `nodePaletteCollapsed`: per-category collapse state
- `recentProjects`: last 5 project names
- `logViewerFilters`: level, nodeFilter, searchText

## Shared Components (`src/components/`)

`Alert`, `Button`, `Card`, `Input`, `LoadingSpinner`, `LogViewer`, `Select`, `ThemeToggle` — all exported from `components/index.ts`.

Use these primitives for new UI. Do not introduce new component libraries.

## Key API Calls by Feature

| Feature | Endpoints used |
|---|---|
| Canvas startup | `GET /api/v1/nodes` (load schemas) |
| Run pipeline | `POST /api/v1/pipelines/run` (NDJSON stream) |
| Templates | `GET/POST/DELETE /api/v1/pipelines/templates/*` |
| Run history | `GET /api/v1/runs`, `GET /api/v1/runs/{id}` |
| Checkpoints | `GET /api/v1/runs/{id}/checkpoints/*` |
| Datasets | `GET /api/v1/data/inputs`, `GET /api/v1/data/outputs` |
| Upload | `POST /api/v1/data/inputs/upload` |
| Projects | `/api/v1/projects/*` |
| Registry | `GET /api/v1/system/projects-registry` |
| Health | `GET /api/v1/system/health` |
