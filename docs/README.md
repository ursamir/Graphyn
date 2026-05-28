# Graphyn Platform Documentation

This is a general-purpose AI/workflow execution platform. It exposes a REST API, a Python SDK, a CLI, and an MCP server for building, running, and managing data processing pipelines — primarily audio ML, but domain-agnostic via plugins.

This index is the entry point for all documentation. Start here, then follow the links to the topic you need.

---

## Documentation Map

| Document | What it covers |
|---|---|
| **[NODE_CATALOGUE.md](./NODE_CATALOGUE.md)** | **All 30 plugin nodes with ports, config fields, and capability flags** |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | System layers, component dependency graph, data flows, phase history |
| [NODE_SYSTEM.md](./NODE_SYSTEM.md) | Node base class, ports, config, metadata, capability fields, registry, AutoDiscovery |
| [PIPELINE_EXECUTION.md](./PIPELINE_EXECUTION.md) | Graph IR, DAG executor, caching, checkpoints, all execution modes |
| [BACKEND_CORE.md](./BACKEND_CORE.md) | RunJournal, RunControl, PipelineLogger, ArtifactSerializerRegistry, ArtifactStore, ProvenanceStore |
| [DOMAIN_SERVICES.md](./DOMAIN_SERVICES.md) | IngestionService, ProjectManager, QualityChecker, AudioSampleHandler |
| [API_REFERENCE.md](./API_REFERENCE.md) | All `/api/v1/` REST endpoints, request/response shapes, streaming protocol |
| [SDK_AND_CLI.md](./SDK_AND_CLI.md) | Python SDK (Pipeline, PipelineNode) and CLI reference |
| [MCP_SERVER.md](./MCP_SERVER.md) | MCP server: all 15 tools, auth, tool registry, error contract |
| [PLUGIN_GUIDE.md](./PLUGIN_GUIDE.md) | Writing and deploying plugins, manifest schema, lifecycle, quality checklist |
| [DATA_FLOW_AND_WORKSPACE.md](./DATA_FLOW_AND_WORKSPACE.md) | Port data types, workspace layout, artifact format, streaming protocol |
| [USERGUIDE.md](./USERGUIDE.md) | Complete user guide — SDK, CLI, API, MCP, nodes, plugins, advanced runtime |
| [KNOWN_ISSUES.md](./KNOWN_ISSUES.md) | Open issues and deferred items |
| [MASTER_ISSUE_REGISTRY.md](./MASTER_ISSUE_REGISTRY.md) | Full issue history — open and resolved |

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

### Validate a pipeline

```bash
venv/bin/python -m app.cli.main validate --graph my-pipeline.graph.json
```

---

## Key Concepts

**Node** — a self-contained processing unit with typed input/output ports and a Pydantic config model. All nodes extend `app.core.nodes.base.Node`.

**Pipeline** — a directed acyclic graph (DAG) of nodes. Defined in IR JSON (canonical) or via the Python SDK. YAML is a deprecated serialization format — use `graphyn migrate` to convert.

**Graph IR** — the canonical pipeline representation (`app/core/ir/`). Versioned, validated, runtime-agnostic JSON. All interfaces produce and consume `GraphIR` objects.

**RuntimeBackend** — the canonical execution entry point (`app/core/runtime_backend.py`). All interfaces call `get_backend().execute(graph)`. `LocalPythonBackend` (default) delegates to `orchestrator.run_pipeline_ir_async()`.

**Registry** — a singleton `NodeRegistry` populated at startup by `AutoDiscovery`. Maps node type strings to Python classes and metadata.

**Plugin** — a manifest-based package in `PluginPackage/`. All 30 production nodes are plugins. `app/core/nodes/` contains only framework infrastructure.

**PortDataType** — the base class for all data types that flow between node ports. Platform types live in `app/models/`. Plugin-domain types live in the plugin's `types.py`.

**ArtifactSerializerRegistry** — pluggable serializer registry (`app/core/artifact_serializer.py`). Platform storage code calls it; domain code registers handlers at startup. Keeps platform infrastructure free of domain knowledge.

**RunJournal / RunControl** — `run_journal.py` owns filesystem persistence for a single run; `run_control.py` owns the active run registry (in-process dict or Redis-backed). `run_manager.py` is a re-export shim for backward compatibility.

**Domain Services** — `app/domain/` contains `IngestionService`, `ProjectManager`, and `QualityChecker`. Platform code never imports from `app/domain/`.

**MCP Server** — exposes 15 tools via the Model Context Protocol (stdio transport), enabling AI agents to discover nodes, generate graphs, validate, execute pipelines, inspect artifacts, and control runs.

---

## Architecture in One Diagram

```
CLI / SDK / API / MCP Agent
        │
        ▼
get_backend().execute(graph)          ← canonical entry point (runtime_backend.py)
        │
        ▼
LocalPythonBackend
        └── orchestrator.run_pipeline_ir_async()
                │
                ├── planner.py         PipelineGraph — DAG build + topo sort + waves
                ├── node_executor.py   NodeExecutor — per-node lifecycle + retry
                ├── executor.py        ParallelExecutor — wave-based asyncio + ThreadPool
                ├── run_journal.py     RunManager — run dir + meta.json + resume state
                ├── run_control.py     Active run registry (pause/resume/cancel)
                ├── checkpoint.py      Per-node checkpoint read/write
                ├── pipeline_cache.py  SHA-256 keyed output cache
                └── artifact_store.py  Content-addressed artifact storage
                        │
                        └── artifact_serializer.py  ArtifactSerializerRegistry
                                └── audio_artifact_serializer.py  AudioSampleHandler (domain)

app/domain/                           ← domain services (never imported by platform)
├── ingestion.py                      URL + HuggingFace ingestion
├── project_manager.py                Project lifecycle
└── quality_checker.py                Dataset quality analysis

PluginPackage/
├── Audio/   (18 nodes)
└── Common/  (12 nodes)
```

---

## What Changed (Phase 9 — Post-Review Fix Pass)

| Old | New |
|---|---|
| `app/core/pipeline.py` (primary executor) | Re-export shim only — logic split into `orchestrator.py`, `planner.py`, `node_executor.py`, `checkpoint.py`, `executor.py` |
| `app/core/run_manager.py` (primary run service) | Re-export shim only — split into `run_journal.py` (persistence) + `run_control.py` (active registry) |
| Domain services in `app/core/` | Moved to `app/domain/ingestion.py`, `project_manager.py`, `quality_checker.py` |
| `AudioSample` imported directly by platform storage | `ArtifactSerializerRegistry` — platform calls registry; domain registers `AudioSampleHandler` at startup |
| `run_pipeline_ir()` called directly by all interfaces | `get_backend().execute()` — `RuntimeBackend` ABC is the canonical entry point |
| `_resolve_capability()` in `orchestrator.py` | Moved to `registry_runtime.py` (BC3) — shared by orchestrator and executor without circular coupling |
| `run_id` as 8-char hex | Full 32-char UUID4 hex |
| 29 plugin nodes | 30 plugin nodes (`model_builder` added to Common) |
