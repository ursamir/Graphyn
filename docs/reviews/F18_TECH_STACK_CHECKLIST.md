# F18 Tech Stack Checklist — Graphyn code review

| Field | Value |
|---|---|
| **Tip** | `d7f5d707d3c7050608f5ef738e551e217ffb26f9` (`d7f5d70`) — **F18**: pipeline queue + slot booking + org fair-share |
| **Branch** | `test/example-06-plugins` |
| **Host** | Server-99 (`/home/meritech/Desktop/newAudio3`) |
| **Scope** | Control plane + Mode B workers through F18 (Waves 1–6 + F18) |
| **Honesty rule** | **Partial implementation = Fail** (same bar as stakeholder review) |
| **Out of scope** | FaceRecognition, product code edits, git push |

## Discovered stack (pin against this tip)

| Layer | Current stack (discoverable) |
|---|---|
| Language / runtime | **Python ≥3.10** (`setup.py`); Docker image **`python:3.12-slim`**; host venv observed **3.12.3** |
| Control plane API | **FastAPI 0.115.6**, **Uvicorn 0.32.1**, **Pydantic 2.10.6**, **python-multipart 0.0.20** |
| HTTP / crypto | **httpx ≥0.27**, **cryptography ≥41** (AES-GCM credentials + blob / envelope KMS) |
| Persistence | **SQLite** (`sqlite3`) under `{GRAPHYN_HOME}/auth/users.db` (+ orgs/agents/metering/OIDC state); workspace JSON/files + optional **Redis** store (`extras_require["redis"]`); **no Postgres** shipped |
| Distributed | In-tree `JobQueue` + `DistributedStateStore` (file flock RMW / Redis WATCH CAS) — **no external broker** |
| Console | **React 19.2.x**, **Vite 8.x**, **TypeScript ~6**, **Zustand 5**, **React Router 7**, **React Flow 11**, **Tailwind 3.4**, **oxlint**; UI image **node:22-alpine** build → **nginx:1.27-alpine** |
| Compose services | `graphyn-api`, `graphyn-ui`; Mode B overlay adds `graphyn-worker`; optional `docker-compose.modeb-mtls.yml` |
| MCP | Optional extra **`mcp==1.27.0`** (`setup.py` extras) |
| CI | `.github/workflows/ci.yml` — Python 3.12 smoke (`scripts/ci_smoke.sh`) + Node 20 UI build/test |
| Auth defaults | Compose: `GRAPHYN_AUTH_REQUIRED=1`, fail-closed empty token |

**Reviewer scoring:** each item is **Pass** or **Fail**. Fail if missing, stubbed, docs-only, or only partially wired. Record evidence path/command in the Notes column when filing.

---

## TS-API — Control plane API quality

| ID | Statement | How to verify | Pass criteria |
|---|---|---|---|
| TS-API-01 | FastAPI app mounts under `/api/v1` with documented routers (auth, orgs, workers, billing, agents, compliance, …). | `ls app/api/routers/`; `grep -n 'include_router\|APIRouter' app/api/main.py`; open `docs/API_REFERENCE.md` | All enterprise routers present and imported; no dead stubs for shipped waves |
| TS-API-02 | Error responses use a consistent envelope (status + detail/code) on auth and quota failures. | Hit `GET /api/v1/system/health` unauth vs auth; read `app/api/main.py` bearer deps; `unit_test/api/test_auth_gate_sensitive.py` | 401/403/409 with structured detail; empty token rejected when auth required |
| TS-API-03 | Idempotency / sensitive mutations are gated (not open CORS wildcards for authenticated APIs). | `app/api/idempotency.py`; UI `graphyn-ui/nginx.conf` proxy; `unit_test/api/test_security_p0_api.py` | Auth required in production compose; proxy only `/api` to API |
| TS-API-04 | Public routes are an explicit allowlist (health, OIDC start/callback, billing webhook). | `grep -n 'public\|allowlist\|PUBLIC' app/api/main.py app/api/routers/*.py` | Billing webhook and OIDC public paths intentional; everything else Bearer/session |
| TS-API-05 | Request models use Pydantic v2 with field bounds for quotas (e.g. `max_concurrent_jobs ge=0`). | `app/api/routers/orgs.py` quota body; `app/api/routers/workers.py` claim models | Validation rejects negatives; OpenAPI reflects models |
| TS-API-06 | API version / build provenance available for sealed runs (`BUILD_INFO.json` / git SHA args). | `Dockerfile` `GRAPHYN_GIT_SHA`; `cat /app/BUILD_INFO.json` in image or compose build args | Build records git SHA when provided; not silently empty in release builds |

