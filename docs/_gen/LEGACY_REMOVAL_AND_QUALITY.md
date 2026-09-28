# Legacy removal & production quality — Secrets → Credentials

| Field | Value |
|-------|-------|
| **Date** | 2026-09-28 (Asia/Calcutta / IST) |
| **Branch** | `cursor/usecase-plugins-workflows` |
| **Scope** | LOCAL only (never Cursor cloud). Tip synced to S99 `~/Desktop/newAudio3`. |
| **Policy** | Credentials store is **the** secret/connection system. Prefer delete legacy over dual banners. |

## Removed legacy (product surfaces)

### Console UI
| Path / entry | Action |
|---|---|
| `graphyn-ui/src/features/secrets/SecretsView.tsx` (+ folder) | **Deleted** |
| Admin rail item **Secrets** | **Removed** (Admin keeps Credentials · Ops · Access) |
| Cmd-K palette “Secrets” | **Replaced** with Credentials (`k` keywords) |
| Jump key `k` | Remapped **secrets → credentials** |
| KeyboardHelp / NAV_SHORTCUT_LABEL secrets | Removed; credentials listed |
| `AppView` `'secrets'` | Removed from store / VIEW_LABEL / NAV_HINTS |
| `paths.adminSecrets` | Removed |
| `viewMap` secrets case + `VIEW_PATH_HINT.secrets` | Removed |
| Editor named-secret picker (`GET /secrets` + `SecretNameSelect`) | **Removed**; inspector uses Credentials `connection_id` picker + env-bootstrap hint |

### Routes
| URL | Behaviour |
|---|---|
| `/admin/secrets` | Canonical redirect → `/admin/credentials` (bookmark safety) |
| `/admin/credentials` | Sole console secret/connection page |

### API / MCP
| Surface | Action |
|---|---|
| `app/api/routers/secrets.py` | **Deleted**; unmounted from `app/api/main.py` |
| REST `/api/v1/secrets*` | **404** (covered by `unit_test/api/test_secrets_router.py`) |
| `app/mcp/handlers/secrets.py` | **Deleted** |
| MCP `secrets_list` / `secrets_set` | **Unregistered** |
| 422 redaction | Moved from `/secrets` → `/credentials` payload/secret fields (`app/api/errors.py`) |

### Docs / onboarding copy
| Doc | Change |
|---|---|
| `docs/ops/CREDENTIAL_STORE.md` | Console = Credentials only; ops env bootstrap section (CLI/env, no second page) |
| `docs/DEPLOYMENT.md` | Credentials-first; REST `/secrets` note removed |
| `docs/TRUST_MODEL.md` | Credentials matrix + named-file ops bootstrap; hardening table updated |
| `docs/GETTING_STARTED.md` | Admin group: Credentials (not Secrets) |
| `docs/MCP_SERVER.md` / `MCP_AGENT_PACK_COVERAGE.md` | secrets tools → credential tools; count ~77 |
| `docs/CLEANUP_LEGACY.md` | Pointer to this wave |

## Kept (intentionally — not a second product console)

| Piece | Why |
|---|---|
| `app/core/secrets.py` + `resolve_secret()` | Runtime fallback used by LLM/SMTP/credential resolve |
| CLI `graphyn secrets list/set/delete` | Ops bootstrap under `GRAPHYN_HOME/secrets/` (names only on list) |
| IR `secret_policy` / inline-secret rejection | Security — unrelated to dual UI |
| Credential store + UI + REST + MCP | **Product** secret/connection system |

## Clean naming / IA (locked, preserved)

- UI chrome: **Workspace**; API/fields may still say `project`.
- Rail: Home · Editor · Runs · Models · Ship · Datasets; Library = Plugins + Artifacts; Deploy = Worker fleet; Admin = Credentials · Ops · Access.
- Editor label (internal view id `builder` unchanged).
- Ops MCP chip: **~77 tools (agent-facing)** (no “29 tools” drift).
- No FaceRecognition product surface; Devices honesty stub — **no fake MCU flash**.

## Quality fixes (this wave)

1. Dual Secrets vs Credentials product surface eliminated (UI + REST + MCP).
2. Editor no longer fetches legacy `/secrets` for inspector pickers.
3. Credential 422s redact `payload` / secret-like field inputs.
4. Tests: legacy routes 404; MCP secrets module/tools absent; credentials tools required in registry expectations; auth-gate sensitive GET uses `/credentials`.
5. Ops honesty: env/CLI bootstrap documented without a second console page.
6. Access page copy: “credential-write” (not secret-write) pending Access API.
7. Typecheck (`tsc -b`) clean after UI removals.

## Tests touched

- `unit_test/api/test_secrets_router.py` → asserts 404
- `unit_test/mcp/test_handler_secrets.py` → module gone + tools absent
- `unit_test/mcp/test_tool_registry.py` → credentials in EXPECTED; secrets_* forbidden
- `unit_test/api/test_auth_gate_sensitive.py` → `/api/v1/credentials`
- Core store tests (`test_secrets_store.py`) retained for ops bootstrap module

## Smoke checklist (S99)

- [ ] `GET /health` (API) → ok
- [ ] UI `/admin/credentials` loads; list/create surfaces present
- [ ] `/admin/secrets` → lands on Credentials (canonical)
- [ ] Rail Admin has **no** Secrets item; Credentials present
- [ ] Workspace strip IA unchanged
- [ ] Ops MCP chip ≠ “29 tools”
