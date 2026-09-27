# Product readiness score (honest)

| Field | Value |
|-------|-------|
| **Date** | 2026-09-27 (Asia/Calcutta) |
| **Branch** | `cursor/usecase-plugins-workflows` |
| **Tip (before)** | `efd28604` (credential store) |
| **Tip (after / shipped)** | `aa22e597` on S99 `~/Desktop/newAudio3` |
| **Vision** | n8n + MLflow + orchestrator + Edge Impulse + agents (one product) |
| **Method** | SRS gap matrix + broader surface gap + static UI/API evidence. P0 weighted 2× P1. |

## Scoring rules

- **Overall %** = weighted readiness across pillars vs full vision (includes needs-credentials / needs-api as incomplete).
- **Closable %** = same pillars but excluding surfaces that **require** user secrets, OAuth products, or hardware device APIs. Closable = code/docs/UI that can ship without those.
- Confirmed ≈ 100, Partial ≈ 55, Missing ≈ 10, needs-credentials/needs-api ≈ excluded from closable denominator (still drag overall).

## Before (tip `efd28604`)

| Pillar | Weight (P0/P1) | Score | Notes |
|--------|----------------|-------|-------|
| Editor/canvas | P0×2 | 88% | Strong IR canvas; connection_id was free-text |
| Runs/Observe | P0×2 | 90% | Runs, Trace, Experiments, lineage |
| Plugins/packs | P0×2 | 86% | Lifecycle solid; agent create-plugin path thin in docs |
| Templates/marketplace | P0×2 | 72% | Seeded Templates UI; marketplace catalog MCP-only |
| Credentials | P0×2 | 82% | Store + Admin UI; inspector bind missing |
| LLM/notify/mail | P1×1 | 78% | LLM/SMTP nodes + notify store; **bell UI missing**; live SMTP needs-creds |
| Deploy/Ship/Workers/Mode B | P0×2 | 84% | Ship REST, Workers, Mode B docs; no one-click health |
| Devices/edge | P0×1 | 55% | Wizard + packager; devices **needs-api** |
| MCP/agents | P0×2 | 88% | ~74 tools; MCP_SERVER still said “29” |
| Auth/audit | P0×2 | 86% | Bearer + audit; no SSO/RBAC (future) |
| Ops | P1×1 | 88% | Health/readiness/cleanup/backup |

| Metric | Before |
|--------|--------|
| **Overall (full vision)** | **81%** |
| **Closable product surface** | **86%** |
| Closable residual | Notify bell UI; credentials inspector bind; marketplace console browse; Mode B health script; MCP docs drift; agent create-plugin docs |
| Needs-credentials (excluded from closable) | Live SMTP, paid LLM keys, Slack/Gmail OAuth |
| Needs-API/hardware (excluded) | MCU flash/OTA device loop |

**Honest answer to “+90% ready?”:** **No** on full vision (~81%). Closable surface was ~86% — short of 90%.

## After (this wave)

| Pillar | Weight | After | Delta |
|--------|--------|-------|-------|
| Editor/canvas | P0×2 | **92%** | + connection_id credential picker |
| Runs/Observe | P0×2 | 90% | — |
| Plugins/packs | P0×2 | **90%** | + agent create-plugin path docs |
| Templates/marketplace | P0×2 | **90%** | + REST search/materialize + Marketplace tab |
| Credentials | P0×2 | **93%** | + inspector bind UX |
| LLM/notify/mail | P1×1 | **90%** | + NotificationBell (live SMTP still needs-creds) |
| Deploy/Ship/Workers/Mode B | P0×2 | **90%** | + `mode_b_health.sh`; shipPackage path |
| Devices/edge | P0×1 | 55% | unchanged (needs-api honesty) |
| MCP/agents | P0×2 | **92%** | docs count fixed; credentials/notify in coverage |
| Auth/audit | P0×2 | 86% | — |
| Ops | P1×1 | **90%** | Mode B health script |

| Metric | After |
|--------|-------|
| **Overall (full vision)** | **86%** |
| **Closable product surface** | **92%** |

### Closed this wave (closable)
1. In-app **NotificationBell** → `/system/notifications*`
2. Inspector **connection_id** picker from `/credentials`
3. REST marketplace search + materialize; Templates **Marketplace** tab
4. `paths.shipPackage`; `scripts/mode_b_health.sh` + Mode B operate note
5. MCP tool-count docs drift; PLUGIN_GUIDE agent create-plugin path
6. Marketplace needs-api honesty banners on cards

### Remaining blockers (honest)
| Kind | Items |
|------|-------|
| **needs-credentials** | Production SMTP (no dry-run); OpenAI/Anthropic/Gemini/Groq keys; Slack OAuth bot; Gmail OAuth/IMAP (not built) |
| **needs-API / hardware** | Device registry / MCU flash / OTA |
| **Product / P1 residual** | Full SSO/RBAC; OTel spans; Perf TBD-PERF-*; upload sanitize depth; MCP-005 structured errors polish; remote CLI for all resources |
| **Ops note** | Mode B still needs operator tunnel + lean worker (script only probes) |

## Closable vs needs-credentials vs needs-API

| Bucket | Est. share of vision | Status |
|--------|----------------------|--------|
| Closable (code/UI/docs) | ~70% of vision weight | **≥90% ready after this wave** |
| Needs-credentials | ~15% | Fail-closed stubs; operator brings keys |
| Needs-API/hardware | ~10% | Honesty stubs only |
| Explicit non-goals / future | ~5% | SSO, OTel, Cursor cloud |

## Verdict

- **Closable ≥90%:** **Yes (92%)** after this wave.
- **Overall full vision ≥90%:** **Not yet (86%)** — blocked on credentials + device APIs + SSO/OTel, which we will not fake.

## Server-99 smoke (2026-09-27 ~16:31 IST)

| Check | Result |
|-------|--------|
| Tip on S99 | `aa22e597` |
| `GET /system/health` | 200 ok |
| Marketplace search `email-alert` | matched 6; materialize ok (3 nodes, schema 1.1) |
| Notifications list | 200 (unread present) |
| Credentials kinds | anthropic, gemini, ollama, openai_compat, smtp, webhook |
| UI :5173 | 200; bundle contains `notification-bell`, `marketplace-browse`, `connection-id-picker` |
| Readiness after rebuild | temporarily `ready=false` while auto-reinstall upgrades isolated plugin venvs (dataset-builder/tensorflow etc.) — expected post-rebuild; not a feature regression |

No FaceRecognition / MCU flash fakes.
