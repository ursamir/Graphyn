# Checklist — Requirements & logic

Tip `6978329f529c59567fdfa4397c5bea5a6b1c9099` · 2026-10-08 IST. Source: `docs/REQUIREMENTS_SPEC.md` (4955 lines; 339 ID rows, 330 unique IDs; P0/P1 below), `docs/ENTERPRISE_READINESS.md`, logical invariants. Supersedes `docs/reviews/F18_REQUIREMENTS_LOGICAL_CHECKLIST.md`.

Status legend: **PASS (live)** = exercised on the live stack or by passing tests in this review · **PARTIAL** = works with a documented gap · **FAIL** = contradicted by live run or failing test · **UNVERIFIED** = not exercised; per the honesty rule this is *not* credit for implementation.

Traceability: only 17 of 339 requirement rows are referenced by ID anywhere in `app/`, `graphyn-ui/src`, `PluginPackage/` or `unit_test/`. There is no requirement→test matrix in the repo.

## Counts (unique P0/P1 IDs)

| Status | Count |
|---|---|
| UNVERIFIED | 224 |
| PASS (live) | 41 |
| PARTIAL | 27 |
| FAIL (live/test) | 7 |

| Priority | PASS | PARTIAL | FAIL | UNVERIFIED |
|---|---|---|---|---|
| P0 | 39 | 22 | 7 | 135 |
| P1 | 2 | 5 | 0 | 89 |

## How to verify (generic)

- UI rows (FR-*, UX-*, NFR-A11Y/BRW): manual click-through on :5173 with a non-admin token + vitest component tests. Pass = behaviour visible, no console errors.
- Runtime rows (RT-*): build a minimal IR, `POST /api/v1/pipelines/run`, inspect `GET /runs/{id}` + run dir. Pass = state/artifacts match the statement.
- Distributed rows (DIST-*, RT-CRASH-003): bring up `docker-compose.modeb.yml` overlay, confirm worker in `GET /workers`, run ex29. Pass = node→worker map populated, artifacts materialize.
- Security rows (SEC-*, THREAT-*): negative tests (traversal, SSRF to 127.0.0.1/169.254.169.254, secret in IR, unauthenticated call). Pass = blocked with 4xx and no side effect.
- OPS rows: documented procedure exists + dry-run executes. Pass = doc present and command succeeds without data loss.

## ENTERPRISE_READINESS claims vs reality

| Claim | Reality | Status |
|---|---|---|
| Mode B self-host "Available" | ArtifactRef materialization raises UnboundLocalError (transfer.py:229-244, F15 commit a1c5952); live worker not registered; 20 distributed tests fail | FAIL |
| Waves 1–6 + F18 "Done", exit criteria "tests green" | pytest: 195 failed / 307 errors (452 from removed plugins not pruned, 27 real regressions) | FAIL |
| Credentials store + connection binding | connection_id resolution live for ollama/smtp; values never returned | PASS |
| Model registry prod gate | request→approve enforced, direct prod 403; but no separation of duties (same actor) | PARTIAL |
| Ship/edge packaging | tflite/edge/mcu work; 7 backend/targets are stubs that report success | PARTIAL |
| HITL approvals | awaiting_approval + API decision works | PASS |
| Egress controls | restricted mode exists but default is trusted (no SSRF block for workflow nodes) | PARTIAL (FAIL vs THREAT-008) |

## Logical invariants

| ID | Invariant | How verified | Result |
|---|---|---|---|
| INV-01 | A run that writes a stub file must not report success for that backend | edge_optimizer tflm, deployment_packager cmsis_pack (50daf859) | **FAIL** — run succeeded with BACKEND_STUB.txt / PACKAGE_STUB.txt |
| INV-02 | Output of node A is consumable by node B when ports are wired (`object` ports) | python_code → set_map/if_switch/prompt_template | **FAIL** — CodeResult wrapper not unwrapped |
| INV-03 | A write node either writes or fails | object_store put of dict | **FAIL** — silent [] |
| INV-04 | Delete API either deletes or returns 4xx | DELETE /projects/{p}/pipelines/{x} | **FAIL** — 500 ImportError (projects.py:1050) |
| INV-05 | Requester ≠ approver for prod promotion | request-prod then approve-prod same token | **FAIL** |
| INV-06 | Readiness worker_count agrees with GET /workers | live | **FAIL** — 1 vs [] (stale counted) |
| INV-07 | Ship package runtime matches artifact format | runtime=tflite, model.keras packaged | **FAIL** |
| INV-08 | Cancel is terminal and immediate | 85c16d3c | PASS |
| INV-09 | Replay produces a new run with same graph hash; verify passes | 7aedc1c0 + verify | PASS |
| INV-10 | Secret values never appear in IR, list responses or node outputs | secret_in_ir 422; credentials list; credential_probe redacted | PASS |
| INV-11 | Default provider of an "LLM" node is an LLM | llm_chat provider=local default echoes input | **FAIL** (labelling) |
| INV-12 | Docs counts match registry (node types, MCP tools, packs) | NODES.md 49 / AGENTS.md 156 manifests & 9 packs / README 77 MCP tools vs live 36 / 35 / 79 | **FAIL** |
| INV-13 | Retry policy actually retries | f6e79faf logs attempt 2/2 | PASS |
| INV-14 | Experiments compare shows metrics recorded on runs | experiments compare | **FAIL** — metric_keys [] |

## Per requirement (P0/P1)

