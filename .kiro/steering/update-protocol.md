---
inclusion: always
---

# Update Protocol

When you modify code, update the matching steering file AND the matching `docs/` file before finishing. Update only the specific row, section, or example that changed — never rewrite entire files.

## Steering File → Code

| Steering File | Update when modifying |
|---|---|
| `project-overview.md` | New top-level dirs, interfaces, env vars, entry points |
| `node-base.md` | `base.py`, `ports.py`, `config.py`, `retry.py`, `metadata.py` |
| `node-registry.md` | `registry.py`, `discovery.py`, `catalogue.py`, `compat.py`, `errors.py` |
| `plugin-development.md` | `plugins/`, `app/core/plugins/**`, `PluginPackage/**` |
| `plugin-ecosystem.md` | `app/core/plugins/**` |
| `pipeline-execution.md` | `orchestrator.py`, `planner.py`, `node_executor.py`, `checkpoint.py`, `executor.py`, `pipeline_cache.py`, `ir/` |
| `api-structure.md` | `app/api/main.py` |
| `api-endpoints.md` | `app/api/routers/**` |
| `sdk-cli.md` | `sdk.py`, `app/cli/main.py` |
| `backend-services.md` | `run_journal.py`, `run_control.py`, `logger.py`, `artifact_store.py`, `domain/**` |
| `mcp-server.md` | `app/mcp/**` |
| `data-models.md` | `app/models/**` |
| `frontend-canvas.md` | `flow/`, `store/`, `utils/`, `App.tsx`, `main.tsx` |
| `frontend-features.md` | `features/`, `hooks/`, `components/` |

## Docs File → Code

| Doc | Update when |
|---|---|
| `docs/USERGUIDE.md` | New CLI command, SDK method, runtime mode, config option |
| `docs/API_REFERENCE.md` | New/changed REST endpoint, request/response field, streaming event |
| `docs/NODE_SYSTEM.md` | New node base feature, capability field, registry/discovery change |
| `docs/PIPELINE_EXECUTION.md` | New execution mode, IR schema change, executor feature |
| `docs/BACKEND_CORE.md` | New `RunManager` method, logger event, ingestion change |
| `docs/MCP_SERVER.md` | New MCP tool, changed tool behavior, new error type |
| `docs/SDK_AND_CLI.md` | New SDK method, CLI command or flag |
| `docs/DATA_FLOW_AND_WORKSPACE.md` | New data type, workspace layout change |
| `docs/PLUGIN_GUIDE.md` | Plugin API change, new plugin in `PluginPackage/` |
| `docs/ARCHITECTURE.md` | New interface, major structural change |
| `docs/KNOWN_ISSUES.md` | Fix → remove from open tables. New issue → add to correct priority tier. |
| `docs/MASTER_ISSUE_REGISTRY.md` | Any new issue found or any issue resolved — update status and move to Resolved table. |

## Action Checklists

**Fix an open issue:**
1. Fix the code
2. Move the issue row to the Resolved table in `docs/MASTER_ISSUE_REGISTRY.md`
3. Remove it from the matching priority tier in `docs/KNOWN_ISSUES.md`

**New plugin node:**
1. Implement in `PluginPackage/Audio/` or `PluginPackage/Common/`
2. Add row → `plugin-development.md` Registered Plugins table
3. Update capability matrix → `PluginPackage/NODES.md`
4. Update → `docs/PLUGIN_GUIDE.md`

**New API endpoint:** update `api-endpoints.md` → `docs/API_REFERENCE.md`

**New CLI command or SDK method:** update `sdk-cli.md` → `docs/USERGUIDE.md` + `docs/SDK_AND_CLI.md`

**New MCP tool:** update `mcp-server.md` → `docs/MCP_SERVER.md` + `docs/USERGUIDE.md`

**New env var:** add row to `project-overview.md` Environment Variables table

**New issue found during work:** add to `docs/MASTER_ISSUE_REGISTRY.md` in the correct priority section and add a row to the Quick Reference table. Add to `docs/KNOWN_ISSUES.md` in the correct tier.
