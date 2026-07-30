# Graphyn UI

Domain-agnostic visual console for the Graphyn platform.

## What it is

Not an audio-only builder. First-class surfaces for:

| View | Backend coverage |
|---|---|
| **Builder** | Node catalog, Graph IR canvas, validate, run stream, import/export IR |
| **Runs** | List, detail, pause/resume/cancel, debug-report |
| **Artifacts** | List/filter, detail, lineage, replay |
| **Plugins** | List, search, install, enable/disable, uninstall |
| **Templates** | Versioned Graph IR templates |
| **Data** | `/data/inputs` + `/data/outputs` browser |
| **Projects** | Project list/create + versions/spec |
| **System** | Health, readiness, metrics, webhooks, cleanup |

## Start

```bash
# API (repo root)
venv/bin/uvicorn app.api.main:app --reload --port 8001

# UI
cd graphyn-ui
npm install
npm run dev
```

Open `http://127.0.0.1:5173`

Vite proxies `/api`, `/files`, `/input-files`, `/run-files` to `http://127.0.0.1:8001`.

Optional: `VITE_API_BASE_URL=http://127.0.0.1:8001/api/v1`

## Design notes

- Graph IR is the only pipeline language in the UI (no YAML-first flow).
- Domain packs (audio annotation, quality gates, etc.) belong as plugins / optional modules — not the product identity.
