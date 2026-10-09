# Trust model — authorization, secrets, workflow nodes

> Option A+: **local multi-user RBAC** (F11) plus optional **OIDC/SSO** (Wave 1), **org tenancy** (Wave 2), quotas/metering (Wave 3), **KMS/BYOK + residency + compliance export** (Wave 4), and **opt-in container plugin isolation** (Wave 5; subprocess default), plus **agent principals / MCP RBAC** (Wave 6). Shared bearer / named tokens remain break-glass. TEE/SGX and cloud KMS APIs are **Not shipped** — see `docs/ENTERPRISE_READINESS.md`.

Graphyn is a **multi-org, single-control-plane** product: local username/password users (and optional OIDC) carry global roles + per-project membership ACL + **organization membership** with an active `org_id` that scopes listings. A shared `GRAPHYN_API_TOKEN` (and named token map) still works as operator break-glass. There is **no** multi-org / `org_id` SaaS tenancy yet.

---

## 1. Authentication modes (API + MCP)

| Mode | When | Behaviour |
|---|---|---|
| **Unauthenticated-dev** | `GRAPHYN_API_TOKEN` unset **and** auth not required | All `/api/v1/*` routes and MCP tools accept callers without a token. Intended for local single-user development only. |
| **Shared bearer** | `GRAPHYN_API_TOKEN` set | REST requires `Authorization: Bearer <token>`; MCP requires `_meta.auth_token`. Same token for every operator and worker. |
| **Named tokens** | `GRAPHYN_API_TOKENS` and/or `GRAPHYN_API_TOKENS_FILE` set | Each listed token is accepted (REST + MCP) alongside `GRAPHYN_API_TOKEN`. A mapped token **binds the audit actor** (`actor_verified: true`). Text form: `name:token` (operator) or `name:token:worker[:worker_id]`; JSON: `{"token":"name"}` or `{"token":{"name","kind","worker_id"}}`. **Operator** tokens keep full control-plane access. **Worker-scoped** tokens (`kind=worker`) may only act as their bound `worker_id` on `/jobs/*`, worker heartbeat, claim/complete/events, and blob put/get (header `X-Graphyn-Worker-Id` or body/query). Fail closed when auth is configured. |
| **Local users + sessions** | At least one user in `UserStore` (`GRAPHYN_HOME/auth/users.db`) | `POST /api/v1/auth/login` (username/password) issues a 12 h session bearer (`gxs_…`). Personal API tokens (`gxu_…`) from Access. Identity `kind=user` carries roles + project memberships; RBAC middleware enforces route + project ACL (`app.core.trust.rbac`). |
| **Organizations** | Always (default org migrated on upgrade) | `GET/POST /orgs`, activate, members. User identity carries `org_id` / `org_role` / `orgs`. Projects, credentials and workers list within the active org. |
| **OIDC / SSO** | `GRAPHYN_OIDC_ENABLED=1` + issuer + client id | Authorization-code + PKCE; discovery from issuer; callback verifies ID token (JWKS) or userinfo; provisions/links a local user; issues the **same session credential** as password login. Password login remains available unless `GRAPHYN_OIDC_PASSWORD_LOGIN=0`. Public routes: `/auth/oidc/{config,start,callback,finish}`. |
| **Fail-closed** | `GRAPHYN_AUTH_REQUIRED=1` **or** `GRAPHYN_ENV` ∈ {`production`,`prod`,`staging`} | Empty `GRAPHYN_API_TOKEN` is rejected when no users/OIDC path covers the caller (401 / MCP unauthorized). Set a token or configure users/OIDC before exposing the API. |

**Audit identity.** With the single shared token (or no auth) the actor is the self-declared `X-Actor` header (or `"unidentified"`) and is recorded `actor_verified: false`. `"system"` is reserved for internal background jobs (no HTTP request). `GET /api/v1/me` shows the caller how they will be recorded.

