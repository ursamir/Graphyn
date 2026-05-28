# User Guide — Pipeline Engine

A general-purpose AI/workflow execution platform. Build, run, and manage processing pipelines through the Python SDK, CLI, REST API, or MCP (for AI agents). No frontend required.

---

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [Core Concepts](#2-core-concepts)
3. [Python SDK](#3-python-sdk)
4. [CLI Reference](#4-cli-reference)
5. [REST API](#5-rest-api)
6. [MCP — AI Agent Interface](#6-mcp--ai-agent-interface)
7. [Writing Nodes](#7-writing-nodes)
8. [Writing Plugins](#8-writing-plugins)
9. [Plugin Management](#9-plugin-management)
10. [Advanced Runtime Modes](#10-advanced-runtime-modes)
11. [Workspace & Artifacts](#11-workspace--artifacts)
12. [Configuration & Environment](#12-configuration--environment)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Quick Start

### Prerequisites

- Python 3.10+
- Virtual environment at `venv/`

### Start the API server

```bash
venv/bin/uvicorn app.api.main:app --reload --port 8001
```

All endpoints: `http://localhost:8001/api/v1/`

### Run a pipeline from the CLI

```bash
# From IR JSON (canonical)
venv/bin/python -m app.cli.main run --graph my-pipeline.graph.json

# From YAML (deprecated — use migrate to convert)
venv/bin/python -m app.cli.main run --config my-pipeline.yaml
```

### Run a pipeline from Python

```python
from app.core.sdk import PipelineNode, Pipeline

pipeline = Pipeline([
    PipelineNode("dataset_ingest",    {"path": "workspace/datasets/input/speech"}),
    PipelineNode("audio_conditioner", {"sample_rate": 16000}),
    PipelineNode("segmenter",         {"mode": "vad"}),
    PipelineNode("feature_frontend",  {"feature_type": "mfcc"}),
    PipelineNode("dataset_builder",   {"split_ratios": {"train": 0.8, "val": 0.1, "test": 0.1}}),
], seed=42)
pipeline.run()
```

### Start the MCP server (for AI agents)

```bash
graphyn mcp
# or
python -m app.mcp.server
```

---

## 2. Core Concepts

### Node

A self-contained processing unit. Each node has:
- **Typed input/output ports** — data flows between nodes through typed ports
- **Pydantic config** — validated at construction time
- **Lifecycle hooks** — `setup()`, `process()`, `teardown()`
- **Capability metadata** — machine-readable hardware/execution requirements

### Pipeline

A directed acyclic graph (DAG) of nodes. Defined via:
- **Python SDK** — `Pipeline([PipelineNode(...), ...])`
- **IR JSON** — canonical `.graph.json` format
- **YAML** — deprecated; use `graphyn migrate` to convert

### Graph IR

The canonical pipeline representation. Versioned, validated, runtime-agnostic JSON. All interfaces produce and consume `GraphIR` objects. Current version: `"1.1"`.

### Registry

A singleton `NodeRegistry` populated at startup by `AutoDiscovery`. Scans `app/models/` and `plugins/` (or `GRAPHYN_PLUGINS_DIR`) automatically. All 29 production nodes are loaded from `PluginPackage/` via the plugin system.

### Workspace

Runtime data root at `workspace/` (configurable via `GRAPHYN_PROJECT_DIR`). Contains datasets, run artifacts, cache, and project data.

---

## 3. Python SDK

### Building a Pipeline

```python
from app.core.sdk import PipelineNode, Pipeline

# Create nodes — config is validated immediately
node = PipelineNode("audio_conditioner", {"sample_rate": 16000})

# Build pipeline — nodes are auto-chained output→input
pipeline = Pipeline(
    nodes=[...],
    seed=42,           # for reproducibility
    name="my-pipeline",
    description="Optional description",
)
```

### Running a Pipeline

```python
# Basic run
outputs = pipeline.run()

# With options
outputs = pipeline.run(
    use_cache=True,      # cache node outputs (default True)
    checkpoint=True,     # write per-node checkpoints for resumability
    streaming=False,     # use streaming execution for streaming nodes
)

# Get run ID and control the run
outputs, run = pipeline.run_with_manager()
print(f"Run ID: {run.run_id}")
```

### Serialization

```python
# Save to IR JSON (canonical)
pipeline.to_json("my-pipeline.graph.json")

# Load from IR JSON
pipeline = Pipeline.from_json("my-pipeline.graph.json")

# Load from YAML (deprecated)
pipeline = Pipeline.from_yaml("my-pipeline.yaml")

# Get the backing GraphIR object
graph = pipeline.to_ir()
```

### Discovering Nodes

```python
from app.core.registry_runtime import get_registry

registry = get_registry()

# List all nodes
for meta in registry.list_nodes():
    print(meta.node_type, meta.category, meta.description)

# Filter by category
audio_nodes = registry.list_nodes(category="audio")

# Get node config schema
schema = registry.get_config_schema("audio_conditioner")

# Get node metadata
meta = registry.get_metadata("audio_conditioner")
print(meta.requires_gpu, meta.supports_edge, meta.batch_support)
```

### Working with the Graph IR Directly

```python
from app.core.ir import GraphIR, IRNode, IREdge, IRMetadata, load_ir, dump_ir
from app.core.ir import CURRENT_IR_VERSION

# Build a graph manually
graph = GraphIR(
    schema_version=CURRENT_IR_VERSION,
    metadata=IRMetadata(name="my-graph", seed=42),
    nodes=[
        IRNode(id="ingest_0", node_type="dataset_ingest", config={"path": "data/"}),
        IRNode(id="cond_0",   node_type="audio_conditioner", config={"sample_rate": 16000}),
    ],
    edges=[
        IREdge(src_id="input_0", src_port="output", dst_id="clean_0", dst_port="input"),
    ],
)

# Serialize / deserialize
data = dump_ir(graph)          # → dict
graph = load_ir(data)          # → GraphIR (validates)
```

---

## 4. CLI Reference

### `graphyn run`

Execute a pipeline.

```bash
graphyn run --graph PATH [OPTIONS]
graphyn run --config PATH [OPTIONS]   # YAML (deprecated)

Options:
  --seed N              Override pipeline seed
  --parallel            Enable parallel wave execution
  --resume RUN_ID       Resume from a prior run's checkpoints
  --include-nodes ID,.. Execute only these nodes (comma-separated)
  --exclude-nodes ID,.. Skip these nodes (comma-separated)
  --event-driven        Run in event-driven mode
```

### `graphyn validate`

Validate a pipeline without running it.

```bash
graphyn validate --graph PATH    # validate IR JSON
graphyn validate --config PATH   # validate YAML
```

### `graphyn inspect`

Print a human-readable summary of an IR JSON graph.

```bash
graphyn inspect --graph PATH
```

Output: graph metadata, node list, edge list, capability summary.

### `graphyn nodes`

List registered node types.

```bash
graphyn nodes                              # all nodes
graphyn nodes --category audio             # filter by category
graphyn nodes --capability requires_gpu=false supports_edge=true
```

### `graphyn migrate`

Convert a YAML pipeline config to IR JSON.

```bash
graphyn migrate --config pipeline.yaml [--output pipeline.graph.json]
```

### `graphyn runs`

Manage run history.

```bash
graphyn runs list              # table of recent runs
graphyn runs logs RUN_ID       # log entries for a run
```

### `graphyn plugin`

Manage plugins from the command line (Phase 5).

```bash
graphyn plugin install SOURCE [--upgrade]   # install a plugin
graphyn plugin list [--enabled]             # list installed plugins
graphyn plugin enable NAME                  # enable a plugin
graphyn plugin disable NAME                 # disable a plugin
graphyn plugin remove NAME                  # uninstall a plugin
graphyn plugin search QUERY                 # search plugin index
graphyn plugin info NAME                    # show plugin details (JSON)
```

### `graphyn mcp`

Start the MCP server (stdio transport).

```bash
graphyn mcp
GRAPHYN_API_TOKEN=secret graphyn mcp   # with auth
```

---

## 5. REST API

Base URL: `http://localhost:8001/api/v1/`

Auth: optional `Authorization: Bearer <token>` (set `GRAPHYN_API_TOKEN`).

### Node Discovery

```
GET  /api/v1/nodes                          List all nodes
GET  /api/v1/nodes/{node_type}              Node metadata + capability
GET  /api/v1/nodes/{node_type}/config-schema  JSON Schema for config
POST /api/v1/nodes/{node_type}/validate-config  Validate a config dict
GET  /api/v1/types                          All registered port data type FQNs
GET  /api/v1/nodes/compatible?output_type=<fqn>&direction=input|output
```

### Pipeline Execution

```
POST /api/v1/pipelines/validate   Validate IR JSON or YAML
POST /api/v1/pipelines/run        Execute → NDJSON stream
POST /api/v1/pipelines/run-async  Execute async → {"run_id": "..."}
```

**Request body (IR JSON):**
```json
{"schema_version": "1.1", "metadata": {"name": "...", "seed": 42},
 "nodes": [...], "edges": [...]}
```

**NDJSON stream events:**
```jsonc
{"type": "pipeline_start", "total_nodes": 5, "timestamp": "..."}
{"type": "node_start",  "node_type": "CleanNode", "node_index": 0, "timestamp": "..."}
{"type": "node_end",    "node_type": "CleanNode", "node_index": 0, "duration": 0.12, "timestamp": "..."}
{"type": "node_error",  "node_type": "...", "error_message": "...", "error_type": "...", "timestamp": "..."}
{"type": "done",        "run_id": "...", "duration_s": 1.23, "timestamp": "..."}
{"type": "error",       "message": "...", "timestamp": "..."}
```

### Run Management

```
GET  /api/v1/runs                           All runs, newest first
GET  /api/v1/runs/{run_id}/status           {"status": "running|completed|failed"}
GET  /api/v1/runs/{run_id}/checkpoints      List checkpoint node IDs
POST /api/v1/runs/{run_id}/pause            Pause after current node
POST /api/v1/runs/{run_id}/resume           Resume from pause
POST /api/v1/runs/{run_id}/cancel           Cancel after current node
```

### Data Management

```
GET  /api/v1/data/inputs                    Input labels + file counts
POST /api/v1/data/inputs/upload             Upload audio file (multipart)
GET  /api/v1/data/outputs                   Output projects + versions
POST /api/v1/data/merge                     Merge dataset versions
POST /api/v1/ingest/url                     Ingest from URLs
POST /api/v1/ingest/huggingface             Ingest from HuggingFace Hub
```

### System

```
GET  /api/v1/system/health                  {"status": "ok"}
POST /api/v1/system/cleanup                 Delete all runs + cache ⚠️
```

---

## 6. MCP — AI Agent Interface

The MCP server exposes 11 tools via the Model Context Protocol (stdio transport). AI agents can discover nodes, generate graphs, validate, execute pipelines, and inspect artifacts without any frontend.

### Start

```bash
graphyn mcp
```

### Available Tools

| Tool | What it does |
|---|---|
| `list_nodes` | Discover all node types with schemas and capability metadata |
| `generate_graph` | Build a `GraphIR` from a node list (auto-chains or explicit edges) |
| `validate_graph` | Validate a `GraphIR` document |
| `get_graph_schema` | Get the JSON Schema for `GraphIR` |
| `get_graph_capability_summary` | Aggregate capability flags across all nodes in a graph |
| `get_event_schema` | Get the NDJSON event type schema |
| `execute_pipeline` | Execute a `GraphIR` → returns `run_id` immediately |
| `inspect_run` | List runs or inspect a specific run's metadata/logs/graph/checkpoints |
| `pause_run` | Pause an active run |
| `resume_run` | Resume a paused run |
| `cancel_run` | Cancel an active run |

### Example: Discover and Filter Nodes

```json
// List all audio nodes
{"tool": "list_nodes", "arguments": {"category": "audio"}}

// Find CPU-only, edge-compatible nodes
{"tool": "list_nodes", "arguments": {
  "capability_filter": {"requires_gpu": false, "supports_edge": true}
}}

// Get config schema for a specific node
{"tool": "list_nodes", "arguments": {"node_type": "audio_conditioner", "schema_only": true}}
```

### Example: Generate and Execute a Graph

```json
// Generate a graph
{"tool": "generate_graph", "arguments": {
  "nodes": [
    {"node_type": "dataset_ingest",    "config": {"path": "data/"}},
    {"node_type": "audio_conditioner", "config": {"sample_rate": 16000}},
    {"node_type": "deployment_packager", "config": {"target": "mobile"}}
  ]
}}

// Execute it
{"tool": "execute_pipeline", "arguments": {"graph": <GraphIR from above>}}

// Check status
{"tool": "inspect_run", "arguments": {"run_id": "abc12345", "status_only": true}}
```

### Authentication

Set `GRAPHYN_API_TOKEN` and pass it in every tool call:
```json
{"tool": "list_nodes", "arguments": {"_meta": {"auth_token": "my-secret-token"}, ...}}
```

---

## 7. Writing Nodes

All production nodes live in `PluginPackage/`. To write a new node, create a plugin — do not add files to `app/core/nodes/`. See [PLUGIN_GUIDE.md](./PLUGIN_GUIDE.md) for the full template, backend pattern, and checklist.

### Minimal Node

```python
# PluginPackage/Audio/my_plugin/nodes.py
from __future__ import annotations
from typing import ClassVar
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

class MyNode(Node):
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="my_node",
        label="My Node",
        description="Transforms audio samples.",
        category="Processing",
        version="1.0.0",
        tags=["audio"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
        streaming_support=False,
        realtime_support=False,
    )
    input_ports: ClassVar[dict] = {
        "input": InputPort(name="input", data_type=list[AudioSample], required=True)
    }
    output_ports: ClassVar[dict] = {
        "output": OutputPort(name="output", data_type=list[AudioSample])
    }
    class Config(NodeConfig):
        backend: str = "auto"   # "cpu" | "gpu" | "auto"

    def process(self, samples):   # SISO shorthand
        return samples
```

### Lifecycle Hooks

```python
def setup(self):
    self.model = load_model()   # called once before first process()

def teardown(self):
    self.model = None           # called once after last process()

def on_start(self):
    pass                        # called before each process()

def on_end(self):
    pass                        # called after successful process()

def on_error(self, exc):
    pass                        # called when process() raises
```

### Retry Policy

```python
from app.core.nodes.retry import RetryPolicy

class MyNode(Node):
    retry_policy: ClassVar[RetryPolicy] = RetryPolicy(
        max_attempts=3,
        backoff_seconds=1.0,
        backoff_multiplier=2.0,
    )
```

### Streaming Node

```python
class MyStreamingNode(Node):
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        ..., streaming_support=True
    )

    async def process_stream(self, inputs):
        for chunk in generate_chunks(inputs["input"]):
            yield {"output": chunk}
```

### Multi-Port Node

```python
class MySplitNode(Node):
    input_ports: ClassVar[dict] = {
        "input": InputPort(name="input", data_type=list)
    }
    output_ports: ClassVar[dict] = {
        "train": OutputPort(name="train", data_type=list),
        "val":   OutputPort(name="val",   data_type=list),
    }

    def process(self, inputs: dict) -> dict:
        samples = inputs["input"]
        split = int(len(samples) * 0.8)
        return {"train": samples[:split], "val": samples[split:]}
```

### Custom Data Types

```python
from app.core.nodes.ports import PortDataType

class TextSample(PortDataType):
    text: str = ""
    language: str = "en"
    metadata: dict = {}

# Use as port data_type — AutoDiscovery registers it in TypeCatalogue
```

---

## 8. Writing Plugins

See [PLUGIN_GUIDE.md](./PLUGIN_GUIDE.md) for the complete guide including `plugin.toml` schema, backend pattern, custom types, lifecycle hooks, and the quality checklist.

```python
# PluginPackage/Audio/my_plugin/nodes.py
from __future__ import annotations
from typing import ClassVar
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.models.audio_sample import AudioSample

class MyPluginNode(Node):
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="my_plugin", label="My Plugin",
        description="Plugin node.", category="Processing",
        version="1.0.0", tags=["audio"],
        requires_gpu=False, supports_cpu=True, supports_edge=True,
        deterministic=True, cacheable=True,
    )
    input_ports: ClassVar[dict] = {
        "input": InputPort(name="input", data_type=list[AudioSample], required=True)
    }
    output_ports: ClassVar[dict] = {
        "output": OutputPort(name="output", data_type=list[AudioSample])
    }
    class Config(NodeConfig):
        pass

    def process(self, samples):
        return samples
```

Install via `PluginManager` — do not drop raw `.py` files into `plugins/`:

```bash
graphyn plugin install PluginPackage/Audio/my_plugin/
```

---

## 9. Plugin Management

Phase 5 adds a managed plugin lifecycle. Plugins are installed from a source string (local path, Git URL, HTTP archive, or index name), validated against a `plugin.toml` manifest, and tracked in a persistent store. All operations are available via CLI, REST API, and SDK.

### Installing Plugins

```bash
# Install by name (looks up the plugin index)
graphyn plugin install audio-denoiser

# Install from a local directory
graphyn plugin install /path/to/audio-denoiser/

# Install from a Git URL
graphyn plugin install git+https://github.com/example/audio-denoiser.git

# Install from an HTTP archive
graphyn plugin install https://example.com/audio-denoiser-1.2.0.zip

# Upgrade an existing installation
graphyn plugin install audio-denoiser --upgrade
```

### Listing Plugins

```bash
graphyn plugin list              # all installed plugins
graphyn plugin list --enabled    # only enabled plugins
```

### Enabling and Disabling

```bash
graphyn plugin enable audio-denoiser    # reload node types into registry
graphyn plugin disable audio-denoiser   # unload node types from registry
```

### Removing Plugins

```bash
graphyn plugin remove audio-denoiser    # uninstall and delete files
```

### Searching the Plugin Index

```bash
graphyn plugin search denois            # search by name, description, or tags
graphyn plugin info audio-denoiser      # show full plugin details as JSON
```

### SDK Usage

```python
from app.core.sdk import Pipeline

pipeline = Pipeline([...])

# Install by name
record = pipeline.install_plugin("audio-denoiser")
print(f"Installed {record.name} {record.version}")

# Install from a local path
record = pipeline.install_plugin("/path/to/audio-denoiser/")

# Upgrade an existing installation
record = pipeline.install_plugin("audio-denoiser", upgrade=True)
```

### REST API

```
GET    /api/v1/plugins                    List all installed plugins
POST   /api/v1/plugins/install            Install a plugin (body: {"source": str, "upgrade": bool})
GET    /api/v1/plugins/search?q=<query>   Search the plugin index
GET    /api/v1/plugins/{name}             Get a specific installed plugin
POST   /api/v1/plugins/{name}/enable      Enable a plugin
POST   /api/v1/plugins/{name}/disable     Disable a plugin
DELETE /api/v1/plugins/{name}             Uninstall a plugin
```

Remote sources (`git+`, `http://`, `https://`) install asynchronously — the endpoint returns `{"status": "installing", "name": "..."}` immediately. Poll `GET /api/v1/plugins/{name}` for the result.

### Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `GRAPHYN_PLUGINS_DIR` | `"plugins"` | Directory where plugins are installed |
| `GRAPHYN_PLUGIN_AUTO_INSTALL` | `""` | Set to `"1"` or `"true"` to auto-install missing Python dependencies via pip |
| `GRAPHYN_PLUGIN_INDEX_URL` | `""` | URL of a remote plugin index JSON file |

---

## 10. Advanced Runtime Modes

### Parallel Execution

Independent nodes execute concurrently within each topological wave.

```python
# SDK
pipeline.run(parallel=True, max_workers=8)

# CLI
graphyn run --graph pipeline.graph.json --parallel
```

Events emitted: `wave_start` / `wave_end` per wave.

### Resumability

Resume a failed or interrupted run from the last successful checkpoint.

```python
# First run with checkpointing
outputs, run = pipeline.run_with_manager(checkpoint=True)
prior_run_id = run.run_id

# Resume after failure
pipeline.run(resume_run_id=prior_run_id)
```

```bash
graphyn run --graph pipeline.graph.json --resume abc12345
```

### Partial Execution

Execute only a subset of nodes.

```python
# Include specific nodes
pipeline.run(include_nodes=["clean_0", "segment_0"])

# Exclude specific nodes
pipeline.run(exclude_nodes=["augment_0"])

# Inject inputs for boundary nodes
pipeline.run(
    include_nodes=["export_0"],
    input_overrides={"export_0": {"input": my_samples}},
)
```

```bash
graphyn run --graph pipeline.graph.json --include-nodes clean_0,segment_0
graphyn run --graph pipeline.graph.json --exclude-nodes augment_0
```

### Conditional Branching

Edges can carry boolean conditions that gate data flow.

```python
from app.core.ir import IREdge

# Edge only transmits when source has > 10 samples
edge = IREdge(
    src_id="clean_0", src_port="output",
    dst_id="export_long", dst_port="input",
    condition="len(output['output']) > 10",
)
```

Allowed in conditions: comparisons (`==`, `!=`, `<`, `>`, `<=`, `>=`), boolean ops (`and`, `or`, `not`), `len()`, subscript access (`output["key"]`), literals.

### Event-Driven Execution

Nodes trigger on external events (file changes, timers, queue messages).

```python
from app.core.ir import IRNode
from app.core.ir import CURRENT_IR_VERSION
from app.core.ir.models import GraphIR, IRMetadata

# Bind a node to a timer source
graph = GraphIR(
    schema_version=CURRENT_IR_VERSION,
    metadata=IRMetadata(name="event-pipeline", seed=0),
    nodes=[
        IRNode(
            id="trigger",
            node_type="my_node",
            config={},
            event_trigger={
                "source_type": "timer",
                "source_config": {"interval_s": 60.0},
            },
        )
    ],
    edges=[],
)

from app.core.runtime_backend import get_backend
get_backend().execute(graph, event_driven=True)
```

Available event sources: `timer` (`interval_s`), `file_watcher` (`path`, `pattern`), `queue` (asyncio.Queue).

```bash
graphyn run --graph pipeline.graph.json --event-driven
```

### Runtime Control (Pause / Resume / Cancel)

```python
# Via SDK
outputs, run = pipeline.run_with_manager()
run.pause()    # pause after current node
run.resume()   # resume from pause
run.cancel()   # cancel after current node

# Via REST API
import httpx
httpx.post(f"http://localhost:8001/api/v1/runs/{run_id}/pause")
httpx.post(f"http://localhost:8001/api/v1/runs/{run_id}/resume")
httpx.post(f"http://localhost:8001/api/v1/runs/{run_id}/cancel")

# Via MCP
{"tool": "pause_run",  "arguments": {"run_id": "abc12345"}}
{"tool": "resume_run", "arguments": {"run_id": "abc12345"}}
{"tool": "cancel_run", "arguments": {"run_id": "abc12345"}}
```

---

## 11. Workspace & Artifacts

### Directory Structure

```
workspace/
├── datasets/
│   ├── input/{label}/*.wav|mp3     # input audio organized by label
│   └── output/{project}/{version}/ # exported datasets
│       ├── train|val|test/{label}/{hash}.wav
│       ├── labels.csv              # id,path,label,split
│       └── metadata.json
├── runs/{run_id}/
│   ├── meta.json                   # run metadata and status
│   ├── logs.json                   # NDJSON event log
│   ├── graph.json                  # GraphIR that was executed
│   ├── resume_state.json           # checkpoint state (when checkpoint=True)
│   └── checkpoints/node_{id}/      # per-node output snapshots
├── cache/{sha256}/                 # node output cache
└── webhooks.json                   # webhook configuration
```

### Inspecting Runs

```bash
# List recent runs
graphyn runs list

# View logs for a run
graphyn runs logs abc12345

# Via REST API
curl http://localhost:8001/api/v1/runs
curl http://localhost:8001/api/v1/runs/abc12345/status
```

### `meta.json` Fields

```json
{
  "run_id": "abc12345",
  "created_at": "2024-01-01T00:00:00+00:00",
  "status": "completed",
  "duration_s": 12.34,
  "num_nodes": 5,
  "node_stats": [{"node_id": "clean_0", "duration_s": 0.12}],
  // On resume:
  "resumed_from": "prior_run_id",
  "skipped_nodes": ["input_0"],
  "executed_nodes": ["clean_0", "export_0"],
  // On partial execution:
  "partial_execution": true,
  "included_nodes": ["clean_0", "export_0"]
}
```

---

## 12. Configuration & Environment

| Variable | Default | Purpose |
|---|---|---|
| `GRAPHYN_PROJECT_DIR` | `"workspace"` | Runtime data root |
| `GRAPHYN_API_TOKEN` | `""` | Bearer token for API/MCP auth (unset = no auth) |
| `GRAPHYN_PLUGINS_DIR` | `"plugins"` | Plugin directory |
| `VITE_API_BASE_URL` | `http://localhost:8001` | Frontend API base URL |

### Authentication

Set `GRAPHYN_API_TOKEN` to require authentication on all API and MCP requests:

```bash
export GRAPHYN_API_TOKEN=my-secret-token
venv/bin/uvicorn app.api.main:app --reload --port 8001

# API requests
curl -H "Authorization: Bearer my-secret-token" http://localhost:8001/api/v1/nodes

# MCP requests — pass in _meta
{"tool": "list_nodes", "arguments": {"_meta": {"auth_token": "my-secret-token"}}}
```

---

## 13. Troubleshooting

### Node not found

```
ValueError: Unknown node type 'my_node'. Available types: [...]
```

Check: (1) plugin is installed via `PluginManager` and enabled; (2) class has `metadata: ClassVar[NodeMetadata]`; (3) `node_type` matches what you're using. Run `graphyn nodes` to list all registered types.

### Config validation error

```
ValueError: Invalid config for node 'clean': ...
```

Check the node's `Config` class fields. Use `graphyn nodes --category audio` to see available nodes, then `GET /api/v1/nodes/{node_type}/config-schema` for the exact schema.

### Resume fails

```
ResumeError: Resume run 'abc12345' not found at workspace/runs/abc12345
```

The prior run directory doesn't exist or `resume_state.json` is missing. Ensure the original run used `checkpoint=True`.

### Partial execution — boundary node gets None input

When a boundary node's upstream is excluded and no `input_overrides` or checkpoint is available, the port receives `None`. Either provide `input_overrides` or ensure a prior run with `checkpoint=True` exists.

### VADNode fails to construct

```
ValueError: webrtcvad not installed
```

Install: `venv/bin/pip install webrtcvad`. Supports only 8000/16000/32000/48000 Hz and 10/20/30 ms frames.

### MCP tool returns `run_not_active`

`pause_run`/`resume_run`/`cancel_run` only work on currently running pipelines. The run must be active (started but not yet completed/failed).

### Cache not working

The cache only applies to nodes with list-valued inputs (audio samples). `SplitNode` and `ExportNode` always re-execute. Set `use_cache=False` to disable entirely.

### Tests

```bash
venv/bin/pytest                          # all tests
venv/bin/pytest tests/mcp/ -v            # MCP tests only
venv/bin/pytest tests/ -x -q             # stop on first failure
```
