---
inclusion: always
---

# Pipeline Engine — Master Index

General-purpose AI/workflow execution platform. Four interfaces share `app/core/` (Visual UI deprecated):

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
| DAG executor | `app/core/pipeline.py` |
| Graph IR | `app/core/ir/` (`models.py`, `loader.py`, `yaml_shim.py`, `migrate.py`) |
| Condition evaluator | `app/core/conditions.py` |
| Event sources | `app/core/events.py` |
| Parallel executor | `app/core/executor.py` |
| Caching | `app/core/pipeline_cache.py` |
| Run lifecycle | `app/core/run_manager.py` |
| Structured logging | `app/core/logger.py` |
| SDK | `app/core/sdk.py` |
| Ingestion | `app/core/ingestion.py` |
| Project lifecycle | `app/core/project_manager.py` |
| Data models | `app/models/` |
| API factory | `app/api/main.py` |
| API routers | `app/api/routers/` |
| CLI | `app/cli/main.py` |
| MCP server | `app/mcp/server.py`, `auth.py`, `tool_registry.py`, `handlers/` |
| Plugin install target | `plugins/` (managed by PluginManager — do not edit directly) |
| Plugin ecosystem | `app/core/plugins/` |

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `GRAPHYN_API_TOKEN` | `""` | Bearer token (unset = no auth) |
| `GRAPHYN_HOME` | `~/.graphyn/` | Platform home: plugins, shared cache, credentials |
| `GRAPHYN_PROJECT_DIR` | `"workspace"` | Runtime data root |
| `GRAPHYN_PLUGINS_DIR` | `"plugins"` | Plugin install directory |
| `GRAPHYN_PLUGIN_AUTO_INSTALL` | `""` | `"1"` or `"true"` to auto-install missing plugin deps via pip |
| `GRAPHYN_PLUGIN_INDEX_URL` | `""` | Remote plugin index URL |

## Run Commands

```bash
venv/bin/uvicorn app.api.main:app --reload --port 8001   # API
venv/bin/python -m app.cli.main run --graph <json>        # CLI
graphyn mcp                                                # MCP server
venv/bin/pytest                                            # Tests
```

## Steering File Index

| File | Loads when editing | Topic |
|---|---|---|
| `node-base.md` | `base.py`, `ports.py`, `config.py`, `retry.py`, `metadata.py` | Node base, ports, lifecycle, capability fields |
| `node-registry.md` | `registry.py`, `discovery.py`, `catalogue.py`, `compat.py`, `errors.py` | Registry, AutoDiscovery, TypeCatalogue |
| `plugin-development.md` | `plugins/**`, `app/core/plugins/**`, `PluginPackage/**` | Plugin authoring, install, registered plugins table |
| `plugin-ecosystem.md` | `app/core/plugins/**` | PluginManager internals, error hierarchy, load sequence |
| `pipeline-execution.md` | `pipeline.py`, `validation.py`, `pipeline_cache.py`, `ir/` | DAG executor, IR, caching, runtime modes |
| `api-structure.md` | `app/api/main.py` | Factory, auth, CORS, routers |
| `api-endpoints.md` | `app/api/routers/**` | All endpoints, streaming protocol |
| `sdk-cli.md` | `sdk.py`, `app/cli/**` | SDK and CLI usage |
| `backend-services.md` | `run_manager.py`, `logger.py`, `ingestion.py`, `project_manager.py` | RunManager, Logger, Ingestion |
| `mcp-server.md` | `app/mcp/**` | MCP server, tools, auth |
| `data-models.md` | `app/models/**` | Data types, metadata conventions, workspace layout |
| `python-venv.md` | `**/*.py`, `requirements.txt`, `setup.py`, `pyproject.toml` | Always use `venv/bin/python` |
| `context7.md` | (always) | Fetch library docs before implementing with any dependency |
| `update-protocol.md` | (always) | Which steering file and docs file to update after each change |
