# Trust model — workflow nodes (python_code + HTTP egress)

> Option A (this release): **trusted operators** on a shared bearer / single-tenant deployment.
> Full RBAC/tenancy and container isolation (Option B) are out of scope — see `KNOWN_ISSUES.md` (RBAC-1).

## Summary

| Capability | Trust assumption | Hardening today | Not claimed |
|---|---|---|---|
| `python_code` | Graph authors are trusted operators | AST import/call filters; `allow_network=False` by default; `open()` needs explicit `allowed_paths` | Process/container sandbox |
| `http_request` / `http_webhook` | Same; arbitrary HTTP is intentional | Optional `GRAPHYN_HTTP_EGRESS_MODE=restricted` + allowlist | Full SSRF-proof pin-IP client (TOCTOU remains) |
| ASR / `structured_llm` HTTP | Calls vendor / configured provider URLs | Provider-specific clients | Does **not** yet share the workflow egress helper (document only; wire later if needed) |
| Platform webhooks (`WebhookService`) | Admin-configured callback | Always blocks private/loopback at save/send; pin-IP connect | — |

## `python_code` (SEC-002)

`python_code` runs `exec()` in-process after an AST walk. Filters reject dangerous imports (`os`, `subprocess`, …), dunder access, and unrestricted `open()`. That is **defense-in-depth**, not a sandbox:

- Untrusted multi-tenant graphs must **not** expose this node without isolation (future Option B: container / subprocess jail).
- Keep `allow_network` off unless the operator intentionally needs it.
- Keep `allowed_paths` empty unless the snippet must read specific files.

UI copy, node metadata, and docs must not call this a "sandbox".

## HTTP egress (SEC-003)

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

## Related

- Architecture security table: `docs/ARCHITECTURE.md` §10
- Open RBAC gap: `docs/KNOWN_ISSUES.md` → RBAC-1
- Node reference: `PluginPackage/NODES.md`
