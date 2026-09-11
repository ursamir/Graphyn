# Getting Started

Graphyn runs typed DAG pipelines (Graph IR) from a console, SDK, CLI, REST API, or MCP.

**This guide owns:** install, first run, and how to operate Graphyn (single machine vs multi-machine).
Deep design: [DISTRIBUTED_EXECUTION.md](./DISTRIBUTED_EXECUTION.md). Docker: [DEPLOYMENT.md](./DEPLOYMENT.md).

**Server-99 / Docker:** after `docker compose up`, prove the IDE loop with
`scripts/docker_ide_loop_smoke.sh` (see [DEPLOYMENT.md](./DEPLOYMENT.md#prove-the-ide-loop-server-99--docker)).
Local uvicorn alone does not close the goal env gap.

## Choose an operating mode

| Mode | When | Backend | Who runs nodes |
|---|---|---|---|
| **A — Single machine** | Dev laptop, one box, all plugins here | `LocalPythonBackend` (default) | This process runs every node |
| **B — Multi machine** | Split light work and GPU/specialized workers | `GRAPHYN_BACKEND=distributed` | Control plane schedules; workers claim by labels/capabilities |

In mode B you can run a **full-capability** worker (all plugins) or **specialized** workers (e.g. `--labels gpu` with only GPU plugins). IR `placement` on each node routes work.

---

## Prerequisites

- Python 3.11+
- Node.js 20+ (console only)
- Mode B: same Graphyn version + needed plugins on every worker host

## Install (once per machine)

```bash
git clone https://github.com/ursamir/Graphyn.git
cd Graphyn
python3 -m venv venv
venv/bin/pip install -U pip
# setup.py is the dependency source of truth; [dev] adds pytest/hypothesis
venv/bin/pip install -e ".[dev]"
# Optional extras: mcp | redis | events | vad | hf | tf | all
# Docker / locked pins: pip install -r requirements.txt && pip install -e . --no-deps
venv/bin/python -c "from pathlib import Path; from app.core.plugins.manager import PluginManager as M; m=M(); [m.install(str(p), upgrade=True) for d in ('Audio','Common') for p in Path('PluginPackage', d).iterdir() if (p / 'plugin.toml').exists()]"
```

Dependency model: see root README / AGENTS.md. Validate sync with `venv/bin/python scripts/check_deps.py`.

---

## Mode A — Single machine (full catalog locally)

Default local backend. Do not set GRAPHYN_BACKEND.


### Start API and console

Ensure `GRAPHYN_SKIP_PLUGIN_LOAD` is **unset** (if set to `1`, `/api/v1/nodes` returns `[]` and the Builder catalog is empty). Optional: `export GRAPHYN_HOME=$PWD/.graphyn-e2e` when using the e2e plugin tree, or rely on `~/.graphyn/plugins/installed/`.

- API: `venv/bin/uvicorn app.api.main:app --reload --port 8001`
- Console: `cd graphyn-ui && npm install && npm run dev`
- API URL: `http://localhost:8001/api/v1/`
- UI URL: `http://localhost:5173`

### Run a graph

- `venv/bin/python -m app.cli.main run --graph examples/templates/basic-wakeword.graph.json`

### SDK

Use `Pipeline` and `PipelineNode` from `app.core.sdk`; call pipeline.run(). See [SDK_AND_CLI.md](./SDK_AND_CLI.md) for full examples.

### MCP

- `venv/bin/python -m app.mcp.server`

Console groups: **Build** (Builder, Templates, Proposals, Runs) · **Observe** (Trace, Experiments, Artifacts) · **Library** (Plugins, Data, Projects) · **Deploy** (Edge, Workers) · **Admin** (Secrets, System).

**Data vs Projects:** Data is files in/out (`workspace/datasets/`). Projects is the dataset workspace over the same output folder (versions/snapshots/lineage). Loop: Upload in Data → Build/ingest in Builder → Runs/Artifacts → manage in Projects → compare in Experiments / package in Edge.

---

## Mode B — Multi machine (control plane + workers)

Use when some nodes need another host (GPU, edge, specialized plugins).

### B1 — Control plane

- Set env GRAPHYN_BACKEND=distributed (optional GRAPHYN_API_TOKEN)
- Start API with host 0.0.0.0 port 8001 (control plane)
- Local / unconstrained nodes run on the control plane; GPU-tagged nodes wait for a worker

### B2 — Worker hosts

Install Graphyn plus plugins that worker should own, then start a worker against the control URL (/api/v1) with worker-id, labels, and optional pool.

Example:

- `venv/bin/python -m app.cli.main worker start --control-url http://<CONTROL_IP>:8001/api/v1 --worker-id gpu-1 --labels gpu,lab --pool gpu-lab`

| Worker style | How |
|---|---|
| **Full-capability** | Install Audio + Common; broad labels; can claim most node types |
| **Specialized** | Install only needed plugins; labels like gpu and pool like gpu-lab; only matching jobs claimed |

Check Deploy → Workers in the console. Demo: examples/29_distributed_placement/pipeline.graph.json with GRAPHYN_BACKEND=distributed.

IR placement (schema 1.2): mode auto|local|worker|pool, plus tags, require_gpu, min_vram_mib, pool, worker. Full contracts: [DISTRIBUTED_EXECUTION.md](./DISTRIBUTED_EXECUTION.md).

### Same-host smoke

Run distributed API locally, then start a worker with control-url http://127.0.0.1:8001/api/v1, worker-id local-gpu, labels gpu, and --once.

Exact flags and env table: [DISTRIBUTED_EXECUTION.md](./DISTRIBUTED_EXECUTION.md) (CLI + runbook sections).

---

## Next reading

| Need | Doc |
|---|---|
| Product direction | [PRODUCT_VISION.md](./PRODUCT_VISION.md) |
| Distributed contracts | [DISTRIBUTED_EXECUTION.md](./DISTRIBUTED_EXECUTION.md) |
| Docker Compose | [DEPLOYMENT.md](./DEPLOYMENT.md) |
| Architecture | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| Nodes | [NODE_CATALOGUE.md](./NODE_CATALOGUE.md) |
| Plugins | [PLUGIN_GUIDE.md](./PLUGIN_GUIDE.md) |
| REST / SDK / CLI / MCP | [API_REFERENCE.md](./API_REFERENCE.md), [SDK_AND_CLI.md](./SDK_AND_CLI.md), [MCP_SERVER.md](./MCP_SERVER.md) |
| Limits | [KNOWN_ISSUES.md](./KNOWN_ISSUES.md) |