Unauthenticated by design (always): `GET /`, `GET /health`. `POST /api/v1/hooks/{workspace}/{pipeline}` is outside the global bearer dependency but **authenticates itself** (§1a).  
**DNS-rebinding guard (unauthenticated-dev):** while `GRAPHYN_API_TOKEN` is unset, every request whose `Host` is not `localhost` / `*.localhost` / an IP literal (incl. `[::1]`) / `graphyn-api` (compose service name, used by the UI nginx proxy for `/files`) / `testserver` gets **403**. Add LAN / DNS names with `GRAPHYN_ALLOWED_HOSTS=name1,name2` (`*` disables the guard), or set a token (guard is off once a token is configured). IP literals are always accepted because a rebinding page can only present its own DNS name.  
Static mounts `/files`, `/input-files`, `/run-files` use the **same** bearer policy as `/api/v1` when a token is configured.  
OpenAPI UI (`/docs`, `/redoc`, `/openapi.json`) is not bearer-gated — treat the API host as operator-trusted network.

Sensitive routers (plugins install, credentials, workers admin/job claim, deploy-related project packaging, proposals) are mounted with the **same** `_auth_dep` as the rest of `/api/v1`. There is no separate admin IdP.


### 1a. Inbound webhooks and approval gates

**Inbound webhooks** (`POST /api/v1/hooks/{workspace}/{pipeline}`) accept exactly two credentials:

| Credential | Check | Recorded actor |
|---|---|---|
| HMAC-SHA256 | `X-Graphyn-Signature: sha256=HMAC(secret, "<X-Graphyn-Timestamp>." + raw_body)`, constant-time compare. Per-pipeline secret = credential connection of kind `inbound_webhook` (sealed in the credentials store; shown once by `…/hook/rotate`; only its id is in `hook.json`). | `webhook:<hook_id>`, `actor_verified: true` |
| Bearer token | Same token rules as `/api/v1` (`GRAPHYN_API_TOKEN` or a `GRAPHYN_API_TOKENS` token). | `webhook:<hook_id>`; verified only for a mapped token (name kept as `claimed_actor`) |

No credential → 401, even in unauthenticated-dev (the hook route never falls back to "allow all"). A disabled / missing hook → 404 before any signature work.

**Replay protection:** the timestamp is inside the MAC and must be within ±`GRAPHYN_WEBHOOK_TOLERANCE_S` (default 300 s); a signature already accepted within the window is refused (409). The seen-signature cache is **in-process** — with several API workers a replay could land once per worker inside the window; use `Idempotency-Key` (24 h, persisted per hook) for exactly-once starts. Other limits: body cap `GRAPHYN_WEBHOOK_MAX_BYTES` (1 MiB), per-hook in-process token bucket (`GRAPHYN_WEBHOOK_RATE_BURST` / `GRAPHYN_WEBHOOK_RATE_PER_MIN`), `?env=` restricted to the hook's `allowed_envs` (the query string is not signed). Credentials (`authorization`, `cookie`, signature) are never forwarded to the graph; payload values are stored only as the run's override inputs, while run meta / audit keep `payload_sha256`, size, source IP and idempotency key. Refusals are audited (`webhook.rejected`).

**Approval gates** (`hitl_approve`): decisions arrive only out-of-band — `POST /runs/{id}/gates/{node}/decision` (bearer, token-bound actor) or MCP `decide_gate`. The decision file is create-only and must match the gate's random `request_id`, so an upstream node cannot self-approve and a decision cannot be overwritten. MCP **approve** requires `GRAPHYN_MCP_HUMAN_APPROVAL=1` (an agent cannot approve its own gate by default); MCP reject is always allowed and recorded as `mcp:<actor>` unverified unless the MCP token is mapped. `role` is caller-declared (checked against `approver_roles`, not authenticated). Audit `gate.decision` stores `comment_sha256`, never the comment.

---

## 2. Authorization matrix (current single-tenant bearer)

**Legend:** "Bearer holder" = anyone who presents a valid `GRAPHYN_API_TOKEN` (or any local caller in unauthenticated-dev). Capabilities are **not** scoped by project, user, or role.

