# Architecture

> Source of truth: `app/` source code.  
> Back to → [OVERVIEW.md](OVERVIEW.md)

---

## Table of Contents

1. [System Layers](#1-system-layers)
2. [Component Dependency Graph](#2-component-dependency-graph)
3. [Data Flow: Pipeline Execution](#3-data-flow-pipeline-execution)
4. [Data Flow: Artifact Lifecycle](#4-data-flow-artifact-lifecycle)
5. [Node Lifecycle](#5-node-lifecycle)
6. [Registry Bootstrap Sequence](#6-registry-bootstrap-sequence)
7. [Plugin Load Sequence](#7-plugin-load-sequence)
8. [Execution Modes](#8-execution-modes)
9. [IR Version Strategy](#9-ir-version-strategy)
10. [Security Boundaries](#10-security-boundaries)
11. [Phase History](#11-phase-history)

---

## 1. System Layers

```
┌─────────────────────────────────────────────────────────────────────┐
│  INTERFACE LAYER                                                    │
│                                                                     │
│  app/api/          app/core/sdk.py    app/cli/      app/mcp/        │
│  FastAPI REST       Pipeline class    argparse CLI  stdio JSON-RPC  │
│  10 routers         PipelineNode      14 commands   14 tools        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ all call run_pipeline_ir()
┌──────────────────────────────▼──────────────────────────────────────┐
│  EXECUTION LAYER                                                    │
│                                                                     │
│  app/core/pipeline.py                                               │
│  ├── run_pipeline_ir()        primary async entry point             │
│  ├── run_pipeline_ir_async()  async implementation                  │
│  ├── PipelineGraph            DAG builder + topo sort               │
│  ├── NodeExecutor             per-node lifecycle driver             │
│  └── _ir_to_pipeline_config() IR → PipelineConfig conversion        │
│                                                                     │
│  app/core/executor.py                                               │
│  └── ParallelExecutor         wave-based asyncio + ThreadPool       │
│                                                                     │
│  app/core/conditions.py       safe condition expression evaluator   │
│  app/core/events.py           FileWatcher / Timer / Queue sources   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  NODE LAYER                                                         │
│                                                                     │
│  app/core/nodes/base.py       Node base class + SISO wrapper        │
│  app/core/nodes/ports.py      InputPort / OutputPort / PortDataType │
│  app/core/nodes/config.py     NodeConfig (Pydantic base)            │
│  app/core/nodes/metadata.py   NodeMetadata + capability fields      │
│  app/core/nodes/retry.py      RetryPolicy (exponential backoff)     │
│  app/core/nodes/observers.py  NodeObserver / LoggingObserver        │
│  app/core/nodes/registry.py   NodeRegistry singleton                │
│  app/core/nodes/discovery.py  AutoDiscovery scanner                 │
│  app/core/nodes/catalogue.py  TypeCatalogue (FQN → type)            │
│  app/core/nodes/compat.py     CompatibilityChecker                  │
│  app/core/nodes/errors.py     Exception hierarchy                   │
│                                                                     │
│  PluginPackage/Audio/         18 audio plugin nodes                 │
│  PluginPackage/Common/        11 common plugin nodes                │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  IR LAYER                                                           │
│                                                                     │
│  app/core/ir/models.py        GraphIR, IRNode, IREdge, IRMetadata   │
│  app/core/ir/loader.py        load_ir(), dump_ir(), version check   │
│  app/core/ir/yaml_shim.py     YAML → GraphIR conversion             │
│  app/core/ir/migrate.py       YAML file → .graph.json file          │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  BACKEND SERVICES LAYER                                             │
│                                                                     │
│  app/core/run_manager.py      RunManager: lifecycle + control       │
│  app/core/logger.py           PipelineLogger: structured events     │
│  app/core/pipeline_cache.py   PipelineCache: SHA-256 keyed          │
│  app/core/artifact_store.py   ArtifactStore: content-addressed      │
│  app/core/provenance.py       ProvenanceStore: lineage tracking     │
│  app/core/ingestion.py        URL + HuggingFace ingestion           │
│  app/core/project_manager.py  Project lifecycle                     │
│  app/core/quality_checker.py  Dataset quality analysis              │
│  app/core/webhook.py          Outbound webhook delivery             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  DATA MODELS LAYER                                                  │
│                                                                     │
│  app/models/audio_sample.py       AudioSample (PortDataType)        │
│  app/models/feature_array.py      FeatureArray (PortDataType)       │
│  app/models/tensor_batch.py       TensorBatch (PortDataType)        │
│  app/models/model_artifact.py     ModelArtifact (PortDataType)      │
│  app/models/tflite_artifact.py    TFLiteArtifact (PortDataType)     │
│  app/models/prediction_result.py  PredictionResult (PortDataType)   │
│  app/models/deployment_artifact.py DeploymentArtifact               │
│  app/models/data_sample.py        DataSample (base)                 │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  PLUGIN LAYER                                                       │
│                                                                     │
│  app/core/plugins/manager.py      PluginManager (single entry point)│
│  app/core/plugins/installer.py    PluginInstaller (source resolver) │
│  app/core/plugins/loader.py       PluginLoader (manifest + register)│
│  app/core/plugins/store.py        PluginStore (persistence)         │
│  app/core/plugins/manifest.py     PluginManifest (Pydantic model)   │
│  app/core/plugins/index.py        PluginIndexClient (remote index)  │
│  app/core/plugins/dependencies.py DependencyChecker                 │
│  app/core/plugins/errors.py       Plugin exception hierarchy        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Dependency Graph

```
sdk.py
  └── pipeline.py (run_pipeline_ir)
        ├── ir/loader.py (load_ir, dump_ir)
        │     └── ir/models.py (GraphIR, IRNode, IREdge)
        ├── nodes/registry.py (NodeRegistry singleton)
        │     ├── nodes/base.py (Node)
        │     ├── nodes/metadata.py (NodeMetadata)
        │     └── nodes/catalogue.py (TypeCatalogue)
        ├── executor.py (ParallelExecutor)
        ├── pipeline_cache.py (PipelineCache)
        ├── run_manager.py (RunManager)
        │     ├── artifact_store.py (ArtifactStore)
        │     └── provenance.py (ProvenanceStore)
        ├── logger.py (PipelineLogger)
        ├── conditions.py (evaluate_condition)
        └── events.py (EventSource subclasses)

api/main.py
  └── api/routers/*.py
        └── sdk.py (Pipeline, PipelineNode)

mcp/server.py
  └── mcp/tool_registry.py
        └── mcp/handlers/*.py
              └── sdk.py / pipeline.py / run_manager.py / ...

cli/main.py
  └── sdk.py (Pipeline.from_json, Pipeline.from_yaml)
  └── pipeline.py (run_pipeline_ir)

plugins/manager.py
  ├── plugins/installer.py
  ├── plugins/loader.py
  │     └── nodes/discovery.py (AutoDiscovery._import_file)
  ├── plugins/store.py
  └── plugins/index.py
```

---

## 3. Data Flow: Pipeline Execution

```
User Input (IR JSON / YAML / SDK nodes)
         │
         ▼
    load_ir(data)                    ← validates GraphIR schema + version
         │
         ▼
    _ir_to_pipeline_config(graph)    ← GraphIR → PipelineConfig (NodeSpec + EdgeSpec)
         │
         ▼
    PipelineGraph(config)
    ├── instantiate Node objects from NodeSpecs
    ├── validate edges via CompatibilityChecker
    ├── topological sort (Kahn's algorithm)
    └── compute execution waves (level-based BFS)
         │
         ▼
    RunManager()                     ← creates run directory, writes meta.json
    run.save_graph_ir(dump_ir(graph))← writes graph.json, computes graph_hash
    register_active_run(run)         ← enables pause/resume/cancel via API
         │
         ▼
    For each wave (parallel) or node (sequential):
    ├── assemble inputs from upstream node_outputs
    ├── evaluate edge conditions (conditions.py)
    ├── check PipelineCache (SHA-256 key)
    │   ├── HIT  → use cached outputs
    │   └── MISS → NodeExecutor.execute(inputs)
    │              ├── node.setup() [once]
    │              ├── node.on_start()
    │              ├── node.process(inputs)  ← or process_stream()
    │              ├── node.on_end()
    │              └── retry on failure (RetryPolicy)
    ├── save to PipelineCache (if cacheable=True)
    ├── write checkpoint (if checkpoint=True)
    └── update resume_state.json
         │
         ▼
    run.save_metadata(stats)         ← writes final meta.json (status=completed)
    deregister_active_run(run_id)
         │
         ▼
    ArtifactCollection(artifacts, run_id, raw_outputs)
```

---

## 4. Data Flow: Artifact Lifecycle

```
Node produces output
         │
         ▼
    run_manager.register_artifact(
        node_id, node_type, artifact_type, data
    )
         │
         ├── ArtifactStore.register()
         │   ├── compute SHA-256 content_hash
         │   ├── check index.json for deduplication
         │   ├── serialize data to artifacts/{id}/data/
         │   │   ├── audio_samples → WAV files + manifest.json
         │   │   └── others       → data.json
         │   ├── write artifacts/{id}/record.json (ArtifactRecord)
         │   └── update artifacts/index.json
         │
         └── ProvenanceStore.record()
             ├── write provenance/{artifact_id}.json (ProvenanceRecord)
             └── append to provenance/by_run/{run_id}.json
         │
         ▼
    ArtifactRecord returned
    (artifact_id, content_hash, artifact_type, node_id, run_id, data_path)
         │
         ▼
    Later: ProvenanceStore.get_lineage(artifact_id)
    ├── load provenance/{artifact_id}.json
    ├── recursively resolve input_artifact_ids
    └── return tree dict (never raises — error nodes for missing records)
```

---

## 5. Node Lifecycle

```
Node instantiation
  Node.__init__(config, seed, observer)
  └── Config.model_validate(config)   ← Pydantic validation

Pipeline execution (per node):
  NodeExecutor.setup()
  └── node.setup()                    ← one-time init (load models, open files)

  For each execution (with retry):
  ├── node.on_start()
  ├── observer.on_node_start(node_type, run_id)
  ├── node.process(inputs)            ← or process_stream() for streaming
  ├── node.on_end()
  └── observer.on_node_end(node_type, run_id, duration, counts)

  On failure:
  ├── node.on_error(exc)
  ├── observer.on_node_error(node_type, run_id, exc)
  └── retry if attempts remaining (RetryPolicy.wait_before_attempt(i))

  NodeExecutor.teardown()
  └── node.teardown()                 ← release resources

SISO shorthand (auto-detected by __init_subclass__):
  process(self, data)                 ← single-value signature
  ↓ wrapped to:
  process(self, inputs: dict)         ← unpacks inputs["input"], repacks {"output": result}
```

---

## 6. Registry Bootstrap Sequence

```
Application startup (API / CLI / MCP)
         │
         ▼
    registry_runtime.get_registry()
    ├── (first call) creates NodeRegistry singleton
    ├── PluginManager.load_enabled_plugins()   ← load enabled plugins first
    └── AutoDiscovery.run(
            nodes_dir="app/core/nodes",
            plugins_dir=plugins_home(),
            models_dir="app/models"
        )
        ├── scan app/core/nodes/*.py           ← framework files only (no node impls)
        ├── scan app/models/*.py               ← PortDataType subclasses → TypeCatalogue
        └── scan plugins/{name}/               ← manifest-based plugins (29 nodes)
            └── PluginLoader.load(plugin_dir)
                ├── load_manifest()
                ├── check platform_version
                ├── check min_python
                ├── DependencyChecker.verify()
                └── import entry_points → register node types

    For each Node subclass found:
    ├── derive node_type (explicit or PascalCase → snake_case)
    ├── check for duplicates (DuplicateNodeTypeError)
    ├── validate NodeMetadata presence
    ├── populate metadata.input_ports / output_ports from class declarations
    └── NodeRegistry.register(node_type, cls, metadata)
```

---

## 7. Plugin Load Sequence

```
PluginManager.install(source)
         │
         ▼
    PluginInstaller.resolve(source)
    ├── local path  → copy as-is
    ├── git+URL     → git clone to temp dir
    ├── http(s) URL → download + extract archive
    └── name[==ver] → PluginIndexClient.lookup() → download URL → extract
         │
         ▼
    load_manifest(resolved_dir)
    ├── try plugin.toml (tomllib)
    ├── fallback plugin.json
    └── PluginManifest.model_validate(data)
         │
         ▼
    copy resolved_dir → {plugins_dir}/{manifest.name}/
         │
         ▼
    PluginLoader.load(install_path)
    ├── validate manifest
    ├── check platform_version specifier
    ├── check min_python
    ├── DependencyChecker.verify(dependencies)
    │   └── (if GRAPHYN_PLUGIN_AUTO_INSTALL=1) pip install missing deps
    └── for each entry_point:
        ├── AutoDiscovery._import_file(path)
        └── AutoDiscovery._process_module(module)
            ├── register PortDataType subclasses → TypeCatalogue
            └── register Node subclasses → NodeRegistry
         │
         ▼
    PluginStore.save(PluginRecord)
    └── write ~/.graphyn/plugins/registry.json
```

---

## 8. Execution Modes

```
run_pipeline_ir_async(graph, ...)
         │
         ├── parallel=False (default)
         │   Sequential execution:
         │   for node_id in topo_order:
         │   ├── skip if in completed_nodes (resume)
         │   ├── skip if not in active_nodes (partial)
         │   ├── check pause/cancel (run_manager.wait_if_paused)
         │   ├── assemble inputs + check conditions
         │   ├── cache check
         │   └── NodeExecutor.execute(inputs)
         │
         ├── parallel=True
         │   Wave-based parallel execution:
         │   for wave in execution_waves:
         │   └── ParallelExecutor.run_wave(wave, ...)
         │       └── asyncio.gather(*[_run_node(id) for id in wave])
         │           └── sync nodes → loop.run_in_executor(ThreadPool)
         │               streaming nodes → await execute_stream()
         │
         ├── streaming=True
         │   Streaming nodes use process_stream() async generator
         │   Results collected into lists via _collect_stream_parallel()
         │
         ├── event_driven=True
         │   Source nodes have event_trigger in IRNode
         │   EventSource.watch() yields payloads
         │   Pipeline re-executes on each event
         │
         └── resume_run_id=X
             Load resume_state.json from prior run
             Skip completed_nodes, load their outputs from checkpoints
```

---

## 9. IR Version Strategy

| Version | Changes | Backward Compat |
|---|---|---|
| `1.0` | Initial IR format | Accepted; missing fields default to `None` |
| `1.1` | Added `IREdge.condition`, `IRNode.event_trigger` | Accepted; `1.0` docs treated as `1.1` |

**Rules:**
- Major version mismatch → `IRVersionError` (hard fail)
- Minor version > supported → `UserWarning` (soft warn, continue)
- YAML input → `DeprecationWarning` + auto-convert via `yaml_shim.py`

---

## 10. Security Boundaries

| Boundary | Enforcement |
|---|---|
| `InputNode.path` | Must be inside `workspace/datasets/input/` (resolved path check) |
| `ExportNode.output` | Must be inside `workspace/datasets/output/` |
| `ExportNode.project` / `version` | Must match `^[a-zA-Z0-9_\-]+$` |
| API path components | `_safe_child()` on all user-supplied path segments |
| Template names | `^[A-Za-z0-9_-]+$` |
| Run IDs | Alphanumeric only |
| Upload filenames | Replaced with timestamped names |
| Artifact IDs | `^[A-Za-z0-9_-]+$` |
| Condition expressions | AST whitelist: comparisons, boolean ops, `len()`, `output["key"]` only |
| API auth | Optional Bearer token via `GRAPHYN_API_TOKEN` |
| MCP auth | Token at `arguments._meta.auth_token` |

---

## 11. Phase History

| Phase | Key Features Added |
|---|---|
| Phase 1 | Node base system, typed ports, NodeRegistry, AutoDiscovery, SISO wrapper |
| Phase 2 | Graph IR (v1.0), IR loader/validator, YAML shim + migration, SDK, CLI |
| Phase 3 | Parallel executor (wave-based), streaming nodes, event-driven execution, conditional edges, partial execution, resumable pipelines, runtime control (pause/resume/cancel) |
| Phase 4 | ArtifactStore (content-addressed), ProvenanceStore (lineage), ArtifactCollection, `run_with_manager()`, artifact replay |
| Phase 5 | Plugin ecosystem: PluginManager, PluginInstaller, PluginLoader, PluginStore, PluginIndexClient, manifest-based packages, `plugin.toml` schema |
| Phase 6–8 | 29 plugin nodes across `PluginPackage/Audio/` and `PluginPackage/Common/` — all phases complete |
