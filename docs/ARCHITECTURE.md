# Architecture

> Source of truth: `app/` source code.  
> Back to → [README.md](README.md)

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
│  10 routers         PipelineNode      14 commands   15 tools        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ all call get_backend().execute()
┌──────────────────────────────▼──────────────────────────────────────┐
│  BACKEND ABSTRACTION LAYER                                          │
│                                                                     │
│  app/core/runtime_backend.py                                        │
│  ├── RuntimeBackend (ABC)     canonical execution entry point       │
│  ├── LocalPythonBackend       default — delegates to orchestrator   │
│  ├── get_backend()            returns cached backend singleton      │
│  └── register_backend()       register custom backends              │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  EXECUTION LAYER                                                    │
│                                                                     │
│  app/core/orchestrator.py                                           │
│  ├── run_pipeline_ir()        synchronous shim                      │
│  └── run_pipeline_ir_async()  async implementation                  │
│                                                                     │
│  app/core/planner.py                                                │
│  ├── PipelineGraph            DAG builder + topo sort + waves       │
│  └── _ir_to_pipeline_config() IR → PipelineConfig conversion        │
│                                                                     │
│  app/core/node_executor.py                                          │
│  └── NodeExecutor             per-node lifecycle driver + retry     │
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
│  app/core/registry_runtime.py get_registry(), resolve_capability()  │
│                                                                     │
│  PluginPackage/Audio/         18 audio plugin nodes                 │
│  PluginPackage/Common/        12 common plugin nodes                │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  IR LAYER                                                           │
│                                                                     │
│  app/core/ir/models.py        GraphIR, IRNode, IREdge, IRMetadata   │
│  app/core/ir/loader.py        load_ir(), dump_ir(), version check   │
│  app/core/ir/yaml_shim.py     YAML → GraphIR (deprecated path)      │
│  app/core/ir/migrate.py       YAML file → .graph.json file          │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  BACKEND SERVICES LAYER                                             │
│                                                                     │
│  app/core/run_journal.py      RunManager: run dir + persistence     │
│  app/core/run_control.py      Active run registry (in-proc/Redis)   │
│  app/core/run_manager.py      Re-export shim (backward compat only) │
│  app/core/logger.py           PipelineLogger: structured events     │
│  app/core/pipeline_cache.py   PipelineCache: SHA-256 keyed          │
│  app/core/artifact_store.py   ArtifactStore: content-addressed      │
│  app/core/artifact_serializer.py  ArtifactSerializerRegistry:       │
│                               pluggable type handler interface       │
│  app/core/checkpoint.py       Per-node checkpoint read/write        │
│  app/core/provenance.py       ProvenanceStore: lineage tracking     │
│  app/core/webhook.py          Outbound webhook delivery             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  DOMAIN SERVICES LAYER                                              │
│                                                                     │
│  app/domain/ingestion.py      URL + HuggingFace ingestion           │
│  app/domain/project_manager.py  Project lifecycle                   │
│  app/domain/quality_checker.py  Dataset quality analysis            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  DATA MODELS LAYER                                                  │
│                                                                     │
│  app/models/audio_sample.py       AudioSample (PortDataType)        │
│  app/models/audio_artifact_serializer.py  AudioSampleHandler:       │
│                               domain-side ArtifactTypeHandler impl  │
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
  └── runtime_backend.py (get_backend().execute())
        └── orchestrator.py (run_pipeline_ir — LocalPythonBackend impl)
              ├── ir/loader.py (load_ir, dump_ir)
              │     └── ir/models.py (GraphIR, IRNode, IREdge)
              ├── registry_runtime.py (get_registry, resolve_capability)
              │     └── nodes/registry.py (NodeRegistry singleton)
              │           ├── nodes/base.py (Node)
              │           ├── nodes/metadata.py (NodeMetadata)
              │           └── nodes/catalogue.py (TypeCatalogue)
              ├── planner.py (PipelineGraph, _ir_to_pipeline_config)
              ├── node_executor.py (NodeExecutor)
              ├── executor.py (ParallelExecutor)
              │     └── registry_runtime.py (resolve_capability)  ← NOT orchestrator
              ├── pipeline_cache.py (PipelineCache.compute_key())
              ├── run_journal.py (RunManager)
              │     ├── artifact_store.py (ArtifactStore)
              │     └── provenance.py (ProvenanceStore)
              ├── run_control.py (active run registry)
              ├── checkpoint.py (per-node checkpoint read/write)
              ├── logger.py (PipelineLogger)
              ├── conditions.py (evaluate_condition)
              └── events.py (EventSource subclasses)

