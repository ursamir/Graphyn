# Graphyn — Project Review (Agent Fix Pack)

**Date:** 2026-09-15  
**Status:** **Implemented 2026-09-15** (Batches A–E). Deferred product items remain in `docs/KNOWN_ISSUES.md` (DIST-CANCEL mid-call, RBAC, OTel, Edge loop, UI a11y/responsive, TF-GPU CC≥12, PLUGIN-LOAD bytecode).  
**Scope:** `app/`, `PluginPackage/`, `graphyn-ui/`, `unit_test/`, `examples/`, `scripts/`, docs  
**Audience:** Developer or coding agent fixing issues  
**Rule:** Prefer evidence in this file over outdated doc counts. Canonical runtime: `venv/bin/*`.

---

## How to use

1. Work **Fix batches** in order (Batch A → E). One batch per PR when possible.
2. Each finding: **do / don’t**, files, fix steps, verification.
3. After fixes: update matching `.kiro/steering/` + `docs/` (update protocol); remove fixed rows from `docs/KNOWN_ISSUES.md`.
4. Do **not** reopen items in **Already resolved** unless you re-break them.

---

## Snapshot (ground truth)

| Fact | Value |
|---|---|
| Execution entry | `get_backend().execute(graph)` |
| MCP tools | **29** (`app/mcp/tool_registry.py`) |
| API routers mounted | **17** (`app/api/main.py` `include_router`) |
| Audio `plugin.toml` | **19** (includes `audio_exporter`) |
| Common `plugin.toml` | **29** |
| IR current | `schema_version` **1.2** |
| Auth model | Shared bearer / unauthenticated-dev — **not RBAC** (`docs/TRUST_MODEL.md`) |

---

## Fix batches (recommended order)

| Batch | Goal | Finding IDs |
|---|---|---|
| **A — Blockers / CI** | Build & gate work | F01, F02 |
| **B — Security** | Trust boundaries on execute / FS / install | F03, F04, F05, F06, F07 |
| **C — Runtime correctness** | Schedules, cancel, reclaim | F08, F09, F10, F11 |
| **D — Catalog / plugins** | Inventory, false config, packaging | F12, F13, F14, F15, F16 |
| **E — Docs / hygiene / product debt** | Drift, examples, deferred | F17–F28 |

---

## Findings

### F01 — P0 — `scripts/ui_build.sh` cannot build the UI

**Files:** `scripts/ui_build.sh` (runs `npm ci` at repo root); only `graphyn-ui/package.json` exists  
**Problem:** Script never `cd`s into `graphyn-ui/` → CI/UI build fails.  
**Fix:** `cd "$(dirname "$0")/../graphyn-ui"` (or `npm ci --prefix graphyn-ui && npm run build --prefix graphyn-ui`).  
**Verify:** `bash scripts/ui_build.sh` → `graphyn-ui/dist/` exists.

---

### F02 — P0 — No GitHub Actions; `ci_smoke.sh` is not a real gate

**Files:** no `.github/workflows/`; `scripts/ci_smoke.sh`  
**Problem:** Smoke installs with `GRAPHYN_SKIP_PLUGIN_LOAD=1` and runs ~4 tiny tests. No UI build, no plugin registry, no templates.  
**Fix:** Add workflow: fixed `ui_build.sh` + expanded smoke (plugin load on, `test_all_*_plugins`, `scripts/verify_templates.py`, `check_deps.py`).  
**Verify:** Broken `ui_build` or missing node registration fails CI; main stays green.

---

### F03 — P1 — Inline secret policy not enforced on execute

**Files:** `app/core/ir/secret_policy.py`; `app/api/routers/pipelines.py` (`/run`, `/run-async`); `app/mcp/handlers/execution.py`; `app/core/sdk.py`  
**Problem:** `assert_no_inline_secrets` runs on validate / project save — **not** on execute. Graphs with inline `api_key`/`token` can still run.  
**Fix:** Call `assert_no_inline_secrets(graph)` in one shared pre-execute gate (`get_backend().execute` or all interface entry points). Reject 422 / MCP `inline_secret_error`.  
**Verify:** Extend `unit_test/core/test_secret_policy.py`; API/MCP execute with inline secret → reject.

---

### F04 — P2 — YAML validate skips secret policy

