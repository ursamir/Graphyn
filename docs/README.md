# Graphyn Platform Documentation

> **New comprehensive overview (source-of-truth, generated from code):** → **[OVERVIEW.md](OVERVIEW.md)**  
> **Full node catalogue:** → **[NODE_CATALOGUE.md](NODE_CATALOGUE.md)**  
> **Architecture diagrams:** → **[ARCHITECTURE.md](ARCHITECTURE.md)**

This is a general-purpose AI/workflow execution platform. It exposes a REST API, a Python SDK, a CLI, and an MCP server for building, running, and managing data processing pipelines — primarily audio ML, but domain-agnostic via plugins.

This index is the entry point for all documentation. Start here, then follow the links to the topic you need.

---

## Documentation Map

| Document | What it covers |
|---|---|
| **[OVERVIEW.md](./OVERVIEW.md)** | **Complete platform overview with architecture diagrams — start here** |
| **[NODE_CATALOGUE.md](./NODE_CATALOGUE.md)** | **All 33+ built-in nodes with ports, config fields, and capability flags** |
| [USERGUIDE.md](./USERGUIDE.md) | Complete user guide — SDK, CLI, API, MCP, nodes, plugins, advanced runtime |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | System layers, component dependency graph, data flows, phase history |
| [NODE_SYSTEM.md](./NODE_SYSTEM.md) | Node base class, ports, config, metadata, capability fields, registry, AutoDiscovery |
| [PIPELINE_EXECUTION.md](./PIPELINE_EXECUTION.md) | Graph IR, DAG executor, caching, checkpoints, all execution modes |
| [API_REFERENCE.md](./API_REFERENCE.md) | All `/api/v1/` REST endpoints, request/response shapes, streaming protocol |
| [BACKEND_CORE.md](./BACKEND_CORE.md) | RunManager, PipelineLogger, ArtifactStore, ProvenanceStore, PipelineCache |
| [MCP_SERVER.md](./MCP_SERVER.md) | MCP server: all 14 tools, auth, tool registry, error contract |
| [PLUGIN_GUIDE.md](./PLUGIN_GUIDE.md) | Writing and deploying plugins, manifest schema, lifecycle |
| [SDK_AND_CLI.md](./SDK_AND_CLI.md) | Python SDK (Pipeline, PipelineNode, ArtifactCollection) and CLI reference |
| [DATA_FLOW_AND_WORKSPACE.md](./DATA_FLOW_AND_WORKSPACE.md) | Port data types, workspace layout, artifact format |
| [KNOWN_ISSUES.md](./KNOWN_ISSUES.md) | Active and resolved issues |

---

## Quick Start

### Run the API server

```bash
venv/bin/uvicorn app.api.main:app --reload --port 8001
```

All endpoints are under `http://localhost:8001/api/v1/`.

### Start the MCP server

```bash
graphyn mcp
# or
python -m app.mcp.server
```

Reads JSON-RPC from stdin, writes responses to stdout. Logs to stderr.

### Run a pipeline from the CLI

```bash
venv/bin/python -m app.cli.main run --graph workspace/configs/templates/basic-wakeword.graph.json
```

### Run a pipeline from Python

```python
from app.core.sdk import PipelineNode, Pipeline

pipeline = Pipeline([
    PipelineNode("dataset_ingest",    {"path": "data/audio"}),
    PipelineNode("audio_conditioner", {"sample_rate": 16000}),
    PipelineNode("segmenter",         {"mode": "vad"}),
    PipelineNode("feature_frontend",  {"feature_type": "mfcc"}),
    PipelineNode("dataset_builder",   {"split_ratios": {"train": 0.8, "val": 0.1, "test": 0.1}}),
], seed=42)
pipeline.run()
```

### Validate a pipeline YAML

```bash
venv/bin/python -m app.cli.main validate --graph my-pipeline.graph.json
```

---

## Key Concepts

**Node** — a self-contained processing unit with typed input/output ports and a Pydantic config model. All nodes extend `app.core.nodes.base.Node`.

**Pipeline** — a directed acyclic graph (DAG) of nodes. Defined in IR JSON (canonical) or YAML (deprecated) or via the Python SDK. Executed by `run_pipeline_ir()`.

**Graph IR** — the canonical pipeline representation (`app/core/ir/`). Versioned, validated, runtime-agnostic JSON. All interfaces produce and consume `GraphIR` objects. YAML is a deprecated serialization format.

**IRCapabilityMetadata** — per-node capability hints embedded in a `GraphIR` (Phase 1). When set on an `IRNode`, overrides the node class's `NodeMetadata` capability fields for that instance.

**Registry** — a singleton `NodeRegistry` populated at startup by `AutoDiscovery`. Maps node type strings (e.g. `"audio_conditioner"`) to their Python classes and metadata.

