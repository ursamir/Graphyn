# Graphyn

**Typed DAG workflows for AI, ML, and automation.**

Design pipelines as Graph IR, run them locally or on distributed workers, and keep full accountability across console, SDK, CLI, REST, and MCP.

## Why Graphyn

| Pillar | You get |
|---|---|
| Workflow | IR-native Builder, templates, plugins as nodes |
| ML lifecycle | Runs, metrics, artifacts, experiment compare |
| Orchestration | Typed DAG waves, cache, resume, distributed placement |
| Edge | Train, optimize, package wizard |
| Agentic | MCP tools + human-approved graph proposals |
| Accountability | Trace any artifact back to run, graph, and worker |

North star: [docs/PRODUCT_VISION.md](docs/PRODUCT_VISION.md).

## Quick start

See [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) for install, API, console, SDK, CLI, and MCP.

## Interfaces

| Surface | Entry |
|---|---|
| REST | http://localhost:8001/api/v1/ |
| Console | graphyn-ui/ (Vite, port 5173) |
| SDK | app.core.sdk Pipeline / PipelineNode |
| CLI | python -m app.cli.main |
| MCP | graphyn mcp (23 tools) |

## Documentation

| Doc | |
|---|---|
| [Getting started](docs/GETTING_STARTED.md) | Install and first pipeline |
| [Architecture](docs/ARCHITECTURE.md) | System design |
| [Distributed execution](docs/DISTRIBUTED_EXECUTION.md) | Workers and placement |
| [API reference](docs/API_REFERENCE.md) | REST |
| [Plugin guide](docs/PLUGIN_GUIDE.md) | Extend with nodes |
| [Doc index](docs/README.md) | Full map |

## Development

Run unit_test/ with venv pytest. Contributor guide: [AGENTS.md](AGENTS.md). Limitations: [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).
