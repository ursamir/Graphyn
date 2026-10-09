# F18 Requirements & Logical Checklist — Graphyn

| Field | Value |
|---|---|
| **Tip** | `d7f5d707d3c7050608f5ef738e551e217ffb26f9` (`d7f5d70`) — **F18** |
| **Branch** | `test/example-06-plugins` |
| **Normative inputs** | `docs/REQUIREMENTS_SPEC.md` (SRS), `docs/ENTERPRISE_READINESS.md` F11–F18, `docs/TRUST_MODEL.md`, `docs/DISTRIBUTED_EXECUTION.md`, live code under `app/` |
| **Honesty rule** | **Partial = Not Met** (Fail). Available only if concrete code + tests/docs. Stubs, labels-without-behavior, or “coming soon” UI = Not Met. |
| **Out of scope** | FaceRecognition; Stripe Checkout (explicitly Not shipped); TEE/SGX; cloud KMS APIs; git push |

### Status values

| Status | Meaning |
|---|---|
| **Met** | Implemented end-to-end; verifiable Pass criteria below |
| **Not Met** | Missing, Partial, docs-only, or dishonest claim |
| **N/A (honest)** | Explicitly Not shipped at this tip — pass only if docs/UI say Not shipped (no fake UX) |

---

## RQ-IAM — Identity, SSO, RBAC (F11–F12 / Gate A)

| ID | Requirement (must-have) | How to verify | Met criteria |
|---|---|---|---|
| RQ-IAM-01 | Shared/named API Bearer authenticates REST + MCP when configured. | `app/api/main.py` bearer; `app/mcp/auth.py` | Invalid/missing token → 401 / MCP unauthorized |
| RQ-IAM-02 | Local username/password users + session credentials (`gxs_…`). | `UserStore`; Access → Users | Login issues session; RBAC roles apply |
| RQ-IAM-03 | Global roles + per-project membership ACL. | `rbac.py` `required_permission`; project members API | Cross-project write without membership → 403 |
| RQ-IAM-04 | OIDC/SSO: authorization-code + PKCE; discovery; ID token/userinfo; provisions local user; same session type. | `oidc.py`; `test_oidc_auth.py` | Full path works when enabled; off = unchanged F11 |
| RQ-IAM-05 | Password fallback controllable via `GRAPHYN_OIDC_PASSWORD_LOGIN`. | env + login UI | `0` hides/disables password when SSO on |
| RQ-IAM-06 | Worker join/enrollment + worker-scoped tokens. | enrollment in users/distributed; TRUST_MODEL | Worker token limited to worker routes as designed |
| RQ-IAM-07 | Optional mTLS worker identity. | `docker-compose.modeb-mtls.yml` | Enabled path requires client cert (N/A if overlay unused, but code must exist) |

---

## RQ-ORG — Org tenancy & isolation (F13 / Wave 2)

| ID | Requirement | How to verify | Met criteria |
|---|---|---|---|
| RQ-ORG-01 | Default org migration (`org_default`) folds legacy users/projects/credentials. | `ensure_tenancy_migrated` | Fresh upgrade assigns default org |
| RQ-ORG-02 | Org CRUD + members + activate APIs. | `app/api/routers/orgs.py` | Create/switch/list members works |
| RQ-ORG-03 | **Invariant:** projects belonging to org A are invisible/forbidden to org B actors. | `test_orgs_tenancy.py`; project list with alternate active org | Cross-org 403/empty — never leak |
| RQ-ORG-04 | **Invariant:** credentials scoped to org; cannot resolve/use cross-org credential by id. | credential store org_id + API | Cross-org get/update → 403/404 |
| RQ-ORG-05 | Active org from session meta + optional `X-Graphyn-Org-Id`. | `bind_org_to_identity` | Header cannot escalate into org without membership |
| RQ-ORG-06 | Multi-tenant SaaS productization beyond orgs (full billing product) is **Not shipped** — honesty required. | ENTERPRISE Deploy row; Access UI | UI/docs must not claim full SaaS billing |

---

## RQ-QUO — Quotas, metering, billing webhook (F14 / Wave 3 + F18 fields)