**Files:** `app/api/routers/pipelines.py` (`validate_pipeline_config` YAML branch)  
**Problem:** IR validate scans secrets; YAML→IR path does not.  
**Fix:** After `yaml_config_to_ir`, call `assert_no_inline_secrets(graph)`.  
**Verify:** YAML with `api_key: sk-…` → 422.

---

### F05 — P2 — Input file jail + symlink follow can escape root

**Files:** `app/api/routers/data.py` (`_safe_child`); `app/api/main.py` (`StaticFiles(..., follow_symlink=True)` on `/input-files`)  
**Problem:** Path jail may not resolve symlink targets; static mount follows them → host file read.  
**Fix:** Resolve leaf and require `is_relative_to(input_root)`; prefer `follow_symlink=False` on mounts; serve only via jailed API.  
**Verify:** Symlink under input → outside file; GET must 400/404.

---

### F06 — P2 — Empty plugin allowlist allows all remotes in prod

**Files:** `app/core/config.py` (`plugin_source_is_allowed`); installer  
**Problem:** Unset `GRAPHYN_PLUGIN_ALLOWED_SOURCES` = allow all remotes, even when `auth_required()` / production.  
**Fix:** If `auth_required()`, require non-empty allowlist (or deny remote installs). Keep allow-all only for unauthenticated-dev.  
**Verify:** Prod + empty allowlist + remote install → error.

---

### F07 — P2 — ASR / structured_llm bypass HTTP egress helper

**Files:** `PluginPackage/Common/asr_transcribe/nodes.py`; `structured_llm/nodes.py`; `app/core/egress.py`  
**Problem:** `http_request`/`http_webhook` call `validate_http_egress_url`; ASR/LLM use raw `httpx` — `restricted` mode does not apply (noted in TRUST_MODEL, still a gap).  
**Fix:** Validate provider URLs via `validate_http_egress_url` before `httpx`.  
**Verify:** Restricted + private/metadata URL → raise; public OK.

---

### F08 — P1 — Schedule tick not cross-process safe

**Files:** `app/core/schedules.py`; ticker in `app/api/main.py`  
**Problem:** Threading `RLock` + plain `schedules.json` replace — no flock. Multi-worker / concurrent tick can double-fire.  
**Fix:** Exclusive flock around load→claim due→bump `next_run_at`→save (same pattern as job queue).  
**Verify:** Two processes tick one due schedule → exactly one run.

---

### F09 — P2 — Corrupt `schedules.json` silently becomes `[]`

**Files:** `app/core/schedules.py` `_load`  
**Problem:** Parse failure returns `[]`; later save can wipe real schedules.  
**Fix:** Fail closed on corrupt file; backup; refuse mutators.  
**Verify:** Invalid JSON + create schedule must not overwrite with empty+one.

---

### F10 — P1 — In-process cancel is cooperative only (open)

**Files:** `app/core/node_executor.py`; KNOWN_ISSUES `DIST-CANCEL-1`, `DIST-CANCEL-2`  
**Problem:** Cancel observed between retries / before `process`; mid-`process` / mid-yield only killed for isolated subprocesses.  
**Fix:** Default long GPU/train nodes to `runtime=isolated`; document; optional hard timeout.  
**Verify:** `venv/bin/pytest unit_test/core/test_node_executor_cancel.py` + stuck sleep test for isolated.

---

### F11 — P2 — Heartbeat succeeds when lease renew fails

**Files:** `app/api/routers/workers.py` (`worker_heartbeat`); KNOWN_ISSUES DIST-RECLAIM-1 remaining  
**Problem:** Registry updates; lease renew errors logged only → reclaim while worker looks healthy.  
**Fix:** Fail heartbeat (503) or return explicit `lease_renew_failed`; worker retries.  
**Verify:** Force renew raise → heartbeat not full success; reclaim tests.

---

### F12 — P1 — `audio_exporter` missing from aggregate tests + some docs

**Files:** `PluginPackage/Audio/audio_exporter/`; `unit_test/plugins/audio/test_all_audio_plugins.py` (18 entries); `PluginPackage/NODES.md`; `docs/NODE_CATALOGUE.md`; `docs/PLUGIN_GUIDE.md`  
**Problem:** 19 Audio manifests; exporter used in many example graphs; aggregate test + docs claim “18 Audio” / undercount node catalogue (**48** sections vs **49** types including exporter).  
**Fix:** Add to `ALL_AUDIO_PLUGINS` + process smoke; document exporter; bump to **19 Audio / 49 node types**.  
**Verify:** `rg audio_exporter PluginPackage/NODES.md docs/NODE_CATALOGUE.md`; pytest asserts `audio_exporter` registered.

