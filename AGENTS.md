# Graphyn — Agent Guide

General-purpose AI/workflow execution platform (**graphyn-sdk**). Four interfaces share `app/core/`:

| Interface | Entry |
|---|---|
| REST API | `venv/bin/uvicorn app.api.main:app --reload --port 8001` → `/api/v1/` |
| Python SDK | `app/core/sdk.py` |
| CLI | `venv/bin/python -m app.cli.main` |
| MCP | `graphyn mcp` / `python -m app.mcp.server` |
| UI | `graphyn-ui/` — Vite React console (`npm run dev`) |

Canonical docs: `docs/README.md`. Architecture: `docs/ARCHITECTURE.md`. Kiro steering (detailed): `.kiro/steering/`.

## Vision

Build, run, and manage typed DAG pipelines — domain-agnostic via plugins (audio ML is a first-party pack, not the product identity). Graph IR (`.graph.json`) is the single pipeline language. Interfaces execute via `get_backend().execute(graph)`.

## Hard Rules

1. **Python via venv only:** `venv/bin/python`, `venv/bin/pip`, `venv/bin/pytest`, `venv/bin/uvicorn`.
2. **Platform never imports `app/domain/`.** Domain registers into platform registries at startup.
3. **Platform never imports `AudioSample` for storage.** Use `ArtifactSerializerRegistry`.
4. **Execution entry:** `get_backend().execute()` — not direct `orchestrator` calls from interfaces.
5. **`resolve_capability`** from `registry_runtime.py`, never from `orchestrator`.
6. **Plugins live in `PluginPackage/`.** Never edit `plugins/` (install target).
7. **YAML is deprecated.** Prefer `.graph.json`; migrate with `graphyn migrate`.
8. **After code changes:** update matching `.kiro/steering/` file and matching `docs/` file (see update protocol rule).
9. **`app/` modules:** keep the 7-field architectural contract docstring (see file-header rule).

## Layout

```
app/api/          FastAPI routers
app/cli/          argparse CLI
app/mcp/          MCP stdio server (15 tools)
app/core/         IR, nodes framework, orchestrator, plugins, artifacts
app/domain/       Ingestion, ProjectManager, QualityChecker
app/models/       PortDataType implementations
PluginPackage/    Source plugins (Audio + Common; WakeWord/Video are experimental/non-manifest)
plugins/          Optional local override via GRAPHYN_PLUGINS_DIR (default install: ~/.graphyn/plugins/installed/)
graphyn-ui/       React + Vite platform console (IR-native Builder + Runs/Artifacts/Plugins/…)
unit_test/        Pytest suite
examples/         End-to-end demos
docs/             Human docs (source of truth alongside code)
.kiro/steering/   Detailed agent steering by area
```

## Bounded Contexts (BC)

| BC | Name | Location |
|---|---|---|
| BC1 | Graph Language | `app/core/ir/` |
| BC2 | Node Contract | `app/core/nodes/{base,ports,config,retry,metadata}.py` |
| BC3 | Node Catalog | `registry`, `discovery`, `app/core/plugins/` |
| BC4 | Execution Planner | `planner.py` |
| BC5 | Execution Runtime | `orchestrator`, `node_executor`, `executor`, `conditions`, `events` |
| BC6 | Observability & Storage | `checkpoint`, `artifact_*`, `run_*`, `provenance`, `pipeline_cache`, `logger` |

## Quick Commands

```bash
venv/bin/uvicorn app.api.main:app --reload --port 8001
cd graphyn-ui && npm run dev
venv/bin/python -m app.cli.main run --graph <file.graph.json>
venv/bin/pytest unit_test/
GRAPHYN_SKIP_PLUGIN_LOAD=1 venv/bin/pytest unit_test/   # faster / isolated
```