| Resource | Read | Create / write | Modify / delete | Execute / install / deploy | Access secret **values** |
|---|---|---|---|---|---|
| **Projects** | Bearer holder (all projects) | Bearer holder | Bearer holder | n/a | n/a |
| **Graphs** (pipelines / IR) | Bearer holder (any project) | Bearer holder | Bearer holder | Bearer holder (run) | n/a (do not embed secrets in IR) |
| **Runs** | Bearer holder | Bearer holder (enqueue) | Bearer holder (pause/cancel/…) | Bearer holder | n/a |
| **Artifacts** | Operator / claim holder / signed URL | Worker with claim (jobs/ keys) or operator | Bearer holder | Replay via bearer / signed GET | n/a |
| **Datasets** (input/output mounts) | Bearer holder | Bearer holder | Bearer holder | n/a | n/a |
| **Plugins** | Bearer holder (list/search) | n/a | Enable/disable/uninstall: bearer | **Install** + dependency install: bearer | n/a |
| **Credentials** (platform connections) | Bearer holder — **redacted fields only** | Bearer holder (create/update) | Bearer holder (revoke/delete) | Resolved in-process by nodes | **Never** via list/get API/MCP; raw values only inside runtime resolve |
| **Named-secret files** (ops bootstrap under `GRAPHYN_HOME/secrets/`) | CLI `secrets list` — names only | CLI `secrets set` | CLI `secrets delete` | `resolve_secret()` in-process | **Never** via product REST/MCP (removed) |
| **Workers** | Bearer holder | Register / heartbeat: bearer (worker-scoped → own id) | Deregister / PATCH ACL: **operator** | Claim/complete: bearer (worker-scoped → own id) | n/a |
| **Deployments** (edge packs / wizard outputs) | Bearer holder (project-scoped files) | Bearer holder | Bearer holder | Package/deploy actions: bearer | n/a |
| **Proposals** | Bearer holder | Bearer holder / MCP with auth | Accept/reject: bearer | Apply via accept: bearer | n/a |

### Shipped vs not (identity)

| Capability | Status |
|---|---|
| RBAC / roles (admin, operator, builder, approver, auditor, viewer) | **Shipped (F11)** — `app.core.trust.rbac` |
| Local per-user accounts + sessions + personal API tokens | **Shipped (F11)** — `app.core.trust.users` |
| Per-project membership ACL (default deny across projects) | **Shipped (F11)** — membership required unless role has `projects.all` |
| OIDC / SSO (authorization-code + PKCE) | **Shipped (Wave 1)** — optional via `GRAPHYN_OIDC_*` |
| Multi-tenant org boundaries (`org_id` + membership + active org) | **Shipped (Wave 2)** |
| Per-org quotas + metering events + billing webhook seam | **Shipped (Wave 3)** — not a full billing product |
| Customer-managed KMS / BYOK (local + local envelope) | **Shipped (Wave 4)** — cloud KMS Not shipped (extension point, no stubs) |
| Org data residency / region pinning (fail-closed opt-in) | **Shipped (Wave 4)** |
| Compliance export pack + audit retention config | **Shipped (Wave 4)** |
| Opt-in container plugin sandbox (docker/podman) | **Shipped (Wave 5)** — subprocess remains default |
| TEE / SGX attested plugin execution | **Not shipped** (no hardware path) |
| Agent principals + per-agent RBAC (`gxa_…` / MCP) | **Shipped (Wave 6)** — OIDC client_credentials Not shipped |
| Admin org usage/quotas UI + billing webhook status | **Shipped (Wave 6)** |
| Stripe Checkout / payment UI | **Not shipped** |
| Edge OTA closed-loop device fleet | **Partial** — ship packages only; needs hardware |
| Separate worker credentials vs API token | **Partial** — worker-scoped named tokens + join/enrollment; shared bearer still supported |
| Fine-grained secret ACL (per-secret readers) | **Not shipped** |

The §2 matrix above still describes **legacy shared-bearer** capabilities (anyone with the break-glass token). User identities are constrained by RBAC + membership; do not cite the bearer matrix as the multi-user model.

---

## 3. Credentials & secrets hardening

