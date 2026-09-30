# UI Vision Audit — live console vs locked IA

| Field | Value |
|-------|-------|
| **Date** | 2026-09-28 (Asia/Calcutta / IST) |
| **Branch** | `cursor/usecase-plugins-workflows` |
| **Before tip (walk)** | `6910298b` on S99 `~/Desktop/newAudio3` |
| **After tip (shipped)** | `1cad6c59` (terminology/MCP); debt close-out tip below |
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
| Editor | `/workspaces/docker_smoke/editor` | n8n-like canvas, catalog L, inspector R, execution log; catalog pages full `/nodes` registry |
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

- ~~Inactive Home muted like disabled strip~~ **CLOSED** (Pick badge + contrast).
- ~~Dual Secrets vs Credentials~~ — **removed** (Credentials only; see LEGACY_REMOVAL_AND_QUALITY.md).
- Devices / OTA still needs-api.
- Full SSO/RBAC Access page still future.
- Observe panels (Lineage/Compare) live under Runs — correct; keep avoiding Overview↔Editor circular CTAs.


## Debt close-out (Home affordance) — 2026-09-28 IST

> Secrets/Credentials **cross-links** from `d095121f` were **superseded**: legacy Secrets UI/API/MCP deleted (see `LEGACY_REMOVAL_AND_QUALITY.md`). Home Pick badge retained.

## Prior note (superseded dual education)

## Debt close-out archive — 2026-09-28 IST

| Field | Value |
|-------|-------|
| **Before tip** | `f88ff08d` |
| **After tip** | `d095121f` |
| **Scope** | FRONTEND `graphyn-ui` only; S99 local rebuild; locked rail IA unchanged; no FaceRecognition |

### Fixes

1. **Home affordance (workspace strip)** — Home stays always enabled/clickable. Disabled siblings use `opacity-35` + `grayscale` + muted icon. Enabled Home (no workspace) uses stronger ink/accent icon, `font-medium`, and a **Pick** badge so it never looks identical to greyed Editor/Runs/Models/Ship/Datasets. `data-strip-role` / `data-strip-enabled` for DOM checks. Active strip items also get the same ring as global nav.
2. **Secrets ↔ Credentials** — Secrets page: copy marks it as legacy env keys; accent banner **"Credentials is the live store"** + Open Credentials; empty state CTA prefers Credentials. Credentials page: notes inspector `connection_id` + link back to Admin → Secrets. Command palette: Credentials (live store) + Secrets (legacy env keys).
3. **Project chrome** — quick pass found no remaining user-visible Project* leftovers (prior wave already flipped chrome; API `project` fields kept).

### Live re-verify (S99 :5173)

`docker compose build graphyn-ui && up -d` → **200**. Bundle HIT: `data-strip-role`, `opacity-35`, `Credentials is the live store`, `Open Credentials`, `connection_id`.

| Check | Before (`before-debt-*`) | After (`after-debt-*`) |
|-------|--------------------------|------------------------|
| Workspaces strip Home vs disabled | Home muted like siblings when not active (`opacity-40`×5; no Pick) | Home dark + **Pick**; siblings `opacity-35`+grayscale×5; `data-strip-role`×6 |
| Secrets onboarding | "Graphs reference secrets by name…"; empty "Add a named credential…" | Live-store banner + Open Credentials; legacy description; empty dual CTA |
| Credentials | Precedence only | + `connection_id` note + Admin → Secrets cross-link |
| Rail IA | PASS | PASS (same strip + Build/Library/Deploy/Admin) |

Screenshots/DOM: `docs/_gen/ui-audit/before-debt-*.png`, `after-debt-*.png`, `dom-before-debt-*.html`, `dom-after-debt-*.html`.

### Remaining (unchanged / out of scope)

- Devices / OTA still needs-api.
- Full SSO/RBAC Access page still future.
