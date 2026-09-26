# Graphyn Credential Store

**Local only** — durable under `GRAPHYN_HOME/credentials/` (never Cursor cloud).

Credentials belong to the **Graphyn platform**, not to node/graph JSON. Plugins
declare **credential kinds**; graphs/nodes store only **connection id refs**.
Runtime resolves `id → secret` for that step only and fails closed with
`NeedsCredentialsError` when missing.

## Layout on disk

```
{GRAPHYN_HOME}/credentials/          # mode 0700
  .key                               # master key (mode 0600) if GRAPHYN_CREDENTIALS_KEY unset
  store.sqlite                       # encrypted connection payloads (mode 0600)
```

- Master key: env `GRAPHYN_CREDENTIALS_KEY` (preferred) **or** generated once into `.key`.
- Payloads are sealed (`v1:` + authenticated stream cipher). List/get APIs never return raw secrets (secret fields shown as `***`).

## Built-in kinds

| Kind | Typical fields | Env bootstrap |
|------|----------------|---------------|
| `openai_compat` | `api_key`, `base_url?`, `default_model?` | `OPENAI_API_KEY`, `OPENAI_BASE_URL` |
| `anthropic` | `api_key`, `base_url?` | `ANTHROPIC_API_KEY` |
| `gemini` | `api_key`, `base_url?` | `GEMINI_API_KEY` / `GOOGLE_API_KEY` |
| `ollama` | `base_url?`, `api_key?`, `default_model?` | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |
| `smtp` | `host`, `port`, `user`, `password`, `from_addr`, `tls`, `dry_run` | `GRAPHYN_SMTP_*` |
| `webhook` | `url`, `events?` | — |

Plugins may call `register_kind(...)` at load time. **Using** an existing
connection of a known kind never requires an API restart.

## Precedence (resolve)

1. **Explicit connection id** on the node / call (`connection_id`)
2. **Workspace default** for that kind (`POST /api/v1/credentials/{id}/default`)
3. **Env / named-secret bootstrap** (`OPENAI_API_KEY`, `GRAPHYN_SMTP_*`, …)

Named secrets under `GRAPHYN_HOME/secrets/` remain available as env-style
fallbacks via `resolve_secret()`.

## REST (`/api/v1/credentials`)

Same Bearer auth as other admin APIs (`GRAPHYN_API_TOKEN`).

| Method | Path | Notes |
|--------|------|-------|
| GET | `/credentials/kinds` | Kind registry (field schemas; no secrets) |
| GET | `/credentials` | List metadata + redacted fields |
| POST | `/credentials` | Create (`name`, `kind`, `payload`, `is_default?`) |
| GET | `/credentials/{id}` | Get one (redacted) |
| PATCH/PUT | `/credentials/{id}` | Update / rotate (`rotate=true` replaces payload) |
| POST | `/credentials/{id}/default` | Bind workspace default for kind |
| DELETE | `/credentials/{id}?delete=0\|1` | Soft-revoke or hard-delete |

**Never** returns raw secret values. Do not log request bodies that contain payload secrets in custom middleware.

## MCP tools

- `list_credentials`
- `create_credential`
- `get_credential` (redacted)
- `update_credential`
- `revoke_credential`

## Plugin wiring

In `plugin.toml`:

```toml
[plugin]
credential_kinds = ["openai_compat", "smtp"]

[config_schema.my_node]
connection_id = { type = "string", title = "Credential connection id", default = "" }
```

Node `Config` should expose `connection_id` and pass it to `chat_completion` /
`send_email` / `resolve_connection`.

## Console

Admin → **Credentials** (`/admin/credentials`): thin list/create/revoke UI.
Named env-style secrets remain under Admin → **Secrets**.

## Hot path

Create / rotate / revoke writes SQLite immediately. The next node execution
resolves the new connection **without** restarting `graphyn-api`.