| ID | Requirement | How to verify | Met criteria |
|---|---|---|---|
| RQ-QUO-01 | Per-org quotas: seats, projects, runs/day, credentials. | `MeterStore` / `PUT /orgs/{id}/quotas` | Enforcement returns 409 `quota_exceeded` |
| RQ-QUO-02 | F18 adds `max_concurrent_jobs` (default 8) and `max_queued_jobs` (default 100). | `DEFAULT_QUOTAS`; schema ALTER | Fields persisted and read back |
| RQ-QUO-03 | Usage + meter-events export APIs. | `GET /orgs/{id}/usage`, `…/meter-events` | Counters reflect creates/runs |
| RQ-QUO-04 | Billing webhook HMAC seam (`GRAPHYN_BILLING_WEBHOOK_SECRET` / Stripe-Signature). | `POST /billing/webhook`; `verify_billing_webhook_signature` | Bad signature → 401; good → delivery recorded |
| RQ-QUO-05 | **Billing claims honesty:** status endpoint states Checkout / payment methods **Not shipped**. | `GET /billing/status` | No fake charge/Checkout UI |
| RQ-QUO-06 | Admin metering UI under Access → Organizations. | UI feature access | Shows usage/quotas + webhook status |

---

## RQ-KMS — KMS, residency, compliance (F15 / Wave 4 / Gate E)

| ID | Requirement | How to verify | Met criteria |
|---|---|---|---|
| RQ-KMS-01 | Local + envelope KMS providers resolve data keys for credentials/blob. | `kms.py` `resolve_data_key` | Envelope seals DEK under `{GRAPHYN_HOME}/kms/` |
| RQ-KMS-02 | Cloud KMS names raise — extension point, not stubbed success. | Set `GRAPHYN_KMS_BACKEND=aws` in test | Raises `KmsError` / hard fail |
| RQ-KMS-03 | Org `region` + optional residency enforce fail-closed. | residency module + org patch | Enforce=1 blocks mismatched blob put/materialize |
| RQ-KMS-04 | Compliance export pack + retention knobs. | `/compliance/export` | Zip contains audit JSONL window + snapshots |
| RQ-KMS-05 | Credential encrypt-at-rest + Mode B blob encrypt opt-in. | credential store; `blob_crypto.py` | Ciphertext at rest; plaintext not in DB/files |

---

## RQ-SND — Plugin sandbox & confidential compute (F16 / Gate B)

| ID | Requirement | How to verify | Met criteria |
|---|---|---|---|
| RQ-SND-01 | Default isolation = subprocess; container/docker/podman opt-in. | `plugin_isolation_mode()` | Default subprocess without env |
| RQ-SND-02 | Container path: no-new-privileges, non-root, bind mounts, network mode. | `run_in_container` | Flags present in docker/podman argv |
| RQ-SND-03 | HTTP egress allowlist inherited into container; CNI DNS filter Not shipped (honest). | `sandbox_status()` docstring | Docs admit allowlist is in-process validators |
| RQ-SND-04 | TEE/SGX **Not shipped** — must not claim attested hardware. | ENTERPRISE Gate B; sandbox_status | Honesty strings; no attestation APIs |
| RQ-SND-05 | `python_code` AST filter is **not** a sandbox (TRUST_MODEL). | node metadata / docs | UI/docs must not label it sandbox |
| RQ-SND-06 | RestrictedUnpickler on distributed/isolated plugin loads (DIST-010). | pickle trust tests / modules | Allowlist enforced |

---

## RQ-AGT — Agent / MCP identity (F17 / Wave 6 / Gate D)

| ID | Requirement | How to verify | Met criteria |
|---|---|---|---|
| RQ-AGT-01 | Agent store with roles + project memberships + org_id. | `agents.py`; Access → Agents | CRUD + list scoped |
| RQ-AGT-02 | Mint opaque `gxa_…` tokens; token shown once. | `mint_token` | Secret only in mint response |
| RQ-AGT-03 | **Invariant:** agent tokens are least-privilege — only granted roles/memberships. | API call with viewer agent vs admin route | Excess permission → 403 |
| RQ-AGT-04 | **Invariant:** revoked tokens are dead (API + MCP). | `revoke_token` then call | 401/unauthorized after revoke |
| RQ-AGT-05 | Disabled agent cannot mint; existing tokens should fail auth policy. | disable agent + request | Fail closed |
| RQ-AGT-06 | MCP actor binds `agent:<slug>` for audit. | `resolve_mcp_actor` | Audit shows agent principal |
| RQ-AGT-07 | OIDC client_credentials for agents **Not shipped** (`oidc_client_id` label only). | ENTERPRISE Gate D Partial honesty | Docs/UI say Not shipped — Met as honesty; claiming live exchange = Not Met |
| RQ-AGT-08 | MCP tools do not return secret values (MCP-001). | list credentials via MCP | Redacted / names only |