| Control | Behaviour |
|---|---|
| Product store | `GRAPHYN_HOME/credentials/` (encrypted payloads); Admin → Credentials UI |
| REST / MCP | `/api/v1/credentials` + credential MCP tools — **redacted** only. In `fields`, a secret field that is set reads `"***"` and an unset one reads `""`. Every response also carries `secret_fields_set: {field: bool}` so clients can tell "redacted" from "never set" without seeing the value |
| Ops bootstrap | Optional `GRAPHYN_HOME/secrets/<NAME>` files (`0700`/`0600`) + process env via CLI |
| Validation errors | `/api/v1/credentials` 422 responses redact `payload` / secret field `input` |
| Node resolution | `connection_id` → credential store; else `resolve_secret(name)` → file then env; miss errors cite the **name**, never the value |
| Env fallback scope | `resolve_secret()` / `llm_client.resolve_api_key()` read process env **only** for secret-shaped names (`*_API_KEY`, `*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`, `*_DSN`, `*_URL`, `*_URI`) that do **not** start with `GRAPHYN_`, or names in `GRAPHYN_SECRET_ENV_ALLOWLIST`. A node can never read `GRAPHYN_CREDENTIALS_KEY` / `GRAPHYN_API_TOKEN` by naming it. `llm_client` raises `NeedsCredentialsError` for a refused `api_secret_name`. `credentials.resolve_llm_credentials` and every plugin that takes a secret *name* from config (`http_request.auth_env`, `http_webhook.hmac_env`, `rag_*_connector.secret_name`, `vector_store_*` DSN secret, `speaker_separator.auth_token_env`, `structured_llm`, `asr_transcribe`) resolve through `resolve_secret()` — no plugin reads `os.environ` by a config-supplied name (regression: `unit_test/core/test_leftover_secret_env.py`). |
| LLM endpoint binding | A resolved API key is sent only to the endpoint bound to its credential: the connection's `base_url` (or provider default when unset). A node `base_url` that differs is refused. For env / named-secret keys the binding is the provider default (`*_BASE_URL` env); a different host needs `GRAPHYN_LLM_BASE_URL_ALLOWLIST=api.groq.com,…` or (preferred) a connection carrying that `base_url`. Plugins that build their own request (`structured_llm`, `asr_transcribe` openai_compat) use `llm_client.resolve_llm_endpoint()` for the same binding. |
| Credential PATCH | A merge update that changes an endpoint field (`base_url`, `host`, `port`, `url`, `endpoint`) must re-supply every stored secret field (or use `rotate=true` with a full payload) — a stored key is never re-bound to a new host implicitly. |
| Webhook URL | Treated as a secret (path/query usually is the token). REST **and** MCP (`get_webhooks` / `put_webhooks` / `test_webhook`) return `redact_webhook_url_for_api()` form (`scheme://host/***`); audit `resource_id` is redacted; audit export always re-serialises through `normalize_audit_event` (raw `events.jsonl` is never returned); egress/webhook error text and logs never embed the full URL. |
| Output downloads | `GET /outputs/file` refuses config/secret files inside the jail roots: `webhooks.json`, `registry.json`, `schedules.json`, `notifications.jsonl`, dotfiles / `.env*`, `*.sqlite`/`*.db`/`*.key`/`*.pem`/`*.jsonl`, and anything under `credentials/`, `secrets/`, `audit/`, `plugins/`, `distributed/` or a dot-directory (403). Explicit downloads (`?download=1`, run outputs zip, ship package download) are audited with path, size, sha256 and the token-bound actor (`model.download` / `run.output_download` / `run.outputs_zip` / `ship.download`); previews and probes are not. |
| Dataset paths | MCP `list_dataset_versions` / `get_dataset_version`, `POST /projects/{name}/quality-check` and `QualityChecker.run` validate project (`[\w-]{1,128}`) and version (`v<N>[.<N>…]`) and require the resolved path to stay under `datasets/output` (422 / `validation_failed`; no `manifest.json` / `quality_report.json` written elsewhere). |
| Plugin sources | URL userinfo (`https://user:TOKEN@…`) is used for the fetch only; the persisted `PluginRecord.source`, install logs, REST dependency-job errors and MCP plugin errors use `redact_url_userinfo()`. |
| Logging | Store/API paths must not log secret values |

---

## 4. Workflow nodes (`python_code` + HTTP egress)

