# Claude Code Technical Review — Graphyn
**Repo tip:** 3b48b36e6c16101b0d524e73236f0a5852b7bb81
**Branch:** cursor/usecase-plugins-workflows
**Date:** 2026-09-29 (Asia/Calcutta)
**CLI:** Claude Code 2.1.268
**Method:** Four read-only Claude Code passes (general deep-dive, architecture, security+credentials, UI/IA+readiness), merged.

---

## Executive summary

1. **The single biggest product-honesty gap is undisclosed non-functional plugin stubs.** 94–106 of 156 bundled node plugins (RAG, Vision, TinyML, MLOps, Agents, WakeWord, Video) silently return empty/fabricated output by default, with no badge in the UI, no mention in `docs/ARCHITECTURE.md`/`NODE_CATALOGUE.md`, and at least one shipped marketplace template wired to a node that always fakes its result. This is the exact failure mode the project's own docs say must never happen.
2. **The project's "ground truth" documents are themselves wrong by large margins**, and the doc AGENTS.md tells agents to trust (`PROJECT_REVIEW.md`) is among the stalest: MCP tool count is documented as 29 vs an actual 78 (2.7×); plugin manifests are documented as "48 packages" vs an actual 156 (>3×).
3. **Four P0 security bugs give any authenticated caller either arbitrary filesystem access or credential/secret disclosure**: unvalidated project-name path traversal (`project_manager.py`), a scheme-check gap that defeats the plugin-source allowlist (`git://`/`ssh://`), a webhook endpoint + audit log that return the raw webhook URL (the secret itself) in plaintext, and plugin-install error messages that leak credentials embedded in source URLs via a pollable job-status endpoint.
4. **A genuinely serious cross-process locking gap exists specifically on Windows/non-POSIX platforms.** Both the schedule ticker and the distributed job queue's default store silently drop all file-locking via `except ImportError: fcntl = None`, reintroducing the exact double-fire/double-claim race the code and docs claim is closed — and this platform prerequisite is documented nowhere.
5. **Reclaimed distributed jobs leave permanent, unreconciled side effects.** Lease-generation fencing correctly rejects a zombie worker's late `complete()`, but nothing rolls back or tombstones blobs that worker already wrote — an architectural gap matching the project's own `KNOWN_ISSUES.md` entry.
6. **`DistributedBackend` is not the drop-in replacement for `LocalPythonBackend` the docs claim it is**: caching and conditional-edge semantics silently no-op for remote-placed nodes, and pause does not propagate to already-dispatched remote jobs (only cancel does) — both undocumented and both capable of wasting GPU-hours or producing stale results.
7. **SSRF/egress controls have multiple real bypasses**: redirect-following on URL ingestion skips re-validation per hop; `python_code` with `allow_network=True` fully bypasses the egress policy; the webhook sender has no IP-pinning despite docs and code comments claiming it does (DNS-rebinding TOCTOU); and the secret-key-name denylint is trivially evaded by renaming a field.
8. **A previously-"fixed" bug class does not generalize.** The "selection silently reconfigures global workspace" bug is genuinely fixed in `ArtifactsView.tsx` but is still live, unfixed, in `RunsView.tsx` — direct evidence that this audit-heavy project's narrative claims ("fixed system-wide") need independent re-verification, not just trust.
9. **MCP and REST are not fully equivalent trust surfaces**, contrary to how the docs frame them: MCP's `execute_pipeline` skips full IR validation and the shutdown-drain check that REST enforces, and `docs/MCP_SERVER.md` incorrectly claims schedules/worker-pool management are REST-only when they are live MCP tools.
10. **Console IA vs. Web-IDE vision compliance is strong and defensively engineered** — the stable rail, forbidden-pattern guards (`(): never` throws), hash-route retirement, and Secrets→Credentials removal are all genuinely complete, not just documented as complete. This is the most solid area of the whole review.
11. **Test coverage has an inverse relationship with risk.** The 106 newest, least-mature plugins (68% of the node surface) share exactly one aggregate test that silently swallows individual install failures (`except Exception: continue`) and spot-checks only 6 node types — meaning a substantial fraction of the stub-plugin problem (finding #1) could be entirely broken, not just stubbed, undetected by CI.
12. **The bearer API token is stored in `localStorage`** on both the security and UI/IA passes' independent findings — full API compromise on any XSS, a team-acknowledged P1 gap (`App.tsx:1233,1240-1244`) rather than a surprise.
13. **Frontend/backend "honesty banners" are consistently well-engineered**: Devices/OTA, Access/RBAC, and ship-package model-path all fail closed with clear, labeled, non-fake stubs rather than fabricated success — this pattern holds everywhere it was checked.
14. **A `store`↔`URL` integrity bug** seeds `activeProject` from stale `localStorage` before the URL is parsed, briefly rendering a workspace-scoped Editor for a workspace not in the address bar — a direct violation of the locked "URL is source of truth" requirement, self-correcting a tick later.
15. **Where claims could be checked against real, substantive code** (secret-policy tests, cancel semantics, distributed concurrency tests, data-router symlink jail, credential-store consolidation, hash-route retirement), they mostly **held up** — this is not a project of fabricated work, but one whose rate of new work has outpaced its rate of verifying and documenting that work.

---

## 1. Architecture

**Map:** REST (18 routers) / CLI / MCP (78 tools) all converge on a single canonical entry point, `get_backend().execute(graph)` — verified with zero bypasses anywhere in `app/api/routers/`, `app/cli/`, `app/mcp/handlers/`, or `app/core/agentic/`. `LocalPythonBackend` runs the orchestrator/planner/executor stack in-process; `DistributedBackend` places nodes onto remote workers via a job queue + worker registry + content-addressed blob transfer. Plugins register into a single `NodeRegistry` populated by boot-time auto-discovery across `app/core/nodes/*.py`, `app/models/*.py`, and `plugins/{name}/`. MCP handlers are a genuine thin parity layer over the same `app/core/*` classes as REST for the surfaces checked (execution, artifacts/provenance, credentials, proposals).

**Dual paths / legacy remnants** (see `docs/ARCHITECTURE.md` §1, architecture pass §2 for full table):
- `app/core/run_manager.py` — clean 39-line deprecated re-export shim; one stale import remains (`yaml_shim.py:205`).
- YAML pipeline format — still reachable, always warns, routes through the same canonical backend (not a bypass).
- Legacy `GRAPHYN_HOME/secrets/` file store vs. `credentials/store.sqlite` — genuinely consolidated: REST `/api/v1/secrets`, MCP `secrets_list/secrets_set`, and `SecretsView` were all deleted in one commit (`3b9cc66`); only a narrow CLI ops-bootstrap tier remains by design.
- UI hash routes (`#/...`) — fully retired, not just redirected; `parsePath.ts` never reads `location.hash` for routing.
- **Isolated vs. in-process plugin execution is a live, intentional architectural duality** (not legacy) with materially divergent guarantees: isolated plugins cannot stream, carry subprocess overhead and a 3600s default timeout, and cross a `RestrictedUnpickler` trust boundary — invisible from a node's own code, only visible via `plugin.toml`'s `runtime` field.
- `PluginManager`'s "single entry point" claim has two live bypasses (`app/api/routers/plugins.py:73`, `app/core/nodes/discovery.py:229-231`), low-impact today only because `plugins/` is empty.
- Distributed blob transfer (`transfer.py`) and `ArtifactStore` are two structurally independent content-addressed stores with the same hashing concept — duplication of design, not shared code.
- `docs/ARCHITECTURE.md` understates plugin/node counts by >3× and `docs/MCP_SERVER.md` incorrectly claims schedules/worker management are REST-only (they are live MCP tools) — both matter for architecture/security review scoping.

---

## 2. Production quality

- **Legacy removal is largely clean and test-guarded**, not cosmetic: Secrets→Credentials deletion is backed by regression tests that assert 404/`ModuleNotFoundError` on the old surfaces; hash-route retirement removed the actual component files, not just the router.
- **Naming drift ("project" vs. "Workspace"):** mostly fixed but 10 concrete user-visible strings still say "project," several sitting directly next to a sibling string that correctly says "Workspace" in the same component (`CommandPalette.tsx:154`, `BuilderView.tsx:1410/1420`, `DataView.tsx:1008-1010`, `SystemView.tsx:762,890`, `EdgeWizardView.tsx:889`, `TemplatesView.tsx:1011`) — proving genuine drift, not intentional wire-format naming.
- **Store↔URL integrity bug (new finding):** `appStore.ts:186-192,336` seeds `activeProject`/initial view from stale `localStorage` before the URL is consulted, briefly rendering a workspace-scoped Editor for a workspace the address bar never named. Self-corrects via `App.tsx:359-363,487-518` a tick later, but violates the locked "URL is source of truth" requirement and fires stray scoped fetches in the interim.
- **`CommandPalette.tsx` maintains a third, independently hand-copied nav-label list** (`VIEW_JUMPS`), separate from `App.tsx`'s `NAV_GROUPS` and the already-centralized `routes/nav.ts` — the exact drift class that has already bitten this team once (per `nav.ts`'s own doc comment).
- **Test coverage for the seven newest plugin packs (106/156 plugins, 68% of node surface) is effectively zero**: one aggregate test asserts `len(installed) >= 100`, spot-checks 6 node types, and silently swallows individual install failures (`except Exception: continue`) — a meaningful number of stub plugins could be entirely broken, not just stubbed, undetected.
- **`graphyn-ui/src` test coverage overall is near-zero**: only two test files exist in the whole tree, covering small API-layer helpers; zero tests for ~30 feature views (some 1000+ lines) or the global store/routing.
- **Type-safety discipline is better than assumed**: zero `as any`/`@ts-ignore`/`@ts-expect-error` in `src/`; the one `as unknown as` cast is guarded by a preceding type-narrowing check.
- **Doc/spec drift**: `docs/REQUIREMENTS_SPEC.md:3300` still normatively lists "Secrets" in the Admin IA group though the shipped console replaced it with Credentials — a greenfield rebuild from the SRS alone would regress the fixed IA.
- Deprecated dual-path surfaces remain live and reachable (YAML pipeline input, legacy `PipelineCache.has()`) — labeled and warning, not silent, but still real surface area.

