# Graphyn

**Typed DAG workflows for AI, ML, and automation.**

Design pipelines as Graph IR, run them on one machine or across workers, and keep accountability via console, SDK, CLI, REST, and MCP.

## Operating modes

| Mode | Backend | Idea |
|---|---|---|
| **A — Single machine** | Default local backend | One host runs the API and every node (full plugin catalog locally) |
| **B — Multi machine** | Distributed backend | Control plane schedules; workers claim jobs by labels / pools / GPU / installed plugins |

Mode B supports a **full-capability** worker (all plugins) or **specialized** workers (subset of plugins + capability labels).

How to run both modes: **[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)**.
Contracts: [docs/DISTRIBUTED_EXECUTION.md](docs/DISTRIBUTED_EXECUTION.md).

## Why Graphyn

| Pillar | You get |
|---|---|
| Workflow | IR-native Builder, templates, plugins as nodes |
| ML lifecycle | Runs, metrics, artifacts, experiment compare |
| Orchestration | Typed DAG waves, cache, resume, distributed placement |
| Edge | Train, optimize, package wizard |
| Agentic | MCP tools + human-approved graph proposals |
| Accountability | Trace any artifact back to run, graph, and worker |

Vision: [docs/PRODUCT_VISION.md](docs/PRODUCT_VISION.md).

## Quick start

Follow **[Getting Started](docs/GETTING_STARTED.md)** — install once, then Mode A (single machine) or Mode B (control plane + workers).

## Interfaces

| Surface | Entry |
|---|---|
| REST | API host, path /api/v1/ (default port 8001) |
| Console | graphyn-ui (default port 5173) |
| SDK | app.core.sdk Pipeline / PipelineNode |
| CLI | app.cli.main |
| MCP | app.mcp.server (23 tools) |

## Documentation

| Doc | Purpose |
|---|---|
| [Getting started](docs/GETTING_STARTED.md) | Install and Mode A / Mode B operations |
| [Distributed execution](docs/DISTRIBUTED_EXECUTION.md) | Placement, workers, jobs, env |
| [Architecture](docs/ARCHITECTURE.md) | System design |
| [API reference](docs/API_REFERENCE.md) | REST |
| [Plugin guide](docs/PLUGIN_GUIDE.md) | Author nodes |
| [Doc index](docs/README.md) | Full map |

## Development

Contributor / agent guide: [AGENTS.md](AGENTS.md). Limitations: [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).
