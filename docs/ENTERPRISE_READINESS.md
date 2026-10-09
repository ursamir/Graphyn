# Graphyn enterprise readiness

**Branch:** `test/example-06-plugins`  
**Baseline tip:** `fdcd9a7` (F11 — local users + RBAC + project membership)  
**Wave 1 tip:** F12 — OIDC/SSO  
**Wave 2 tip:** F13 — org tenancy  
**Wave 4 tip:** F15 — KMS/BYOK + residency + compliance export  
**Wave 5 tip:** F16 — container plugin sandbox (opt-in)  
**Wave 6 tip:** F17 — Agent / MCP identity + admin metering UI  
**F18.1 tip:** Security fix agent-disable + credential org gate (+ F18 queue/slots)  
**F19 tip:** `4053714` — full-review fixes F-01…F-25 (F-09 owned by F20) + live Mode B fixes; live image `newaudio3-graphyn-api:4053714b3de9` (`/app/BUILD_INFO.json` git_sha)  
**Owner:** Graphyn bot  
**Updated:** 2026-10-08 (F19 review fixes; Mode B re-verified live on Server-99; F18.1 security; F18 queue/slots; waves 1–6 closed)

Tracks expected enterprise features vs **Available / Partial / Missing**, with progress checkboxes and a wave plan. Source of truth for gaps: `/workspace/graphyn-enterprise-gap-matrix.md` (box) + live Server-99 tip. Update this file after each wave.

Status legend matches the gap matrix: **Available** = concrete code + tests/docs; **Partial** = real code incomplete vs gate; **Missing** = absent.

---

## Progress summary

| Gate | Target | Status | Wave |
|---|---|---|---|
| Deploy Mode B self-host | Available | [x] Available (F11 / Mode B; F19 re-verified live) | — |
| Deploy multi-tenant SaaS | Available | [~] Partial (org tenancy; not full SaaS product) | Wave 2 done |
| **A** IAM / SSO / RBAC | Available | [x] Available (local RBAC + OIDC) | **Wave 1 done** |
| **B** Confidential workers | Partial (software) | [~] Partial (no TEE) | later |
| **C** Orgs / quotas / billing | Available | [x] Orgs + quotas + metering/billing webhook | **Wave 2–3 done** |
| **D** Agent / MCP self-serve | Available | [x] Available (+ agent principals/RBAC) | **Wave 6 done** |
| **E** Compliance / residency / KMS | Available | [x] KMS local+envelope, residency, compliance pack | **Wave 4 done** |
| SLA / HA | optional | [ ] Out-of-scope | — |

---

## Checklist — expected features

### Deploy

- [x] **Available** — Mode B control + workers (`docker-compose.modeb.yml`, optional mTLS overlay)
- [x] **Available** — Mode A local single-process
- [x] **Available** — Org tenancy (`org_id` + membership + active org) — Wave 2
- [~] **Partial** — Multi-tenant SaaS productization: orgs/quotas/metering + admin usage UI + billing webhook status shipped; **Stripe Checkout / payment UI Not shipped** (no fake payment processing)

### Product C+D (ML + agent + workers + audit)

- [x] **Available** — One control plane for ML + general workflows
- [x] **Available** — Worker / plugin platform, ArtifactRef Mode B transfer
- [x] **Available** — Audit trail + export
- [~] **Partial** — Edge device OTA feedback loop — ship packages + wizard exist; closed-loop device fleet ack/telemetry needs hardware not present on this host (left Partial honestly)

### Gate A — IAM / SSO / RBAC