---

## 3. Security

Four P0s give any authenticated bearer holder either arbitrary filesystem access or secret/credential disclosure (full detail in §6 table):
1. **Path traversal via unvalidated project name** (`project_manager.py:78-82`) — `_require_project()` never calls the existing `_validate_name` guard; reachable through 40+ routes in `projects.py` and directly via `ship.py`. On this review's Windows environment, directly exploitable for arbitrary file read/write.
2. **Plugin source allowlist bypass** (`installer.py:132-137`) — `git://`/`ssh://`/mixed-case scheme sources skip the `GRAPHYN_PLUGIN_ALLOWED_SOURCES` check entirely while still being piped into `git clone`.
3. **Webhook URL (the secret itself) returned in plaintext** by `GET /api/v1/system/webhooks` and permanently retrievable via the audit log/trace endpoint, even after rotation.
4. **Plugin-install error messages leak embedded credentials** (e.g. `https://user:TOKEN@host/...`) via a pollable job-status endpoint and the synchronous 500 body.

Additional confirmed bypasses/gaps (P1, full list in §6): SSRF via redirect-following on URL ingestion (no per-hop re-validation, unlike the plugin installer which does this correctly); `python_code allow_network=True` as a full, systemic bypass of the `restricted` egress policy; a secret-key-name denylist (`secret_policy.py`) trivially evaded by renaming/splitting a field despite being documented as a "P0 fail-closed control"; no IP-pinning on the webhook sender despite `docs/TRUST_MODEL.md:81` and the code's own docstring claiming it; git-sourced plugin installs dereferencing symlinks via `shutil.copytree(symlinks=False)` (arbitrary file read, inconsistent with the zip/tar protection which correctly rejects symlinks); a PEP 508 dependency-URL check that isn't gated on `auth_required()`; a `str.format()`/`format_map()` dunder-traversal bypass of the `python_code` AST filter (info-disclosure only, not RCE — `getattr`/`eval`/`exec`/`compile` remain absent from `safe_builtins`); incomplete/router-scoped 422 secret redaction; the bearer API token stored in `localStorage`; and the shipped `docker-compose.yml` default (`GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS=1`) fully disabling the dataset symlink-escape check rather than narrowly permitting symlinks.

