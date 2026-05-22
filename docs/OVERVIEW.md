# Graphyn Platform — Complete Overview

> **Source of truth:** this document is derived from the source code, not from prior docs.  
> **Scope:** everything under `app/`. The `audiobuilder/` Visual UI has been deprecated and is no longer maintained.

---

## Table of Contents

1. [What is Graphyn?](#1-what-is-graphyn)
2. [Four Interfaces, One Core](#2-four-interfaces-one-core)
3. [Architecture Diagram](#3-architecture-diagram)
4. [Node System](#4-node-system) → [NODE_SYSTEM.md](NODE_SYSTEM.md)
5. [Pipeline Execution](#5-pipeline-execution) → [PIPELINE_EXECUTION.md](PIPELINE_EXECUTION.md)
6. [Graph IR (Intermediate Representation)](#6-graph-ir) → [PIPELINE_EXECUTION.md](PIPELINE_EXECUTION.md)
7. [Data Models & Port Types](#7-data-models--port-types) → [DATA_FLOW_AND_WORKSPACE.md](DATA_FLOW_AND_WORKSPACE.md)
8. [REST API](#8-rest-api) → [API_REFERENCE.md](API_REFERENCE.md)
9. [Python SDK & CLI](#9-python-sdk--cli) → [SDK_AND_CLI.md](SDK_AND_CLI.md)
10. [MCP Server](#10-mcp-server) → [MCP_SERVER.md](MCP_SERVER.md)
11. [Backend Services](#11-backend-services) → [BACKEND_CORE.md](BACKEND_CORE.md)
12. [Plugin Ecosystem](#12-plugin-ecosystem) → [PLUGIN_GUIDE.md](PLUGIN_GUIDE.md)
13. [Workspace Layout](#13-workspace-layout)
14. [Configuration & Environment Variables](#14-configuration--environment-variables)
15. [Running the Platform](#15-running-the-platform)

---

## 1. What is Graphyn?

Graphyn is a **general-purpose AI/workflow execution platform** built around a DAG (Directed Acyclic Graph) pipeline engine. Its primary domain is audio ML — loading, preprocessing, augmenting, and training models on audio data — but the node system is domain-agnostic and extensible via plugins.

**Core design principles:**

- **One canonical format:** all pipelines are represented as `GraphIR` JSON (`.graph.json`). YAML is a deprecated legacy format with a migration path.
- **Four equal interfaces:** REST API, Python SDK, CLI, and MCP Server all share the same `app/core/` execution engine. (The Visual UI `audiobuilder/` has been deprecated.)
- **Typed ports:** every node declares typed input/output ports. The `PortDataType` base class and `TypeCatalogue` enforce type safety at graph construction time.
- **Pluggable:** new node types can be added via the plugin system without modifying core code.

---

## 2. Four Interfaces, One Core

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT INTERFACES                        │
│                                                                 │
│  REST API          Python SDK        CLI           MCP Server   │
│  app/api/          app/core/sdk.py   app/cli/      app/mcp/     │
│  :8001/api/v1/     Pipeline(...)     graphyn CLI   stdio JSON-  │
│                                      run/validate  RPC (15 tools│
└──────────────────────────┬──────────────────────────────────────┘
                           │  all call
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                         app/core/                               │
│                                                                 │
│  pipeline.py          run_pipeline_ir()  ← primary entry point  │
│  executor.py          ParallelExecutor   ← wave-based parallel  │
│  ir/                  GraphIR models     ← canonical format     │
│  nodes/               Node base + registry (no built-in node impls) │
│  plugins/             PluginManager      ← extensibility        │
│  artifact_store.py    ArtifactStore      ← content-addressed    │
│  provenance.py        ProvenanceStore    ← lineage tracking     │
│  run_manager.py       RunManager         ← lifecycle + control  │
│  logger.py            PipelineLogger     ← structured events    │
└─────────────────────────────────────────────────────────────────┘
                           │  reads/writes
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      workspace/  (runtime data)                 │
│  runs/  artifacts/  provenance/  cache/  datasets/  plugins/    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Architecture Diagram

```
                         ┌──────────────────────────────────────────┐
                         │              GRAPHYN PLATFORM             │
                         └──────────────────────────────────────────┘

  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
  │  REST API    │  │  Python SDK  │  │     CLI      │  │  MCP Server  │
  │  FastAPI     │  │  Pipeline    │  │  graphyn CLI │  │  stdio JSON- │
  │  :8001       │  │  PipelineNode│  │  run/validate│  │  RPC 15 tools│
  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
         │                 │                  │                  │
         └─────────────────┴──────────────────┴──────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │     run_pipeline_ir()          │
                    │     app/core/pipeline.py       │
                    └───────────────┬───────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
              ▼                     ▼                     ▼
   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
   │  PipelineGraph   │  │  ParallelExecutor│  │  PipelineCache   │
   │  - DAG builder   │  │  - Wave-based    │  │  - SHA-256 keyed │
   │  - Topo sort     │  │  - asyncio +     │  │  - WAV + manifest│
   │  - Kahn's algo   │  │    ThreadPool    │  └──────────────────┘
   └──────────────────┘  └──────────────────┘
              │
              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │                    NODE EXECUTION                            │
   │                                                              │
   │  NodeExecutor                                                │
   │  setup() → [on_start → process → on_end]* → teardown()      │
   │  RetryPolicy: exponential backoff                            │
   │  NodeObserver: LoggingObserver / CompositeObserver           │
   └──────────────────────────────────────────────────────────────┘
              │
              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │                    NODE REGISTRY                             │
   │                                                              │
   │  NodeRegistry (singleton)                                    │
   │  ├── _classes: {node_type → Node subclass}                   │
   │  ├── _metadata: {node_type → NodeMetadata}                   │
   │  └── type_catalogue: TypeCatalogue                           │
   │                                                              │
   │  AutoDiscovery                                               │
   │  ├── scans app/models/              (PortDataType subclasses) │
   │  └── scans plugins/                (manifest-based, 29 nodes)│
   └──────────────────────────────────────────────────────────────┘
              │
              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │                    BACKEND SERVICES                          │
   │                                                              │
   │  RunManager        ArtifactStore      ProvenanceStore        │
   │  - run lifecycle   - content-addr.    - lineage tracking     │
   │  - pause/resume/   - SHA-256 dedup    - get_lineage()        │
   │    cancel          - typed records    - find_by_run()        │
   │  - checkpoints     - 6 artifact types - find_reproducible()  │
   │  - resume state                                              │
   └──────────────────────────────────────────────────────────────┘
```

---

## 4. Node System

See → **[NODE_SYSTEM.md](NODE_SYSTEM.md)**

**Quick summary:**

Every processing unit is a `Node` subclass with:
- Typed `InputPort` / `OutputPort` declarations
- A Pydantic `Config(NodeConfig)` inner class
- A `process()` method (SISO shorthand or multi-port)
- Optional `RetryPolicy` for fault tolerance
- Optional `NodeObserver` for structured event callbacks
- `NodeMetadata` with capability fields (`requires_gpu`, `cacheable`, `deterministic`, etc.)

**29 plugin nodes** across two packages:

| Package | Count | Examples |
|---|---|---|
| `PluginPackage/Audio/` | 18 | `dataset_ingest`, `audio_conditioner`, `segmenter`, `feature_frontend`, `speech_enhancer` |
| `PluginPackage/Common/` | 11 | `dataset_builder`, `trainer`, `evaluator`, `edge_optimizer`, `realtime_inference` |

Full node catalogue → **[NODE_CATALOGUE.md](NODE_CATALOGUE.md)**

---

## 5. Pipeline Execution

See → **[PIPELINE_EXECUTION.md](PIPELINE_EXECUTION.md)**

**Execution modes:**

| Mode | Flag | Description |
|---|---|---|
| Sequential | default | Nodes run one at a time in topological order |
| Parallel | `parallel=True` | Nodes in the same wave run concurrently via asyncio + ThreadPool |
| Streaming | `streaming=True` | Streaming nodes use `process_stream()` async generator |
| Event-driven | `event_driven=True` | Nodes triggered by `EventSource` (file watcher, timer, queue) |
| Resumable | `checkpoint=True` + `resume_run_id=X` | Skip completed nodes, load from checkpoints |
| Partial | `include_nodes=[...]` or `exclude_nodes=[...]` | Execute a subset of nodes |

**Execution flow:**

```
GraphIR → PipelineConfig → PipelineGraph → topological sort → execution waves
                                                                      │
                                              ┌───────────────────────┤
                                              │  For each wave:       │
                                              │  ┌─────────────────┐  │
                                              │  │ assemble inputs │  │
                                              │  │ check cache     │  │
                                              │  │ NodeExecutor    │  │
                                              │  │   .execute()    │  │
                                              │  │ save cache      │  │
                                              │  │ write checkpoint│  │
                                              │  └─────────────────┘  │
                                              └───────────────────────┘
```

---

## 6. Graph IR

The **Graph Intermediate Representation** is the canonical pipeline format. All interfaces produce and consume `GraphIR`.

```json
{
  "schema_version": "1.1",
  "metadata": {
    "name": "my-pipeline",
    "seed": 42,
    "description": "",
    "tags": []
  },
  "nodes": [
    {
      "id": "ingest_0",
      "node_type": "dataset_ingest",
      "config": {"path": "workspace/datasets/input/speech"},
      "label": null,
      "capability_metadata": null,
      "event_trigger": null
    }
  ],
  "edges": [
    {
      "src_id": "input_0",
      "src_port": "output",
      "dst_id": "clean_0",
      "dst_port": "input",
      "condition": null
    }
  ],
  "parameters": {}
}
```

**Key IR types:**

| Type | Purpose |
|---|---|
| `GraphIR` | Top-level container; validates node ID uniqueness and edge references |
| `IRNode` | Single node: `id`, `node_type`, `config`, optional `capability_metadata`, `event_trigger` |
| `IREdge` | Directed edge with optional `condition` expression for conditional routing |
| `IRMetadata` | Graph-level: `name`, `seed`, `description`, `tags` |
| `IRCapabilityMetadata` | Per-node capability overrides (takes precedence over `NodeMetadata`) |
| `IRParameter` | Graph-level parameter definitions |

**Version:** current is `1.1`. Accepts `1.0` (missing `condition`/`event_trigger` default to `None`). Rejects major version ≠ 1.

---

## 7. Data Models & Port Types

See → **[DATA_FLOW_AND_WORKSPACE.md](DATA_FLOW_AND_WORKSPACE.md)**

All inter-node data types extend `PortDataType` (Pydantic `BaseModel`):

| Type | Key Fields | Primary Producer |
|---|---|---|
| `AudioSample` | `path`, `sample_rate`, `data` (float32 ndarray), `label`, `metadata` | `InputNode`, `MicInputNode`, `FileInputNode` |
| `FeatureArray` | `data` (float32 [T,F]), `label`, `sample_rate`, `source_path`, `metadata` | `FeatureExtractorNode` |
| `TensorBatch` | `data` (float32 [N,...]), `labels`, `split`, `source_ids`, `metadata` | `DatasetBuilderNode` |
| `ModelArtifact` | `model_path`, `labels`, `history`, `metrics` | `ModelTrainerNode` |
| `TFLiteArtifact` | `tflite_path`, `labels`, `quantisation`, `file_size_bytes` | `TFLiteExporterNode` |
| `PredictionResult` | `source_path`, `predicted_label`, `probabilities`, `metadata` | `InferenceNode` |
| `DeploymentArtifact` | `artifact_path`, `model_format`, `target_hardware`, `labels`, `benchmark` | Deployment nodes |
| `DataSample` | `id`, `source`, `metadata` | Base type for custom domains |

---

## 8. REST API

See → **[API_REFERENCE.md](API_REFERENCE.md)**

Base URL: `http://localhost:8001/api/v1/`  
Auth: optional `Authorization: Bearer <GRAPHYN_API_TOKEN>`

**10 routers, 50+ endpoints:**

| Router | Prefix | Key Operations |
|---|---|---|
| `nodes` | `/nodes` | List, get, validate config, port schema, compatible nodes |
| `pipelines` | `/pipelines` | Validate, run (streaming NDJSON), run-async, templates |
| `runs` | `/runs` | List, get, status, checkpoints, artifacts, provenance |
| `run_control` | `/runs/{id}` | Pause, resume, cancel active runs |
| `data` | `/data` | Input/output dataset browsing, file upload, merge |
| `system` | `/system` | Health, cleanup, webhooks |
| `projects` | `/projects` | Full project lifecycle |
| `ingest` | `/ingest` | URL and HuggingFace dataset ingestion with SSE progress |
| `artifacts` | `/artifacts` | List, get, lineage tree, replay |
| `plugins` | `/plugins` | Install, enable, disable, uninstall, search |

**Streaming protocol** (`POST /pipelines/run`): `application/x-ndjson` — one JSON event per line with types: `pipeline_start`, `node_start`, `node_end`, `node_error`, `done`, `error`.

---

## 9. Python SDK & CLI

See → **[SDK_AND_CLI.md](SDK_AND_CLI.md)**

**SDK:**
```python
from app.core.sdk import Pipeline, PipelineNode

pipeline = Pipeline([
    PipelineNode("dataset_ingest",    {"path": "workspace/datasets/input/speech"}),
    PipelineNode("audio_conditioner", {"sample_rate": 16000}),
    PipelineNode("segmenter",         {"mode": "vad"}),
    PipelineNode("feature_frontend",  {"feature_type": "mfcc"}),
    PipelineNode("dataset_builder",   {"split_ratios": {"train": 0.8, "val": 0.1, "test": 0.1}}),
], seed=42)

result = pipeline.run()          # returns ArtifactCollection
result.artifacts                 # list[ArtifactRecord]
result["node_id"]                # backward-compat dict access
```

**CLI commands:**

| Command | Description |
|---|---|
| `graphyn run --graph <path>` | Execute IR JSON pipeline |
| `graphyn run --config <path>` | Execute YAML pipeline (deprecated) |
| `graphyn validate --graph <path>` | Validate IR JSON |
| `graphyn migrate --config <path>` | Convert YAML → IR JSON |
| `graphyn inspect --graph <path>` | Print graph summary + capability report |
| `graphyn nodes [--category X]` | List registered node types |
| `graphyn runs list` | List recent runs |
| `graphyn runs logs <run_id>` | Print run logs |
| `graphyn artifacts list` | List artifacts |
| `graphyn plugin install <source>` | Install a plugin |
| `graphyn plugin list` | List installed plugins |
| `graphyn mcp` | Launch MCP server |

---

## 10. MCP Server

See → **[MCP_SERVER.md](MCP_SERVER.md)**

Transport: **stdio JSON-RPC**. Start: `graphyn mcp` or `python -m app.mcp.server`.

**15 tools:**

| Tool | Purpose |
|---|---|
| `list_nodes` | Discover node types, port types, compatible nodes |
| `generate_graph` | Build a GraphIR from a node list |
| `validate_graph` | Validate a GraphIR dict |
| `get_graph_schema` | Return GraphIR JSON Schema |
| `get_graph_capability_summary` | Aggregate capability flags for a graph |
| `get_event_schema` | Return event source schema |
| `execute_pipeline` | Run a pipeline, return run_id |
| `inspect_run` | Browse runs, logs, checkpoints, graph |
| `pause_run` / `resume_run` / `cancel_run` | Runtime control |
| `list_artifacts` | Query artifact store |
| `get_artifact_lineage` | Get lineage tree for an artifact |
| `replay_run` | Re-execute a prior run from its stored graph |
| `optimize_execution` | Analyze graph for hardware placement and wave recommendations |

---

## 11. Backend Services

See → **[BACKEND_CORE.md](BACKEND_CORE.md)**

| Service | File | Responsibility |
|---|---|---|
| `RunManager` | `run_manager.py` | Run lifecycle, pause/resume/cancel, checkpoints, resume state, artifact registration, provenance summary |
| `PipelineLogger` | `logger.py` | Structured JSON event emission; optional `Queue` for streaming to API |
| `ArtifactStore` | `artifact_store.py` | Content-addressed artifact registry; SHA-256 deduplication; 6 artifact types |
| `ProvenanceStore` | `provenance.py` | Lineage tracking; `get_lineage()` recursive tree; `find_by_run()`; `find_reproducible()` |
| `PipelineCache` | `pipeline_cache.py` | SHA-256 keyed WAV+manifest cache; respects `cacheable` flag from `IRCapabilityMetadata` |
| `IngestionService` | `ingestion.py` | URL and HuggingFace dataset download with progress events |
| `ProjectManager` | `project_manager.py` | Project lifecycle, versioning, taxonomy, quality reports |
| `QualityChecker` | `quality_checker.py` | Dataset quality analysis |
| `WebhookService` | `webhook.py` | Outbound webhook delivery |

---

## 12. Plugin Ecosystem

See → **[PLUGIN_GUIDE.md](PLUGIN_GUIDE.md)**

Plugins are **manifest-based packages** (directory + `plugin.toml` or `plugin.json`). The `PluginManager` is the single entry point.

**Plugin lifecycle:**

```
source string
    │
    ▼
PluginInstaller.resolve()     ← local path / git URL / HTTP archive / index name
    │
    ▼
load_manifest(plugin_dir)     ← parse + validate plugin.toml / plugin.json
    │
    ▼
PluginLoader.load()           ← check compat, check deps, import entry points
    │                            register node types via AutoDiscovery
    ▼
PluginStore.save()            ← persist PluginRecord to ~/.graphyn/plugins/
```

**`plugin.toml` required fields:** `name`, `version`, `description`, `author`, `platform_version`, `entry_points`.

---

## 13. Workspace Layout

```
workspace/                          ← GRAPHYN_PROJECT_DIR (default: ./workspace)
├── datasets/
│   ├── input/{label}/*.wav|mp3     ← source audio files
│   └── output/{project}/{version}/
│       ├── train|val|test/{label}/{hash}.wav
│       ├── labels.csv              ← id, path, label, split
│       └── metadata.json
├── runs/{run_id}/
│   ├── meta.json                   ← status, duration, node_stats
│   ├── logs.json                   ← structured event log
│   ├── graph.json                  ← GraphIR snapshot for this run
│   ├── resume_state.json           ← completed_nodes list (checkpoint=True)
│   └── checkpoints/node_{id}/
│       ├── *.wav
│       └── manifest.json
├── artifacts/{artifact_id}/
│   ├── record.json                 ← ArtifactRecord metadata
│   └── data/                       ← serialized artifact data
├── provenance/
│   ├── {artifact_id}.json          ← ProvenanceRecord per artifact
│   └── by_run/{run_id}.json        ← JSON array of artifact_ids
├── cache/{sha256}/
│   ├── *.wav
│   └── manifest.json
├── configs/templates/
│   └── {name}.graph.json           ← pipeline templates
└── plugins/                        ← legacy flat-file plugins (deprecated)

~/.graphyn/                         ← GRAPHYN_HOME (platform home)
└── plugins/
    ├── registry.json               ← PluginStore index
    └── {plugin_name}/              ← installed plugin packages
```

---

## 14. Configuration & Environment Variables

All configuration is read through `app/core/config.py`. Never read env vars directly.

| Variable | Default | Purpose |
|---|---|---|
| `GRAPHYN_HOME` | `~/.graphyn/` | Platform home: plugins, credentials |
| `GRAPHYN_PROJECT_DIR` | `workspace/` | Runtime data root |
| `GRAPHYN_API_TOKEN` | `""` | Bearer token; empty = no auth |
| `GRAPHYN_PLUGINS_DIR` | `plugins/` | Plugin install directory |
| `GRAPHYN_PLUGIN_AUTO_INSTALL` | `""` | Set `"1"` to auto-pip-install plugin deps |
| `GRAPHYN_PLUGIN_INDEX_URL` | `""` | Remote plugin index URL |

**Three-tier directory model:**

```
GRAPHYN_HOME (~/.graphyn/)          ← platform-level, shared across projects
GRAPHYN_PROJECT_DIR (workspace/)    ← project-level runtime data
Platform source tree (app/)         ← read-only, shipped with package
```

---

## 15. Running the Platform

```bash
# API server
venv/bin/uvicorn app.api.main:app --reload --port 8001

# CLI — run a pipeline
graphyn run --graph examples/01_wake_word/pipeline.graph.json

# CLI — migrate YAML to IR JSON
graphyn migrate --config my_pipeline.yaml

# MCP server (stdio)
venv/bin/python -m app.mcp.server
# or via CLI:
graphyn mcp

# Tests
venv/bin/pytest

# Python SDK
venv/bin/python -c "
from app.core.sdk import Pipeline, PipelineNode
p = Pipeline([PipelineNode('input', {'path': 'workspace/datasets/input/speech'})])
result = p.run()
print(result)
"
```

---

## Sub-Documents

| Document | Contents |
|---|---|
| [NODE_SYSTEM.md](NODE_SYSTEM.md) | Node base class, ports, config, retry, metadata, registry, AutoDiscovery |
| [NODE_CATALOGUE.md](NODE_CATALOGUE.md) | All 29 plugin nodes with ports and config fields |
| [PIPELINE_EXECUTION.md](PIPELINE_EXECUTION.md) | DAG executor, IR, caching, parallel/streaming/event-driven/resumable modes |
| [API_REFERENCE.md](API_REFERENCE.md) | All REST endpoints, request/response shapes, streaming protocol |
| [SDK_AND_CLI.md](SDK_AND_CLI.md) | SDK classes, CLI commands, examples |
| [MCP_SERVER.md](MCP_SERVER.md) | All 15 MCP tools, auth, error contract |
| [BACKEND_CORE.md](BACKEND_CORE.md) | RunManager, Logger, ArtifactStore, ProvenanceStore |
| [DATA_FLOW_AND_WORKSPACE.md](DATA_FLOW_AND_WORKSPACE.md) | Port data types, workspace layout, artifact format |
| [PLUGIN_GUIDE.md](PLUGIN_GUIDE.md) | Writing plugins, manifest schema, lifecycle |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Structural decisions, phase history |
| [KNOWN_ISSUES.md](KNOWN_ISSUES.md) | Active and resolved issues |