- [x] **Available** — Shared / named API Bearer (REST + MCP)
- [x] **Available** — Worker-scoped tokens + join/enrollment (F11)
- [x] **Available** — Optional mTLS worker identity
- [x] **Available** — Local username/password users + sessions (F11)
- [x] **Available** — Global roles + per-project membership ACL (F11)
- [x] **Available** — Access UI: Users & roles, Project members, My account (F11)
- [x] **Available** — SSO / OIDC login (discovery, PKCE, callback, session consistent with local users+RBAC)
- [x] **Available** — Password login remains fallback when OIDC off / allowed
- [x] **Available** — Login UI wired for SSO
- [x] **Available** — Unit + API tests for OIDC
- [x] **Available** — TRUST_MODEL / KNOWN_ISSUES honesty (RBAC + OIDC + org tenancy + quotas shipped)
- [x] **Available** — RBAC edges hardened (project.members + users.admin; OIDC-only password change guard)
- [x] **Available** — Org / tenant membership APIs (`org_id`) — Wave 2

### Gate B — Confidential workers

- [x] **Available** — Plugin allowlist / hash pins / trusted flag
- [x] **Available** — Isolated plugin subprocess + RestrictedUnpickler
- [~] **Partial** — AST-filtered `python_code` (not a sandbox)
- [ ] **Missing** — TEE / SGX / hardware confidential compute
- [x] **Available** — Mode B volume isolation (no shared host workspace)

### Gate C — Orgs / quotas / billing

- [x] **Available** — Pool / per-worker claim quotas
- [x] **Available** — Multi-tenant org / workspace DB — **Wave 2**
- [x] **Available** — Billing webhook seam + meter events (Wave 3)
- [x] **Available** — Per-org quotas (seats, projects, runs/day, credentials) — Wave 3
- [x] **Available** — Admin metering / usage UI + billing webhook status (Access → Organizations) — Wave 6
- [x] **Available** — Pipeline job queue + per-worker slot booking + org fair-share (F18)
- [ ] **Not shipped** — Stripe Checkout / invoices / payment methods UI

### Gate D — Agent / MCP

- [x] **Available** — MCP tool surface (~80 tools)
- [x] **Available** — Agent proposals inbox
- [x] **Available** — Plugin + template self-serve; credentials without secrets in IR
- [x] **Available** — Agent principals (`kind=agent`, `gxa_…` tokens) + per-agent RBAC (global roles + project memberships) for API/MCP — Wave 6
- [~] **Partial** — Agent ↔ OIDC: optional `oidc_client_id` label for audit; live client_credentials exchange **Not shipped** (admin-minted tokens instead)

### Gate E — Compliance

- [x] **Available** — Credential encrypt-at-rest
- [x] **Available** — Mode B blob encrypt (GBE2, opt-in)
- [x] **Available** — HTTP egress mode + allowlist + SSRF guards
- [x] **Available** — Signed short-lived blob GET URLs
- [x] **Available** — Data residency / region pinning (`org.region` + `GRAPHYN_RESIDENCY_*`, fail-closed opt-in)
- [x] **Available** — Compliance export pack (`GET /api/v1/compliance/export` zip + retention config)
- [x] **Available** — Customer-managed KMS / BYOK (`GRAPHYN_KMS_BACKEND=local|envelope`; cloud KMS is an extension point, not stubbed)
- [x] **Available** — Opt-in container plugin sandbox (`GRAPHYN_PLUGIN_ISOLATION=container`; subprocess default)
- [ ] **Not shipped** — TEE / SGX attested execution (no hardware path on this host)

---

## Wave plan

| Wave | Scope | Exit criteria | Owner | Status |
|---|---|---|---|---|
| **Wave 1 — Gate A** | OIDC/SSO (configurable IdP), password fallback, Login UI, tests, doc honesty, RBAC edge harden | OIDC on/off via env; full login path; no stubs; Mode B api+ui rebuilt; tests green; commit F12 | Graphyn bot | **Done** |
| **Wave 2 — Org tenancy** | `org_id` / org membership isolation (not billing yet) | Schema + API + ACL isolation + tests; separate commit | Graphyn bot | **Done** |
| **Wave 3** | Billing / metering hooks + per-org quotas | APIs + webhook seam + enforcement | Graphyn bot | **Done** |
| **Wave 4** | KMS/BYOK + residency + compliance export | Working local+envelope KMS; org region fail-closed; compliance zip; docs | Graphyn bot | **Done** |
| **Wave 5** | Container plugin sandbox | Opt-in docker/podman isolation; egress allowlist story; TEE honesty | Graphyn bot | **Done** |
| **Wave 6** | Agent / MCP identity | Agent principals + tokens + RBAC + Access UI; admin metering UI; docs | Graphyn bot | **Done** |