| Capability | Trust assumption | Hardening today | Not claimed |
|---|---|---|---|
| `python_code` | Graph authors are trusted operators | AST import/call filters; any `_`-prefixed attribute rejected; exec/spawn families (`posix_spawn`, `execv*`, `spawn*`, `fork`, `kill`, …) and frame/code introspection attributes (`gi_frame`, `f_globals`, `tb_frame`, …) rejected; `json` / `math` are curated wrapper namespaces (never real modules) and `import` resolves only to them; `str.format`/`format_map` banned; `allow_network=False` by default and refused entirely when egress mode is `restricted`; `open()` needs explicit `allowed_paths` | Process/container sandbox |
| `http_request` / `http_webhook` | Same; arbitrary HTTP is intentional | **Restricted egress by default (F19)**: private / loopback / link-local / ULA / metadata denied, resolve-then-connect IP pinning (`EgressTransport`), every hop re-checked; trusted internal targets via `GRAPHYN_HTTP_EGRESS_INTERNAL_ALLOW`; optional public allowlist; httpx only with `follow_redirects=False` (a 3xx is a failure, so a redirect cannot reach an unchecked host — the `http_webhook` urllib fallback, which followed redirects, was removed); `http_request` caps the streamed body (`max_response_bytes`) and retries only retryable statuses on idempotent methods / with `Idempotency-Key`; credentials come from a named `connection_id` (`http_auth` **requires** non-empty `allowed_hosts`, `webhook` URL as secret) or a secret *name* — never an inline secret field | Network-layer sandbox (policy is enforced in-process) |
| LLM providers (`llm_chat`, `structured_llm`, `app/core/ml/llm_client.py`), URL ingest, `send_email` SMTP relay, S3 endpoints (`object_store`, `dataset_ingest`) | Calls vendor / configured provider URLs | Same policy: HTTP via `egress_post` / `egress_client` (validated + IP-pinned); SMTP dials the validated IP (`_PinnedSMTP`, STARTTLS still verifies the hostname); S3 endpoint URL validated before any boto3 call | boto3 connection pinning (endpoint is operator-configured, validated once per node run) |
| Platform webhooks (`WebhookService`) | Admin-configured callback | Always blocks private/loopback at save/send; POST connects to a validated public IP (`validated_webhook_ips`) with the original Host/SNI | DNS that returns a new public address after the pin is chosen |

### `python_code` (SEC-002)

`python_code` runs `exec()` in-process after an AST walk. Filters reject dangerous imports (`os`, `subprocess`, …), dunder access, and unrestricted `open()`. That is **defense-in-depth**, not a sandbox:

- Untrusted multi-tenant graphs must **not** expose this node without isolation (subprocess isolation is default for isolated plugins; set `GRAPHYN_PLUGIN_ISOLATION=container` for docker/podman — Wave 5).
- Real module objects are never injected: `json.codecs.sys.modules['os']`-style traversal is impossible because `json` is a `SimpleNamespace(loads, dumps, JSONDecodeError)` and `math` exposes only its public functions/constants. Only `import json` / `import math` (and `from json import loads` style) are accepted; everything else — including network modules even with `allow_network=True` — is refused (`allow_network` is effectively reserved; use an egress-checked HTTP node).
- Keep `allow_network` off unless the operator intentionally needs it. `allow_network=True` is refused while `GRAPHYN_HTTP_EGRESS_MODE=restricted`.
- `str.format` / `format_map` calls are rejected (they bypass the dunder-attribute filter).
- Keep `allowed_paths` empty unless the snippet must read specific files.

UI copy, node metadata, and docs must not call this a "sandbox".

### HTTP egress (SEC-003)

Env knobs (read live from the environment — no import-time cache):

| Variable | Default | Meaning |
|---|---|---|
| `GRAPHYN_HTTP_EGRESS_MODE` | `restricted` | **Default since F19.** `restricted` = deny private / loopback / link-local / ULA / CGNAT / reserved / metadata destinations (resolve-then-connect, IP pinned, redirects re-checked). `trusted` = explicit operator opt-out (private targets allowed; metadata still denied). |
| `GRAPHYN_HTTP_EGRESS_ALLOWLIST` | empty | Comma-separated public hosts/domains. When non-empty **and** mode is `restricted`, the URL hostname must match (exact or subdomain). Also applies to the SMTP relay. |
| `GRAPHYN_HTTP_EGRESS_INTERNAL_ALLOW` | empty | Trusted internal targets that may resolve to private addresses: `host`, `host:port`, `IP`, `IP:port`, `[v6]:port` or CIDR, e.g. `172.17.0.1:11434,ollama:11434`. Port-scoped entries only match that port. `169.254.0.0/16`, `fe80::/10`, `fd00:ec2::254`, `100.100.100.200` and metadata hostnames can **never** be allowlisted. Docker compose sets the host Ollama (`172.17.0.1:11434,host.docker.internal:11434`). |
| `GRAPHYN_PLUGIN_ALLOWED_SOURCES` | empty | Empty = allow all remotes **only** in unauthenticated-dev. When `auth_required()` (prod/staging/`GRAPHYN_AUTH_REQUIRED`), empty allowlist **denies** remote installs (fail closed). Local paths always allowed. scp-style git remotes (`git@host:owner/repo.git`, `host:repo.git`) and transport-helper forms (`ext::…`) are classified as **remote** (and rejected as an unsupported scheme), never as local paths. `git clone` runs with `-c protocol.allow=never -c protocol.<scheme>.allow=always -c http.followRedirects=false` where `<scheme>` is the source's own http/https/git scheme (`file` only for local-path `.git` sources). |
| `GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS` | unset | When unset, dataset path jail resolves symlink targets and rejects escapes. Set `1` for Docker layouts that intentionally symlink datasets outside `GRAPHYN_PROJECT_DIR`. `/input-files` StaticFiles uses `follow_symlink=False`. |

