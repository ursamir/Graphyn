# Graphyn UI — Requirements Matrix

> Source of truth for enterprise console completeness.  
> Status: `DONE` | `PARTIAL` | `MISSING` | `N/A`  
> Updated: 2026-07-29 (hardening pass complete for P0/P1)

## Legend

| Column | Meaning |
|---|---|
| Req | Requirement ID |
| FE | Implemented in `graphyn-ui/` |
| BE | Backend `/api/v1` exists |
| Notes | Gap / follow-up |

---

## A. Platform shell & security

| Req | Requirement | FE | BE | Notes |
|---|---|---|---|---|
| A1 | Graphyn brand / domain-agnostic product shell | DONE | N/A | |
| A2 | Navigation: Builder, Runs, Artifacts, Plugins, Templates, Data, Projects, System | DONE | N/A | |
| A3 | API base URL configurable (`VITE_API_BASE_URL`) | DONE | N/A | |
| A4 | Bearer token auth on all API calls | DONE | DONE | Client injection |
| A5 | Token settings UI (persist locally) | DONE | N/A | Settings modal |
| A6 | Typed API errors (status, detail, path) | DONE | DONE | `ApiError` |
| A7 | Request timeout + AbortController support | DONE | N/A | |
| A8 | Retry safe GETs with backoff | DONE | N/A | |
| A9 | `X-Request-ID` correlation header | DONE | N/A | CORS allows it |
| A10 | Global toast / status messaging | DONE | N/A | |
| A11 | Empty / loading / error states on every view | DONE | N/A | |
| A12 | Deep-linkable routes (`/runs/:id` etc.) | DONE | N/A | Hash routes `#/runs/:id` |
| A13 | Error boundary | DONE | N/A | |

---

## B. Builder (Graph IR)

| Req | Requirement | FE | BE | Notes |
|---|---|---|---|---|
| B1 | Load node catalog | DONE | DONE | `GET /nodes` |
| B2 | Add/remove nodes, connect edges (DAG fan-in/out) | DONE | DONE | Multi-edge allowed |
| B3 | Multi-port handles from port schema | PARTIAL | DONE | Dynamic handles when ports known |
| B4 | Port compatibility hints | PARTIAL | DONE | Soft-check via `/nodes/compatible` |
| B5 | Full config form from JSON Schema | PARTIAL | DONE | Schema-driven editors; advanced widgets deferred |
| B6 | Per-node `validate-config` | DONE | DONE | |
| B7 | Validate whole graph (IR) | DONE | DONE | |
| B8 | Run streaming NDJSON | DONE | DONE | |
| B9 | Cancel in-flight run | DONE | N/A | AbortController |
| B10 | Async run + follow in Runs | DONE | DONE | `POST /pipelines/run-async` |
| B11 | Import / export `.graph.json` | DONE | N/A | |
| B12 | Persist layout positions in export | DONE | DONE | GraphIR `ui.positions` (not `parameters`) |
| B13 | Save canvas as versioned template | DONE | DONE | |
| B14 | Clear canvas with confirm | DONE | N/A | |

---

## C. Runs

| Req | Requirement | FE | BE | Notes |
|---|---|---|---|---|
| C1 | List runs (paginated) | DONE | DONE | limit/offset |
| C2 | Run detail (meta + logs) | DONE | DONE | |
| C3 | Live status / progress | DONE | DONE | `GET .../status` poll |
| C4 | Pause / resume / cancel | DONE | DONE | Status-gated |
| C5 | Debug report | DONE | DONE | |
| C6 | Checkpoints list + samples | DONE | DONE | |
| C7 | Run artifacts | DONE | DONE | |
| C8 | Run provenance | DONE | DONE | |
| C9 | Jump from Builder lastRunId | DONE | N/A | |

---

## D. Artifacts

| Req | Requirement | FE | BE | Notes |
|---|---|---|---|---|
| D1 | List + filter run_id / node_type / artifact_type | DONE | DONE | |
| D2 | Detail | DONE | DONE | |
| D3 | Lineage | DONE | DONE | |
| D4 | Replay → open new run | DONE | DONE | Navigates to Runs |

---

## E. Plugins

| Req | Requirement | FE | BE | Notes |
|---|---|---|---|---|
| E1 | List installed | DONE | DONE | |
| E2 | Search index | DONE | DONE | |
| E3 | Install (local/remote) | DONE | DONE | |
| E4 | Poll async install job | DONE | DONE | |
| E5 | Enable / disable / uninstall with errors | DONE | DONE | |
| E6 | Refresh node catalog after change | DONE | N/A | |
| E7 | Upgrade + expected_sha256 | DONE | DONE | |

---

## F. Templates

| Req | Requirement | FE | BE | Notes |
|---|---|---|---|---|
| F1 | List + latest version | DONE | DONE | |
| F2 | Version picker | DONE | DONE | |
| F3 | Load into Builder | DONE | DONE | |
| F4 | Upload IR file | DONE | DONE | |
| F5 | Save from Builder | DONE | DONE | |
| F7 | Import examples as templates (1 example → 1 template) | DONE | DONE | Canonical graph per example folder; shards pruned |

---

## G. Data

| Req | Requirement | FE | BE | Notes |
|---|---|---|---|---|
| G1 | Browse outputs / inputs | DONE | DONE | |
| G2 | Output stats | DONE | DONE | |
| G3 | Authenticated file open/preview | DONE | DONE | Blob fetch + auth |
| G4 | Upload input audio/files | DONE | DONE | multipart |
| G5 | Merge datasets | DONE | DONE | |
| G6 | URL / HF ingest + SSE | DONE | DONE | Auth-aware stream fallback |

---

## H. Projects

| Req | Requirement | FE | BE | Notes |
|---|---|---|---|---|
| H1 | List / create | DONE | DONE | |
| H2 | Rename / delete / clone / status | DONE | DONE | |
| H3 | Spec view + edit | DONE | DONE | |
| H4 | Taxonomy / contract view+edit | DONE | DONE | JSON editors |
| H5 | Versions list + stats + samples | DONE | DONE | |
| H6 | Restore version | DONE | DONE | |
| H7 | Snapshots create/list/restore | DONE | DONE | |
| H8 | Diff / lineage | DONE | DONE | |
| H9 | Annotations / quality / curation suite | PARTIAL | DONE | Deferred P2 UX; APIs exist |

---

## I. System

| Req | Requirement | FE | BE | Notes |
|---|---|---|---|---|
| I1 | Health / readiness badges | DONE | DONE | |
| I2 | Metrics snapshot | DONE | DONE | |
| I3 | Webhooks get/put/test | DONE | DONE | |
| I4 | Cleanup with toggles | DONE | DONE | cache + artifacts flags |
| I5 | Projects registry search | DONE | DONE | |

---

## Backend gaps found during mapping

| Gap | Action |
|---|---|
| No missing core endpoints for mapped P0/P1 UI | None required |
| CORS already allows `Authorization`, `X-Request-ID` | Confirmed in `app/api/main.py` |
| Static mounts need Bearer when token set | FE uses authenticated blob fetch |

## Deferred (P2 domain packs)

- Full annotation workspace (waveform-centric)
- Quality dashboard / export-gate UX
- Curation queue UX  

These remain optional domain modules; APIs already exist under `/projects/*`.
