# Broader surface gap inventory (mail / notifications / LLM / agents)

| Field | Value |
|-------|-------|
| **Date** | 2026-09-26 (Asia/Calcutta) |
| **Branch** | `cursor/usecase-plugins-workflows` |
| **Scope** | Beyond Wave-1 ML packs: mail, notifications, LLM providers, agents/HITL/schedules/webhooks; note open Auth/audit/ship/datasets P0/P1 only |
| **Marks** | DONE · PARTIAL · MISSING · needs-api · needs-credentials |

**Sources scanned:** `docs/REQUIREMENTS_SPEC.md`, `docs/SRS_ALIGNMENT_GAP_MATRIX.md` (+ JSON), `docs/PRODUCT_VISION.md`, `docs/MCP_AGENT_PACK_COVERAGE.md`, `docs/PLUGIN_NODE_PLATFORM_CATALOG.md`, `PluginPackage/{Agents,Common,RAG}/**`, `app/core/{webhook,run_notify,secrets}.py`, MCP tool registry / system router.

---

## 1. Email / mail (send · receive · SMTP · providers)

| Item | Status | Evidence / notes |
|------|--------|------------------|
| Outbound SMTP send (env credentials) | PARTIAL → closing this wave | No `send_email` node before this wave; Wave adds plugin + `GRAPHYN_SMTP_*` + dry-run |
| Inbound IMAP / mailbox product | MISSING | No inbox/IMAP product in SRS or plugins — **do not invent** |
| Gmail / Microsoft OAuth mail | needs-credentials + needs-api | No OAuth mail connector |
| Mail as run-completion sink | PARTIAL → closing | Today: webhook only (`run_notify` → `WebhookService`); Wave adds optional SMTP sink |
| Marketplace “email alert” templates | PARTIAL → closing | Agents `webhook-alert` uses `http_webhook`; add `email-alert` / `notify-on-run` |

**Env (outbound only):** `GRAPHYN_SMTP_HOST`, `GRAPHYN_SMTP_PORT`, `GRAPHYN_SMTP_USER`, `GRAPHYN_SMTP_PASSWORD`, `GRAPHYN_SMTP_FROM`, `GRAPHYN_SMTP_TLS` (default `1`), `GRAPHYN_SMTP_DRY_RUN` (`1` = no network), `GRAPHYN_NOTIFY_EMAIL_TO` (run-complete email sink).

---

## 2. Notifications (in-app · webhook · Slack · email · run completion)

| Item | Status | Evidence / notes |
|------|--------|------------------|
| Ops webhook config REST + MCP | DONE | System router webhooks + MCP `get_webhooks` / `put_webhooks` / `test_webhook` |
| Run-complete webhook hook | DONE | `app/core/run_notify.notify_run_terminal` → `pipeline_complete` / `pipeline_failed` |
| Node-level HTTP webhook | DONE | `PluginPackage/Common/http_webhook` |
| Slack as **notification** sink | PARTIAL / needs-credentials | `rag_slack_connector` is **ingest**, not notify; Slack incoming webhook URL works via `http_webhook` / ops webhook |
| In-app notification center / bell | MISSING | No product UI for in-app alerts beyond Runs/Trace |
| Email alert on run complete | PARTIAL → closing | SMTP sink on `run_notify` this wave |
| Slack OAuth bot product | needs-api / needs-credentials | Out of scope without Slack app |

---

## 3. LLM integrations (OpenAI · Anthropic · Azure · Ollama · Gemini · …)

| Item | Status | Evidence / notes |
|------|--------|------------------|
| `structured_llm` openai_compat + local_heuristic | DONE | httpx; fail-closed without key; Groq via `base_url` |
| `llm_chat` multi-provider | PARTIAL → closing | Was stub-only; Wave: stub + openai_compat + ollama |
| `rag_generate` real completion | PARTIAL → closing | Stub default; Wave: openai_compat + ollama when `stub=False` |
| OpenAI / Groq / any OpenAI-compatible | DONE (pattern) | Secret/env `OPENAI_API_KEY` / `GROQ_API_KEY` + `OPENAI_BASE_URL` |
| Ollama / local OpenAI-compatible | PARTIAL → closing | `provider=ollama` (default `http://127.0.0.1:11434/v1`, no key required) |
| Anthropic Messages API native | PARTIAL / needs-credentials | Via openai_compat gateway/`base_url` only; no native SDK |
| Azure OpenAI | PARTIAL / needs-credentials | Via openai_compat `base_url` + key; no Azure AD flow |
| Gemini native | MISSING / needs-credentials | No plugin |
| Secrets fail-closed | DONE | `resolve_secret` + clear RuntimeError / needs-credentials |
| MCP LLM chat product | MISSING (by design) | MCP is control-plane (pipelines/runs), not a chat product |