---

## RQ-QSL — Pipeline queue, slots, fair-share (F18)

| ID | Requirement | How to verify | Met criteria |
|---|---|---|---|
| RQ-QSL-01 | Per-worker slot cap = `max_claimed`; used_slots = claimed+running. | `slots.py`; workers API | Numbers consistent under load |
| RQ-QSL-02 | **Invariant:** slot book on claim and release on complete/fail/cancel/reclaim is atomic w.r.t. durable queue mutate — **no slot leak**. | Concurrent claim + cancel tests; inspect `used_slots` after cancel/fail | used_slots returns to prior baseline |
| RQ-QSL-03 | When worker full, jobs remain pending; `queue_reason` ∈ {`no_capacity`,`org_quota`,`waiting_worker`}. | `infer_queue_reason`; `GET /jobs/queue` | Reasons accurate for pinned vs pool |
| RQ-QSL-04 | Global shared pending order; workers pull next eligible via claim. | `JobQueue.claim` + fair-share picker | Idle worker with free slot obtains work |
| RQ-QSL-05 | **Invariant:** two orgs sharing workers cannot starve each other unfairly — dispatch prefers lower utilization (`running/max_concurrent`), FIFO within org. | `_pick_fair_share_job`; F18 unit tests with two orgs | Org at high util yields to org at low util when both pending |
| RQ-QSL-06 | Over `max_concurrent_jobs` → claim blocked / `queue_reason=org_quota`. | force concurrent cap | No extra claim for that org |
| RQ-QSL-07 | Over `max_queued_jobs` → enqueue refused (`QuotaExceeded`). | enqueue beyond depth | 409/error; no silent accept |
| RQ-QSL-08 | Pool caps (`GRAPHYN_POOL_MAX_CLAIMED`) still enforced alongside slots. | `parse_pool_max_claimed` / `_quota_blocks_claim` | Pool-at-quota blocks claim |
| RQ-QSL-09 | Queue visibility in API + Workers UI Queue tab. | router + UI | Operators can see position/reason/slots |
| RQ-QSL-10 | Honesty: job-level Mode B queue ≠ separate SaaS admission product; Stripe still Not shipped. | ENTERPRISE F18 detail | Docs match |

---

## RQ-DIST — Distributed execution & ArtifactRef (SRS DIST-* / PERS-*)

| ID | Requirement | How to verify | Met criteria |
|---|---|---|---|
| RQ-DIST-01 | Workers register/heartbeat/deregister (DIST-001/008/011). | workers router + registry | Stale workers skipped |
| RQ-DIST-02 | Atomic claim CAS (DIST-020/PERS-015); concurrent claim single winner (DIST-022). | store mutate_queue tests | Exactly one claimed_by |
| RQ-DIST-03 | Lease fencing on complete (DIST-023); reclaim increments generation (DIST-024/031). | complete/reclaim paths | 409 on stale lease |
| RQ-DIST-04 | Cancel durable; success complete after cancel forbidden (DIST-034). | cancel then complete | Rejected |
| RQ-DIST-05 | **Invariant:** ArtifactRef multi-worker without shared volumes — wire uses `artifact://` + blob HTTP only (DIST-005/009). | modeb volumes; `strip_host_paths`; artifact pack | Worker without control workspace still runs nodes |
| RQ-DIST-06 | Unreclaimed host paths fail closed before put. | `UnreclaimedHostPathError` / scan | Put rejected if source_path remains |
| RQ-DIST-07 | Content hash on hydrate; mismatch fails. | `hydrate_ref_bytes` | Hash mismatch error |
| RQ-DIST-08 | Durable queue/registry default for Mode B (DIST-035). | store selection | Not memory-only in compose Mode B |
| RQ-DIST-09 | At-least-once delivery honesty (DIST-SEM-001); exactly-once not promised for side effects. | DISTRIBUTED_EXECUTION / SRS | Docs state at-least-once |