**Checked and found secure as claimed:** router auth coverage (all 18 routers + 3 static mounts via one consistent `_auth_dep`); MCP auth as a single choke point; the plugin-source allowlist's traversal/NUL handling; the data-router path jail's symlink resolution (when the Docker override above is not set); the `python_code` AST filter's dunder-attribute/restricted-builtins core (separate from the format-string bypass); and the credential-at-rest encryption construction (encrypt-then-MAC, constant-time verify, random nonces — sound logic, though hand-rolled rather than a vetted AEAD, see P2s).

Credential-store design is otherwise clean: allowlist-based payload validation, `get_payload()` restricted to the resolver, and consistent redaction on list/get. Remaining P2s: homegrown AEAD without key separation between encryption and MAC; unsalted single-pass SHA-256 for passphrase-style master keys (no KDF work factor); and the legacy plaintext-on-disk secrets store sitting alongside the encrypted credential store with different at-rest guarantees.

---

## 4. Console IA vs Web IDE vision

**Verdict: matches the locked spec, and is defensively engineered against regression** — the strongest-verified area of the whole review.
- Workspace strip order/labels, group membership (Build/Library/Deploy/Admin), and the single-boolean enable/disable pattern all exactly match the locked spec (`App.tsx:66-108,800-831`).
- Forbidden patterns are guarded in code, not just absent by omission: `paths.libraryModels`, `paths.deployShip`, `paths.deployShipDevices` are typed `(): never` and throw if any caller tries to resurrect a global Models/Ship page; bookmarked legacy URLs are canonicalized rather than rendered.
- Routing is real `BrowserRouter` path-based routing; hash routing is genuinely retired (component files deleted, not just redirected), with a one-shot cold-boot cleanup plus a per-navigation strip as belt-and-suspenders.
- Secrets→Credentials removal is real: no `SecretsView.tsx` anywhere, no `'secrets'` in the `AppView` union, backend routes/handlers don't exist, and dedicated regression tests assert the removal.
- One doc/spec drift: `docs/REQUIREMENTS_SPEC.md:3300`'s normative §10.2 IA table still lists Secrets instead of Credentials (P2, greenfield-rebuild risk).
- Honesty banners are consistently strong: Devices/OTA, ship-package model paths, and Access/RBAC all fail closed with explicit, labeled, non-fake stubs (`DevicesView.tsx:35-42`, `EdgeWizardView.tsx:1082-1089`, `AccessView.tsx:20-45`) — matched by zero RBAC routes actually mounted on the backend, confirming the frontend isn't overclaiming relative to what exists.