---

## TS-WRK — Worker / Mode B distributed correctness

| ID | Statement | How to verify | Pass criteria |
|---|---|---|---|
| TS-WRK-01 | Mode B splits control vs worker homes; **no shared host `./workspace` bind** on worker. | `docker-compose.modeb.yml` volumes for `graphyn-worker` | Worker workspace is named volume; comment forbids shared host workspace |
| TS-WRK-02 | Control sets `GRAPHYN_BACKEND=distributed`; worker starts via `graphyn worker start --control-url …`. | Same compose `command:` / env | Worker points at control `/api/v1`; heartbeat configured |
| TS-WRK-03 | Cross-machine ports use `artifact://` + blob put/get — not host absolute paths on the wire. | `app/models/artifact_ref.py`; `app/core/artifacts/artifact_pack.py` `strip_host_paths`; `unit_test/core/test_distributed_artifact_uri.py` | Host paths fail closed after pack; Mode B transfer tests green |
| TS-WRK-04 | Claim uses durable `mutate_queue` CAS (flock / Redis WATCH), not process-local Lock alone. | `JobQueue.claim` + `DistributedStateStore.mutate_queue` in `app/core/distributed/{queue,store}.py`; DIST-020 | Concurrent claim: one winner; loser empty/next |
| TS-WRK-05 | Lease TTL default ~60s; reclaim returns job to `pending` and widens worker pin. | `DEFAULT_LEASE_TTL_S`; `reclaim_expired_leases`; DIST-030–032 tests | Expired lease reclaimable; pin widened per spec |
| TS-WRK-06 | Complete/fail requires `worker_id == claimed_by` and matching lease generation (409 otherwise). | `JobQueue.complete`; `unit_test/core/distributed/` / `test_workers_jobs_router.py` | Fencing holds; late complete from dead worker rejected |
| TS-WRK-07 | Optional mTLS overlay fails closed when enabled; worker presents client cert. | `docker-compose.modeb-mtls.yml`; `app/api/mtls_serve.py` | With overlay, plain HTTP worker cannot claim |
| TS-WRK-08 | Worker-scoped tokens preferred over shared bearer (`GRAPHYN_WORKER_TOKEN` / named map). | `.env.example`; `docs/TRUST_MODEL.md`; enrollment APIs | Documented + enforceable mapping; shared bearer treated as break-glass |
| TS-WRK-09 | Plugin advertise / hash pins refuse ineligible node types when configured. | `_plugins_allow` in `queue.py`; `GRAPHYN_WORKER_REQUIRE_PLUGIN_ADVERTISE` | Mismatched hash or missing type → not claimable |

---

## TS-QSL — Queue + slot booking + fair-share (F18)