---

## Wave 1 detail (Gate A)

### Expected behaviour

1. **Off by default.** `GRAPHYN_OIDC_ENABLED` unset/0 → behaviour identical to F11 (password + token).
2. **On:** discovery from `GRAPHYN_OIDC_ISSUER`, authorization code + **PKCE** (S256), callback exchanges code, validates ID token (JWKS) or userinfo, finds/creates user in `UserStore`, issues the same **session credential** as password login (`gxs_…`, 12 h).
3. **Password fallback** remains when `GRAPHYN_OIDC_PASSWORD_LOGIN` is not `0`.
4. **UI:** Login shows “Sign in with SSO” when auth-status reports OIDC enabled; ticket exchange avoids putting the session token in the IdP redirect query long-term.
5. **RBAC unchanged** for authorization — OIDC users are `kind=user` with roles/memberships.

### Env (see `.env.example`)

`GRAPHYN_OIDC_ENABLED`, `GRAPHYN_OIDC_ISSUER`, `GRAPHYN_OIDC_CLIENT_ID`, `GRAPHYN_OIDC_CLIENT_SECRET` (optional public+PKCE), `GRAPHYN_OIDC_REDIRECT_URI`, `GRAPHYN_OIDC_SCOPES`, `GRAPHYN_OIDC_AUTO_PROVISION`, `GRAPHYN_OIDC_DEFAULT_ROLES`, `GRAPHYN_OIDC_PASSWORD_LOGIN`, `GRAPHYN_OIDC_UI_ORIGIN`.

---

## Wave 2 detail (org tenancy)

1. **Default org migration** — existing users/projects/credentials fold into `org_default` (`slug=default`).
2. **APIs** — `GET/POST /orgs`, `GET/PATCH /orgs/{id}`, `POST /orgs/{id}/activate`, members CRUD.
3. **Active org** — session credential meta + `users.active_org_id` + optional `X-Graphyn-Org-Id`.
4. **Isolation** — projects / runs (via project filter) / credentials / workers scoped to active org; cross-org 403.
5. **UI** — Access → Organizations (switch, create, members).
6. **Honesty** — ORG-1 marked shipped for org tenancy.

---

## Wave 3 detail (metering / billing)

1. **Quotas** — `PUT/GET /orgs/{id}/quotas` (seats, projects, runs/day, credentials); defaults in `DEFAULT_QUOTAS`.
2. **Usage** — `GET /orgs/{id}/usage` live counters; `GET /orgs/{id}/meter-events` export.
3. **Enforcement** — project create, credential create, seat add, run-async check quotas (409 `quota_exceeded`).
4. **Billing webhook** — `POST /billing/webhook` HMAC (`GRAPHYN_BILLING_WEBHOOK_SECRET` / Stripe-Signature v1); records delivery + meter event.
5. **Not included** — Stripe Checkout, invoices UI, payment methods (hooks only).


## Wave 4 detail (compliance / KMS / residency)

1. **KMS / BYOK** — `app.core.trust.kms`: `KeyProvider` protocol; `LocalFileKeyProvider` (default); `LocalEnvelopeKeyProvider` (CMK wraps DEK under `{GRAPHYN_HOME}/kms/`). Credentials + Mode B blob keys resolve via `resolve_data_key`. `GRAPHYN_KMS_BACKEND=aws|gcp|azure` **raises** (no fake cloud calls). Plug AWS/GCP later by implementing `get_data_key` and registering the backend.
2. **Residency** — `orgs.region` column + API create/patch; `GRAPHYN_RESIDENCY_REGION` on the node; `GRAPHYN_RESIDENCY_ENFORCE=1` fail-closed on blob put / workspace materialize when regions disagree.
3. **Compliance pack** — `GET /api/v1/compliance/status|export|retention`; zip includes audit JSONL (retention-window filtered), KMS/residency snapshots, doc excerpts. `GRAPHYN_AUDIT_RETENTION_DAYS` (default 365).
4. **Honesty** — Cloud KMS and TEE called out as Not shipped.