| ID | Pri | SRS line | Section | Statement | Status | Evidence |
|---|---|---|---|---|---|---|
| SM-001 | P0 | 177 | 5.2 Success metrics (measurable) | Time to first successful run via Templates | PARTIAL | Templates stamp+run in <10 min for runnable families (ex01 3e8f2410, 35 s) but 71/129 file templates and 96% of catalog invalid on this branch |
| SM-002 | P0 | 178 | 5.2 Success metrics (measurable) | Artifact → graph Trace | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SM-003 | P0 | 179 | 5.2 Success metrics (measurable) | Opens same run lineage (path URL, no hash) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SM-004 | P0 | 180 | 5.2 Success metrics (measurable) | 100% via Models UI when APIs available | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SM-005 | P1 | 181 | 5.2 Success metrics (measurable) | Agent proposal → saved pipeline | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SM-006 | P1 | 182 | 5.2 Success metrics (measurable) | Always-on failure → failed run | UNVERIFIED | always-on schedule failure path not exercised |
| SM-007 | P0 | 183 | 5.2 Success metrics (measurable) | E2E smoke login → run → lineage path | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SM-008 | P0 | 184 | 5.2 Success metrics (measurable) | Completable by human **and** MCP agent without leaving Graphyn | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| API-FORBID-001 | P0 | 790 | 9.0.1 Error envelope schema | Returning secret **values** in any list/get response | PASS (live) | GET /credentials returns names+meta only (api_checks.credentials_list) |
| API-FORBID-002 | P0 | 791 | 9.0.1 Error envelope schema | Echoing submitted secret values in 422 `input` fields on secrets routes | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| API-FORBID-003 | P0 | 792 | 9.0.1 Error envelope schema | Silent empty list when index is corrupted (must 503 or quarantine error) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| API-FORBID-004 | P0 | 793 | 9.0.1 Error envelope schema | Accepting Graph IR that embeds non-empty secret-shaped config keys | PASS (live) | IR with secret-shaped config rejected 422 secret_in_ir during guardrail smoke |
| API-FORBID-005 | P0 | 794 | 9.0.1 Error envelope schema | Committing new artifacts for a run after cancel is acknowledged | PARTIAL | run_journal guard exists (code ref); cancel run 85c16d3c went cancelled immediately; artifact-after-cancel not stress-tested |
| API-FORBID-006 | P0 | 795 | 9.0.1 Error envelope schema | Claiming a job without CAS / lease fencing | PARTIAL | claim CAS unit tests in distributed suite pass; Mode B live down |
| API-FORBID-007 | P0 | 796 | 9.0.1 Error envelope schema | Cross-tenant data via path traversal (`../`) | PASS (live) | run-id traversal (../) -> 404 |
| FR-AUTH-001 | P0 | 3382 | 11.1 Auth, token, actor | Unauthenticated users **shall** be directed to `/login` or Settings with `returnTo` when API returns 401 | PARTIAL | UI /login route exists; vitest covers; no manual click-through |
| FR-AUTH-002 | P0 | 3383 | 11.1 Auth, token, actor | Console **shall** store API Bearer token (Settings); values **shall not** appear in URLs or Graph IR | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-AUTH-003 | P0 | 3384 | 11.1 Auth, token, actor | When token set, API **shall** require Bearer; fail-closed when auth required / prod\ | PASS (live) | empty/bad bearer -> 401; GRAPHYN_AUTH_REQUIRED=1 in compose |
| FR-AUTH-004 | P1 | 3385 | 11.1 Auth, token, actor | Mutations **shall** accept `X-Actor`; console **shall** allow editing actor (Access / localStorage) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-AUTH-005 | P0 | 3386 | 11.1 Auth, token, actor | Auth honesty banner **shall** distinguish Connected / Sign in required / Can't reach API | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| UX-STATE-001 | P0 | 3393 | 11.2 Errors, empty, loading | Every primary surface **shall** define loading, empty, and error states (no blank white) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| UX-STATE-002 | P0 | 3394 | 11.2 Errors, empty, loading | Empty states **shall** offer a next-click CTA | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| UX-STATE-003 | P0 | 3395 | 11.2 Errors, empty, loading | Destructive actions **shall** require confirm (armed button / typed CLEANUP for cleanup) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| UX-STATE-004 | P0 | 3396 | 11.2 Errors, empty, loading | Toasts **shall** cover success/error/info; dismissible | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| UX-STATE-005 | P1 | 3397 | 11.2 Errors, empty, loading | Per-route error boundary **should** provide recovery CTA | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| UX-STATE-006 | P1 | 3398 | 11.2 Errors, empty, loading | Offline / API-down **should** show retry wall | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| UX-STATE-007 | P1 | 3399 | 11.2 Errors, empty, loading | 404 and 403 pages (resource missing vs forbidden) **should** exist | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ROUTE-001 | P0 | 3405 | 11.3 Routing & deep links | Deep links **shall** survive refresh for workspace, run, panel, proposal, artifact query | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ROUTE-002 | P0 | 3406 | 11.3 Routing & deep links | Cross-links **shall** pass context (`run_id`, workspace, artifact_id) — users **shall not** re-paste IDs for primary flows | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ROUTE-003 | P0 | 3407 | 11.3 Routing & deep links | URL **shall** be source of truth for workspace id; store mirrors URL | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ROUTE-004 | P1 | 3408 | 11.3 Routing & deep links | Copy-link **should** exist on run, model, proposal, lineage | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ROUTE-005 | P1 | 3409 | 11.3 Routing & deep links | Open-in-new-tab **shall** work for primary resources | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-CMDK-001 | P1 | 3415 | 11.4 Command palette & shortcuts | ⌘/Ctrl+K (and `/` where scoped) **shall** open Command palette | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-CMDK-002 | P1 | 3416 | 11.4 Command palette & shortcuts | Jump keys **shall** match sidebar destinations (incl. Secrets, Models, Access) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-CMDK-003 | P1 | 3417 | 11.4 Command palette & shortcuts | `?` **shall** open keyboard help overlay; Esc closes | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-LOGIN-001 | P0 | 3453 | 12.1 Login (`/login`) | System **shall** provide token input and Continue that persists token client-side | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-LOGIN-002 | P1 | 3454 | 12.1 Login (`/login`) | After save, system **should** verify token (readiness/nodes) before claiming success | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-LOGIN-004 | P1 | 3456 | 12.1 Login (`/login`) | 401 remediation **may** use Settings drawer; `/login` **shall** remain a valid path | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-HOME-001 | P0 | 3475 | 12.2 Workspaces picker & Home (`/workspa | User **shall** create, open, filter (mine/examples), rename, clone, delete workspaces | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-HOME-002 | P0 | 3476 | 12.2 Workspaces picker & Home (`/workspa | Home **shall** list pipelines with draft/staging/prod and open Editor | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-HOME-003 | P0 | 3477 | 12.2 Workspaces picker & Home (`/workspa | User **shall** Publish→staging, Request prod, Approve prod, Rollback draft when APIs allow | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-HOME-004 | P0 | 3478 | 12.2 Workspaces picker & Home (`/workspa | Home **shall** show recent runs scoped by workspace and open run detail | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-HOME-005 | P1 | 3479 | 12.2 Workspaces picker & Home (`/workspa | Home **shall** show Always-on schedules with Run now + link to Ops | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-HOME-006 | P0 | 3480 | 12.2 Workspaces picker & Home (`/workspa | User **shall** link/unlink dataset inputs; Browse library/Artifacts | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-HOME-008 | P1 | 3482 | 12.2 Workspaces picker & Home (`/workspa | Spec/taxonomy/contract/versions/snapshots/diff **shall** remain available (collapsed OK) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-HOME-009 | P1 | 3483 | 12.2 Workspaces picker & Home (`/workspa | Situation strip **should** show Mode, last run, pending proposals, always-on count, failed schedule | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-HOME-010 | P1 | 3484 | 12.2 Workspaces picker & Home (`/workspa | Partial API failure on Home load **shall not** silently blank successful sections | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ED-001 | P0 | 3502 | 12.3 Editor (`/workspaces/:id/editor…`) | Canvas **shall** add/wire nodes from catalog with typed ports, config from schema, zoom/pan | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ED-002 | P0 | 3503 | 12.3 Editor (`/workspaces/:id/editor…`) | Validate **shall** surface errors; Run disabled on empty canvas | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ED-003 | P0 | 3504 | 12.3 Editor (`/workspaces/:id/editor…`) | Run **shall** stream events (NDJSON); Cancel **shall** cancel backend run and abort stream | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ED-004 | P0 | 3505 | 12.3 Editor (`/workspaces/:id/editor…`) | Save to workspace pipeline **shall** persist Graph IR | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ED-005 | P0 | 3506 | 12.3 Editor (`/workspaces/:id/editor…`) | Import/export graph and save-as-template **shall** work | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ED-006 | P1 | 3507 | 12.3 Editor (`/workspaces/:id/editor…`) | Triggers dock **shall** manage schedules for current pipeline and show webhook honesty | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ED-007 | P1 | 3508 | 12.3 Editor (`/workspaces/:id/editor…`) | Agent drawer **shall** create proposals into Agent inbox | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ED-008 | P1 | 3509 | 12.3 Editor (`/workspaces/:id/editor…`) | Credential picker **shall** select secret **names** only | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ED-009 | P1 | 3510 | 12.3 Editor (`/workspaces/:id/editor…`) | Mode A **shall** show placement-ignored badge; Mode B **shall** expose placement fields | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ED-010 | P0 | 3511 | 12.3 Editor (`/workspaces/:id/editor…`) | Load/save **shall** preserve edge conditions, event triggers, labels, graph parameters | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ED-011 | P1 | 3512 | 12.3 Editor (`/workspaces/:id/editor…`) | Dirty Editor **should** block route leave with confirm | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-RUN-001 | P0 | 3531 | 12.4 Runs — History / Live / Compare + p | History **shall** list runs (workspace-scoped) with status, time, id, filters | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-RUN-002 | P0 | 3532 | 12.4 Runs — History / Live / Compare + p | Detail **shall** support Pause / Resume / Cancel (stale-aware) / Delete terminal | PASS (live) | API pause/resume (d134aff8) + cancel (85c16d3c) verified; UI buttons not clicked |
| FR-RUN-003 | P0 | 3533 | 12.4 Runs — History / Live / Compare + p | Panels **shall** include Logs, Outputs, Lineage, Details/Debug, Checkpoints | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-RUN-004 | P1 | 3534 | 12.4 Runs — History / Live / Compare + p | Live **shall** poll running/pending with node/worker visibility | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-RUN-005 | P1 | 3535 | 12.4 Runs — History / Live / Compare + p | Compare **shall** select 2–5 runs; params/metrics table; honest empty metrics; charts/CSV when available | PARTIAL | runs compare/diff works; /experiments/compare returns metric_keys [] although metrics_by_path has test_accuracy (app/core/mlops/experiments.py:133,289) |
| FR-RUN-006 | P1 | 3536 | 12.4 Runs — History / Live / Compare + p | Promote aliases and Register model **shall** be available from succeeded runs | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-RUN-007 | P1 | 3537 | 12.4 Runs — History / Live / Compare + p | Mode B **shall** show `node → worker` chips when placement map exists | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-RUN-008 | P1 | 3538 | 12.4 Runs — History / Live / Compare + p | Explain/fix failure **shall** create an agent proposal | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-RUN-009 | P0 | 3539 | 12.4 Runs — History / Live / Compare + p | Lineage panel **shall** show hop chain, graph hash/plugin versions header, repro pack (lite OK) | PARTIAL | provenance + graph endpoints return lineage; git_commit null in meta (image built w/o GRAPHYN_GIT_SHA) |
| FR-RUN-010 | P0 | 3540 | 12.4 Runs — History / Live / Compare + p | Standalone Trace as strip peer **shall not** be required; run lineage path is canonical | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-RUN-011 | P1 | 3541 | 12.4 Runs — History / Live / Compare + p | Error `detail` objects from run control **should** surface precise messages | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-RUN-012 | P1 | 3542 | 12.4 Runs — History / Live / Compare + p | History **should** support multi-select affordance before Compare | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-MOD-001 | P0 | 3557 | 12.5 Models (`/workspaces/:id/models`) | List/filter models; show stages latest/staging/prod and pending_prod | PASS (live) | model register/get works (review-full-kws-2026-10-08) |
| FR-MOD-002 | P0 | 3558 | 12.5 Models (`/workspaces/:id/models`) | Request prod / Approve prod **shall** call registry APIs from UI | PARTIAL | request-prod/approve-prod work, but same actor can request and approve (no separation of duties) - model_registry.py:534-560 |
| FR-MOD-003 | P0 | 3559 | 12.5 Models (`/workspaces/:id/models`) | Register model from run id/slug **shall** work | PASS (live) | register from run verified (api_checks.model_register) |
| FR-MOD-004 | P1 | 3560 | 12.5 Models (`/workspaces/:id/models`) | Model card **shall** deep-link Trace/run and **should** link datasets | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-MOD-005 | P1 | 3561 | 12.5 Models (`/workspaces/:id/models`) | Use in Ship CTA **should** prefill package wizard | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-MOD-006 | P1 | 3562 | 12.5 Models (`/workspaces/:id/models`) | Workspace scope vs all-registries **shall** be clear | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-SHIP-001 | P0 | 3575 | 12.6 Ship (+ Devices) | Package wizard **shall** support template → configure → run-async → download | PARTIAL | ship create works (pkg-8095716b4433) via API; runtime "tflite" packaged model.keras without format validation; unsigned by default (ship.py:77) |
| FR-SHIP-002 | P0 | 3576 | 12.6 Ship (+ Devices) | Missing model path **shall** warn with CTAs (Templates/Editor/Artifacts) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-SHIP-003 | P1 | 3577 | 12.6 Ship (+ Devices) | Devices **shall** exist; Devices **may** be needs-API stub | PARTIAL | Devices view exists; libraryArtifacts/libraryModels/deployShip/deployShipDevices route builders typed `never` in src/routes/paths.ts |
| FR-SHIP-004 | P1 | 3578 | 12.6 Ship (+ Devices) | Auto-pick model from registry **should** work | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-SHIP-005 | P1 | 3579 | 12.6 Ship (+ Devices) | Package diagnostics + lineage bar **shall** link source run | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-DATA-001 | P0 | 3596 | 12.7 Datasets | Browse Inputs/Outputs; Manage Upload/Ingest/Merge | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-DATA-002 | P0 | 3597 | 12.7 Datasets | Paths **shall** stay jailed inside workspace | PASS (live) | csv_table rejects path outside workspace; run-id traversal 404 |
| FR-DATA-003 | P1 | 3598 | 12.7 Datasets | Merge **shall** create target workspace/version consumable by Home | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-DATA-004 | P1 | 3599 | 12.7 Datasets | Ingest (URL/HF) **shall** show progress/log; SSE when available | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-DATA-007 | P1 | 3602 | 12.7 Datasets | Workspace Datasets **should** CTA “Browse shared library” → `/library/datasets` | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-TPL-001 | P0 | 3614 | 12.8 Templates (`/templates`) | List Examples/Saved; search; sync examples; stamp into workspace | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-TPL-002 | P0 | 3615 | 12.8 Templates (`/templates`) | Without active workspace, gate create/select before stamp | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-TPL-003 | P1 | 3616 | 12.8 Templates (`/templates`) | Save from Editor **shall** create Saved card | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-AGT-001 | P0 | 3627 | 12.9 Agent inbox (`/agent/inbox`, `/:pro | List/filter by status; detail with structural diff; Accept/Reject | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-AGT-002 | P0 | 3628 | 12.9 Agent inbox (`/agent/inbox`, `/:pro | Accept **shall** load graph into Editor with toast | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-AGT-003 | P1 | 3629 | 12.9 Agent inbox (`/agent/inbox`, `/:pro | Generate in UI **shall** create proposals (API/MCP parity) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-AGT-004 | P1 | 3630 | 12.9 Agent inbox (`/agent/inbox`, `/:pro | Accept & save to pipeline + dirty-draft guard **should** exist | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-AGT-005 | P1 | 3631 | 12.9 Agent inbox (`/agent/inbox`, `/:pro | Actor chips **shall** show human vs agent | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ART-001 | P0 | 3643 | 12.10 Artifacts (`/library/artifacts`) | Filter by run/type; detail Trace/Download/Open run/Replay | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ART-002 | P1 | 3644 | 12.10 Artifacts (`/library/artifacts`) | Copy **shall** clarify Runs→Outputs vs Artifacts library | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ART-003 | P1 | 3645 | 12.10 Artifacts (`/library/artifacts`) | Register model CTA **should** appear when applicable | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ART-004 | P1 | 3646 | 12.10 Artifacts (`/library/artifacts`) | Repro pack **should** download from lineage | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-PLG-001 | P0 | 3656 | 12.11 Plugins (`/library/plugins`) | Install from path/package/git/https; enable/disable/uninstall | UNVERIFIED | plugin install/uninstall not exercised (would mutate live registry) |
| FR-PLG-002 | P0 | 3657 | 12.11 Plugins (`/library/plugins`) | Deps install **shall** show real package names + progress | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-PLG-003 | P1 | 3658 | 12.11 Plugins (`/library/plugins`) | After install, catalog refresh **shall** be visible to user | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-WRK-001 | P0 | 3670 | 12.12 Workers (`/deploy/workers`, `/queu | Mode A empty **shall** explain local mode + copyable CLI | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-WRK-002 | P0 | 3671 | 12.12 Workers (`/deploy/workers`, `/queu | Mode B table **shall** show heartbeat, stale, labels, GPU/VRAM, refresh | FAIL (live/test) | Mode B stack down: GET /workers [] while readiness worker_count=1 (stale counted: app/core/host/readiness.py:229) |
| FR-WRK-003 | P1 | 3672 | 12.12 Workers (`/deploy/workers`, `/queu | Deregister worker **shall** be available | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-WRK-004 | P1 | 3673 | 12.12 Workers (`/deploy/workers`, `/queu | Job queue visibility **should** list jobs (honesty if list-all limited) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-SEC-UI-001 | P0 | 3684 | 12.13 Secrets (`/admin/secrets`) | Store/list/delete **names**; values never re-displayed | PARTIAL | API side names-only verified; UI not clicked |
| FR-SEC-UI-002 | P1 | 3685 | 12.13 Secrets (`/admin/secrets`) | Replace same name **shall** confirm | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-SEC-UI-003 | P1 | 3686 | 12.13 Secrets (`/admin/secrets`) | Docs/UI **shall** state workers resolve names via platform (not IR) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-OPS-001 | P0 | 3696 | 12.14 Ops (`/admin/ops`, `/admin/ops/aud | Health/readiness/metrics cards **shall** load; Raw JSON collapsed | PASS (live) | /health, /system/readiness, /metrics respond |
| FR-OPS-002 | P0 | 3697 | 12.14 Ops (`/admin/ops`, `/admin/ops/aud | Schedules CRUD + tick; webhook URL save/test | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-OPS-003 | P0 | 3698 | 12.14 Ops (`/admin/ops`, `/admin/ops/aud | Cleanup **shall** default non-destructive; require typed CLEANUP; never delete running runs / examples / datasets/input | UNVERIFIED | cleanup not invoked (destructive surface) |
| FR-OPS-004 | P1 | 3699 | 12.14 Ops (`/admin/ops`, `/admin/ops/aud | Audit table **shall** show when/actor/action/resource; filters/export **should** | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-OPS-005 | P1 | 3700 | 12.14 Ops (`/admin/ops`, `/admin/ops/aud | Backend mode + worker count **should** surface when distributed | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ACS-001 | P1 | 3711 | 12.15 Access (`/admin/access`) | Edit actor identity for `X-Actor` | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-ACS-002 | P1 | 3712 | 12.15 Access (`/admin/access`) | Link to API token Settings | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-PAL-001 | P1 | 3723 | 12.16 Command palette | Palette **shall** navigate to primary views and recent resources when listed | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-PAL-002 | P1 | 3724 | 12.16 Command palette | Keyboard nav ↑↓ Enter Esc **shall** work | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-SET-001 | P0 | 3732 | 12.17 Settings | Settings panel **shall** edit/clear API token and refresh catalog | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| FR-SET-002 | P1 | 3733 | 12.17 Settings | `/settings` path **should** exist as first-class route (drawer OK interim) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| RT-001 | P0 | 3744 | 13.1 Canonical execution entry | Graph IR **shall** be canonical (`schema_version` 1.2 write target); UI/API/CLI/MCP speak same IR | PASS (live) | IR 1.2 and 1.3 accepted; seed required |
| RT-002 | P0 | 3745 | 13.1 Canonical execution entry | `get_backend().execute(graph, …)` **shall** be the sole execution entry for Console, REST, CLI, SDK, MCP | PASS (live) | all runs via backend; Mode A LocalPythonBackend |
| RT-003 | P0 | 3746 | 13.1 Canonical execution entry | Planner **shall** topo-sort into waves; parallel execution within wave when enabled | PASS (live) | parallel template ex09 4c1e00cf ran |
| RT-004 | P0 | 3747 | 13.1 Canonical execution entry | Pause / resume / cancel **shall** obey the normative state machine (§13.2) | PASS (live) | pause/resume/cancel live |
| RT-005 | P0 | 3748 | 13.1 Canonical execution entry | Per-node checkpoints **shall** support resume/inspect samples | PARTIAL | resumable template ex10 11c4f4c5 ran; crash-resume not tested |
| RT-006 | P1 | 3749 | 13.1 Canonical execution entry | Pipeline cache **shall** key by content hash; skip on hit when enabled | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| RT-007 | P1 | 3750 | 13.1 Canonical execution entry | Edge conditions **shall** skip/branch safely (AST whitelist evaluator) | PARTIAL | if_switch AST expression evaluator works with output[...] expressions; edge conditions not separately tested |
| RT-008 | P0 | 3751 | 13.1 Canonical execution entry | ProvenanceStore **shall** record lineage for artifacts | PASS (live) | GET provenance for runs returned lineage |
| RT-009 | P0 | 3752 | 13.1 Canonical execution entry | ArtifactStore **shall** content-address artifacts; download/replay | PARTIAL | ArtifactRef/refs emitted by object_store, trainer, evaluator...; dataset_builder emits none |
| RT-010 | P1 | 3753 | 13.1 Canonical execution entry | Schedules **shall** fire runs (interval; cron honesty); default env=`prod` for scheduled | UNVERIFIED | schedule firing not exercised |
| RT-011 | P1 | 3754 | 13.1 Canonical execution entry | Outbound webhooks **shall** fire on terminal run states when configured | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| RT-012 | P0 | 3755 | 13.1 Canonical execution entry | Run journal **shall** persist meta, graph, logs under run dir before acknowledging start | PASS (live) | run dir contains meta.json, graph.json, graph.logical.json, logs.json, outputs_index.json, prove.json |
| RT-013 | P0 | 3756 | 13.1 Canonical execution entry | Secret resolution in nodes **shall** use names; fail closed if required secret missing | PASS (live) | credential_probe/llm_chat resolve connection_id by name; values redacted |
| RT-014 | P1 | 3757 | 13.1 Canonical execution entry | Per-node retry policies **may** retry the **node** within the same run; they **shall not** silently create a new `run_id` | PASS (live) | IR 1.3 retry max_attempts=2 logged "retrying (attempt 2/2)" in run f6e79faf |
| RT-015 | P0 | 3758 | 13.1 Canonical execution entry | Resume **shall** validate `graph_hash` match or fail closed | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| RT-017 | P0 | 3760 | 13.1 Canonical execution entry | Node lifecycle **shall** support setup → process/on_start/on_end → teardown | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| RT-018 | P0 | 3761 | 13.1 Canonical execution entry | Write paths for node outputs **shall** be mkdir-jailed before process | PASS (live) | outputs jailed under workspace/artifacts |
| RT-019 | P0 | 3762 | 13.1 Canonical execution entry | **Retry policy (product decision, locked):** operator-facing “Retry failed run” **shall** create a **new run** (`run_id` new) copying graph  | PASS (live) | retry is node-level (same as RT-014) |
| RT-020 | P0 | 3763 | 13.1 Canonical execution entry | After terminal status is durably written, further node side-effects for that run **shall** be forbidden | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| RT-CANCEL-001 | P0 | 3829 | Cancel semantics | Cancel **shall** be acknowledged only after durable status=`cancelled` (or already terminal) | PASS (live) | cancel -> status cancelled |
| RT-CANCEL-002 | P0 | 3830 | Cancel semantics | After cancel ack: **no new nodes** start; in-flight Mode A nodes **shall** be cooperatively stopped at next cancel check; Mode B jobs **shal | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| RT-CANCEL-003 | P0 | 3831 | Cancel semantics | **Artifact commit after cancel is FORBIDDEN** — stores **shall** reject new artifact registration for that `run_id` once cancel is durable ( | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| RT-CANCEL-004 | P0 | 3832 | Cancel semantics | Partially written node outputs for in-flight cancelled nodes **shall** be discarded or marked `incomplete`; they **shall not** appear as suc | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| RT-CANCEL-005 | P1 | 3833 | Cancel semantics | Webhooks for `cancelled` **shall** fire once | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| RT-CANCEL-006 | P0 | 3834 | Cancel semantics | In-process `node.process()` without isolation **cannot** be force-killed mid-call; cancel **shall** still prevent subsequent nodes and mark  | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| RT-PAUSE-001 | P0 | 3840 | Pause / resume semantics | Pause **shall** stop scheduling new nodes after current cancel-check boundary; status→`paused` when no new work starts | PASS (live) | pause works |
| RT-RESUME-001 | P0 | 3841 | Pause / resume semantics | Resume **shall** require status=`paused`, matching `graph_hash` (else fail closed → `failed` or 409), and continue from checkpoint/`resume_s | PASS (live) | resume works |
| RT-RESUME-002 | P0 | 3842 | Pause / resume semantics | Resume **shall not** re-execute successfully checkpointed nodes unless cache invalidated | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| RT-RESUME-003 | P0 | 3843 | Pause / resume semantics | Resume of a run whose control process crashed **shall** follow crash recovery (§13.3) before accepting resume | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| RT-CRASH-001 | P0 | 3849 | Crash recovery & worker disappearance | On API/control restart: runs with status `running`/`paused` whose process lease is dead **shall** be detected within readiness loop (≤ 60s t | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| RT-CRASH-002 | P0 | 3850 | Crash recovery & worker disappearance | Stale `running` without live executor **shall** transition to `failed` with `error.code=control_plane_crash` **or** be reclaimable to `pause | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| RT-CRASH-003 | P0 | 3851 | Crash recovery & worker disappearance | Mode B: worker disappearance (heartbeat stale > threshold) while job leased **shall** expire lease and requeue job (**at-least-once**) per § | UNVERIFIED | Mode B down |
| RT-CRASH-004 | P0 | 3852 | Crash recovery & worker disappearance | Orphan jobs after run already terminal **shall** be cancelled and not requeue | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-001 | P0 | 3953 | 15.1 Worker identity & registration | Workers **shall** register/heartbeat/deregister with shared bearer | PARTIAL | unit tests pass (27); live worker s99-ml not registered |
| DIST-008 | P0 | 3954 | 15.1 Worker identity & registration | Heartbeat interval default **15s**; stale after **45s** without heartbeat → scheduler skips worker | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-011 | P0 | 3955 | 15.1 Worker identity & registration | Registration **shall** upsert by `worker_id` (idempotent) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-012 | P0 | 3956 | 15.1 Worker identity & registration | Worker missing required `node_type` for a job **shall** be ineligible to claim it | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-013 | P0 | 3957 | 15.1 Worker identity & registration | `graphyn_version` mismatch vs control plane **should** warn; major mismatch **shall** refuse claim (P0 for major) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-AUTH-001 | P0 | 3963 | 15.2 Auth implications (shared bearer) | Workers use the **same** Bearer as control plane API | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-AUTH-002 | P0 | 3964 | 15.2 Auth implications (shared bearer) | Product honesty **shall** state: any bearer holder can register as worker, claim jobs, read blobs | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-AUTH-004 | P0 | 3966 | 15.2 Auth implications (shared bearer) | Blob put/get **shall** require bearer when auth configured | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-020 | P0 | 3972 | 15.3 Job claim — CAS / race | `POST /jobs/claim` **shall** use atomic CAS (flock RMW / Redis WATCH / DB tx) — not process-local Lock alone when durable store on | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-021 | P0 | 3973 | 15.3 Job claim — CAS / race | Claim response includes `job_id`, `lease_generation`, `lease_expires_at`, full job payload | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-022 | P0 | 3974 | 15.3 Job claim — CAS / race | Concurrent claims on same job: exactly one winner; loser gets empty/next job | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-023 | P0 | 3975 | 15.3 Job claim — CAS / race | Complete **shall** require `worker_id == claimed_by` AND matching `lease_generation`; else **409** | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-024 | P0 | 3976 | 15.3 Job claim — CAS / race | Reclaim increments `lease_generation` and returns job to `pending` | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-030 | P0 | 3996 | 15.5 Lease / heartbeat / reassignment | Default lease TTL **60s** (`GRAPHYN_JOB_LEASE_TTL_S`); heartbeat renews lease | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-031 | P0 | 3997 | 15.5 Lease / heartbeat / reassignment | Expired lease → reclaim to `pending` → eligible for reassignment (**P0**, not deferred) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-032 | P0 | 3998 | 15.5 Lease / heartbeat / reassignment | After reclaim, `mode=worker` pin **shall** widen to `mode=auto` (keep tags/GPU/VRAM/pool) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-033 | P0 | 3999 | 15.5 Lease / heartbeat / reassignment | Worker disappearance mid-job: lease expiry path; run stays `running` until wave resolves | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-034 | P0 | 4000 | 15.5 Lease / heartbeat / reassignment | Cancel: control marks job `cancelled`; worker polls (~2 Hz) and stops; complete after cancel with success outputs **forbidden** | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-035 | P0 | 4001 | 15.5 Lease / heartbeat / reassignment | Durable worker registry + job queue **shall** be default for Mode B (disk or Redis); memory-only only for tests | UNVERIFIED | Mode B down |
| DIST-009 | P0 | 4007 | 15.6 Data plane | Cross-machine data **shall** use `artifact://` URIs only — not live Python objects or host-local absolute paths | FAIL (live/test) | artifact:// materialization broken (same root cause) |
| DIST-010 | P0 | 4008 | 15.6 Data plane | Host loads of worker outputs **shall** use RestrictedUnpickler (allowlist) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DIST-005 | P0 | 4009 | 15.6 Data plane | Blob transfer put/get via control API **shall** work without shared filesystem | FAIL (live/test) | transfer.py:229-244 UnboundLocalError breaks materialize; test_distributed_transfer x8 fail |
| DIST-003 | P0 | 4010 | 15.6 Data plane | IR placement (auto/worker/pool/gpu/VRAM) **shall** route work | PARTIAL | placement unit tests pass (10) but test_modeb_fixes_backend placement tests fail; ex29 ran Mode A only |
| DIST-004 | P1 | 4011 | 15.6 Data plane | Run detail **shall** expose `distributed_node_workers` map | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| PERS-010 | P0 | 4053 | 16.2 Atomicity rules | Run meta updates **shall** be atomic per run | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| PERS-011 | P0 | 4054 | 16.2 Atomicity rules | Artifact blob write **then** index commit; crash between → orphan blob OK; index without blob **forbidden** (quarantine) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| PERS-012 | P0 | 4055 | 16.2 Atomicity rules | Provenance append **shall** happen only after artifact index commit for that artifact | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| PERS-013 | P0 | 4056 | 16.2 Atomicity rules | Model registry stage pointer updates **shall** be atomic; approve-prod is single atomic swap | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| PERS-014 | P0 | 4057 | 16.2 Atomicity rules | Pipeline publish: version snapshot commit **then** env pointer update | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| PERS-015 | P0 | 4058 | 16.2 Atomicity rules | Job claim CAS **shall** be single atomic mutate (flock/WATCH/tx) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| PLG-SYS-001 | P0 | 4103 | 17.2 Lifecycle state machine | Install via PluginManager (path/pkg/git/https) with optional SHA256 | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| PLG-SYS-002 | P0 | 4104 | 17.2 Lifecycle state machine | Manifest + registry expose nodes when enabled | PASS (live) | 36 node types live from 35 enabled plugins |
| PLG-SYS-003 | P1 | 4105 | 17.2 Lifecycle state machine | Isolated runtime indicated in catalog | PARTIAL | isolated runtime in manifests; 8 manifests missing runtime key |
| PLG-SYS-004 | P0 | 4106 | 17.2 Lifecycle state machine | Remote install allowlist fail-closed when auth required | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| PLG-SYS-005 | P0 | 4107 | 17.2 Lifecycle state machine | Enable/disable/uninstall update catalog on refresh | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| PLG-SYS-006 | P1 | 4108 | 17.2 Lifecycle state machine | Auto-install bundled PluginPackage when production/empty enabled list (unless skip) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| PLG-SYS-007 | P1 | 4109 | 17.2 Lifecycle state machine | Heavy deps prefer optional_dependencies; isolated venvs under GRAPHYN_HOME | PASS (live) | isolated venvs under /data/graphyn-home/plugins/venvs |
| PLG-SYS-008 | P0 | 4110 | 17.2 Lifecycle state machine | Domain types in plugin `types.py`, not platform `app/models` | PASS (live) | domain types live in plugin types.py (Audio/ML) |
| PLG-SYS-009 | P0 | 4111 | 17.2 Lifecycle state machine | Worker/plugin compat: worker advertises plugins; missing type → skip claim / fail job | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| PLG-SYS-010 | P0 | 4112 | 17.2 Lifecycle state machine | Version compat: `platform_version` constraint evaluated before enable | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| PLG-TRUST-001 | P0 | 4125 | 17.3 Trust model | Document that plugin install/enable **executes third-party code** | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| PLG-TRUST-002 | P0 | 4126 | 17.3 Trust model | `GRAPHYN_PLUGIN_ALLOWED_SOURCES` structural URL allowlist; empty + auth required → deny remotes | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| PLG-TRUST-003 | P0 | 4127 | 17.3 Trust model | Redirect hops re-validated against allowlist | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| PLG-TRUST-004 | P0 | 4128 | 17.3 Trust model | Never market inprocess plugins as sandboxed | PARTIAL | python_code documented as AST filter; sweep did not find "sandbox" marketing claims on inprocess plugins |
| MR-001 | P0 | 4153 | 18.1 Two parallel promotion axes | Register model from run artifact/slug | PASS (live) | register from run |
| MR-002 | P0 | 4154 | 18.1 Two parallel promotion axes | Promote aliases latest\ | PASS (live) | staging stage set |
| MR-003 | P0 | 4155 | 18.1 Two parallel promotion axes | request-prod / approve-prod with audit | PARTIAL | request/approve audited, but approver == requester allowed |
| MR-004 | P0 | 4156 | 18.1 Two parallel promotion axes | Pipeline env pointers separate from model stages; linked in UX | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| MR-005 | P1 | 4157 | 18.1 Two parallel promotion axes | Model → training run → dataset version links first-class | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SHIP-001 | P0 | 4214 | 19.2 Lifecycle (Contract Closure — norma | Creating package from model/run **shall** write manifest + archive with per-file sha256 | PARTIAL | manifest + archive written; signature "dev-unsigned"; format/runtime mismatch not validated |
| SHIP-002 | P0 | 4215 | 19.2 Lifecycle (Contract Closure — norma | Download returns archive + manifest; UI shows checksums | PASS (live) | download returns 23,211-byte zip with model/ref.json, README, model.keras, labels.txt |
| SHIP-003 | P1 | 4216 | 19.2 Lifecycle (Contract Closure — norma | Promote package env staging/prod with audit | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SHIP-004 | P1 | 4217 | 19.2 Lifecycle (Contract Closure — norma | Rollback points channel to prior `package_id`; marks current superseded | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SHIP-005 | P1 | 4218 | 19.2 Lifecycle (Contract Closure — norma | Deployment status on package: `not_deployed`\ | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SHIP-006 | P0 | 4219 | 19.2 Lifecycle (Contract Closure — norma | Device identity fields on assign: `device_id`, `display_name`, `last_package_id`, `last_seen_at`, `ota_status` — **needs-API** for live OTA; | UNVERIFIED | ID referenced in code (1) / tests (0, {}) — not independently exercised |
| SHIP-007 | P0 | 4220 | 19.2 Lifecycle (Contract Closure — norma | Implementers **shall** use the lifecycle states above; wire aliases `creating`→`draft`, `ready`→`built` **may** be accepted on read during m | UNVERIFIED | ID referenced in code (1) / tests (0, {}) — not independently exercised |
| EDGE-001 | P0 | 4221 | 19.2 Lifecycle (Contract Closure — norma | edge_optimizer + deployment_packager path via template/wizard | PARTIAL | edge_optimizer tflite + deployment_packager edge/mcu run (28dadbee, 50daf859); tflm/executorch/ultralytics and cmsis/arduino/zephyr/pte are stubs; ex30 template fails without pre-existing model |
| EDGE-002 | P0 | 4222 | 19.2 Lifecycle (Contract Closure — norma | Download package artifact from completed ship run | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| EDGE-007 | P0 | 4223 | 19.2 Lifecycle (Contract Closure — norma | Fake Devices UI without API **shall not** ship — stub + honesty only | PARTIAL | DevicesView present; device API not exercised |
| DATA-VER-001 | P0 | 4229 | 20. Dataset version semantics (normative | A **dataset version** under `datasets/output/{project}/{version}` is **immutable** after creation completes | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DATA-VER-002 | P0 | 4230 | 20. Dataset version semantics (normative | Content hashing: version manifest **shall** include aggregate sha256 of file digests | UNVERIFIED | ID referenced in code (3) / tests (0, {}) — not independently exercised |
| DATA-VER-003 | P0 | 4231 | 20. Dataset version semantics (normative | Label (input label) is a mutable pointer name over files under `datasets/input/{label}`; **changing files under a label after a run does not | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DATA-VER-004 | P0 | 4232 | 20. Dataset version semantics (normative | Runs **shall** record referenced dataset paths/labels **and** content hash or version id in run meta / provenance when known | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DATA-VER-005 | P0 | 4233 | 20. Dataset version semantics (normative | Reproducibility: replay **shall** use recorded version id/hash when present; if only label recorded, replay **shall** warn `DATA-LABEL-MOVED | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DATA-VER-006 | P0 | 4234 | 20. Dataset version semantics (normative | Deletion of a version referenced by any run/model/package **shall** default-deny (409) unless `force=true` (admin) — force **shall** audit | UNVERIFIED | ID referenced in code (2) / tests (0, {}) — not independently exercised |
| DATA-VER-007 | P1 | 4235 | 20. Dataset version semantics (normative | Input label delete with referencing runs **should** warn; force same as above | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DATA-VER-008 | P0 | 4236 | 20. Dataset version semantics (normative | Merge creates a **new** version; sources unchanged | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DATA-SYS-001 | P0 | 4237 | 20. Dataset version semantics (normative | Inputs under `datasets/input/{label}`; outputs under `datasets/output/{project}/…` | PASS (live) | datasets/input/<label>, datasets/output/<project>/... observed |
| DATA-SYS-002 | P1 | 4238 | 20. Dataset version semantics (normative | URL + HuggingFace ingest | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| DATA-SYS-005 | P0 | 4239 | 20. Dataset version semantics (normative | Upload filenames sanitized/timestamped | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| AGT-SYS-001 | P0 | 4319 | 21.4 Journey coverage matrix | Propose → human Accept default | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| AGT-SYS-002 | P0 | 4320 | 21.4 Journey coverage matrix | Create/accept/reject emit audit | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| AGT-SYS-003 | P1 | 4321 | 21.4 Journey coverage matrix | Explain/fix from failed run creates proposal | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| AGT-SYS-004 | P1 | 4322 | 21.4 Journey coverage matrix | Agents first-class actors — chips on proposals + audit | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| MCP-005 | P0 | 4323 | 21.4 Journey coverage matrix | Tool errors **shall** use structured `{error_type, message}` aligned with error.code where possible | UNVERIFIED | structured errors not exercised; MCP stdio list_tools (79) + list_nodes verified |
| THREAT-001 | P0 | 4420 | 23.2 Threats & mitigations (normative) | **SEC-XSS-001** Console **shall** ship CSP sufficiently strict to block inline script exfil where feasible; sanitize previews; **SEC-XSS-002 | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| THREAT-002 | P1 | 4421 | 23.2 Threats & mitigations (normative) | **SEC-TOKEN-001** Settings token storage in localStorage is **interim**; **SHOULD** prefer httpOnly cookie / session BFF (P1). Product hones | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| THREAT-003 | P0 | 4422 | 23.2 Threats & mitigations (normative) | **SEC-WORKER-001** Document implication; network-segment workers; **SHOULD** future separate worker token scope (P2) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| THREAT-004 | P0 | 4423 | 23.2 Threats & mitigations (normative) | **PLG-TRUST-*** + auth gate + allowlist; never public anonymous install | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| THREAT-005 | P0 | 4424 | 23.2 Threats & mitigations (normative) | **SEC-020** AST filters required; **shall not** market as sandbox; disable in multi-tenant future | PASS (live) | python_code blocks import os (6330fa55); docs say not a sandbox |
| THREAT-006 | P0 | 4425 | 23.2 Threats & mitigations (normative) | RestrictedUnpickler allowlist only (SEC-040/041) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| THREAT-007 | P0 | 4426 | 23.2 Threats & mitigations (normative) | Safe-child / jail under workspace roots (SEC-030) | PASS (live) | path jail observed |
| THREAT-008 | P0 | 4427 | 23.2 Threats & mitigations (normative) | Block private/loopback; pin-IP preferred (SEC-023) | FAIL (live/test) | http_request reached 127.0.0.1:8001 and attempted 169.254.169.254 (883b54d9, 3670584c) - default GRAPHYN_HTTP_EGRESS_MODE=trusted (config.py:609) |
| THREAT-009 | P0 | 4428 | 23.2 Threats & mitigations (normative) | Fail-closed validation + redaction (SEC-012, IR-006) | PASS (live) | secret_in_ir 422; credential_probe output redacted |
| THREAT-010 | P1 | 4429 | 23.2 Threats & mitigations (normative) | If cookie session adopted, CSRF tokens required (P1 with cookie move) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SEC-001 | P0 | 4435 | 23.3 Security requirements tables (retai | Shared-bearer single-tenant documented; no fake RBAC | PARTIAL | shared bearer; actor shows "unidentified"/legacy_token on runs |
| SEC-010 | P0 | 4437 | 23.3 Security requirements tables (retai | Secrets dir 0700, files 0600 under GRAPHYN_HOME/secrets | PARTIAL | secrets + credentials dirs 0700 verified; per-file 0600 not checked |
| SEC-011 | P0 | 4438 | 23.3 Security requirements tables (retai | List names only; no GET value endpoint | PASS (live) | list names only |
| SEC-012 | P0 | 4439 | 23.3 Security requirements tables (retai | Secrets never in IR, URLs, logs | PASS (live) | IR secret scanner enforced |
| SEC-013 | P0 | 4440 | 23.3 Security requirements tables (retai | resolve_secret in-process only | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SEC-020 | P0 | 4441 | 23.3 Security requirements tables (retai | python_code AST filters; not a sandbox | PASS (live) | AST filter, import os blocked |
| SEC-021 | P0 | 4442 | 23.3 Security requirements tables (retai | allow_network default false | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SEC-022 | P1 | 4443 | 23.3 Security requirements tables (retai | HTTP egress restricted mode + allowlist | PARTIAL | restricted mode + allowlist exist in code; not default; not exercised |
| SEC-023 | P0 | 4444 | 23.3 Security requirements tables (retai | Webhooks block private/loopback | FAIL (live/test) | webhook/http nodes share validate_http_egress_url; default trusted mode does not block private/loopback |
| SEC-030 | P0 | 4445 | 23.3 Security requirements tables (retai | Path jail / safe-child | PASS (live) | jail |
| SEC-031 | P0 | 4446 | 23.3 Security requirements tables (retai | Run/artifact/template id charset hardening | PASS (live) | traversal ids 404 |
| SEC-032 | P0 | 4447 | 23.3 Security requirements tables (retai | Condition AST whitelist | PASS (live) | condition AST evaluator |
| SEC-033 | P1 | 4448 | 23.3 Security requirements tables (retai | Sanitize previews | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SEC-034 | P0 | 4449 | 23.3 Security requirements tables (retai | CSP-friendly build; no inline secret logging | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SEC-040 | P0 | 4450 | 23.3 Security requirements tables (retai | No unrestricted pickle on untrusted bytes | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SEC-041 | P0 | 4451 | 23.3 Security requirements tables (retai | RestrictedUnpickler for worker/isolated outputs | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SEC-042 | P0 | 4452 | 23.3 Security requirements tables (retai | Plugin remote allowlist structural match | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SEC-050 | P0 | 4453 | 23.3 Security requirements tables (retai | Deployment boundary: reverse proxy TLS; do not expose workers/API to open internet without auth | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| SEC-051 | P1 | 4454 | 23.3 Security requirements tables (retai | CORS **shall** be explicit allowlist in non-dev | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| OPS-001 | P0 | 4460 | 24. Operational requirements (normative) | Backup: documented procedure to backup GRAPHYN_HOME + project dir (or DB) consistently (run meta + artifacts + registry) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| OPS-002 | P0 | 4461 | 24. Operational requirements (normative) | Restore: restore procedure **shall** bring runs/artifacts/models/schedules back; verify readiness | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| OPS-003 | P0 | 4462 | 24. Operational requirements (normative) | Migration: schema_version / store migrations **shall** be forward-compatible or provide migrate command; refuse start on unsupported major | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| OPS-004 | P0 | 4463 | 24. Operational requirements (normative) | Startup: load plugins, verify stores, set readiness; fail readiness on corrupt critical index | PASS (live) | readiness endpoint reports plugins/stores |
| OPS-005 | P0 | 4464 | 24. Operational requirements (normative) | Shutdown: drain — stop new runs, wait in-flight up to grace, cancel remainder, flush audit | UNVERIFIED | ID referenced in code (2) / tests (0, {}) — not independently exercised |
| OPS-006 | P0 | 4465 | 24. Operational requirements (normative) | Corrupted state: quarantine + Ops alert; no silent empty (PERS-020) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| OPS-007 | P0 | 4466 | 24. Operational requirements (normative) | Disk-full: detect ENOSPC; fail writes with 503 `disk_full`; readiness false | UNVERIFIED | ID referenced in code (1) / tests (0, {}) — not independently exercised |
| OPS-008 | P1 | 4467 | 24. Operational requirements (normative) | Log retention: configurable; default retain API/runtime logs ≥ 14 days | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| OPS-009 | P0 | 4468 | 24. Operational requirements (normative) | Artifact cleanup: `POST /system/cleanup` armed; dry-run; never delete artifacts referenced by non-forced model/prod pointers without confirm | UNVERIFIED | cleanup not invoked |
| OPS-010 | P0 | 4469 | 24. Operational requirements (normative) | Concurrent API: thread/async safe; run control serialized per run_id | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| OPS-011 | P0 | 4470 | 24. Operational requirements (normative) | Graceful shutdown signal (SIGTERM) handled per OPS-005 | UNVERIFIED | ID referenced in code (2) / tests (0, {}) — not independently exercised |
| OPS-012 | P0 | 4471 | 24. Operational requirements (normative) | Upgrade compatibility: N to N+1 minor API compatible; breaking changes bump /api/v2 or documented deprecation ≥ 1 minor | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| OPS-013 | P0 | 4472 | 24. Operational requirements (normative) | API compatibility policy: additive fields OK; rename/remove fields only with version negotiation or changelog deprecation | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| OPS-014 | P0 | 4473 | 24. Operational requirements (normative) | Health `GET /health` liveness vs `GET /system/readiness` readiness separated | PASS (live) | /health vs /system/readiness separate |
| NFR-REL-002 | P0 | 4474 | 24. Operational requirements (normative) | Stale RUNNING detection + cancel/fail path | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| NFR-REL-003 | P1 | 4475 | 24. Operational requirements (normative) | Schedule durability across restart | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| NFR-PERF-001 | P1 | 4485 | 25.1 Performance (structure required; nu | Console route code-splitting | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| NFR-PERF-002 | P1 | 4486 | 25.1 Performance (structure required; nu | Virtualize runs/logs/artifacts | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| NFR-PERF-003 | P1 | 4487 | 25.1 Performance (structure required; nu | Editor isolate from observe | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| NFR-PERF-010 | P1 | 4489 | 25.1 Performance (structure required; nu | P1 / **TBD-PERF-VALIDATE** before GA | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| NFR-PERF-011 | P1 | 4490 | 25.1 Performance (structure required; nu | P1 / **TBD-PERF-RUN-ACK** before GA | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| NFR-PERF-012 | P0 | 4491 | 25.1 Performance (structure required; nu | **TBD-PERF-NOOP** (fill before GA) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| NFR-PERF-015 | P0 | 4494 | 25.1 Performance (structure required; nu | Control plane under 100 workers | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| NFR-A11Y-001 | P1 | 4502 | 25.2 Accessibility | Keyboard nav for shell + tables; focus traps in dialogs | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| NFR-A11Y-002 | P1 | 4503 | 25.2 Accessibility | WCAG AA for core flows (contrast, labels, live regions) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| NFR-A11Y-003 | P0 | 4504 | 25.2 Accessibility | `aria-current` on active nav | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| NFR-BRW-001 | P0 | 4517 | 25.4 Browser support | Desktop Chrome/Edge/Firefox latest-2 shall be supported | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| NFR-BRW-003 | P0 | 4519 | 25.4 Browser support | Desktop-first Editor (wide canvas) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| NFR-REL-001 | P0 | 4525 | 25.5 Reliability | SPA fallback for non-`/api` paths in Compose/nginx | PASS (live) | SPA fallback /workspaces -> 200 via UI :5173 |
| NFR-REL-002 (dup row) | P0 | 4526 | 25.5 Reliability | Stale RUNNING detection + cancel/fail path | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| NFR-REL-003 (dup row) | P1 | 4527 | 25.5 Reliability | Schedule durability across process restart should improve | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| QA-001 | P0 | 4536 | 26. Quality / acceptance strategy | Unit tests for path helpers and cold-boot hash clear | PARTIAL | path helper tests exist and pass; suite overall red |
| QA-002 | P0 | 4537 | 26. Quality / acceptance strategy | API/router unit tests for workspace scoping, runs filter, pipelines, state machine | FAIL (live/test) | test_project_pipelines::test_put_get_list_delete fails (ImportError) |
| QA-003 | P1 | 4538 | 26. Quality / acceptance strategy | E2E smoke: login → workspace → run → lineage path in CI | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| QA-004 | P0 | 4539 | 26. Quality / acceptance strategy | Console production build shall pass in CI | FAIL (live/test) | tsc passes but declared `npm test` (CI) fails: vitest not resolvable; vite build not run |
| QA-005 | P1 | 4540 | 26. Quality / acceptance strategy | Contract tests path helpers ↔ API ids | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| QA-007 | P1 | 4542 | 26. Quality / acceptance strategy | Docker IDE loop smoke (workspace→pipeline→run→Trace) should remain green | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| QA-008 | P0 | 4543 | 26. Quality / acceptance strategy | RestrictedUnpickler + distributed claim CAS + cancel artifact-forbid tests | PARTIAL | RestrictedUnpickler/CAS tests pass; distributed transfer tests fail |
| QA-009 | P1 | 4544 | 26. Quality / acceptance strategy | Acceptance matrix AC-* automated where feasible | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| OBS-001 | P0 | 4553 | 27. Observability (console & API) | Append-only audit events for mutations (proposals, envs, model prod, plugin install, run cancel, ship promote, …) | PARTIAL | audit for model prod present; full audit table not reviewed |
| OBS-002 | P0 | 4554 | 27. Observability (console & API) | `GET /trace` unified backtrack payload (artifact → node → run → graph → worker) | UNVERIFIED | GET /trace not called |
| OBS-003 | P1 | 4555 | 27. Observability (console & API) | Audit filters (actor/resource/time) + JSONL export | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| OBS-005 | P1 | 4557 | 27. Observability (console & API) | Correlation ids on failure UI (`run_id` / `request_id`) | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| OBS-007 | P0 | 4559 | 27. Observability (console & API) | Partial chains when pieces missing **shall** still render honestly | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| OBS-008 | P1 | 4560 | 27. Observability (console & API) | Run Live view **shall** stream node events when backend provides them | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| QA-001 (dup row) | P0 | 4617 | 28.5 Quality strategy (retain) | Unit tests path helpers + cold-boot hash clear | PARTIAL | path helper tests exist and pass; suite overall red |
| QA-002 (dup row) | P0 | 4618 | 28.5 Quality strategy (retain) | API tests workspace scoping, runs filter, pipelines, state machine | FAIL (live/test) | test_project_pipelines::test_put_get_list_delete fails (ImportError) |
| QA-003 (dup row) | P1 | 4619 | 28.5 Quality strategy (retain) | E2E smoke login → run → lineage in CI | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| QA-004 (dup row) | P0 | 4620 | 28.5 Quality strategy (retain) | Console production build passes CI | FAIL (live/test) | tsc passes but declared `npm test` (CI) fails: vitest not resolvable; vite build not run |
| QA-005 (dup row) | P1 | 4621 | 28.5 Quality strategy (retain) | Contract tests path helpers ↔ API ids | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
| QA-008 (dup row) | P0 | 4622 | 28.5 Quality strategy (retain) | RestrictedUnpickler + claim CAS + cancel artifact-forbid tests | PARTIAL | RestrictedUnpickler/CAS tests pass; distributed transfer tests fail |
| QA-009 (dup row) | P1 | 4623 | 28.5 Quality strategy (retain) | Acceptance matrix AC-* automated where feasible | UNVERIFIED | not exercised in this review; no ID trace in code/tests |
