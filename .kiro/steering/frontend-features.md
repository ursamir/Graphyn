---
inclusion: fileMatch
fileMatchPattern: "graphyn-ui/src/features/**"
---

# Frontend — Platform feature screens

`graphyn-ui` feature modules map 1:1 to backend surfaces. Coverage source of truth: console map in `docs/PRODUCT_VISION.md` and this steering file.

| Feature | Path | Backend |
|---|---|---|
| Builder | `features/builder/` | `/nodes`, validate-config, `/pipelines/validate|run|run-async`, templates save |
| Runs | `features/runs/` | `/runs`, status poll, pause/resume/cancel, checkpoints, artifacts, provenance, debug-report |
| Artifacts | `features/artifacts/` | `/artifacts`, lineage, replay → open run |
| Plugins | `features/plugins/` | install/search/enable/disable/uninstall + dependency status / install-deps + catalog refresh |
| Templates | `features/templates/` | `/pipelines/templates` (+ versions); **Import all examples** → `POST .../sync-examples`. Verify with `scripts/verify_templates.py`. |
| Data | `features/data/` | inputs/outputs/stats, upload, merge, `/ingest/*` SSE (auth-aware) |
| Projects | `features/projects/` | CRUD lifecycle, taxonomy/contract/spec, versions/stats/samples/restore, snapshots, diff/lineage |
| System | `features/system/` | health/readiness/metrics/webhooks/cleanup toggles/projects-registry; audit panel |
| Trace | `features/trace/` | `/trace`, `/audit` |
| Experiments | `features/experiments/` | `/experiments`, `/compare` |
| Proposals | `features/proposals/` | `/proposals` (+ accept/reject) |
| Edge | `features/edge/` | edge-deploy wizard → run-async |
| Workers | `features/workers/` | `/workers` list + stale badge |
| Secrets | `features/secrets/` | secrets CRUD |

## Shell (`App.tsx`)

- Nav IA: **Build** (Builder, Templates, Proposals, Runs) · **Observe** (Trace, Experiments, Artifacts) · **Library** (Plugins, Data) · **Deploy** (Edge, Workers) · **Admin** (Projects, Secrets, System)
- Hash routes: `#/`, `#/templates`, `#/proposals`, `#/runs/:id`, `#/trace`, `#/experiments`, `#/edge`, `#/workers`, …
- Settings: Bearer token → `localStorage` `graphyn_api_token` (auto-opens on catalog 401)
- Global `ToastHost` + `ErrorBoundary`; catalog refresh after plugin mutations and after saving the token

## Rules

- Prefer `apiJson()` / `apiFetch()` / `fetchAuthenticatedBlobUrl()` from `src/api/client.ts`.
- Do not reintroduce audio-first branding or YAML-primary pipeline flows.
- Domain packs (annotation, quality, curation) remain P2 optional modules; APIs already under `/projects/*`.
