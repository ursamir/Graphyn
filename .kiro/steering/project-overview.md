---
inclusion: always
---

# Pipeline Engine — Master Index

General-purpose AI/workflow execution platform. Four interfaces share `app/core/`:

| Interface | Entry Point |
|---|---|
| REST API | `app/api/main.py` → `http://localhost:8001/api/v1/` |
| Python SDK | `app/core/sdk.py` |
| CLI | `app/cli/main.py` |
| MCP Server | `app/mcp/server.py` (stdio transport) |

## Key Concepts

- **Node** — processing unit with typed ports + Pydantic `Config` + `process()`. Extends `app.core.nodes.base.Node`.
- **Pipeline** — DAG of nodes. Canonical format: IR JSON (`.graph.json`). YAML is deprecated.
- **Graph IR** — versioned, validated JSON schema (`app/core/ir/`). All interfaces produce/consume `GraphIR`.
- **Registry** — singleton `NodeRegistry` populated at startup by `AutoDiscovery`. Maps `node_type` string → class.
- **PortDataType** — base class for all inter-port data types (`AudioSample`, `FeatureArray`, etc.).
- **Plugin** — self-contained node package. All 29 nodes live in `PluginPackage/`. All phases complete.

## File Map

| Need | File |
|---|---|
| Node base, lifecycle, ports | `app/core/nodes/base.py`, `ports.py`, `config.py`, `retry.py`, `metadata.py` |
| Plugin nodes — Audio (18) | `PluginPackage/Audio/` |
| Plugin nodes — Common (11) | `PluginPackage/Common/` |
| Plugin docs | `PluginPackage/ARCHITECTURE.md`, `PluginPackage/NODES.md` |
| Registry + AutoDiscovery | `app/core/nodes/registry.py`, `discovery.py` |
| DAG orchestrator | `app/core/orchestrator.py` |
| DAG planner + wave builder | `app/core/planner.py` |
| Node executor (single node) | `app/core/node_executor.py` |
| Checkpoint read/write | `app/core/checkpoint.py` |
| Parallel wave executor | `app/core/executor.py` |
| Graph IR | `app/core/ir/` (`models.py`, `loader.py`, `yaml_shim.py`, `migrate.py`) |
| Condition evaluator | `app/core/conditions.py` |
| Event sources | `app/core/events.py` |
| Caching | `app/core/pipeline_cache.py` |
| Run persistence | `app/core/run_journal.py` |
| Active run registry | `app/core/run_control.py` |
| Re-export shim (legacy) | `app/core/run_manager.py`, `app/core/pipeline.py` |
| Structured logging | `app/core/logger.py` |
| Artifact store | `app/core/artifact_store.py` |
| Provenance store | `app/core/provenance.py` |
| Runtime backend ABC | `app/core/runtime_backend.py` |
| SDK | `app/core/sdk.py` |
| Domain services | `app/domain/ingestion.py`, `project_manager.py`, `quality_checker.py` |
| Data models | `app/models/` |
| API factory | `app/api/main.py` |
| API routers | `app/api/routers/` |
| CLI | `app/cli/main.py` |
| MCP server | `app/mcp/server.py`, `auth.py`, `tool_registry.py`, `handlers/` |
| Plugin install target | `plugins/` (managed by PluginManager — do not edit directly) |
| Plugin ecosystem | `app/core/plugins/` |
| Tests | `unit_test/` |

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `GRAPHYN_API_TOKEN` | `""` | Bearer token (unset = no auth) |
| `GRAPHYN_HOME` | `~/.graphyn/` | Platform home: plugins, shared cache, credentials |
| `GRAPHYN_PROJECT_DIR` | `"workspace"` | Runtime data root — must be set before importing `app.api.main` or `app.cli.main` |
| `GRAPHYN_PLUGINS_DIR` | `"plugins"` | Plugin install directory |
| `GRAPHYN_PLUGIN_AUTO_INSTALL` | `""` | `"1"` or `"true"` to auto-install missing plugin deps via pip |
| `GRAPHYN_PLUGIN_INDEX_URL` | `""` | Remote plugin index URL |

## Run Commands

```bash
venv/bin/uvicorn app.api.main:app --reload --port 8001   # API
venv/bin/python -m app.cli.main run --graph <json>        # CLI
graphyn mcp                                                # MCP server
venv/bin/pytest unit_test/                                 # Tests
```

## Steering File Index

| File | Loads when editing | Topic |
|---|---|---|
| `node-base.md` | `base.py`, `ports.py`, `config.py`, `retry.py`, `metadata.py` | Node base, ports, lifecycle, capability fields |
| `node-registry.md` | `registry.py`, `discovery.py`, `catalogue.py`, `compat.py`, `errors.py` | Registry, AutoDiscovery, TypeCatalogue |
| `plugin-development.md` | `plugins/**`, `app/core/plugins/**`, `PluginPackage/**` | Plugin authoring, install, registered plugins table |
| `plugin-ecosystem.md` | `app/core/plugins/**` | PluginManager internals, error hierarchy, load sequence |
| `pipeline-execution.md` | `orchestrator.py`, `planner.py`, `node_executor.py`, `checkpoint.py`, `executor.py`, `pipeline_cache.py`, `ir/` | DAG executor, IR, caching, runtime modes |
| `api-structure.md` | `app/api/main.py` | Factory, auth, CORS, routers |
| `api-endpoints.md` | `app/api/routers/**` | All endpoints, streaming protocol |
| `sdk-cli.md` | `sdk.py`, `app/cli/**` | SDK and CLI usage |
| `backend-services.md` | `run_journal.py`, `run_control.py`, `logger.py`, `artifact_store.py`, `domain/**` | Run persistence, active run registry, logger, artifacts |
| `mcp-server.md` | `app/mcp/**` | MCP server, tools, auth |
| `data-models.md` | `app/models/**` | Data types, metadata conventions, workspace layout |
| `python-venv.md` | `**/*.py`, `requirements.txt`, `setup.py`, `pyproject.toml` | Always use `venv/bin/python` |
| `context7.md` | (always) | Fetch library docs before implementing with any dependency |
| `update-protocol.md` | (always) | Which steering file and docs file to update after each change |