**AutoDiscovery** — scans `app/core/nodes/` (framework files only), `app/models/`, and `plugins/` at import time. Any `.py` file in a plugin's entry points containing a `Node` subclass with a `metadata: ClassVar[NodeMetadata]` is registered automatically.

**Plugin** — a manifest-based package in `PluginPackage/` installed via `PluginManager`. All 29 production nodes are plugins. The `app/core/nodes/` directory contains only framework infrastructure — no node implementations.

**PortDataType** — the base class for all data types that flow between node ports. Subclass it to define domain-specific types. `AudioSample`, `DataSample`, `FeatureArray`, `ModelArtifact`, `TFLiteArtifact`, and `PredictionResult` are all `PortDataType` subclasses.

**DataSample** — a domain-agnostic base data type (`id`, `source`, `metadata`). Subclass it for new domains (e.g. `TextSample`, `ImageSample`).

**AudioSample** — the data type for audio clips (`path`, `sample_rate`, `data`, `label`, `metadata`). One example of a domain-specific `PortDataType`.

**MCP Server** — interface at `app/mcp/`. Exposes 15 tools via the Model Context Protocol (stdio transport), enabling AI agents to discover nodes, generate graphs, validate, execute pipelines, inspect artifacts, and control runs.

---

## Example Use Cases

- **Audio dataset preparation** — load WAV files, clean, augment, segment, split, export
- **ML training pipelines** — extract features, build datasets, train Keras models, export TFLite
- **Speech command classification** — end-to-end from raw audio to deployed TFLite model
- **Speaker verification** — annotate speaker identity metadata for contrastive learning
- **Speech enhancement** — generate paired clean/degraded samples for training
- **Data transformation** — any pipeline that reads, transforms, and writes structured data

---

## Architecture in One Diagram

```
Browser / CLI / SDK / AI Agent
        │
        ▼
FastAPI app  (app/api/main.py — thin factory)
        │
        ├── /api/v1/nodes/*       → nodes.py router
        ├── /api/v1/pipelines/*   → pipelines.py router
        ├── /api/v1/runs/*        → runs.py router
        ├── /api/v1/data/*        → data.py router
        ├── /api/v1/system/*      → system.py router
        ├── /api/v1/projects/*    → projects.py router
        └── /api/v1/ingest/*      → ingest.py router

MCP Server  (app/mcp/server.py — stdio transport)
        │
        ├── list_nodes            → handlers/discovery.py
        ├── generate_graph        → handlers/graph.py
        ├── validate_graph        → handlers/graph.py
        ├── get_graph_schema      → handlers/graph.py
        ├── get_graph_capability_summary → handlers/graph.py
        ├── get_event_schema      → handlers/graph.py
        ├── execute_pipeline      → handlers/execution.py
        └── inspect_run           → handlers/artifacts.py
                │
                ▼
        app/core/  (shared by all interfaces)
        ├── nodes/          Node System (registry, discovery, base, ports…)
        │   └── (no audio/ or ml/ subdirs — all nodes are plugins)
        ├── ir/             Graph IR (models.py, loader.py, yaml_shim.py, migrate.py)
        ├── pipeline.py     DAG executor (run_pipeline_ir)
        ├── validation.py   Pipeline config validation
        ├── run_manager.py  Per-run directory + metadata
        ├── logger.py       Structured event logger
        ├── ingestion.py    URL / HuggingFace ingestion
        ├── pipeline_cache.py  WAV + manifest cache
        └── sdk.py          PipelineNode / Pipeline SDK
```

---

## What Changed in the Pydantic Migration

| Old | New |
|---|---|
| `register(registry)` in plugins | `AutoDiscovery` via `metadata: ClassVar[NodeMetadata]` |
| `registry[node_type]["class"]` | `registry.get_class(node_type)` |
| `registry[node_type]["schema"]` | `registry.get_config_schema(node_type)` |
| `validate_node_config(config, schema)` | `NodeClass.Config.model_validate(config)` |
| `datetime.utcnow()` | `datetime.now(timezone.utc)` |
| `@dataclass` on `IngestionJob` | `class IngestionJob(BaseModel)` |
| `AudioSample(path=...)` constructor | `AudioSample.model_validate({...})` |
| 500-line `app/api/main.py` monolith | Thin factory + 7 focused routers |
| Legacy root-path endpoints | All routes under `/api/v1/` only |
| `Node` class in sdk.py | `PipelineNode` class |
| Audio-specific first/last node rules in `validate_pipeline` | Generalized validation, no domain constraints, supports DAG format |
| Node implementations in `app/core/nodes/*.py` (flat) | Node implementations in `PluginPackage/Audio/` and `PluginPackage/Common/` (plugins) |
| ML nodes in `examples/06/plugins/` | ML nodes in `PluginPackage/Common/` (plugins) |
| ML data types in `examples/06/plugins/data_types.py` | ML data types in `app/models/` (built-in) |