---

### F13 — P1 — Cross-doc plugin / MCP / router count drift

**Files:** `docs/ARCHITECTURE.md` (23 tools, 16 routers, 18+12 plugins); `README.md` (23 tools); `.cursor/rules/api-and-mcp.mdc` (15 tools); `PluginPackage/ARCHITECTURE.md` (18 Audio / stale Common list); `docs/PLUGIN_GUIDE.md` (under-lists Common); `docs/README.md` (MCP 23) vs `AGENTS.md` / `MCP_SERVER.md` body (29)  
**Problem:** Agents follow wrong inventory; GUIDE Common list stops early vs catalogue.  
**Fix:** One pass: **29 MCP tools**, **17 routers**, **19 Audio + 29 Common = 48 plugins / 49 node types** if exporter is a distinct type (or generate from `plugin.toml` + ClassVars).  
**Verify:** `rg 'register\("' app/mcp/tool_registry.py | wc -l` → 29; lists match on-disk manifests.

---

### F14 — P1 — `dataset_balancer` advertises unimplemented modes

**Files:** `PluginPackage/Common/dataset_balancer/plugin.toml` (`balance_by` enum); `nodes.py` raises unless `balance_by=="class"`  
**Problem:** UI/schema offers `speaker`/`duration`; runtime `NotImplementedError`.  
**Fix:** Narrow enum to `["class"]` until implemented, **or** implement modes.  
**Verify:** Schema enum ⊆ implemented paths; unit tests.

---

### F15 — P1 — WakeWord / empty Video not installable plugins

**Files:** `PluginPackage/WakeWord/**` (no `plugin.toml`); `PluginPackage/Video/` empty  
**Problem:** Not auto-installable; layout implies first-class packs.  
**Fix:** (a) add manifests + nodes, or (b) move to `experimental/` / archive; README on empty Video.  
**Verify:** Intentional status matches `find … -name plugin.toml`.

---

### F16 — P2 — Many manifests omit `node_types`

**Files:** ~many Audio/Common `plugin.toml` without `plugin.node_types`  
**Problem:** Isolated load / catalog tooling less reliable.  
**Fix:** Backfill `node_types = [...]` on every production manifest.  
**Verify:** Script: every `plugin.toml` has non-empty `node_types`.

---

### F17 — P2 — `faster-whisper` in `requirements.txt` not in `setup.py`

**Files:** `requirements.txt`; `setup.py`  
**Problem:** `check_deps.py` EXTRA; `pip install -e .` vs `pip -r` diverge.  
**Fix:** Move to extras (e.g. `asr`) **or** remove from default requirements; keep gate clean.  
**Verify:** `venv/bin/python scripts/check_deps.py` clean.

---

### F18 — P2 — Examples bypass `get_backend()` via `pipeline` shim

**Files:** `examples/09_*`, `12_*`, `15_*`, `16_*`, `17_*`, `18_*` (`from app.core.pipeline import run_pipeline_ir`)  
**Problem:** Mode B / custom backends never exercised by demos.  
**Fix:** Use `get_backend().execute(...)` or SDK `Pipeline.run()`.  
**Verify:** Smoke under `GRAPHYN_BACKEND=distributed` or mock `get_backend`.

---

### F19 — P2 — Example prose / IR version lag

**Files:** example docstrings still naming legacy nodes (`file_input`, `silence_detector`, …); most graphs `schema_version: "1.1"` (current **1.2**)  
**Fix:** Rewrite prose; bump templates (esp. placement) to 1.2 via sync script.  
**Verify:** `scripts/verify_templates.py`; `rg 'file_input|silence_detector' examples` clean of false claims.

---

### F20 — P2 — UI has no typed API contracts / no frontend tests

**Files:** `graphyn-ui/src/api/client.ts` (`as T` casts); `package.json` (build/lint only)  
**Fix:** OpenAPI/zod for hot paths; vitest for `apiJson` + one view smoke.  
**Verify:** Intentional response shape break fails tests.

---

### F21 — P2 — Model prod approve API has no console surface

**Files:** `app/api/routers/models.py` (`request-prod`, `approve-prod`); Runs UI promote only  
**Fix:** Add UI **or** document API-only and hide incomplete prod path.  
**Verify:** UI↔OpenAPI match or explicit “API-only” note.