## Wave 5 detail (container plugin sandbox)

1. **Default** remains subprocess (`GRAPHYN_PLUGIN_ISOLATION=subprocess`).
2. **Opt-in** `container` / `docker` / `podman` runs the isolated worker via `docker|podman run` with bind mounts at identical absolute paths, `no-new-privileges`, non-root user.
3. **Egress** — same `GRAPHYN_HTTP_EGRESS_*` allowlist/mode inherited into the container; network `none|bridge|allowlist` (allowlist uses bridge + in-process validators — not a custom CNI DNS filter).
4. **TEE/SGX** — Not shipped (documented; no fake attestation).


## Wave 6 detail (Agent / MCP identity)

1. **Agent store** — `app.core.trust.agents`: slug, roles (same global ROLE_NAMES), project memberships, org_id, optional `oidc_client_id` label.
2. **Tokens** — credential kind `agent` → opaque `gxa_…`; mint/revoke via `/api/v1/agents/{id}/tokens`.
3. **Identity / RBAC / MCP** — `kind=agent` shares the user permission table; MCP `check_auth` + `resolve_mcp_actor` bind `actor=agent:<slug>` for audit.
4. **UI** — Access → Agents; Organizations panel shows usage/quotas + billing webhook status (no Checkout).
5. **Honesty** — TEE Not shipped; Stripe Checkout Not shipped; Edge OTA remains Partial (no device fleet hardware).

## F18 detail (pipeline queue + slot booking)

Extends the existing Mode B `JobQueue` / worker `max_claimed` control plane (no new broker):

1. **Per-worker slots (A)** — `max_claimed` is the slot cap (`max_slots`); `used_slots` = claimed+running jobs. Claim books a slot atomically under `mutate_queue`; complete/fail/cancel/reclaim releases it. When full, jobs stay pending (`queue_reason=no_capacity` when pinned / all eligible full).
2. **Global pool (B)** — one shared pending order; idle workers with free slots pull the next eligible job via `POST /jobs/claim`. `GET /jobs/queue` lists position + reason + worker slot snapshot. Workers UI → Queue tab shows the live list.
3. **Org fair-share (C)** — F14 quotas gained `max_concurrent_jobs` / `max_queued_jobs`. Claim prefers the org with lower running/quota utilization (FIFO within that). Over concurrent → `queue_reason=org_quota`; over queue depth → enqueue refused (`QuotaExceeded`).

Honesty: this is job-level (node) queueing on shared workers, not a separate SaaS run-admission product. Stripe Checkout still Not shipped.

## F19 detail (full-review fixes + live Mode B)

Review: `docs/reviews/full/SUMMARY.md` (untracked). Per-finding commits and evidence: `docs/reviews/full/FIXES_F19.md` (untracked).

**Mode B (F-03): the basis for "Available"** (Server-99, modeb overlay, worker `s99-ml`):
- A multi-node run succeeded: local `dataset_ingest` → worker `feature_frontend` → local `dataset_builder` / `model_builder` → worker `trainer` → local `evaluator` → worker `edge_optimizer`. Artifacts crossed in both directions, the sealed record verifies, and `meta.environment.git_commit` is set. Run ids are in FIXES_F19.md.
- `GET /system/readiness` counts only live workers (`worker_count`) and reports `stale_worker_count` separately.
- Defects that only showed up on the live two-container stack, all fixed:
  1. `GET /runs` returned 500 on a NaN metric (F19.24). `SafeJSONResponse` is now the default response class, the journal writes strict JSON, and the evaluator omits an undefined ROC AUC.
  2. Control and worker raced to rebuild the shared plugin venvs directory, and the worker lost `edge_optimizer` (F19.23 / F19.25). Fixed with a per-venv `flock`, self-healing for half-built venvs, and no redundant cross-container rebuild.
  3. F18 put `worker_slots` inside the claimed job, so every remote job failed with `extra_forbidden` (F19.26).
  4. The API deadlocked because the queue and the workers shared one state-store lock, which inverted against the registry lock (F19.27).
  5. Requested cancels were logged as `ERROR` (F19.28).
  6. The log noise found live is cleaned up (F19.30–F19.32):
     - `mcp_tool_call` no longer needs the optional MCP SDK; only the stdio server does.
     - `python_code` sees `csv_table` results as rows.
     - A worker completion fenced with 409 is logged as an expected drop.
     - An isolated plugin failure logs a single WARNING line.
     - Missing-credential failures are logged as WARNING.