---

## 5. Test/ops readiness and remaining blockers

All test/ops blockers identified are **genuine, correctly-labeled, fail-closed gaps** — not faked or hidden:

| Blocker | Status | Evidence |
|---|---|---|
| SMTP | Fail-closed + dry-run | `app/core/smtp_notify.py:141-186` — dry-run never opens a socket; raises `NeedsCredentialsError` when unset; real SMTP exceptions re-raised, not swallowed |
| LLM keys (OpenAI/Anthropic/Gemini/Groq) | Fail-closed | `app/core/llm_client.py:11,325-378` — documented policy, concrete raises per provider; only `ollama`/`stub` skip the requirement |
| MCU flash/OTA | Honest stub, tracked P0/P2 | `DevicesView.tsx:7-53` — no fake fleet/flash/OTA progress; backend has no device registry route |
| SSO / full RBAC | Deferred non-goal, honestly stubbed | `AccessView.tsx:20-45`; zero RBAC routes in `app/api/main.py:271-288`; explicitly out-of-scope in SRS |
| OTel | Not built, docs-only | repo-wide grep hits only markdown; zero instrumentation or fake trace UI |
| S99 smoke | Real, hard-assertion scripts | `scripts/docker_ide_loop_smoke.sh` and `mode_b_health.sh` hard-fail (`exit 1`) on non-success, no fabricated entries |