---

### F22 — P3 — `pipeline.py` still implements deprecated YAML `run_pipeline`

**Files:** `app/core/pipeline.py`  
**Fix:** Move body to shim/sdk; keep deprecate re-export only.  
**Verify:** No fat logic in `pipeline.py`; YAML deprecation tests pass.

---

### F23 — P3 — `_resolve_capability` still re-exported from orchestrator/pipeline

**Files:** `app/core/orchestrator.py`; `app/core/pipeline.py` `__all__`  
**Fix:** Deprecate re-export; importers use `registry_runtime` only.  
**Verify:** `rg 'from app.core.(orchestrator|pipeline) import.*resolve_capability'`.

---

### F24 — P3 — Stale docstrings / MCP surface gaps

**Files:** `artifacts.py` docstring still says `run_pipeline_ir` (code uses `get_backend`); MCP lacks schedules/workers/ingest parity  
**Fix:** Fix docstring; either add MCP tools or document intentional omission in `MCP_SERVER.md`.

---

### F25 — P2 — Event-driven demo may not exit promptly

**Tracked:** KNOWN_ISSUES `EVENT-DRIVEN-EXIT-1`  
**Fix:** Harden `app/core/events.py` close; CI timeout around example 15.  
**Verify:** Example exits &lt; N s after cancel.

---

### F26 — P2 — Keras on GPU CC ≥12 fails (mitigated by CPU default)

**Tracked:** `TF-GPU-CC12-1`  
**Fix:** Wait for TF/CUDA; keep CPU default; document `GRAPHYN_TF_FORCE_GPU=1`.

---

### F27 — P3 — Product / a11y / scale deferred (do not fake as shipped)

| ID | Topic |
|---|---|
| RBAC-1 | No roles/tenants/OIDC |
| OTEL-1 | No OTel spans across workers |
| EDGE-LOOP-1 | No device flash/feedback loop |
| UI-A11Y-1 | Incomplete a11y (not WCAG AA) |
| UI-RESPONSIVE-1 | Desktop-first intentional |
| SCALE-3 | run-async status via `meta.json` polling |
| PLUGIN-LOAD-1 | Stale bytecode / vanished paths (partially mitigated) |

---

### F28 — P2 — Optional-heavy plugin tests skip in default CI

**Files:** classifier / YAMNet / audiocraft / espeak / pyannote / tflite tests  
**Fix:** Split offline vs `[tf]`/backend job; fail if skip rate too high on that job.  
**Verify:** At least one non-skip matrix run for critical ML nodes.

---

## Already resolved — do not reopen

- SEC-001 plugin allowlist prefix matching (structural URL)  
- SEC-002 `python_code` = trusted-operator (not sandbox)  
- SEC-003 HTTP egress for `http_request` / `http_webhook` (ASR/LLM still F07)  
- PLUGIN-001/002 install + registry locks  
- DIST-001/002/003 claim + durable mutators + worker registry RMW  
- DEPS-1 setup/requirements gate (`check_deps.py`) — except F17 EXTRA  
- Auth fail-closed when `GRAPHYN_AUTH_REQUIRED` / prod env + empty token  

---

## Architecture checks (passed)

- No `app/core` importing `app.domain` as a module dependency  
- API / MCP / CLI / SDK execute paths use `get_backend().execute` (examples often do not — F18)  
- Domain audio serialization via `register_audio_serializer()` at API startup  

---

## Quick commands

```bash
venv/bin/python scripts/check_deps.py
venv/bin/pytest unit_test/ -q --maxfail=10
GRAPHYN_SKIP_PLUGIN_LOAD=1 venv/bin/pytest unit_test/core/ -q   # isolated
bash scripts/ui_build.sh                                         # after F01
bash scripts/ci_smoke.sh                                         # after F02 expand
venv/bin/python scripts/verify_templates.py
```

---

## Suggested PR titles

1. `fix(ci): make ui_build.sh work and wire a real smoke gate`  
2. `fix(security): enforce inline secret policy on all execute paths`  
3. `fix(schedules): flock claim-before-tick; fail closed on corrupt JSON`  
4. `fix(plugins): audio_exporter tests + balancer schema honesty + count sync`  
5. `docs: align MCP=29, routers=17, Audio=19, Common=29`
