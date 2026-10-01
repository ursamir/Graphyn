# Trust model — authorization, secrets, workflow nodes

> Option A (this release): **trusted operators** on a **shared-bearer / single-tenant** deployment.
> Full RBAC/tenancy and container isolation (Option B) are out of scope — see `KNOWN_ISSUES.md` (RBAC-1).

Graphyn today is a **single-operator** platform: one shared API token (when configured) unlocks the entire control plane. There is **no** multi-user identity, **no** per-project ACL, and **no** role matrix. This document makes those boundaries explicit so they are not confused with a shipped IdP.

---

## 1. Authentication modes (API + MCP)

| Mode | When | Behaviour |
|---|---|---|
| **Unauthenticated-dev** | `GRAPHYN_API_TOKEN` unset **and** auth not required | All `/api/v1/*` routes and MCP tools accept callers without a token. Intended for local single-user development only. |
| **Shared bearer** | `GRAPHYN_API_TOKEN` set | REST requires `Authorization: Bearer <token>`; MCP requires `_meta.auth_token`. Same token for every operator and worker. |
| **Fail-closed** | `GRAPHYN_AUTH_REQUIRED=1` **or** `GRAPHYN_ENV` ∈ {`production`,`prod`,`staging`} | Empty `GRAPHYN_API_TOKEN` is rejected (401 / MCP unauthorized). Set a token before exposing the API. |

Unauthenticated by design (always): `GET /`, `GET /health`.  
**DNS-rebinding guard (unauthenticated-dev):** while `GRAPHYN_API_TOKEN` is unset, every request whose `Host` is not `localhost` / `*.localhost` / an IP literal (incl. `[::1]`) / `graphyn-api` (compose service name, used by the UI nginx proxy for `/files`) / `testserver` gets **403**. Add LAN / DNS names with `GRAPHYN_ALLOWED_HOSTS=name1,name2` (`*` disables the guard), or set a token (guard is off once a token is configured). IP literals are always accepted because a rebinding page can only present its own DNS name.  
Static mounts `/files`, `/input-files`, `/run-files` use the **same** bearer policy as `/api/v1` when a token is configured.  
OpenAPI UI (`/docs`, `/redoc`, `/openapi.json`) is not bearer-gated — treat the API host as operator-trusted network.

Sensitive routers (plugins install, credentials, workers admin/job claim, deploy-related project packaging, proposals) are mounted with the **same** `_auth_dep` as the rest of `/api/v1`. There is no separate admin IdP.

---

## 2. Authorization matrix (current single-tenant bearer)

**Legend:** "Bearer holder" = anyone who presents a valid `GRAPHYN_API_TOKEN` (or any local caller in unauthenticated-dev). Capabilities are **not** scoped by project, user, or role.

| Resource | Read | Create / write | Modify / delete | Execute / install / deploy | Access secret **values** |
|---|---|---|---|---|---|
| **Projects** | Bearer holder (all projects) | Bearer holder | Bearer holder | n/a | n/a |
| **Graphs** (pipelines / IR) | Bearer holder (any project) | Bearer holder | Bearer holder | Bearer holder (run) | n/a (do not embed secrets in IR) |
| **Runs** | Bearer holder | Bearer holder (enqueue) | Bearer holder (pause/cancel/…) | Bearer holder | n/a |
| **Artifacts** | Bearer holder (all keys / blobs) | Bearer holder / workers with bearer | Bearer holder | Replay via bearer | n/a |
| **Datasets** (input/output mounts) | Bearer holder | Bearer holder | Bearer holder | n/a | n/a |
| **Plugins** | Bearer holder (list/search) | n/a | Enable/disable/uninstall: bearer | **Install** + dependency install: bearer | n/a |
| **Credentials** (platform connections) | Bearer holder — **redacted fields only** | Bearer holder (create/update) | Bearer holder (revoke/delete) | Resolved in-process by nodes | **Never** via list/get API/MCP; raw values only inside runtime resolve |
| **Named-secret files** (ops bootstrap under `GRAPHYN_HOME/secrets/`) | CLI `secrets list` — names only | CLI `secrets set` | CLI `secrets delete` | `resolve_secret()` in-process | **Never** via product REST/MCP (removed) |
| **Workers** | Bearer holder | Register / heartbeat: bearer | Deregister: bearer | Claim/complete jobs: bearer | n/a |
| **Deployments** (edge packs / wizard outputs) | Bearer holder (project-scoped files) | Bearer holder | Bearer holder | Package/deploy actions: bearer | n/a |
| **Proposals** | Bearer holder | Bearer holder / MCP with auth | Accept/reject: bearer | Apply via accept: bearer | n/a |