---

## 4. Agents / HITL / schedules / webhooks

| Item | Status | Evidence / notes |
|------|--------|------------------|
| Agents pack nodes | PARTIAL | Registered (`llm_chat`, `hitl_approve`, `tool_router`, …); several still stub backends |
| HITL + ship/model prod approve | DONE | `hitl_approve` node; model/ship approve REST + MCP |
| Schedules CRUD + ticker | DONE | `app/core/schedules.py` + system router + MCP schedule tools |
| Webhooks ops + node | DONE | See §2 |
| Agentic proposals | DONE | proposals store + UI + MCP |
| Generic chat LLM product | MISSING (out of scope) | PRODUCT_VISION explicitly excludes |

---

## 5. Auth / audit / ship / datasets — open P0/P1 only

| Item | Status | Notes |
|------|--------|-------|
| Bearer fail-closed / X-Actor | DONE | Confirmed in SRS matrix |
| Audit JSONL + export MCP | DONE | |
| Ship packages REST + MCP | DONE | |
| Dataset versions MCP | DONE | |
| FR-AUTH console honesty banner | PARTIAL (P1 residual) | Login/Settings exist; full banner/returnTo not fully audited |
| MCP-005 structured tool errors | PARTIAL | Residual |
| Devices / MCU flash real hardware | needs-api | Honesty stubs only — **do not fake flash** |
| Upload sanitize Phase 2 | PARTIAL | DATA-SYS-005 |

---

## Closable this wave (no user secrets required for CI)

1. Shared `app/core/llm_client.py` + upgrade `llm_chat` / `rag_generate` (+ ollama on `structured_llm`).
2. `send_email` plugin (SMTP env + dry-run).
3. Optional email on `run_notify` when `GRAPHYN_NOTIFY_EMAIL_TO` set (respects `GRAPHYN_SMTP_DRY_RUN`).
4. ASCEN marketplace scenarios: `email-alert`, `notify-on-run`, `llm-local-chat`.
5. Unit tests that skip/mock without credentials; Server-99 smoke with dry-run / Ollama-if-present.

## Explicitly NOT claimed

- Gmail OAuth / IMAP inbox product
- Production mail delivery without `GRAPHYN_SMTP_*`
- Native Anthropic / Gemini / Azure AD SDKs
- Devices flash / FaceRecognition / Cursor cloud deploy

---

## Wave implementation notes (2026-09-26)

### Closed this wave
| Surface | Change |
|---------|--------|
| LLM multi-provider | `app/core/llm_client.py` — stub / openai_compat / ollama; fail-closed `NeedsCredentialsError` |
| `llm_chat` | Real providers; stub default; optional `input` port for linear chains |
| `rag_generate` | Real openai_compat + ollama when `stub=False` |
| `structured_llm` | Added `ollama` provider |
| Mail outbound | `PluginPackage/Common/send_email` + `app/core/smtp_notify.py` (dry-run / needs-credentials) |
| Run-complete email | `run_notify` optional SMTP sink via `GRAPHYN_NOTIFY_EMAIL_TO` |
| Marketplace | ASCEN: `email-alert`, `notify-on-run`, `llm-local-chat` (+ industry variants) |

### Still needs user credentials / product APIs
- Production SMTP (`GRAPHYN_SMTP_*` without dry-run)
- OpenAI / Groq / Anthropic gateway keys
- Ollama daemon on host for local LLM smoke
- Gmail OAuth / IMAP inbox (explicitly not built)
- Slack OAuth bot notify product (use incoming webhook URL)
- In-app notification center UI
- Native Gemini / Azure AD SDKs
- Devices MCU flash hardware APIs


## Wave continuation (2026-09-26 IST)

### Closed
- Native Anthropic + Gemini clients in `llm_client` (fail-closed NeedsCredentialsError; mocks in unit tests)
- In-app notifications store + REST `GET/POST /api/v1/system/notifications*` + MCP `list_notifications` / `mark_notifications_read` + `run_notify` sink
- Ollama wiring via `OLLAMA_BASE_URL=http://172.17.0.1:11434/v1`, model `tinyllama:1.1b`, `OLLAMA_NUM_GPU=0`

### Still needs-credentials
- Production SMTP without dry-run
- OpenAI / Groq / Anthropic / Gemini API keys
- Slack OAuth bot (use incoming webhook)
- Gmail OAuth / IMAP (not built)