Restricted mode is the default. Typical hardening on top:

```bash
export GRAPHYN_HTTP_EGRESS_ALLOWLIST="api.github.com,hooks.example.com"   # public hosts only
export GRAPHYN_HTTP_EGRESS_INTERNAL_ALLOW="172.17.0.1:11434"            # local Ollama
```

A denied destination fails the node immediately (no connect attempt) with e.g.
`HTTP egress blocked: http://169.254.169.254 resolves to 169.254.169.254, a link-local / cloud-metadata address (always denied, cannot be allowlisted).`

In restricted mode the shared helper (`app/core/trust/egress.py`, `check_egress_target` + `EgressTransport`) used by `http_request`, `http_webhook`, `llm_chat` / `structured_llm` / `llm_client`, URL ingest, `send_email` and the S3 endpoints:

1. Allows only `http` / `https`
2. Blocks known metadata hostnames (`metadata.google.internal`, …)
3. Optionally requires the host allowlist
4. Resolves DNS (`getaddrinfo`) and rejects every address that is not `ip.is_global` — private / link-local / loopback / ULA / reserved / multicast / unspecified **and** CGNAT/shared `100.64.0.0/10` (incl. Alibaba metadata `100.100.100.200`), benchmarking, documentation, IETF-protocol ranges; IPv4-mapped / 6to4 / Teredo IPv6 forms are checked against the embedded IPv4 (including `169.254.169.254`). Platform webhooks use the same `is_blocked_ip`.

**DNS rebinding:** `EgressTransport` validates the resolved addresses and connects to one of exactly those IPs (Host header + TLS SNI / certificate check stay on the hostname), so a DNS answer that changes between check and connect cannot retarget the socket. `trust_env` is off so proxies cannot bypass the check.

**Redirects:** workflow HTTP nodes never follow redirects. Egress is validated for the URL actually requested and a `3xx` response fails the node, so a public URL cannot redirect into a private range. (`http_webhook` used to fall back to `urllib` when httpx was missing; `urllib` follows redirects without re-validation, so the fallback was removed and httpx is required.)

**Workflow outbound side effects:** `send_email` sends only to config `to` unless `allow_payload_recipients=true`, and `allowed_recipient_domains` restricts every recipient. `csv_table` / `object_store` paths are jailed to the workspace (`write_paths.jail_relative_path`: no absolute, `~`, drive letter or `..`; symlink escapes rejected).

**External call audit (G6):** every attempt by `http_request`, `http_webhook`, `send_email`, `llm_chat` and `structured_llm` is recorded via `Node.record_external_call` and sealed into `prove.json` as `external_calls`: kind, method, redacted URL (no userinfo / query / fragment; webhook URLs only `scheme://host/***`; SMTP as `smtp://relay:port`), status, `sha256:` of request and response bodies (never the bodies), duration, `connection_id`, node id. Calls before a node failure are recorded too. Secrets never enter the record. Not yet covered: isolated-runtime plugins and Mode B workers.

**Limitations:** DNS is checked once before the HTTP client runs; the client may resolve again (rebinding TOCTOU). Pinning the TCP connection to the validated IP (as `WebhookService` does) is not yet applied to these nodes. IPv6 coverage depends on platform `getaddrinfo`.

Default remains **trusted** so existing deployments do not break.

---



## 5. Pickle trust boundary (distributed + isolated plugins)