api/main.py
  ├── initialize_registry()              ← explicit startup call
  ├── register_audio_serializer()        ← domain serializer registration
  └── api/routers/*.py
        └── sdk.py (Pipeline, PipelineNode)

mcp/server.py
  ├── initialize_registry()              ← explicit startup call
  ├── register_audio_serializer()        ← domain serializer registration
  └── mcp/tool_registry.py
        └── mcp/handlers/*.py
              └── runtime_backend.py (get_backend().execute())
              └── registry_runtime.py (resolve_capability)  ← optimization handler

cli/main.py
  ├── initialize_registry()              ← explicit startup call
  ├── register_audio_serializer()        ← domain serializer registration
  └── sdk.py (Pipeline.from_json, Pipeline.from_yaml)
  └── runtime_backend.py (get_backend().execute())
  └── registry_runtime.py (resolve_capability)  ← inspect command

plugins/manager.py
  ├── plugins/installer.py
  ├── plugins/loader.py
  │     └── nodes/discovery.py (AutoDiscovery._import_file)
  ├── plugins/store.py
  └── plugins/index.py
```

**Key dependency rules:**
- `executor.py` and all MCP/CLI callers import `resolve_capability` from `registry_runtime`, not from `orchestrator`. This prevents intra-BC5 circular coupling.
- Platform code (`artifact_store`, `pipeline_cache`, `checkpoint`) never imports `AudioSample` directly — all type-specific logic goes through `ArtifactSerializerRegistry`.
- Platform code never imports from `app/domain/` — domain code registers into platform registries at startup.

---

## 3. Data Flow: Pipeline Execution

```
User Input (IR JSON / SDK nodes)
         │
         ▼
    load_ir(data)                    ← validates GraphIR schema + version
         │
         ▼
    get_backend().execute(graph)     ← canonical entry point (all interfaces)
         │
         ▼
    LocalPythonBackend.execute()
         └── orchestrator.run_pipeline_ir_async(graph, ...)
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
    register_active_run(run)         ← run_control.py — enables pause/resume/cancel
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
    ├── write checkpoint via checkpoint.py (if checkpoint=True)
    └── update resume_state.json
         │
         ▼
    run.save_metadata(stats)         ← writes final meta.json (status=completed)
    deregister_active_run(run_id)    ← run_control.py
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
         │   │   └── handler.compute_content_hash_input()  ← via ArtifactSerializerRegistry
         │   ├── check index.json for deduplication
         │   ├── serialize data to artifacts/{id}/data/
         │   │   ├── registered type → handler.serialize()  ← via ArtifactSerializerRegistry
         │   │   │   (e.g. "audio_samples" → AudioSampleHandler → WAV + manifest.json)
         │   │   └── unregistered type → data.json (JSON fallback)
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

**ArtifactSerializerRegistry** is the indirection layer that keeps platform infrastructure free of domain knowledge. At startup, `register_audio_serializer()` registers `AudioSampleHandler` for `"audio_samples"`. The registry is fail-open: unregistered types fall back to JSON serialization.

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
  ├── node.on_start()                 ← calls observer.on_node_start() internally
  ├── node.process(inputs)            ← or process_stream() for streaming
  ├── node.on_end()                   ← calls observer.on_node_end() internally
  └── retry on failure (RetryPolicy.wait_before_attempt(i))

  On failure:
  ├── node.on_error(exc)              ← calls observer.on_node_error() internally
  └── retry if attempts remaining

  NodeExecutor.teardown()
  └── node.teardown()                 ← release resources, reset setup state

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
         ├── initialize_registry()              ← idempotent; no-op on second call
         │   (app/core/nodes/__init__.py)
         │   ├── PluginManager.load_enabled_plugins()
         │   └── AutoDiscovery.run(
         │           nodes_dir="app/core/nodes",
         │           plugins_dir=plugins_home(),
         │           models_dir="app/models"
         │       )
         │       ├── scan app/core/nodes/*.py           ← framework files only
         │       ├── scan app/models/*.py               ← PortDataType → TypeCatalogue
         │       └── scan plugins/{name}/               ← manifest-based plugins
         │           └── PluginLoader.load(plugin_dir)
         │               ├── load_manifest()
         │               ├── check platform_version / min_python
         │               ├── DependencyChecker.verify()
         │               └── import entry_points → register node types
         │
         └── register_audio_serializer()        ← domain serializer registration
             (app/models/audio_artifact_serializer.py)
             └── ArtifactSerializerRegistry.register("audio_samples", AudioSampleHandler())

    For each Node subclass found:
    ├── derive node_type (explicit or PascalCase → snake_case)
    ├── check for duplicates (DuplicateNodeTypeError)
    ├── validate NodeMetadata presence
    ├── populate metadata.input_ports / output_ports
    └── NodeRegistry.register(node_type, cls, metadata)

    Test isolation: GRAPHYN_SKIP_PLUGIN_LOAD=1 skips plugin loading.
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
    copy resolved_dir → {plugins_home()}/{manifest.name}/
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
get_backend().execute(graph, ...)
  └── LocalPythonBackend → orchestrator.run_pipeline_ir_async(graph, ...)
         │
         ├── parallel=False (default)
         │   Sequential execution:
         │   for node_id in topo_order:
         │   ├── skip if in completed_nodes (resume)
         │   ├── skip if not in active_nodes (partial)
         │   ├── check pause/cancel (run.wait_if_paused)
         │   ├── assemble inputs + check conditions
         │   ├── cache check
         │   └── NodeExecutor.execute(inputs)
         │
         ├── parallel=True
         │   Wave-based parallel execution:
         │   for wave in execution_waves:
         │   └── ParallelExecutor.run_wave(wave, ...)
         │       └── asyncio.gather(*[_run_node(id) for id in wave])
         │           └── sync nodes → loop.run_in_executor(shared ThreadPool)
         │               streaming nodes → await execute_stream()
         │
         ├── streaming=True
         │   Streaming nodes use process_stream() async generator.
         │   Results collected into lists via _collect_stream().
         │
         ├── event_driven=True
         │   Source nodes have event_trigger in IRNode.
         │   EventSource.watch() yields payloads.
         │   Pipeline re-executes on each event.
         │   (Mutually exclusive with parallel=True)
         │
         └── resume_run_id=X
             Load resume_state.json from prior run.
             Validate graph_hash matches — raises ResumeError if changed.
             Skip completed_nodes, load their outputs from checkpoints.
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
- YAML input → `DeprecationWarning` + auto-convert via `yaml_shim.py`. Use `graphyn migrate` to convert YAML files to `.graph.json`.

---

## 10. Security Boundaries

| Boundary | Enforcement |
|---|---|
| `InputNode.path` | Must be inside `workspace/datasets/input/` (resolved path check) |
| `ExportNode.output` | Must be inside `workspace/datasets/output/` |
| `ExportNode.project` / `version` | Must match `^[a-zA-Z0-9_\-]+$` |
| API path components | `_safe_child()` on all user-supplied path segments |
| Template names | `^[A-Za-z0-9_-]+$` |
| Run IDs | ASCII alphanumeric only (regex validated) |
| Upload filenames | Replaced with timestamped names |
| Artifact IDs | `^[A-Za-z0-9_-]+$` |
| Condition expressions | AST whitelist: comparisons, boolean ops, `len()`, `output["key"]` only |
| API auth | Optional Bearer token via `GRAPHYN_API_TOKEN` |
| MCP auth | Token at `arguments._meta.auth_token` |
| Plugin sources | `GRAPHYN_PLUGIN_ALLOWED_SOURCES` — comma-separated URL prefix allowlist; empty = allow all |
| Checkpoint node IDs | Null byte rejection + path traversal guard via `os.path.abspath` prefix check |
| Webhook DNS | Resolves once, connects to IP directly with `Host` header (DNS rebinding fix) |

---

## 11. Phase History

| Phase | Key Features Added |
|---|---|
| Phase 1 | Node base system, typed ports, NodeRegistry, AutoDiscovery, SISO wrapper |
| Phase 2 | Graph IR (v1.0), IR loader/validator, YAML shim + migration, SDK, CLI |
| Phase 3 | Parallel executor (wave-based), streaming nodes, event-driven execution, conditional edges, partial execution, resumable pipelines, runtime control (pause/resume/cancel) |
| Phase 4 | ArtifactStore (content-addressed), ProvenanceStore (lineage), ArtifactCollection, artifact replay |
| Phase 5 | Plugin ecosystem: PluginManager, PluginInstaller, PluginLoader, PluginStore, PluginIndexClient, manifest-based packages, `plugin.toml` schema |
| Phase 6–8 | 30 plugin nodes across `PluginPackage/Audio/` (18) and `PluginPackage/Common/` (12) — all phases complete |
| Phase 9 | Post-review fix pass — 104 files reviewed, all confirmed bugs fixed. Architecture splits: `pipeline.py` → `orchestrator.py` / `planner.py` / `node_executor.py` / `checkpoint.py` / `executor.py`; `run_manager.py` → `run_journal.py` / `run_control.py`; domain services → `app/domain/`; `ArtifactSerializerRegistry` added; `RuntimeBackend` ABC added; `registry_runtime.py` added. |