| ID | Statement | How to verify | Pass criteria |
|---|---|---|---|
| TS-QSL-01 | Per-worker slots mirror `max_claimed`; used = claimed+running for that worker. | `app/core/distributed/slots.py`; `GET` workers list fields `max_slots`/`used_slots` | Snapshot math matches job counts |
| TS-QSL-02 | Claim books a slot atomically under `mutate_queue`; full worker leaves job pending with `queue_reason=no_capacity` when pinned/all eligible full. | `slots_bookable` + `_quota_blocks_claim` + `infer_queue_reason`; `unit_test/core/test_f18_pipeline_queue_slots.py` | At cap, claim skips worker; reason visible |
| TS-QSL-03 | Complete / fail / cancel / reclaim / worker release frees the slot (no leak). | Trace `complete`, `cancel`, `reclaim_expired_leases`, `release_jobs_for_worker`; F18 tests | After terminal/reclaim, `used_slots` decreases |
| TS-QSL-04 | Global pending order; idle workers pull via `POST /jobs/claim`; `GET /jobs/queue` shows position + reason + slot snapshot. | `app/api/routers/workers.py` queue endpoints; Workers UI Queue tab | API returns position/reason; UI tab exists |
| TS-QSL-05 | Org fair-share: among eligible jobs, prefer lower `running/max_concurrent` utilization, FIFO within. | `_pick_fair_share_job` + `fair_share_key` in `quotas.py`/`queue.py` | Two orgs sharing one worker: neither monopolizes when both have pending work |
| TS-QSL-06 | Quotas `max_concurrent_jobs` / `max_queued_jobs` on org (defaults 8 / 100). | `DEFAULT_QUOTAS` in `app/core/trust/metering.py`; `PUT /orgs/{id}/quotas` | Over concurrent → `org_quota`; over queue depth → enqueue `QuotaExceeded` |
| TS-QSL-07 | Jobs carry `org_id` for fair-share (stamped at prepare). | `app/core/execution/graph_prepare.py` F18 stamp; job model field | Remote jobs have `org_id`; missing org does not break claim path dishonestly |
| TS-QSL-08 | F18 is job-level queue on shared workers — docs must not claim a separate SaaS run-admission product. | `docs/ENTERPRISE_READINESS.md` F18 detail; billing status honesty | Docs match code; Stripe Checkout still Not shipped |

---

## TS-PER — Persistence & migrations

| ID | Statement | How to verify | Pass criteria |
|---|---|---|---|
| TS-PER-01 | Auth/tenancy/metering use SQLite with on-connect migrations (ALTER for new columns). | `OrgStore`/`MeterStore`/`UserStore` `_migrate_*`; F18 columns `max_concurrent_jobs` | Fresh DB and upgrade-from-F14 path both work |
| TS-PER-02 | Distributed queue durability uses file store + flock (default) or Redis CAS. | `app/core/distributed/store.py`; `file_lock.py` | Mode B default not memory-only outside tests |
| TS-PER-03 | Workspace schema version gated (`STATE_SCHEMA_VERSION`). | `app/core/persist/storage_schema.py` | Unsupported version raises; no silent empty success |
| TS-PER-04 | Corrupt store handling quarantines / signals (PERS-020/021 intent). | `store_integrity.py`; readiness endpoints | Corrupt index ≠ silent empty 200 |
| TS-PER-05 | Audit log is append-only JSONL with optional chain verify. | `app/core/trust/audit.py` `record_audit` / `verify_audit_chain` | Append locked; chain verify detects breaks |
| TS-PER-06 | No Postgres requirement in compose/docs for this tip — reviewers must not Fail for missing PG. | `docker-compose*.yml`; requirements | SQLite (+ optional Redis) acknowledged as current stack |

---

## TS-AUTH — AuthN/Z surfaces