Graphyn uses `pickle` for **same-trust-plane** port payloads (isolated plugin IPC and distributed blob transfer). This is **not** a public deserialization API.

| Actor | May create pickle payloads? | Load path |
|---|---|---|
| Control plane / trusted operators | Yes — enqueue materializes port values via `dump_port_value` → content-addressed blobs | Host loads with `RestrictedUnpickler` (`load_port_value`) |
| Registered workers (same bearer) | Yes — job outputs uploaded as blobs the host later loads | Host: restricted; worker may use broader loads for **its own** trusted inputs |
| Unauthenticated / attacker-controlled bytes | **Never** — do not accept pickle over unauthenticated channels or from untrusted plugin sources | Fail closed |

Rules:

1. **Never deserialize attacker-controlled bytes** with `pickle.loads` / unrestricted `Unpickler`.
2. Host-side loads of worker/isolated outputs must go through `RestrictedUnpickler` (allowlist: builtins / numpy / `app.models.*`). Unknown globals raise `UnpicklingError`. Global **names** must be plain identifiers — any `.` is refused (protocol-4 `STACK_GLOBAL('numpy', '_pytesttester.os.getpid')` would otherwise walk to `os.getpid`); `_`-prefixed names are refused except the reconstruct helpers (`_reconstruct`, `_frombuffer`, `_mareconstruct`, copyreg `_reconstructor`); `app.models.*` names must resolve to callables whose `__module__` is under `app.models`; numpy globals must be classes or reconstruct helpers (`memmap`, `fromfile`, … denied); module objects are never returned.
3. Workers run as trusted operators on the shared bearer — they may receive host-produced pickles for job inputs; treat worker→host outputs as **semi-trusted** and keep the restricted loader on the host.
4. Plugin authors must not ship pickle gadgets; isolated worker outputs are recast onto platform types before host unpickle when possible (`recast_plugin_types`).

Regression: `RestrictedUnpickler` tests in `unit_test/core/plugins/test_dep_isolation.py`, `test_restricted_unpickler.py`, `test_security_restricted_unpickler.py`; transfer path in `unit_test/core/test_distributed_transfer.py`.


## 6. Mode B WAVE-1 (distributed workers)

Env knobs (read live; lab defaults keep Mode B working without them):

| Variable | Default | Meaning |
|---|---|---|
| `GRAPHYN_API_TOKENS` / `_FILE` | empty | Named tokens; optional `kind=worker` + `worker_id` binding (see §1) |
| `GRAPHYN_WORKER_TRUST_REQUIRED` | unset | When `1` **and** `auth_required()`, untrusted workers cannot claim |
| `GRAPHYN_WORKER_REQUIRE_PLUGIN_ADVERTISE` | unset | When `1`, empty `plugins` advertisement cannot claim (fail closed) |
| `GRAPHYN_BLOB_SIGNING_KEY` | unset | HMAC secret for short-lived blob GET URLs. Control plane only — no fallback to the API token; unset = signed URLs disabled |
| `GRAPHYN_BLOB_URL_TTL_S` | `300` | Signed blob URL TTL (seconds), capped at 3600 |
| `GRAPHYN_WORKER_TOKEN` | unset | Worker-side bearer (preferred over `GRAPHYN_API_TOKEN` on workers) |
| `GRAPHYN_WORKER_UNBOUND_TOKENS` | unset | `1` = allow `kind=worker` tokens without a `worker_id` binding (lab only; fail closed otherwise unless mTLS supplies the id) |
| `GRAPHYN_HTTP_EGRESS_MODE` | `restricted` | Default everywhere since F19; Mode B compose also sets a public allowlist |
| `GRAPHYN_BLOB_ENCRYPTION_KEY` | unset | urlsafe-b64 32-byte key; encrypts blob files at rest (plaintext sha256 keys). Unset = plaintext |
| `GRAPHYN_BLOB_ENCRYPTION_OLD_KEYS` | unset | Comma-separated retired keys, still tried for decrypt during rotation |
| `GRAPHYN_POOL_MAX_CLAIMED` | unset | JSON `{"gpu-lab":2}` or `gpu-lab=2,cpu=4` concurrent claimed/running caps per pool |
| `GRAPHYN_MTLS_ENABLED` | unset | `1` = require client certs (fail closed). Default HTTP when unset |
| `GRAPHYN_MTLS_CA_CERT` / `_CERT` / `_KEY` | unset | Control CA + server cert/key PEMs |
| `GRAPHYN_MTLS_CLIENT_CERT` / `_CLIENT_KEY` | unset | Worker client cert/key PEMs |
| `GRAPHYN_WORKER_SPOOL` | `1` | Offline store-and-forward under `{GRAPHYN_HOME}/worker_spool/<worker_id>/` |

