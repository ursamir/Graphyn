---
inclusion: fileMatch
fileMatchPattern: "graphyn-ui/src/features/builder/**,graphyn-ui/src/store/**,graphyn-ui/src/api/**,graphyn-ui/src/types/**,graphyn-ui/src/App.tsx,graphyn-ui/src/main.tsx"
---

# Frontend — Graphyn Builder (Canvas + IR)

Platform console for typed DAG workflows. Product identity is **Graphyn**, not audio-only tooling.

## Stack

React + TypeScript + Vite + React Flow + Zustand + Tailwind.
API: Vite proxy `/api` → `:8001`, or `VITE_API_BASE_URL` (default `/api/v1`).

## Views (App shell)

`builder` | `runs` | `artifacts` | `plugins` | `templates` | `data` | `projects` | `system`

## Builder

- Node catalog from `GET /api/v1/nodes` (refreshed after plugin changes).
- Multi-port handles, validate-config, soft compatibility check.
- Canvas → Graph IR; layout in `ui.positions` (not under `parameters`).
- Validate / stream run / cancel / run-async; save as template.
- Import/export `.graph.json` only (no YAML-first path).

## Shell

- Hash deep-links `#/view` and `#/runs/:id`.
- Settings: Bearer token (`graphyn_api_token`).
- `ToastHost` + `ErrorBoundary`. Client: timeout, GET retry, `X-Request-ID`, `ApiError`.

## Store (`useAppStore`)

`view`, `focusRunId`/`openRun`, `catalog`/`refreshCatalog`, `seed`, `logs`, `isRunning`, `lastRunId`, `statusMessage`, `toasts`, `getCanvasGraph`, `pendingGraph` / `loadGraphIntoBuilder` (Templates → Builder handoff; Builder is unmounted off-tab so window events are lost).
