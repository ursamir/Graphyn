# UI Vision Audit — live console vs locked IA

| Field | Value |
|-------|-------|
| **Date** | 2026-09-28 (Asia/Calcutta / IST) |
| **Branch** | `cursor/usecase-plugins-workflows` |
| **Before tip (walk)** | `6910298b` on S99 `~/Desktop/newAudio3` |
| **After tip (shipped)** | `1cad6c59` — UI rebuilt on S99 |
| **Method** | Docs read (PRODUCT_VISION, UI_NORTH_STAR, UI_WORKSPACE_IDE, REQUIREMENTS_SPEC §10, PRODUCT_READINESS_SCORE) + headless Chrome walk of live `graphyn-ui` @ `http://127.0.0.1:5173` (S99) with Bearer planted same-origin |
| **Screenshots** | `docs/_gen/ui-audit/01-*.png` … `16-*.png` (before rebuild) |

## Locked IA checklist (walk)

| Rule | Before | After (this wave) |
|------|--------|-------------------|
| One stable left rail (no Global/Workspace morph) | **PASS** — same strip + Build/Library/Deploy/Admin always | unchanged |
| Strip: Home · Editor · Runs · Models · Ship · Datasets | **PASS** | unchanged |
| Editor/Runs/Models/Ship/Datasets greyed without workspace | **PASS** (Home stays enabled in code; inactive look is muted, not `disabled`) | unchanged |
| Models / Ship / Datasets never in global Library/Deploy | **PASS** — Library=Plugins+Artifacts; Deploy=Worker fleet | unchanged |
| UI term **Workspace** (not Project) in chrome | **PARTIAL** — rail/titles good; Home banner "Project pipelines", "Project settings", create placeholder `my-pipeline-project`, Ship/Ops/error copy still said Project | **FIXED** |
| Editor unified name (no Builder chrome) | **PASS** | unchanged |
| Inter UI / mono for logs·IDs | **PASS** | unchanged |
| Credentials discoverable | **PASS** — Admin → Credentials; list + create; inspector picker exists in Editor | unchanged |
| NotificationBell | **PASS** — header bell with unread badge | unchanged |
| Marketplace tab | **PASS** — Templates → Marketplace pill; REST `/pipelines/marketplace/*` | unchanged |
| Mode B / Workers honesty | **PASS** — Mode A empty state + trust banner | unchanged |
| MCP light UI hint | **PARTIAL** — Ops chip said "29 tools" (stale) | **FIXED** → ~74 tools (agent-facing) |
| No FaceRecognition / fake device flash | **PASS** — Devices honesty stub | unchanged |

## Page-by-page (before)

| Page | URL | IA / product notes |
|------|-----|-------------------|
| Workspaces picker | `/workspaces` | Correct primary entry; create placeholder used "project"; strip greyed except Home |
| Templates | `/templates` | Marketplace tab present; stamp→Editor copy correct |
| Credentials | `/admin/credentials` | Discoverable; smoke-ollama/openai listed; precedence banner |
| Worker fleet | `/deploy/workers` | Mode A honesty; no workers; trust boundary banner |
| Plugins | `/library/plugins` | Packs catalog surface |
| Ops | `/admin/ops` | Health + MCP chip (stale count) |
| Artifacts / Agent inbox / Secrets / Access | library/agent/admin | Reachable; no rail violations |
| Workspace Home | `/workspaces/docker_smoke` | Situation cards OK; **"Project pipelines"** / **"Project settings"** labels |
| Editor | `/workspaces/docker_smoke/editor` | n8n-like canvas, catalog L, inspector R, execution log; catalog 50 categories |
| Runs / Models / Ship / Datasets | workspace paths | Strip-only; Ship lineage still labeled Project |

## Dead ends / empty states

- Workers empty → clear Mode B CTA (good).
- Agent inbox / Models empty paths offer next clicks (acceptable).
- Devices embedded in Ship: honesty-only (expected needs-api).

## Wrong architecture? (guard)

- Did **not** add global Models or morphing rails.
- Did **not** put Models/Ship/Datasets under Library/Deploy.
- API field `project` remains on the wire; UI chrome says Workspace.

## Fixes shipped this wave

1. Chrome terminology: Project → Workspace in Home banner, settings summary, create placeholder, error boundary, Ship lineage/toasts/CTA, Ops schedule picker, Builder pipeline aria-label.
2. Ops MCP honesty: `29 tools` → `~74 tools (agent-facing)`.

## After re-walk

S99: `git pull` → `1cad6c59` → `docker compose build graphyn-ui && up -d` → UI :5173 **200**. Bundle HIT: Workspace settings/pipelines, ~74 tools, my-workspace, Back to Workspaces, Select workspace. Live DOM after hard-nav:

| Check | Result |
|-------|--------|
| Tip on S99 | `1cad6c59` |
| Workspace Home copy | **Workspace pipelines** / **Workspace settings** (Project* gone) |
| Ops MCP chip | **~74 tools (agent-facing)**; no "29 tools" |
| Create placeholder | Bundle has `my-workspace` |
| Rail still locked IA | **PASS** — same strip + groups; Credentials + NotificationBell + Marketplace unchanged |
| After screenshots | `after-ws-home.png`, `after-ops.png`, `after-ship.png`, `after-workspaces.png` |

## Remaining UI debt (honest)

- Inactive Home on global pages can *look* as muted as disabled strip siblings (enabled in DOM; optional contrast polish).
- Dual Secrets vs Credentials education still thin for new users (both under Admin — correct, but onboarding copy could cross-link).
- Devices / OTA still needs-api.
- Full SSO/RBAC Access page still future.
- Observe panels (Lineage/Compare) live under Runs — correct; keep avoiding Overview↔Editor circular CTAs.