| ID | Statement | How to verify | Pass criteria |
|---|---|---|---|
| TS-AUTH-01 | Production compose enables `GRAPHYN_AUTH_REQUIRED=1` and requires `GRAPHYN_API_TOKEN`. | `docker-compose.yml`; `auth_required()` in config | Empty token → API reject |
| TS-AUTH-02 | Local users + sessions (`gxs_…`) + RBAC roles + project memberships shipped (F11). | `app/core/trust/users.py`, `rbac.py`; Access UI | Permission matrix enforced on routers |
| TS-AUTH-03 | OIDC optional: discovery, PKCE S256, JWKS/userinfo, same session credential; off by default. | `app/core/trust/oidc.py`; `unit_test/api/test_oidc_auth.py`; `.env.example` | Off = F11 behaviour; on = full login path, no stubs |
| TS-AUTH-04 | Org tenancy: active org scopes projects/credentials/runs; cross-org 403. | `app/core/trust/orgs.py`; `unit_test/api/test_orgs_tenancy.py` | Isolation holds with `X-Graphyn-Org-Id` / session meta |
| TS-AUTH-05 | Agent principals `kind=agent` with `gxa_…` tokens; mint/revoke; disabled agents cannot mint. | `app/core/trust/agents.py`; `unit_test/api/test_agents_identity.py` | Revoked/disabled token rejected on API and MCP |
| TS-AUTH-06 | MCP `check_auth` + `resolve_mcp_actor` bind actor for audit; secrets never listed. | `app/mcp/auth.py`; MCP-001 | Unauthorized tools fail closed; list tools redacted |
| TS-AUTH-07 | RBAC edges: project.members + users.admin hardened; OIDC-only password change guarded. | ENTERPRISE Gate A checklist; related unit tests | Documented edges covered by tests |

---

## TS-CRY — Crypto / KMS / secrets

| ID | Statement | How to verify | Pass criteria |
|---|---|---|---|
| TS-CRY-01 | Credentials encrypt-at-rest; master key from env or `{GRAPHYN_HOME}/credentials/.key` mode 0600. | Credential store + `.env.example` | Values never returned raw on list/get |
| TS-CRY-02 | KMS backends `local` and `envelope` work; `aws|gcp|azure` **raise** (no fake cloud). | `app/core/trust/kms.py`; `unit_test/api/test_compliance_kms.py` | Cloud names fail loudly; envelope unwraps DEK |
| TS-CRY-03 | Mode B blob encrypt (GBE2) opt-in via `GRAPHYN_BLOB_ENCRYPTION_KEY` / KMS purpose `blob`. | `blob_crypto.py`; modeb compose env | Encrypted blobs decrypt only with key |
| TS-CRY-04 | Signed short-lived blob GET URLs; workers must not hold signing key. | modeb compose comments; transfer/security modules | Worker lacks `GRAPHYN_BLOB_SIGNING_KEY` |
| TS-CRY-05 | IR / logs must not embed secret values (C-002). | IR validation; credential-probe patterns; SEC UI tests | Secrets by name/ref only |

---

## TS-FE — Frontend architecture & state

| ID | Statement | How to verify | Pass criteria |
|---|---|---|---|
| TS-FE-01 | SPA is React 19 + Vite 8 + TS; path routing (no hash product nav). | `graphyn-ui/package.json`; `src/routes/` | HTML5 history paths; build succeeds |
| TS-FE-02 | Global state via Zustand (`appStore.ts`); feature folders under `src/features/`. | `src/store/appStore.ts`; `src/features/*` | Access/Workers/Orgs features present for F11–F18 surfaces |
| TS-FE-03 | Access UI covers Users, Orgs, Agents, metering/billing status (no fake Checkout). | `src/features/access`; ENTERPRISE Wave 6 | UI shows usage/quotas + webhook status honesty |
| TS-FE-04 | Workers UI exposes Queue tab with live pending list. | Workers feature + `GET /jobs/queue` client | Queue position/reason rendered |
| TS-FE-05 | UI build + vitest run in CI (`scripts/ui_build.sh`, `npm test`). | `.github/workflows/ci.yml` | Job green on tip |
| TS-FE-06 | Production UI image serves static via nginx proxying `/api` to API. | `graphyn-ui/Dockerfile`, `nginx.conf` | No API secrets baked into static bundle |

---

## TS-TST — Testing / CI hygiene