Net position per `docs/_gen/PRODUCT_READINESS_SCORE.md` (Closable 92%, Overall 86%) is corroborated, not contradicted, by this review. Remaining engine-level readiness risks not yet reflected in that score: the Windows/non-POSIX locking gap (§6 P0), `DistributedBackend`'s silent cache/conditional-edge and pause-propagation gaps (§6 P1), the zombie-write reconciliation gap in the distributed job queue (§6 P0), and the near-zero test coverage for both the 106 newest plugins and the entire `graphyn-ui` feature-view layer.

---

## 6. Top prioritized findings (P0 / P1 / P2)

**Totals: P0 = 7, P1 = 21, P2 = 19 (47 total, deduplicated across all four passes).**

| # | Sev | Finding | File(s) |
|---|---|---|---|
| 1 | **P0** | Path traversal via unvalidated project name → arbitrary filesystem read/write for any bearer holder | `app/domain/project_manager.py:78-82`; `app/api/routers/ship.py:30-37`; `app/api/routers/projects.py` (40+ routes) |
| 2 | **P0** | Plugin source allowlist bypass: `git://`/`ssh://`/mixed-case schemes skip `GRAPHYN_PLUGIN_ALLOWED_SOURCES` entirely | `app/core/plugins/installer.py:132-137`; `app/api/routers/plugins.py:56,61` |
| 3 | **P0** | System webhook URL (the secret itself) returned in plaintext by API and permanently in audit log/trace | `app/core/webhook.py:91-118`; `app/api/routers/system.py:148-158`; `app/core/audit.py`; `app/api/routers/trace.py:54-59` |
| 4 | **P0** | Plugin-install error messages embed source-URL credentials, returned verbatim via a pollable job-status endpoint | `app/core/plugins/installer.py:236-239,282-284`; `app/api/routers/plugins.py:238-249,361-365` |
| 5 | **P0** | 94–106 of 156 plugins are undisclosed non-functional stubs (`_process_real` re-enters the stub branch); no UI badge, no doc mention, one shipped marketplace template wired to a faking node | `PluginPackage/RAG/hybrid_retrieve/nodes.py:89-110`; `PluginPackage/MLOps/drift_detect/nodes.py:89-108`; `docs/NODE_CATALOGUE.md`; `graphyn-ui/src/features/templates/TemplatesView.tsx`; `examples/templates/marketplace/tpl-mlops-drift-watch-audio.graph.json:16` |
| 6 | **P0** | Cross-process file locking silently degrades to no-op on Windows/non-POSIX (`fcntl` unavailable → unconditional unlocked execution), reintroducing the double-fire/double-claim race the docs claim is closed | `app/core/schedules.py:295-315`; `app/core/distributed/store.py` |
| 7 | **P0** | Reclaimed distributed job side effects are never rolled back — zombie worker's blob writes persist permanently with no reconciliation signal | `app/core/distributed/queue.py:919-933`; `app/core/distributed/transfer.py:94-122` |
| 8 | P1 | `RunsView.tsx` has the exact "selection silently reconfigures global workspace" bug that `ArtifactsView.tsx` fixed — the fix did not generalize | `graphyn-ui/src/features/runs/RunsView.tsx:566-571` |
| 9 | P1 | Documentation quantitative drift: MCP tools 78 actual vs. 29 claimed (2.7×); plugin manifests 156 actual vs. "48 packages" claimed (>3×); router count off by 1–2; `AGENTS.md` directs agents to trust the stalest doc | `AGENTS.md`; `PROJECT_REVIEW.md`; `docs/ARCHITECTURE.md`; `README.md`; `.cursor/rules/api-and-mcp.mdc` |
| 10 | P1 | `DistributedBackend` silently drops caching and conditional-edge semantics for remote-placed nodes — no error/warning surfaced | `app/core/distributed/backend.py:297-309,352-363` |
| 11 | P1 | Pause does not propagate to already-enqueued/running remote jobs (only cancel works) — operator believes GPU workers stopped when they haven't | `app/core/run_journal.py:272-278`; `app/core/distributed/backend.py:387,497` |
| 12 | P1 | MCP `execute_pipeline` has weaker guardrails than REST: skips full IR validation and the shutdown-drain check | `app/mcp/handlers/execution.py:86-89` vs `app/api/routers/pipelines.py:469-509` |
| 13 | P1 | Isolated vs. in-process plugin execution is a structurally different code path with divergent streaming/timeout/failure guarantees, invisible from node code | `app/core/plugins/loader.py:552-556`; `isolated_executor.py:345`; `node_executor.py:255-332` |
| 14 | P1 | `docs/MCP_SERVER.md` incorrectly claims schedules/worker-pool management are REST-only — they are live MCP tools; under-scopes MCP's governance blast radius | `app/mcp/tool_registry.py:353-357,378-379` |
| 15 | P1 | SSRF via redirect bypasses `restricted` egress mode on URL ingestion — no re-validation per redirect hop | `app/domain/ingestion.py:266,316` |
| 16 | P1 | `python_code` with `allow_network=True` fully (and systemically) bypasses the egress SSRF policy | `PluginPackage/Common/python_code/nodes.py:72-74` |
| 17 | P1 | `secret_policy.py` is a pure key-name denylist, trivially evaded (rename/split/encode) despite being documented as a "P0 fail-closed" control | `app/core/secret_policy.py`; `docs/REQUIREMENTS_SPEC.md` |
| 18 | P1 | Webhook sender has no IP-pinning transport (DNS-rebinding TOCTOU); both `docs/TRUST_MODEL.md:81` and the code's own docstring falsely claim pinning is applied | `app/core/webhook.py:163-178,174-177` vs `docs/TRUST_MODEL.md:81` |
| 19 | P1 | Git-sourced plugin installs dereference symlinks via `shutil.copytree(symlinks=False)` — arbitrary file-read primitive, inconsistent with zip/tar's symlink rejection | `app/core/plugins/manager.py:287` |
| 20 | P1 | Dependency URL allowlist check isn't gated on `auth_required()` — a local-only plugin can still pull unrestricted pip URL dependencies under `GRAPHYN_AUTH_REQUIRED=1` | `app/core/plugins/dependencies.py:322-327` |
| 21 | P1 | `python_code` AST filter bypassed via `str.format()`/`format_map()` dunder-attribute traversal (info-disclosure only, no RCE path available) | `PluginPackage/Common/python_code/nodes.py:86-87` |
| 22 | P1 | 422 secret-field redaction is scoped only to `/api/v1/credentials` and its trigger list omits `url`/`secret`/`webhook_url`/`authorization`/`private_key` | `app/api/errors.py:200-213` |
| 23 | P1 | Bearer API token stored in `localStorage` — full API compromise on any XSS; self-acknowledged by the team as a pending P1 | `graphyn-ui/src/api/client.ts:10,28-39,64-65`; `App.tsx:1233,1240-1244` |
| 24 | P1 | Shipped `docker-compose.yml` default (`GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS=1`) fully disables the dataset symlink-escape check rather than narrowly permitting symlinks | `app/api/routers/data.py:67-74`; `docker-compose.yml:38` |
| 25 | P1 | Credential/master-key file permissions (`0600`/`0700`) are POSIX-only and silently no-op on Windows with no documented platform requirement | `app/core/credentials/crypto.py:38-41,82-85` |
| 26 | P1 | `store.ts` seeds `activeProject`/initial view from stale `localStorage` before the URL is parsed — briefly violates "URL is source of truth," fires stray scoped fetches | `graphyn-ui/src/store/appStore.ts:186-192,336`; `App.tsx:359-363,487-518` |
| 27 | P1 | Access/RBAC and Device registry/OTA remain acknowledged product gaps (not code defects) blocking full-vision readiness — track as backlog, not assumed-shipped | `graphyn-ui/src/features/access/AccessView.tsx`; `DevicesView.tsx`; `app/api/main.py:271-288` |
| 28 | P1 | 106/156 plugins (68% of node surface) share one aggregate test that silently swallows install failures and spot-checks only 6 node types — masks broken (not just stubbed) plugins | `unit_test/plugins/test_proposed_plugins_registry.py` |
| 29 | P2 | Homegrown AEAD (SHA-256 counter-mode keystream + HMAC) with no key separation between encryption and MAC, instead of a vetted primitive (AES-GCM/Fernet) | `app/core/credentials/crypto.py:90-133` |
| 30 | P2 | Passphrase-style `GRAPHYN_CREDENTIALS_KEY` hashed with unsalted single-pass SHA-256 — no KDF work factor | `app/core/credentials/crypto.py:45-55` |
| 31 | P2 | Legacy named-secret store is plaintext-on-disk while the credential store is encrypted — inconsistent at-rest guarantee for similar data | `app/core/secrets.py:99-126` |
| 32 | P2 | `auth-status` endpoint (intentionally public) leaks `env` and `token_configured` pre-auth — minor recon value | `app/api/routers/system.py:233-248` |
| 33 | P2 | `/files`, `/run-files` static mounts don't explicitly set `follow_symlink=False` (library default likely already safe) | `app/api/main.py:403,405` |
| 34 | P2 | Git-clone redirects resolved entirely inside the `git` binary, no app-level allowlist re-validation per hop (unlike the archive downloader) | `app/core/plugins/installer.py:207-249` |
| 35 | P2 | `--token` CLI flag exposes the bearer token to local process listing (`ps`) | `app/cli/main.py:1706-1709` |
| 36 | P2 | Two direct `PluginManager` bypasses (low-impact today; `plugins/` dir is empty) | `app/api/routers/plugins.py:73`; `app/core/nodes/discovery.py:229-231` |
| 37 | P2 | Distributed blob transfer and `ArtifactStore` are two unreconciled content-addressed stores — divergent GC/retention risk as distributed path matures | `app/core/distributed/transfer.py:49-122` vs `app/core/artifact_store.py` |
| 38 | P2 | MCP and REST auth independently reimplemented with no shared dependency; token transport also differs (header vs. tool-call argument) | `app/mcp/auth.py:32-69`; `app/api/main.py:175-229` |
| 39 | P2 | Dataset upload logic duplicated between MCP and REST with divergent target directories and filename-handling rules | `app/mcp/handlers/data_ops.py:126-165` vs `app/api/routers/data.py:214-232` |
| 40 | P2 | `App.tsx` is a 1272-line shared shell co-locating nav rail, command palette, and auth/token UI — maintainability smell | `graphyn-ui/src/App.tsx` |
| 41 | P2 | Stale import in deprecated shim referencing `run_manager.py` instead of `run_journal` directly (cosmetic, no behavioral effect) | `app/core/ir/yaml_shim.py:205` |
| 42 | P2 | Normative SRS §10.2 still lists "Secrets" in the Admin IA group, contradicting the shipped Credentials-only IA | `docs/REQUIREMENTS_SPEC.md:3300` |
| 43 | P2 | 10 residual "project" vs. "Workspace" terminology leaks, several inconsistent with an adjacent correctly-labeled sibling string | `graphyn-ui/src/components/CommandPalette.tsx:154,396`; `BuilderView.tsx:1410,1420`; `DataView.tsx:1008-1010`; `SystemView.tsx:762,890`; `EdgeWizardView.tsx:889`; `TemplatesView.tsx:1011` |
| 44 | P2 | `CommandPalette.tsx` maintains its own hand-copied nav-label list (`VIEW_JUMPS`), independent of the already-centralized `routes/nav.ts` — repeat of a previously-fixed drift class | `graphyn-ui/src/components/CommandPalette.tsx:20-35` vs `routes/nav.ts:49-54,76-91` |
| 45 | P2 | Deprecated dual-path surfaces remain live and reachable (YAML pipeline input, legacy `PipelineCache.has()`) — labeled and warning, not silent | `app/api/routers/pipelines.py:18,260,343`; `app/core/ir/migrate.py`; `app/core/ir/yaml_shim.py` |
| 46 | P2 | Case-sensitive host/path matching in plugin-source allowlist could diverge from case-insensitive registries | `app/core/config.py:302-332` |
| 47 | P2 | Minor UI copy mismatch: disabled workspace-strip button title text doesn't exactly match the locked spec string | `graphyn-ui/src/App.tsx:811-815` vs `:582` |