### Explicitly **not** shipped

| Capability | Status |
|---|---|
| RBAC / roles (viewer, editor, admin) | **Not shipped** |
| Per-user accounts / OAuth / OIDC / SSO | **Not shipped** |
| Per-project isolation (user A cannot read project B) | **Not shipped** — bearer sees all projects |
| Multi-tenant DB schemas / org boundaries | **Not shipped** |
| Separate worker credentials vs API token | **Not shipped** — workers use the same bearer |
| Fine-grained secret ACL (per-secret readers) | **Not shipped** |

### Future requirement (when multi-user is supported)

Once multi-user identity exists, **cross-project access must be prevented by default** (project membership or equivalent ACL). That is a **future requirement**, not implemented here — do not treat the matrix above as fake RBAC.

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
| Output downloads | `GET /outputs/file` refuses config/secret files inside the jail roots: `webhooks.json`, `registry.json`, `schedules.json`, `notifications.jsonl`, dotfiles / `.env*`, `*.sqlite`/`*.db`/`*.key`/`*.pem`/`*.jsonl`, and anything under `credentials/`, `secrets/`, `audit/`, `plugins/`, `distributed/` or a dot-directory (403). |
| Dataset paths | MCP `list_dataset_versions` / `get_dataset_version`, `POST /projects/{name}/quality-check` and `QualityChecker.run` validate project (`[\w-]{1,128}`) and version (`v<N>[.<N>…]`) and require the resolved path to stay under `datasets/output` (422 / `validation_failed`; no `manifest.json` / `quality_report.json` written elsewhere). |
| Plugin sources | URL userinfo (`https://user:TOKEN@…`) is used for the fetch only; the persisted `PluginRecord.source`, install logs, REST dependency-job errors and MCP plugin errors use `redact_url_userinfo()`. |
| Logging | Store/API paths must not log secret values |

---

## 4. Workflow nodes (`python_code` + HTTP egress)

| Capability | Trust assumption | Hardening today | Not claimed |
|---|---|---|---|
| `python_code` | Graph authors are trusted operators | AST import/call filters; any `_`-prefixed attribute rejected; exec/spawn families (`posix_spawn`, `execv*`, `spawn*`, `fork`, `kill`, …) and frame/code introspection attributes (`gi_frame`, `f_globals`, `tb_frame`, …) rejected; `json` / `math` are curated wrapper namespaces (never real modules) and `import` resolves only to them; `str.format`/`format_map` banned; `allow_network=False` by default and refused entirely when egress mode is `restricted`; `open()` needs explicit `allowed_paths` | Process/container sandbox |
| `http_request` / `http_webhook` | Same; arbitrary HTTP is intentional | Optional `GRAPHYN_HTTP_EGRESS_MODE=restricted` + allowlist | Full SSRF-proof pin-IP client (TOCTOU remains) |
| ASR / `structured_llm` HTTP | Calls vendor / configured provider URLs | `validate_http_egress_url` before every `httpx` call (same helper as `http_request` / `http_webhook`) | Pin-IP connect (TOCTOU remains) |
| Platform webhooks (`WebhookService`) | Admin-configured callback | Always blocks private/loopback at save/send; POST connects to a validated public IP (`validated_webhook_ips`) with the original Host/SNI | DNS that returns a new public address after the pin is chosen |

### `python_code` (SEC-002)