| ID | Statement | How to verify | Pass criteria |
|---|---|---|---|
| TS-TST-01 | Dedicated F18 unit tests exist and cover slots + fair-share + queue reasons. | `unit_test/core/test_f18_pipeline_queue_slots.py` (~172 lines) | Tests assert book/release and fair-share ordering |
| TS-TST-02 | Wave coverage: OIDC, orgs, metering/billing, KMS/compliance, agents, Mode B security. | `unit_test/api/test_{oidc,orgs,metering,compliance,agents}*.py`; distributed modeb tests | Named suites present and runnable offline where marked |
| TS-TST-03 | `pytest.ini` markers (`offline`, `heavy`, …) respected; CI uses Python 3.12. | `pytest.ini`; `ci.yml` | Smoke script installs + runs unit_test |
| TS-TST-04 | Dep sync: `setup.py` authoritative set; `requirements.txt` pins; `scripts/check_deps.py`. | Header comments in both files | No undeclared direct imports under `app/` for default install |
| TS-TST-05 | Hypothesis/ruff/mypy available via `.[dev]` extras. | `setup.py` extras_require | Dev extra pins present |

---

## TS-OBS — Observability / audit

| ID | Statement | How to verify | Pass criteria |
|---|---|---|---|
| TS-OBS-01 | Audit events recorded for authz-sensitive mutations with actor binding. | `record_audit`; API tests `test_audit_*` | Actor kind distinguishes user/agent/billing_webhook |
| TS-OBS-02 | Compliance export zip + retention config (`GET /compliance/export|status|retention`). | `app/core/trust/compliance.py`; routers | Export includes audit window + KMS/residency snapshots |
| TS-OBS-03 | Meter events + usage counters per org; admin UI reads them. | `MeterStore.usage` / `list_events`; Access Organizations | Counters move on project/cred/run actions |
| TS-OBS-04 | Job events capped (`GRAPHYN_JOB_EVENTS_MAX`) with monotonic `_seq`. | `queue.py` `_stamp_event_seq` | Cap enforced; seq survives trim |
| TS-OBS-05 | Billing webhook status endpoint states Checkout **Not shipped**. | `GET /billing/status`; `billing_webhook_status()` | Honesty string present; no fake payment UI |

---

## TS-OPS — Ops defaults vs secure defaults

| ID | Statement | How to verify | Pass criteria |
|---|---|---|---|
| TS-OPS-01 | Default compose is CPU-safe (no NVIDIA device); GPU is opt-in overlay. | `docker-compose.yml` vs `docker-compose.gpu.yml` | FaceRecognition/other GPU apps not evicted by default |
| TS-OPS-02 | Auth fail-closed in production/staging env. | `GRAPHYN_ENV: production` in compose + `auth_required()` | Cannot start usefully with empty token |
| TS-OPS-03 | Mode B HTTP egress defaults to restricted + allowlist. | `docker-compose.modeb.yml` `GRAPHYN_HTTP_EGRESS_*` | SSRF guards active for HTTP nodes |
| TS-OPS-04 | Plugin isolation default **subprocess**; container opt-in; TEE Not shipped. | `container_sandbox.py`; ENTERPRISE Gate B/E | Docs and `sandbox_status()` agree; no fake attestation |
| TS-OPS-05 | SMTP dry-run default on; credentials key optional with generated file. | compose / `.env.example` | Dry-run prevents accidental mail in lab |
| TS-OPS-06 | Residency enforce off by default; when on, fail-closed on region mismatch. | `GRAPHYN_RESIDENCY_*`; residency module | Enforce=1 blocks cross-region blob put |
| TS-OPS-07 | Docker Compose only — no Helm chart claimed. | compose header comment | Docs do not claim K8s chart shipped |

---

## Scoring sheet

| Category | Item count | Pass | Fail | Notes |
|---|---|---|---|---|
| TS-API | 6 | | | |
| TS-WRK | 9 | | | |
| TS-QSL | 8 | | | |
| TS-PER | 6 | | | |
| TS-AUTH | 7 | | | |
| TS-CRY | 5 | | | |
| TS-FE | 6 | | | |
| TS-TST | 5 | | | |
| TS-OBS | 5 | | | |
| TS-OPS | 7 | | | |
| **Total** | **64** | | | |

**Sign-off:** Reviewer ________  Date ________  Tip SHA `d7f5d70`  Result: Pass only if **zero** Fail and no Partial rationalizations.
