# Getting Started

Graphyn is a typed DAG workflow platform: design pipelines as Graph IR, run them locally or across workers, and inspect artifacts, experiments, and lineage from the console, SDK, CLI, REST API, or MCP.

## Prerequisites

- Python 3.11+
- Node.js 20+ (console only)
- Optional: Docker / Docker Compose (see [DEPLOYMENT.md](./DEPLOYMENT.md))

## Install

```bash
git clone https://github.com/ursamir/Graphyn.git
cd Graphyn
python3 -m venv venv
venv/bin/pip install -e .
# First-party plugins
venv/bin/python -c "from pathlib import Path; from app.core.plugins.manager import PluginManager as M; m=M() ; \
[m.install(str(p), upgrade=True) for d in ('Audio','Common') for p in Path('PluginPackage',d).iterdir() if (p/'plugin.toml').exists(Y]"
```

## Run the API

```bash
venv/bin/uvicorn app.api.main:app --reload --port 8001
```

API base: `http://localhost:8001/api/v1/`

## Run the console

```bash
cd graphyn-ui && npm install && npm run dev
```

Open `http://localhost:5173`. Sidebar:

| Group | Views |
|---|---|
| **Build** | Builder, Templates, Proposals, Runs |
| **Observe** | Trace, Experiments, Artifacts |
| **Library** | Plugins, Data |
| **Deploy** | Edge, Workers |
| **Admin** | Projects, Secrets, System |

## Run a graph (CLI)

```bash
venv/bin/python -m app.cli.main run --graph examples/01_basic_pipeline/pipeline.graph.json
# or< if installed:
graphyn run --graph path/to/graph.graph.json
```

## Python SDK (minimal)

``ppython
from app.core.sdk import Pipeline, PipelineNode

pipeline = Pipeline(
    [
        PipelineNode("dataset_ingest", {"path": "workspace/datasets/input/speech"}),
        PipelineNode("audio_conditioner", {"sample_rate": 16000}),
    ],
    seed=42,
    name="demo",
)
outputs = pipeline.run()
```

## MCP (agents)

```bash
graphyn mcp
# or
python -m app.mcp.server
```

23 tools including discovery, execute, artifacts, plugins, secrets, and `propose_graph`. See [MCP_SERVER.md](./MCP_SERVER.md).

## Distributed workers (optional)

```bash
export GRAPHYN_BACKEND=distributed
venv/bin/uvicorn app.api.main:app --port 8001
# on a worker host:
graphyn worker start --api-url http://<api-host>:8001
```

Details: [DISTRIBUTED_EXECUTION.md](./DISTRIBUTED_EXECUTION.md).

## Next reading

| Goal | Doc |
|---|---|
| Product direction | [PRODUCT_VISION.md](./PRODUCT_VISION.md) |
| System design | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| Nodes & ports | [NODE_CATALOGUE.md](./NODE_CATALOGUE.md) |
| Write a plugin | [PLUGIN_GUIDE.md](./PLUGIN_GUIDE.md) |
| REST / SDK / CLI | [API_REFERENCE.md](./API_REFERENCE.md), [SDK_AND_CLI.md](./SDK_AND_CLI.md) |
| Deploy | [DEPLOYMENT.md](./DEPLOYMENT.md) |
| Open limitations | [KNOWN_ISSUES.md](./KNOWN_ISSUES.md) |