`python_code` runs `exec()` in-process after an AST walk. Filters reject dangerous imports (`os`, `subprocess`, …), dunder access, and unrestricted `open()`. That is **defense-in-depth**, not a sandbox:

- Untrusted multi-tenant graphs must **not** expose this node without isolation (future Option B: container / subprocess jail).
- Real module objects are never injected: `json.codecs.sys.modules['os']`-style traversal is impossible because `json` is a `SimpleNamespace(loads, dumps, JSONDecodeError)` and `math` exposes only its public functions/constants. Only `import json` / `import math` (and `from json import loads` style) are accepted; everything else — including network modules even with `allow_network=True` — is refused (`allow_network` is effectively reserved; use an egress-checked HTTP node).
- Keep `allow_network` off unless the operator intentionally needs it. `allow_network=True` is refused while `GRAPHYN_HTTP_EGRESS_MODE=restricted`.
- `str.format` / `format_map` calls are rejected (they bypass the dunder-attribute filter).
- Keep `allowed_paths` empty unless the snippet must read specific files.

UI copy, node metadata, and docs must not call this a "sandbox".

### HTTP egress (SEC-003)

Env knobs (read live from the environment — no import-time cache):

| Variable | Default | Meaning |
|---|---|---|
| `GRAPHYN_HTTP_EGRESS_MODE` | `trusted` | `trusted` = current behaviour (any http(s) URL). `restricted` = block private/link-local/loopback/metadata ranges and enforce optional allowlist. |
| `GRAPHYN_HTTP_EGRESS_ALLOWLIST` | empty | Comma-separated hosts/domains. When non-empty **and** mode is `restricted`, the URL hostname must match (exact or subdomain). |
| `GRAPHYN_PLUGIN_ALLOWED_SOURCES` | empty | Empty = allow all remotes **only** in unauthenticated-dev. When `auth_required()` (prod/staging/`GRAPHYN_AUTH_REQUIRED`), empty allowlist **denies** remote installs (fail closed). Local paths always allowed. scp-style git remotes (`git@host:owner/repo.git`, `host:repo.git`) and transport-helper forms (`ext::…`) are classified as **remote** (and rejected as an unsupported scheme), never as local paths. `git clone` runs with `-c protocol.allow=never -c protocol.<scheme>.allow=always -c http.followRedirects=false` where `<scheme>` is the source's own http/https/git scheme (`file` only for local-path `.git` sources). |
| `GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS` | unset | When unset, dataset path jail resolves symlink targets and rejects escapes. Set `1` for Docker layouts that intentionally symlink datasets outside `GRAPHYN_PROJECT_DIR`. `/input-files` StaticFiles uses `follow_symlink=False`. |

Enable restricted mode:

```bash
export GRAPHYN_HTTP_EGRESS_MODE=restricted
export GRAPHYN_HTTP_EGRESS_ALLOWLIST="api.github.com,hooks.example.com"
```

In restricted mode the shared helper (`app/core/trust/egress.py`) used by `http_request`, `http_webhook`, `asr_transcribe`, and `structured_llm`:

1. Allows only `http` / `https`
2. Blocks known metadata hostnames (`metadata.google.internal`, …)
3. Optionally requires the host allowlist
4. Resolves DNS (`getaddrinfo`) and rejects every address that is not `ip.is_global` — private / link-local / loopback / ULA / reserved / multicast / unspecified **and** CGNAT/shared `100.64.0.0/10` (incl. Alibaba metadata `100.100.100.200`), benchmarking, documentation, IETF-protocol ranges; IPv4-mapped / 6to4 / Teredo IPv6 forms are checked against the embedded IPv4 (including `169.254.169.254`). Platform webhooks use the same `is_blocked_ip`.

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

## Related

- Architecture security table: `docs/ARCHITECTURE.md` §10
- Open RBAC gap: `docs/KNOWN_ISSUES.md` → RBAC-1
- Node reference: `PluginPackage/NODES.md`
- API auth note: `docs/API_REFERENCE.md` (Bearer / fail-closed)