- RT-CANCEL-003 was checked live: a run was cancelled mid-training, the worker terminated the isolated process group, and its late `complete` got **409 `run_cancelled`** and was dropped.

**Separation of duties and attribution (F-08, F-20):**
- Prod promotion requires the requester and the approver to be different people (`403 separation_of_duties`).
- An admin can waive this per model with the promotion policy (`require_separation_of_duties: false`). The waiver is audited as `sod_waived` / `sod_waived_by`.
- Calls made with the shared `GRAPHYN_API_TOKEN` are attributed to `GRAPHYN_API_TOKEN_ACTOR` (default `operator`) and flagged as unverified. Use named tokens (`GRAPHYN_API_TOKENS`) or user accounts to attribute actions to individuals.

**Known limits:**
- `segmenter` `speaker_turn` uses offline diarization (KNOWN_ISSUES SEG-DIAR-1).
- A Mode B run can be orphaned when the control plane restarts (KNOWN_ISSUES DIST-ORPHAN-1).
- Edge targets (Arduino / Zephyr / CMSIS-Pack), ship signing and SoD are covered by F19 unit tests. They were not re-run on the rebuilt live stack.

## Change log

| When (IST) | Tip / commit | Notes |
|---|---|---|
| 2026-10-07 | `fdcd9a7` F11 | Local users+RBAC+project ACL baseline |
| 2026-10-07 | (this file) | Checklist created |
| 2026-10-07 | F12 | Wave 1 Gate A: OIDC/SSO + docs + tests |
| 2026-10-07 | F13 | Wave 2: org tenancy + isolation + Access UI |
| 2026-10-07 | F14 | Wave 3: quotas + metering + billing webhook |
| 2026-10-07 | F15 | Wave 4: KMS/BYOK + residency + compliance export |
| 2026-10-07 | F16 | Wave 5: container plugin sandbox + TEE honesty |
| 2026-10-07 | F17 | Wave 6: agent principals/RBAC + admin metering UI |
| 2026-10-07 | F18 (this commit on branch) | Pipeline queue + slot booking + org fair-share |
| 2026-10-07 | F18.1 | Security: disabled/deleted agent `gxa_` no longer elevates to operator; credential DELETE/bind_default org gate; QuotaExceeded→409; complete() `_seq`; billing_webhook audit actor_kind |
| 2026-10-08 | F19.1–F19.22 (`2a9d6a0`…`2c55cfe`) | Full-review fixes: Mode B ArtifactRef root, SSRF-safe egress default, pipeline DELETE, outputs listing, payload contract, llm honesty, object_store put, csv symlinks, SoD + actor attribution, vitest, experiments metrics, build provenance, diarization, realtime backends, real edge targets, signed ship packages, required config, port typing + wire checks, doc counts, F18 carried (OpenAPI models, RT-CANCEL-003, contrast, labels, queue deep link) |
| 2026-10-08 | F19.23–F19.32 (`c7bc93d`…`4053714`) | Live Mode B fixes: shared-venv flock + self-heal, NaN-safe JSON, claim payload, state-store lock split (deadlock), cancel log level; clean container logs (MCP SDK-free in-process catalog, python_code table rows, 409 drop wording, one-line isolated failures, needs-credentials WARNING); suite-order test isolation |

---

*FaceRecognition and unrelated dirty-tree edits are out of scope for these waves.*
