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
Static mounts `/files`, `/input-files`, `/run-files` use the **same** bearer policy as `/api/v1` when a token is configured.  
OpenAPI UI (`/docs`, `/redoc`, `/openapi.json`) is not bearer-gated — treat the API host as operator-trusted network.

Sensitive routers (plugins install, secrets, workers admin/job claim, deploy-related project packaging, proposals) are mounted with the **same** `_auth_dep` as the rest of `/api/v1`. There is no separate admin IdP.

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
| **Secrets** (named store) | Bearer holder — **names/metadata only** | Bearer holder (set/put) | Bearer holder (delete) | Resolved in-process by nodes | **Never** via list/get API/MCP/CLI list; only via `resolve_secret()` inside the runtime |
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

## 3. Secrets hardening

| Control | Behaviour |
|---|---|
| Storage | `GRAPHYN_HOME/secrets/<NAME>` files, dir `0700`, files `0600` |
| List / get API | Returns **names only** — no GET-by-name value endpoint |
| Writes | Same bearer gate as other `/api/v1` admin routes |
| MCP / CLI list | Names only; set responses echo the name, never the value |
| Validation errors | `/api/v1/secrets` 422 responses redact `input` for the `value` field |
| Node resolution | `resolve_secret(name)` → store then env; miss errors cite the **name**, never the value |
| Logging | Store/API paths must not log secret values |

---

## 4. Workflow nodes (`python_code` + HTTP egress)

| Capability | Trust assumption | Hardening today | Not claimed |
|---|---|---|---|
| `python_code` | Graph authors are trusted operators | AST import/call filters; `allow_network=False` by default; `open()` needs explicit `allowed_paths` | Process/container sandbox |
| `http_request` / `http_webhook` | Same; arbitrary HTTP is intentional | Optional `GRAPHYN_HTTP_EGRESS_MODE=restricted` + allowlist | Full SSRF-proof pin-IP client (TOCTOU remains) |
| ASR / `structured_llm` HTTP | Calls vendor / configured provider URLs | Provider-specific clients | Does **not** yet share the workflow egress helper (document only; wire later if needed) |
| Platform webhooks (`WebhookService`) | Admin-configured callback | Always blocks private/loopback at save/send; pin-IP connect | — |

### `python_code` (SEC-002)

`python_code` runs `exec()` in-process after an AST walk. Filters reject dangerous imports (`os`, `subprocess`, …), dunder access, and unrestricted `open()`. That is **defense-in-depth**, not a sandbox:

- Untrusted multi-tenant graphs must **not** expose this node without isolation (future Option B: container / subprocess jail).
- Keep `allow_network` off unless the operator intentionally needs it.
- Keep `allowed_paths` empty unless the snippet must read specific files.

UI copy, node metadata, and docs must not call this a "sandbox".

### HTTP egress (SEC-003)

Env knobs (read live from the environment — no import-time cache):

| Variable | Default | Meaning |
|---|---|---|
| `GRAPHYN_HTTP_EGRESS_MODE` | `trusted` | `trusted` = current behaviour (any http(s) URL). `restricted` = block private/link-local/loopback/metadata ranges and enforce optional allowlist. |
| `GRAPHYN_HTTP_EGRESS_ALLOWLIST` | empty | Comma-separated hosts/domains. When non-empty **and** mode is `restricted`, the URL hostname must match (exact or subdomain). |

Enable restricted mode:

```bash
export GRAPHYN_HTTP_EGRESS_MODE=restricted
export GRAPHYN_HTTP_EGRESS_ALLOWLIST="api.github.com,hooks.example.com"
```

In restricted mode the shared helper (`app/core/egress.py`) used by `http_request` and `http_webhook`:

1. Allows only `http` / `https`
2. Blocks known metadata hostnames (`metadata.google.internal`, …)
3. Optionally requires the host allowlist
4. Resolves DNS (`getaddrinfo`) and rejects private / link-local / loopback / ULA / reserved / multicast / unspecified IPs (including `169.254.169.254`)

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
2. Host-side loads of worker/isolated outputs must go through `RestrictedUnpickler` (allowlist: builtins / numpy / `app.models.*`). Unknown globals raise `UnpicklingError`.
3. Workers run as trusted operators on the shared bearer — they may receive host-produced pickles for job inputs; treat worker→host outputs as **semi-trusted** and keep the restricted loader on the host.
4. Plugin authors must not ship pickle gadgets; isolated worker outputs are recast onto platform types before host unpickle when possible (`recast_plugin_types`).

Regression: `RestrictedUnpickler` tests in `unit_test/core/plugins/test_dep_isolation.py`; transfer path in `unit_test/core/test_distributed_transfer.py`.

## Related

- Architecture security table: `docs/ARCHITECTURE.md` §10
- Open RBAC gap: `docs/KNOWN_ISSUES.md` → RBAC-1
- Node reference: `PluginPackage/NODES.md`
- API auth note: `docs/API_REFERENCE.md` (Bearer / fail-closed)