---

## RQ-AUD — Audit, prove, ops NFRs

| ID | Requirement | How to verify | Met criteria |
|---|---|---|---|
| RQ-AUD-01 | Append-only audit JSONL with actor on sensitive mutations. | `audit.py`; audit API tests | Events for org/agent/quota/run control |
| RQ-AUD-02 | Audit chain verify detects tampering. | `verify_audit_chain` | Break → failed verify |
| RQ-AUD-03 | Provenance / lineage for artifacts (RT-008 / Prove pillar). | artifacts lineage API | Backtrack artifact → run/node |
| RQ-AUD-04 | Artifact commit after cancel forbidden (RT-CANCEL-003). | cancel then register artifact | 409/`run_cancelled` |
| RQ-AUD-05 | Auth fail-closed in production compose (ops). | compose env | Empty token rejected |

---

## RQ-ENT — Enterprise readiness matrix honesty (F11–F18)

Map ENTERPRISE_READINESS gates to review outcomes. **Partial rows must Fail the “Available” claim.**

| ID | Gate / claim | Expected at F18 tip | Met criteria |
|---|---|---|---|
| RQ-ENT-01 | Gate A IAM/SSO/RBAC = Available | OIDC + local RBAC | Code+tests; not Partial |
| RQ-ENT-02 | Gate B Confidential workers = Partial (no TEE) | Software isolation only | Docs say Partial/Missing TEE — claiming Available TEE = Not Met |
| RQ-ENT-03 | Gate C Orgs/quotas/billing = Available for hooks; Checkout Not shipped | Quotas+webhook+F18 queue | Checkout honesty |
| RQ-ENT-04 | Gate D Agent/MCP = Available; OIDC client_credentials Not shipped | Agent tokens | Label-only oidc_client_id |
| RQ-ENT-05 | Gate E Compliance/KMS = Available for local+envelope; cloud KMS Not shipped | kms raise on cloud | No fake AWS calls |
| RQ-ENT-06 | F18 queue/slots/fair-share = Available | queue.py/slots/quotas + tests | F18 tests green |
| RQ-ENT-07 | Edge OTA closed-loop = Partial (no device fleet HW) | Honesty | Must remain Partial |
| RQ-ENT-08 | Multi-tenant SaaS productization = Partial | Orgs yes; full SaaS no | Honesty in Deploy section |

---

## Logical invariants summary (quick fail list)

Reviewers can Fail the tip immediately if any invariant breaks:

1. **Fair-share:** Two orgs with pending jobs on a shared worker — high-utilization org does not permanently starve low-utilization org (`fair_share_key` / `_pick_fair_share_job`).
2. **Slot lifecycle:** Book on claim; release on complete/fail/cancel/reclaim/worker-release; `used_slots` never drifts above real claimed+running.
3. **Org isolation:** No cross-org project/credential/run access via API or MCP.
4. **Agent least privilege + revoke:** `gxa_` token cannot exceed roles; revoke → dead.
5. **ArtifactRef without shared volumes:** Mode B worker succeeds using blobs only; host paths stripped.
6. **Billing honesty:** Webhook/metering ≠ Checkout; status must say Not shipped.
7. **CAS claim:** Two concurrent claims on one job → one winner.
8. **Partial = Not Met:** Any ENTERPRISE row marked Partial cannot be scored Available.

---

## Scoring sheet

| Category | Item count | Met | Not Met | N/A (honest) |
|---|---|---|---|---|
| RQ-IAM | 7 | | | |
| RQ-ORG | 6 | | | |
| RQ-QUO | 6 | | | |
| RQ-KMS | 5 | | | |
| RQ-SND | 6 | | | |
| RQ-AGT | 8 | | | |
| RQ-QSL | 10 | | | |
| RQ-DIST | 9 | | | |
| RQ-AUD | 5 | | | |
| RQ-ENT | 8 | | | |
| **Total** | **70** | | | |

**Sign-off:** Reviewer ________  Date ________  Tip SHA `d7f5d70`  
**Rule:** Any **Not Met** on a must-have / invariant → overall **Fail**. N/A (honest) does not Fail if honesty is correct.
