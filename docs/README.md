# Graphyn documentation

Typed DAG workflows for AI/ML and general automation. Graph IR is the shared language across console, SDK, CLI, REST, and MCP.

Start here: **[Getting Started](./GETTING_STARTED.md)** (Mode A single-machine vs Mode B distributed).

## Guides

| Document | Audience |
|---|---|
| [GETTING_STARTED.md](./GETTING_STARTED.md) | Install + Mode A/B operations (single vs multi-machine) |
| [PRODUCT_VISION.md](./PRODUCT_VISION.md) | Product north star and console IA |
| [UI_NORTH_STAR.md](./UI_NORTH_STAR.md) | Product UI plan — path routes, Phase 0 foundation, pillar checklist |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Docker Compose and production baseline |
| [PLUGIN_GUIDE.md](./PLUGIN_GUIDE.md) | Author and ship plugins |
| [DISTRIBUTED_EXECUTION.md](./DISTRIBUTED_EXECUTION.md) | Worker protocol, placement IR, env, runbook |

## Reference

| Document | Covers |
|---|---|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Layers, data flows, IR versions, security |
| [PIPELINE_EXECUTION.md](./PIPELINE_EXECUTION.md) | Graph IR, waves, cache, checkpoints, modes |
| [NODE_CATALOGUE.md](./NODE_CATALOGUE.md) | Built-in plugin nodes (ports and config) |
| [API_REFERENCE.md](./API_REFERENCE.md) | REST /api/v1/ |
| [SDK_AND_CLI.md](./SDK_AND_CLI.md) | Python SDK and CLI |
| [MCP_SERVER.md](./MCP_SERVER.md) | MCP tools (29) and auth |
| [DATA_FLOW_AND_WORKSPACE.md](./DATA_FLOW_AND_WORKSPACE.md) | Port types, workspace layout, artifacts |
| [KNOWN_ISSUES.md](./KNOWN_ISSUES.md) | Current limitations |
| [UI_NORTH_STAR.md](./UI_NORTH_STAR.md) | Path routes + production foundation + journeys J1–J6 + Phase 0–D |
| [UI_UX_REVIEW.md](./UI_UX_REVIEW.md) | 2026-09-15 console UX / IA justification review |
| [PROJECT_REVIEW.md](../PROJECT_REVIEW.md) | 2026-09-15 deep review — prioritized fix pack for agents/devs |
| [TRUST_MODEL.md](./TRUST_MODEL.md) | Auth modes, resource authorization matrix, secrets, python_code + HTTP egress |

## Concepts

- **Graph IR** — versioned JSON DAG (current schema_version: 1.2). Optional placement for workers.
- **RuntimeBackend** — call get_backend().execute(graph). Default LocalPythonBackend; GRAPHYN_BACKEND=distributed for workers.
- **Plugins** — nodes ship as plugin.toml packages under PluginPackage/.
- **Console** — IR-native UI: Build / Observe / Library / Deploy / Admin.

Contributor orientation: [AGENTS.md](../AGENTS.md). Area steering: [.kiro/steering/](../.kiro/steering/).
