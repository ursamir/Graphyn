# Checklist — Tech stack (full review)

| Field | Value |
|---|---|
| Tip | `6978329f529c59567fdfa4397c5bea5a6b1c9099` (F18.1). There are no dependency or compose changes since `d7f5d70`, the tip of the F18 checklist. |
| Supersedes | `docs/reviews/F18_TECH_STACK_CHECKLIST.md`. All TS-API/WRK/QSL/PER/AUTH/CRY/FE/TST/OBS/OPS IDs carry over unchanged. This file adds results for the ones exercised and new sections TS-RT, TS-PLG, TS-TPL, TS-MCP, TS-CLI, TS-EGR, TS-UI2, TS-DOC. |
| Honesty rule | A partial, stubbed, docs-only or fake-data item scores **Fail**. **Unverified** means it was not exercised in this review, and it gets no credit. |
| Stack | Python 3.12 (image python:3.12-slim), FastAPI 0.115.6, Uvicorn 0.32.1, Pydantic 2.10.6, httpx, cryptography; SQLite under GRAPHYN_HOME; file/Redis state store for Mode B; React 19 / Vite 8 / TS ~6 / Zustand 5 / React Router 7 / React Flow 11 / Tailwind 3.4; MCP `mcp==1.27.0`; CI `.github/workflows/ci.yml`. |

## Results for carried-over F18 IDs that were exercised

| ID | Result | Evidence |
|---|---|---|
| TS-API-01 | Pass | Live OpenAPI: 214 paths / 259 operations under `/api/v1`, 27 router files |
| TS-API-02 | Pass | An empty or bad bearer gets 401 with a JSON `detail` |
| TS-API-06 | **Fail** | `/app/BUILD_INFO.json` has `"git_sha": null`, and run meta has `git_commit: null`. The image was built without `GRAPHYN_GIT_SHA`. |
| TS-WRK-01/02 | **Fail (live)** | The overlay is defined, but the running API was not started with `docker-compose.modeb.yml`. The worker container is up, but it can't reach the control plane (DNS) and `GET /workers` returns `[]`. |
| TS-WRK-03 | **Fail** | `app/core/distributed/transfer.py:229-244` assigns `root` only inside `except`, so the normal path raises UnboundLocalError. The 8 tests in test_distributed_transfer fail. |
| TS-WRK-04/05/06 | Pass (unit) | Claim/lease/fencing unit tests pass (test_distributed_p2, registry_mutate). They were not exercised live. |
| TS-AUTH-* | Partial | Bearer auth is enforced, but runs record `actor: unidentified` / `legacy_token`. The legacy token is still enabled (`legacy_token_disabled:false`). OIDC is disabled. |
| TS-CRY-* | Pass (partial check) | Credentials list returns no values. Secrets and credentials dirs are 0700. Per-file modes were not audited. |
| TS-TST-* | **Fail** | pytest has 195 failed and 307 errors. The declared UI `npm test` (also run by CI) fails to resolve `vitest/config`. |
| TS-OBS-* | Partial | Provenance, debug-report and compare work. `experiments/compare` returns no metrics. |
| TS-OPS-* | Partial | `/health` and `/system/readiness` are separate. Readiness counts stale workers (`worker_count:1` while there are 0 live, `app/core/host/readiness.py:229`). |

## TS-RT — Runtime / execution

| ID | Statement | How to verify | Pass criteria | Result |
|---|---|---|---|---|
| TS-RT-01 | All execution goes through `get_backend().execute()` | grep the run entry points; run any graph | Single entry point; meta records the backend | Pass |
| TS-RT-02 | IR 1.2/1.3 validation, with a required seed | POST validate with and without `metadata.seed` | Missing seed gets 422; 1.3 `on_error`/`retry` are accepted | Pass |
| TS-RT-03 | Node-level retry actually retries | IR 1.3 `retry.max_attempts=2` on a failing node | Logs show attempt 2/2 | Pass (run f6e79faf) |
| TS-RT-04 | `on_error` route sends the failure to the error port | IR 1.3 `on_error:{mode:route}` plus error_catch | Run succeeds via the error branch | Pass (d6630a0e) |
| TS-RT-05 | Pause, resume and cancel follow the state machine | `/runs/{id}/pause|resume|cancel` | Status transitions are correct; cancel is terminal | Pass |
| TS-RT-06 | Replay and verify are reproducible | `/runs/{id}/replay`, `/verify` | A new run is created and verify passes | Pass (7aedc1c0) |
| TS-RT-07 | HITL gate pauses at `awaiting_approval` and resumes on decision | hitl_approve plus the decision API | Status flips and the run completes | Pass (bd929e4f) |
| TS-RT-08 | Inter-node payload contract: wrapped results are consumable downstream | python_code → set_map/if_switch/prompt_template | Downstream sees `data` | **Fail**: CodeResult isn't unwrapped by 9 nodes |
| TS-RT-09 | Run metadata has build provenance | run meta `git_commit` | Non-null | **Fail** |
| TS-RT-10 | Mode B materialization of ArtifactRef inputs | unit tests plus a live run of ex29 with a worker | Inputs materialize on the worker | **Fail** (transfer.py:244) |

## TS-PLG — Plugin platform