---

## 7. What is strong / shippable vs not

**Strong / shippable today:**
- The canonical execution entry point (`get_backend().execute()`) holds with zero bypasses across REST, CLI, and MCP.
- Console IA vs. Web-IDE vision compliance: stable rail, forbidden-pattern guards, hash-route retirement, all genuinely locked and defensively engineered against regression.
- Credential store consolidation (Secrets→Credentials) is complete, test-guarded, and not just documented as complete.
- Distributed queue/registry atomicity (`flock`-based read-modify-write, Redis WATCH/MULTI, lease-generation fencing) is real, not aspirational — the *rejection* half of the zombie-write problem works correctly.
- Inline-secret enforcement, cooperative-cancellation semantics, and heartbeat/lease-reclaim fencing are all verified true and match their documentation exactly.
- Six core UI screens (Editor, Runs, Models, Ship, Datasets, Home) are substantial, real implementations with no placeholder screens or `TODO`/`fake`/`mock` markers.
- SMTP/LLM fail-closed behavior, S99 smoke scripts, and honesty-banner stubs (Devices/OTA, Access/RBAC) are production-grade honest engineering — no fake-success pattern found anywhere it was checked.
- CI (`.github/workflows/ci.yml`) is a real gate — install, smoke test, `pytest -q` under `set -euo pipefail`, plus a UI build/test job — contradicting a stale internal doc claim that no CI exists.
- Type-safety discipline in `graphyn-ui` is better than assumed (zero unsafe casts found).