Controls:

* **Worker token scope** — a worker identity (worker token or mTLS cert) may only call the worker protocol (`worker_scope_allows`: register / heartbeat / claim / job GET+events+complete / blob PUT+GET); every other `/api/` route is 403. MCP rejects worker tokens (`forbidden`). An operator token keeps operator rights even when a client cert is presented.
* **Per-worker plugin ACL** — `allowed_plugins` / `plugin_hashes` (pins) / `trusted` / `max_claimed` / `usage_*` on `WorkerInfo` are admin-only: `PATCH /workers/{id}` sets them, and self-registration cannot (existing values always win; a new worker is trusted only when `GRAPHYN_WORKER_TRUST_REQUIRED` is off). Claim intersects advertised ∩ allowlist and checks content hash pins. `plugin_hashes` is hidden from non-operator `GET /workers`.
* **Job ACL** — `GET /jobs/{id}` and job events are limited to the claiming worker; events need a claimed/running job (409 otherwise).
* **Blob GET** — operator token; OR a worker fetching an input blob / `blob_grants` key of a job it holds, or an output key of its own job; OR a valid `exp`+`sig` HMAC URL (`mint_signed_blob_url` / `GET …/artifacts/blob/{key}?exp=&sig=`). Workers refuse absolute blob URLs outside the control origin, so the bearer never leaves the control plane.
* **Remote config** — `assert_remote_config_safe` strips/forbids inline secrets before enqueue (refs only: `*_env`, `secret_name`, `connection_id`).
* **Event redaction** — control redacts secret-shaped keys / bearer / webhook URLs on `events` and `complete` before persistence.
* **Audit** — `worker.register|deregister|trust`, `job.claim|complete|cancel`, `blob.put|get` (metadata only; never raw bytes).
* **mTLS (WAVE-2)** — `scripts/gen_modeb_mtls_certs.sh` + `python -m app.api.mtls_serve` (h11 with SSL) or the `docker-compose.modeb-mtls.yml` overlay; cert CN / URI SAN `urn:graphyn:worker:{id}` (full match) binds worker identity (AND/OR worker token). When enabled, worker protocol mutations without a client cert get 403 and workers refuse an `http://` control URL. The `X-Graphyn-Mtls-Worker-Id` test header never counts as a verified identity and is ignored when `GRAPHYN_ENV` is production / prod / staging. HTTP remains default when disabled.
* **Blob encrypt-at-rest (WAVE-2)** — content-address by plaintext sha256; on-disk GBE2 envelope (`magic‖key_id‖nonce‖AES-256-GCM`, HKDF-derived key, AAD = magic + key id) when `GRAPHYN_BLOB_ENCRYPTION_KEY` set. Legacy GBE1 blobs still decrypt; rotate via `GRAPHYN_BLOB_ENCRYPTION_OLD_KEYS`.
* **Pool / worker quotas (WAVE-2)** — `GRAPHYN_POOL_MAX_CLAIMED` + `WorkerInfo.max_claimed` (admin PATCH); usage counters on `GET /workers`.
* **Worker spool (WAVE-2)** — when control is unreachable, `complete` results spool (per-worker dir, atomic writes) and flush before re-register; spooled job ids stay in heartbeat `active_job_ids`. lease_generation fencing drops stale items. Blob/event spooling is not wired yet (`MODEB-SPOOL-PARTIAL-1`).

Skipped (not shipped): TPM/SGX hardware attestation (no hardware API — plugin hash pins are the software attestation), multi-tenant org/SaaS tables.


## Related

- Architecture security table: `docs/ARCHITECTURE.md` §10
- Billing / per-tenant quotas: `docs/ENTERPRISE_READINESS.md` Wave 3
- KMS / residency / compliance / container sandbox: Waves 4–5 same file
- Node reference: `PluginPackage/NODES.md`
- API auth note: `docs/API_REFERENCE.md` (Bearer / fail-closed)