| ID | Statement | How to verify | Pass criteria | Result |
|---|---|---|---|---|
| TS-PLG-01 | Every enabled plugin loads and registers its node types | `GET /nodes` against the allowlist | 35 plugins → 36 types, no load errors | Pass |
| TS-PLG-02 | Manifest completeness (name, version, entry_points, node_types, runtime, deps) | parse every plugin.toml | All keys present | **Fail**: 8 manifests have no `runtime` |
| TS-PLG-03 | Isolated plugins run in their own venv | check `/data/graphyn-home/plugins/venvs`; run trainer | Venv exists; the run succeeds | Pass |
| TS-PLG-04 | Ports are typed; wiring is type-checked | inspect port types | Domain types, not `object`/`list` | **Fail**: Audio uses `builtins.list` and Common/Agents use `object` |
| TS-PLG-05 | No stub backend reports success | run edge_optimizer tflm and deployment_packager cmsis_pack | The run fails or is flagged | **Fail** (50daf859) |
| TS-PLG-06 | Credential kinds are bound by `connection_id`; values never surface | credential_probe ollama/smtp | Works; output is redacted | Pass |
| TS-PLG-07 | Each plugin has at least one unit test | grep unit_test for the node type | ≥1 per node | **Fail**: credential_probe has 0 |
| TS-PLG-08 | Plugin dependencies are declared and covered | `scripts/check_deps.py` | OK | Pass (15 install_requires covered) |

## TS-TPL — Templates

| ID | Statement | How to verify | Pass criteria | Result |
|---|---|---|---|---|
| TS-TPL-01 | Shipped file templates validate against the live registry | POST validate for all 129 | ≥95% valid | **Fail**: 58/129 (45%) |
| TS-TPL-02 | Marketplace catalog entries validate | materialize and validate all 3,032 | ≥95% (the repo's own test gate) | **Fail**: 112/3,032 (3.7%) |
| TS-TPL-03 | `runnable` flags are honest | `GET /pipelines/templates` | Templates with missing types are flagged | Pass (16 flagged runnable=false) |
| TS-TPL-04 | Runnable families execute end to end | run the representative templates | Run succeeds | Pass for 17 runs; see SWEEP_TEMPLATES |

## TS-MCP / TS-CLI

| ID | Statement | How to verify | Pass criteria | Result |
|---|---|---|---|---|
| TS-MCP-01 | The MCP stdio server starts and lists its tools | `graphyn mcp` with tools/list | Count matches the docs | Partial: 79 live; README says 77 |
| TS-MCP-02 | MCP tool calls work | call `list_nodes` | Returns the registry | Pass |
| TS-MCP-03 | MCP errors are structured `{error_type,message}` | call with bad args | Structured error | Unverified |
| TS-CLI-01 | CLI commands are present and documented | `graphyn --help` | Commands match the docs | Pass (13 commands, incl. `users`) |
| TS-CLI-02 | `--help` is fast and doesn't boot plugins | time `--help` | <1 s, no plugin load | **Fail**: it loads the plugin manager first |
| TS-CLI-03 | The CLI registry matches the deployed registry | `graphyn nodes` on the host vs `GET /nodes` | Same set | **Fail**: host 48 (stale ~/.graphyn) vs live 36 |

## TS-EGR — Egress / SSRF

| ID | Statement | How to verify | Pass criteria | Result |
|---|---|---|---|---|
| TS-EGR-01 | Workflow HTTP nodes block loopback, link-local and metadata destinations by default | http_request to 127.0.0.1:8001 and 169.254.169.254 | Blocked before connect | **Fail**: default `GRAPHYN_HTTP_EGRESS_MODE=trusted` (`app/core/config.py:609`) |
| TS-EGR-02 | Restricted mode plus allowlist is available | config/egress code | Present | Pass (code); not exercised |
| TS-EGR-03 | Redirects are re-validated | http_webhook code | Redirects refused or re-checked | Pass (code, `http_webhook/nodes.py:137,166`) |

## TS-UI2 — Frontend build and test

| ID | Statement | How to verify | Pass criteria | Result |
|---|---|---|---|---|
| TS-UI2-01 | `npm test` runs as declared, as CI does | `npm test` in graphyn-ui | Exit 0 | **Fail**: vitest isn't in devDependencies |
| TS-UI2-02 | The unit tests pass | vitest via the workaround config | All pass | Pass (528/528, 260 suites) |
| TS-UI2-03 | Type check is clean | `tsc --noEmit` | Exit 0 | Pass |
| TS-UI2-04 | SPA fallback and the /api proxy work | curl :5173/workspaces and :5173/api/... | 200 / 401 unauthenticated | Pass |
| TS-UI2-05 | No unroutable declared routes | `src/routes/paths.ts` | None typed `never` | **Fail**: 4 typed `never` |

## TS-DOC — Docs vs reality

| ID | Statement | How to verify | Pass criteria | Result |
|---|---|---|---|---|
| TS-DOC-01 | Node-type counts in docs match the registry | NODES.md, PluginPackage/ARCHITECTURE.md, AGENTS.md, PLUGIN_GUIDE | Equal to the live count of 36 | **Fail**: 49 / 156 / 48 |
| TS-DOC-02 | MCP tool count is consistent | README vs MCP_SERVER.md vs live | All equal | **Fail**: 77 vs 79 |
| TS-DOC-03 | ENTERPRISE_READINESS status is accurate | compare with the tests and Mode B | "Done / tests green / Available" are true | **Fail** |
| TS-DOC-04 | Stub backends and targets are disclosed in node descriptions | `GET /nodes` descriptions | Says "stub" | **Fail** for deployment_packager targets |