**Not yet shippable / needs work before the next milestone:**
- The 94–106 undisclosed stub plugins (§6 #5) — either gate them behind a visible Experimental/Proposed badge or loudly flag stub-mode execution at runtime; do this before adding more Proposed packs.
- The four P0 security bugs (§6 #1–4) — all four are straightforward, well-scoped fixes (add the missing `_validate_name` call, fix the scheme check, redact the webhook URL, strip credentials from installer error strings) and should block any external-facing release until closed.
- The Windows/non-POSIX locking gap (§6 #6) — either fix with a cross-platform lock or document Linux/POSIX as a hard deployment requirement.
- The distributed zombie-write reconciliation gap (§6 #7) and `DistributedBackend`'s silent cache/pause-propagation gaps (§6 #10–11) — real correctness gaps for any production distributed deployment.
- Full SSO/RBAC and device registry/OTA — acknowledged, honestly-stubbed non-goals for v1, not defects, but still blocking "full vision" readiness (86% overall per the team's own readiness score).
- Test coverage for the newest 106 plugins and for the entire `graphyn-ui` feature-view layer — both currently near-zero relative to the code's size and risk.
- Documentation inventory drift (§Executive summary #2) — needs a generated, CI-enforced `docs/_gen/COUNTS.md` rather than more hand-written passes, and `AGENTS.md`'s "trust this doc" rule should point at the generated file.

---

*Sources merged: `docs/_gen/_pass1_raw.md`, `docs/_gen/_pass_architecture.md`, `docs/_gen/_pass_security.md`, `docs/_gen/_pass_uia.md`.*
