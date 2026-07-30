# Graphyn

General-purpose AI/workflow pipeline engine (`graphyn-sdk`). Build and run typed DAG pipelines via REST API, Python SDK, CLI, or MCP — primarily audio ML, extensible through plugins.

## Quick start

```bash
# API
venv/bin/uvicorn app.api.main:app --reload --port 8001

# UI (Graphyn platform console)
cd graphyn-ui && npm install && npm run dev

# CLI
venv/bin/python -m app.cli.main run --graph examples/templates/basic-wakeword.graph.json

# Tests
venv/bin/pytest unit_test/
```

## Documentation

| Doc | Purpose |
|---|---|
| [docs/README.md](docs/README.md) | Doc index + key concepts |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers, data flows, phase history |
| [AGENTS.md](AGENTS.md) | Agent/contributor orientation |
| [.kiro/steering/](.kiro/steering/) | Area-specific steering for AI agents |

## Layout

- `app/` — platform core (IR, nodes framework, orchestrator, API, CLI, MCP)
- `PluginPackage/` — plugin sources (Audio, Common; WakeWord/Video experimental)
- `graphyn-ui/` — Graphyn platform console (IR-native Builder + ops surfaces)
- `examples/` — end-to-end demos (graphs + scripts; no checked-in datasets)
- `unit_test/` — pytest suite
- `docs/` — product documentation
- `.kiro/steering/` — area-specific agent guidance
- `examples/templates/` — tracked starter `.graph.json` templates
- `workspace/` — runtime data only (gitignored)

Install plugins from source:

```bash
venv/bin/python -c "from pathlib import Path; from app.core.plugins.manager import PluginManager; m=PluginManager();
[m.install(str(p), upgrade=True) for d in ('Audio','Common') for p in Path('PluginPackage',d).iterdir() if (p/'plugin.toml').exists()]"
```

Open defects: [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).
