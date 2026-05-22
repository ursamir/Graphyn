# System Design Document — Graphyn Pipeline Engine

> **Source of truth:** the `app/` source tree and `PluginPackage/`.  
> Every claim in this document is derived directly from the implementation.  
> Cross-reference: `docs/DEEP_TECH_REVIEW.md` for known issues.

---

## Table of Contents

1. [Purpose and Scope](#1-purpose-and-scope)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Layer-by-Layer Breakdown](#3-layer-by-layer-breakdown)
   - 3.1 [Configuration Layer](#31-configuration-layer--appcoreconfpy)
   - 3.2 [Data Models Layer](#32-data-models-layer--appmodels)
   - 3.3 [Node System Layer](#33-node-system-layer--appcorenodesbase)
   - 3.4 [Graph IR Layer](#34-graph-ir-layer--appcoreir)
   - 3.5 [Execution Layer](#35-execution-layer--appcorepipelinepy)
   - 3.6 [Backend Services Layer](#36-backend-services-layer)
   - 3.7 [Plugin Ecosystem Layer](#37-plugin-ecosystem-layer--appcorePlugins)
   - 3.8 [Interface Layer](#38-interface-layer)
   - 3.9 [Plugin Nodes](#39-plugin-nodes--pluginpackage)
4. [Cross-Cutting Concerns](#4-cross-cutting-concerns)
5. [Data Flow Walkthroughs](#5-data-flow-walkthroughs)
6. [Architectural Patterns](#6-architectural-patterns)
7. [Extension Points](#7-extension-points)
8. [Coupling and Abstraction Boundaries](#8-coupling-and-abstraction-boundaries)
9. [Lifecycle Flows](#9-lifecycle-flows)
10. [Inconsistencies Between Design Intent and Implementation](#10-inconsistencies-between-design-intent-and-implementation)


---

## 1. Purpose and Scope

Graphyn is a general-purpose AI/workflow pipeline execution platform. Its core abstraction is a **directed acyclic graph (DAG) of typed processing nodes**. Each node declares typed input and output ports, a Pydantic configuration model, and a `process()` method. Nodes are connected by edges; the engine validates type compatibility, resolves execution order, and drives each node through a defined lifecycle.

The platform exposes four independent interfaces that all share the same `app/core/` execution engine:

| Interface | Entry Point | Transport |
|---|---|---|
| REST API | `app/api/main.py` | HTTP/JSON via FastAPI |
| Python SDK | `app/core/sdk.py` | In-process Python calls |
| CLI | `app/cli/main.py` | argparse, subprocess |
| MCP Server | `app/mcp/server.py` | stdio JSON-RPC |

All 29 processing nodes live in `PluginPackage/` as self-contained plugin packages. None are baked into the core engine — the engine is domain-agnostic.

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  INTERFACE LAYER                                                     │
│  app/api/  ·  app/core/sdk.py  ·  app/cli/  ·  app/mcp/             │
└────────────────────────┬─────────────────────────────────────────────┘
                         │ all converge on run_pipeline_ir()
┌────────────────────────▼─────────────────────────────────────────────┐
│  EXECUTION LAYER                                                     │
│  pipeline.py  ·  executor.py  ·  conditions.py  ·  events.py        │
└────────────────────────┬─────────────────────────────────────────────┘
                         │ instantiates and drives
┌────────────────────────▼─────────────────────────────────────────────┐
│  NODE SYSTEM LAYER                                                   │
│  nodes/base.py  ·  ports.py  ·  config.py  ·  registry.py           │
│  discovery.py  ·  metadata.py  ·  compat.py  ·  retry.py            │
└────────────────────────┬─────────────────────────────────────────────┘
                         │ describes graphs via
┌────────────────────────▼─────────────────────────────────────────────┐
│  IR LAYER                                                            │
│  ir/models.py  ·  ir/loader.py  ·  ir/yaml_shim.py  ·  ir/migrate.py│
└────────────────────────┬─────────────────────────────────────────────┘
                         │ persists state via
┌────────────────────────▼─────────────────────────────────────────────┐
│  BACKEND SERVICES LAYER                                              │
│  run_manager.py  ·  logger.py  ·  pipeline_cache.py                 │
│  artifact_store.py  ·  provenance.py  ·  ingestion.py               │
│  project_manager.py  ·  webhook.py  ·  quality_checker.py           │
└────────────────────────┬─────────────────────────────────────────────┘
                         │ typed data via
┌────────────────────────▼─────────────────────────────────────────────┐
│  DATA MODELS LAYER                                                   │
│  app/models/  — AudioSample, FeatureArray, ModelArtifact, etc.       │
└────────────────────────┬─────────────────────────────────────────────┘
                         │ extended by
┌────────────────────────▼─────────────────────────────────────────────┐
│  PLUGIN ECOSYSTEM LAYER                                              │
│  app/core/plugins/  — PluginManager, PluginLoader, PluginStore, etc. │
│  PluginPackage/Audio/ (18 nodes)  ·  PluginPackage/Common/ (11 nodes)│
└──────────────────────────────────────────────────────────────────────┘
```

The dependency direction is strictly top-down. The interface layer depends on the execution layer; the execution layer depends on the node system and IR layers; backend services are used by the execution layer but do not depend on it. The plugin ecosystem layer is a side-channel that populates the node registry at startup.


---

## 3. Layer-by-Layer Breakdown

### 3.1 Configuration Layer — `app/core/config.py`

**Role:** Single source of truth for all filesystem paths and environment variable resolution. No other module reads `os.environ` directly for path or auth configuration.

**Responsibilities:**
- Resolve the three-tier directory model from environment variables.
- Provide typed `Path`-returning functions for every workspace subdirectory.
- Expose `api_token()` for auth configuration.

**Three-tier model:**

```
Tier 1 — GRAPHYN_HOME (~/.graphyn/)
    Platform-level state: plugin registry, installed plugin packages.
    Shared across all projects on the machine.

Tier 2 — GRAPHYN_PROJECT_DIR (./workspace/ resolved to absolute)
    Project-level runtime data: runs/, artifacts/, provenance/,
    cache/, datasets/, webhooks.json.

Tier 3 — Source tree (read-only)
    Built-in node definitions, templates, schemas.
```

**Key functions and their return values:**

| Function | Returns | Env Override |
|---|---|---|
| `graphyn_home()` | `~/.graphyn/` | `GRAPHYN_HOME` |
| `plugins_home()` | `~/.graphyn/plugins/installed/` | `GRAPHYN_PLUGINS_DIR` |
| `plugin_registry_path()` | `~/.graphyn/plugins/registry.json` | — |
| `project_dir()` | `./workspace/` (resolved absolute) | `GRAPHYN_PROJECT_DIR` |
| `runs_dir()` | `{project_dir}/runs/` | — |
| `artifacts_dir()` | `{project_dir}/artifacts/` | — |
| `cache_dir()` | `{project_dir}/cache/` | — |
| `provenance_dir()` | `{project_dir}/provenance/` | — |
| `datasets_input_dir()` | `{project_dir}/datasets/input/` | — |
| `datasets_output_dir()` | `{project_dir}/datasets/output/` | — |
| `api_token()` | `""` or token string | `GRAPHYN_API_TOKEN` |

**Actual behavior vs. intent:** `project_dir()` calls `Path(...).resolve()`, making it absolute. However, `app/api/routers/system.py` and `app/api/routers/pipelines.py` bypass this module and use hardcoded `Path("workspace")` — a known inconsistency documented in the tech review.

**Dependencies:** Only `os`, `pathlib`. No imports from the rest of the codebase. This is the only module with zero internal dependencies.


---

### 3.2 Data Models Layer — `app/models/`

**Role:** Defines the typed data objects that flow between nodes through ports. Every model is a `PortDataType` subclass (itself a Pydantic `BaseModel`), which makes it automatically discoverable by `AutoDiscovery` and registerable in `TypeCatalogue`.

**Files and their types:**

| File | Type | Description |
|---|---|---|
| `audio_sample.py` | `AudioSample` | A single audio clip: `data` (numpy float32 array), `sample_rate`, `path`, `label`, `metadata` |
| `feature_array.py` | `FeatureArray` | A 2D numpy array of extracted features (e.g. mel spectrogram): `data`, `feature_type`, `source_path`, `metadata` |
| `tensor_batch.py` | `TensorBatch` | A batch of tensors for ML inference: `data` (numpy), `labels`, `metadata` |
| `model_artifact.py` | `ModelArtifact` | A trained model reference: `model_path`, `labels`, `history`, `metrics` |
| `tflite_artifact.py` | `TFLiteArtifact` | A TFLite model: `model_path`, `labels`, `input_shape`, `quantized` |
| `prediction_result.py` | `PredictionResult` | Classification output: `source_path`, `predicted_label`, `probabilities`, `metadata` |
| `deployment_artifact.py` | `DeploymentArtifact` | A packaged deployment bundle: `package_path`, `target_platform`, `metadata` |
| `data_sample.py` | `DataSample` | Generic base for non-audio samples |

**Design pattern:** All models use `ConfigDict(arbitrary_types_allowed=True)` because they carry numpy arrays, which Pydantic cannot natively validate. The `PortDataType` base class inherits this setting.

**How data flows:** When a node's `process()` returns `{"output": [AudioSample(...), ...]}`, the executor stores this dict in `node_outputs[node_id]`. The next node's inputs are assembled by looking up `node_outputs[src_id][src_port]` for each incoming edge. The data objects are passed by reference — no copying occurs unless a node explicitly calls `copy.deepcopy()` (as `SpeechEnhancerNode` does).

**Note on missing models:** Several `__pycache__` entries reference `dataset_artifact.py`, `embedding_vector.py`, and `experiment_artifact.py` that do not exist as source files. These were likely removed or renamed but their compiled bytecode remains. Any code that imports them will fail at runtime.


---

### 3.3 Node System Layer — `app/core/nodes/`

This is the most foundational layer of the engine. It defines what a node is, how nodes are described, how they are discovered, and how they are connected.

#### 3.3.1 `base.py` — The Node Base Class

**Role:** Abstract base class for all processing units in the system.

**Key design decisions:**

1. **Generic typing** — `Node[InputT, OutputT]` uses Python generics for documentation purposes, but the actual `process()` signature uses `dict[str, Any]` at runtime. The generics are not enforced.

2. **SISO wrapper** — The `__init_subclass__` hook calls `_maybe_wrap_siso()` on every subclass at class definition time. If a subclass defines `process(self, data)` (second parameter not named `"inputs"`), the wrapper transparently converts it to the canonical `process(self, inputs: dict) -> dict` signature. This allows simple nodes to avoid boilerplate dict unpacking. The original method is stored as `process.__wrapped__` for testing.

3. **Lifecycle hooks** — `setup()`, `on_start()`, `on_end()`, `on_error()`, `teardown()` are no-ops by default. Subclasses override only what they need. The `on_start/on_end/on_error` hooks also forward to an optional `observer` object.

4. **Streaming** — `process_stream()` is an async generator. The default implementation wraps `process()` as a single-item generator using `loop.run_in_executor()` to avoid blocking the event loop. Nodes that produce incremental output override this method.

5. **Config validation** — The inner `Config(NodeConfig)` class is a Pydantic model with `extra="forbid"`. Config is validated at `__init__` time via `Config.model_validate(config)`.

**SISO detection logic:**
```
If cls defines process() AND second param name != "inputs":
    → wrap as SISO: inputs["input"] → data → process(data) → {"output": result}
If cls defines process() AND second param name == "inputs":
    → leave as multi-port
```

**Observer pattern:** The `observer` field accepts any object with `on_node_start`, `on_node_end`, `on_node_error` methods. Failures in observer calls are silently swallowed — observers must never crash a node.

#### 3.3.2 `ports.py` — Port Descriptors

**Role:** Defines `InputPort`, `OutputPort`, and `PortDataType`.

- `InputPort` has: `name`, `data_type` (Python type or `None`), `cardinality` (`"single"` or `"multi"`), `required` (bool), `description`.
- `OutputPort` has: `name`, `data_type`, `description`.
- `PortDataType` is a Pydantic `BaseModel` base class. Subclassing it is the contract for creating a type that can flow through ports.
- Both port types validate `data_type` at declaration time — non-type values raise `ValueError` immediately.
- `cardinality="multi"` means the port receives a `list` of values from multiple upstream connections. The executor handles this by appending to a list rather than overwriting.

#### 3.3.3 `config.py` — NodeConfig Base

**Role:** Pydantic base class for all node configuration models.

- `extra="forbid"` — unknown fields raise `ValidationError` at construction time, preventing silent misconfiguration.
- `frozen=False` — configs are mutable after construction (intentional, for runtime overrides).
- `populate_by_name=True` — allows field population by field name (not just alias).

#### 3.3.4 `metadata.py` — NodeMetadata

**Role:** Describes a node's identity, capabilities, and port schemas for API responses and registry queries.

**Fields:** `node_type`, `label`, `description`, `category`, `version`, `tags`, `input_ports`, `output_ports`, plus 10 capability fields: `requires_gpu`, `supports_cpu`, `supports_edge`, `deterministic`, `cacheable`, `streaming_support`, `realtime_support`, `memory_requirements`, `dependency_requirements`, `batch_support`.

**How it's populated:** `AutoDiscovery._register_node()` copies port declarations from the class's `input_ports`/`output_ports` ClassVars into `metadata.input_ports`/`metadata.output_ports` as serializable dicts (using `_port_to_dict()`). This means the metadata stored in the registry is a snapshot taken at discovery time — it does not update if the class is modified after registration.


#### 3.3.5 `registry.py` — NodeRegistry

**Role:** Thread-safe singleton mapping `node_type` strings to Node subclasses and their metadata.

**Internal state:**
- `_classes: dict[str, type]` — maps `node_type` → Node subclass
- `_metadata: dict[str, NodeMetadata]` — maps `node_type` → NodeMetadata
- `_lock: threading.RLock` — reentrant lock protecting both dicts
- `type_catalogue: TypeCatalogue` — maps FQN strings to PortDataType subclasses

**Thread safety:** All mutations (`register`, `unregister`) and reads that iterate the dicts acquire `_lock`. `find_compatible_nodes()` takes a snapshot of both dicts under a single lock acquisition, then operates on the snapshots without holding the lock — preventing a `KeyError` if `unregister()` races between the snapshot and the metadata lookup.

**Key methods:**
- `register(node_type, node_class, metadata)` — adds to both dicts atomically
- `get_class(node_type)` — raises `NodeNotFoundError` if not found
- `get_metadata(node_type)` — raises `NodeNotFoundError` if not found
- `list_nodes(category=None)` — returns all or filtered metadata
- `find_compatible_nodes(port_type, direction)` — reverse discovery
- `to_json()` / `parse_metadata_list()` — serialization for API responses
- `get_config_schema(node_type)` — returns Pydantic JSON Schema for the node's Config
- `get_port_schema(node_type)` — returns port type schemas via `_type_to_schema()`

**Singleton access:** The singleton is created in `app/core/nodes/__init__.py` and accessed via `app/core/registry_runtime.get_registry()`. The `__init__.py` triggers `AutoDiscovery` on import, so the registry is fully populated by the time any caller uses it.

#### 3.3.6 `discovery.py` — AutoDiscovery

**Role:** Scans directories for Node and PortDataType subclasses and registers them.

**Scan sequence:**
1. Scan `app/core/nodes/*.py` — skips framework files listed in `_EXCLUDED_FILES`
2. Scan `app/core/nodes/*/` subdirectories with `__init__.py` (category folders)
3. Scan `app/models/*.py` — registers PortDataType subclasses into TypeCatalogue
4. Scan `plugins/{name}/` — manifest-based plugins only (delegates to `PluginLoader`)

**Node type derivation:** If a class does not declare `node_type`, it is derived from the class name via `_pascal_to_snake()`:
- `FilterNode` → `filter`
- `TFLiteProcessorNode` → `tf_lite_processor`
- `AudioMixerNode` → `audio_mixer`

**Duplicate handling:** If the same `node_type` is claimed by two different classes, `DuplicateNodeTypeError` is raised immediately (hard fail). If the same class is imported under two different module paths (e.g., startup load + explicit install), it is silently skipped.

**Module import strategy:** For package files, `importlib.import_module(module_name)` is used so relative imports work. For plugin files (no package prefix), `importlib.util.spec_from_file_location` is used with a synthetic module name `{parent_dir}.{stem}`.

#### 3.3.7 `compat.py` — CompatibilityChecker

**Role:** Determines whether an output port type can flow into an input port type.

**Compatibility rules (applied in order):**
1. `(None, None)` → compatible (source/sink nodes)
2. `(X, None)` or `(None, X)` → incompatible
3. Both plain classes → `issubclass(output_type, input_type)`
4. Input is plain `list` → accepts any `list[X]` output
5. Input is `object` → accepts anything (universal sink)
6. Output is `object` → can flow into anything (universal source)
7. Union types → covariant subset check
8. Generic aliases → origins must match, args recursively compatible

**Usage:** Called by `PipelineGraph._build()` during graph construction to validate every edge before execution begins. Also called by `validate_pipeline()` and `_validate_dag_edges()` during API validation.

#### 3.3.8 `retry.py` — RetryPolicy

**Role:** Exponential backoff configuration for node retries.

**Formula:** `wait_i = backoff_seconds × (backoff_multiplier ^ i)` where `i` is the 0-indexed retry attempt number.

**Usage:** Declared as a ClassVar on a Node subclass: `retry_policy: ClassVar[RetryPolicy] = RetryPolicy(max_attempts=3, backoff_seconds=1.0, backoff_multiplier=2.0)`. The `NodeExecutor` reads this at execution time.


---

### 3.4 Graph IR Layer — `app/core/ir/`

**Role:** Defines the canonical, version-controlled, serializable representation of a pipeline graph. All interfaces produce and consume `GraphIR` objects. This layer has zero dependencies on the node system, execution engine, or any other `app/core/` module — it only uses Pydantic and the standard library.

#### 3.4.1 `models.py` — GraphIR Pydantic Models

**`GraphIR`** — top-level model:
- `schema_version: str` — must be `"<major>.<minor>"` format (e.g. `"1.1"`)
- `metadata: IRMetadata` — name, seed, description, created_at, tags
- `nodes: list[IRNode]` — all nodes; IDs must be unique
- `edges: list[IREdge]` — directed connections; src/dst IDs must reference known nodes
- `parameters: dict[str, IRParameter]` — graph-level parameter definitions

**`IRNode`** — one node instance:
- `id: str` — alphanumeric + underscores + hyphens only (validated by regex)
- `node_type: str` — registry key
- `config: Any` — stored as `MappingProxyType(copy.deepcopy(v))` to prevent external mutation
- `label: str | None` — display name
- `capability_metadata: IRCapabilityMetadata | None` — per-instance capability overrides
- `event_trigger: dict | None` — event source binding for event-driven execution

**`IREdge`** — one directed connection:
- `src_id`, `src_port`, `dst_id`, `dst_port` — all strings
- `condition: str | None` — boolean expression evaluated against source outputs

**`IRMetadata`** — graph-level metadata:
- `name: str` — stripped and validated non-empty
- `seed: int` — random seed for reproducibility
- `description`, `created_at`, `tags`

**Immutability:** All models use `ConfigDict(frozen=True)`. However, `IRNode.config` is a `MappingProxyType` wrapping a deep copy — it is immutable at the proxy level but the underlying dict can be accessed via `dict(node.config)`.

**Validation:** `GraphIR._validate_graph()` is a `@model_validator(mode="after")` that checks node ID uniqueness and edge reference integrity. This runs after all field validators, so it has access to the fully constructed object.

#### 3.4.2 `loader.py` — IR Serialization

**Role:** Load, validate, dump, and version-check GraphIR objects.

**Version strategy:**
- Current version: `"1.1"` (`CURRENT_IR_VERSION`)
- Supported major: `1` (`SUPPORTED_MAJOR`)
- Supported minor max: `1` (`SUPPORTED_MINOR_MAX`)
- `"1.0"` documents are accepted and treated as `"1.1"` (missing fields default to `None`)
- Major version mismatch → `IRVersionError` (hard fail)
- Minor version > supported → `UserWarning` (soft warn, continue)

**Key functions:**
- `load_ir(data: dict) → GraphIR` — validates and version-checks a dict
- `load_ir_from_file(path: str) → GraphIR` — reads JSON file, then calls `load_ir()`
- `dump_ir(graph: GraphIR) → dict` — `model_dump(mode="json")` for JSON serialization
- `dump_ir_to_file(graph, path)` — writes with 2-space indent + trailing newline

#### 3.4.3 `yaml_shim.py` — YAML Compatibility

**Role:** Converts legacy YAML pipeline configs to `GraphIR` objects. Emits `DeprecationWarning` on use.

**Conversion logic:** Reads the `pipeline.nodes` list and `pipeline.edges` list (or auto-chains linearly if no edges), constructs `IRNode` and `IREdge` objects, and wraps them in a `GraphIR` with `schema_version="1.1"`.

#### 3.4.4 `migrate.py` — File Migration

**Role:** Converts `.yaml` pipeline files to `.graph.json` IR files on disk. Used by the CLI `migrate` command.


---

### 3.5 Execution Layer — `app/core/pipeline.py`

This is the largest and most complex file in the codebase (1510 lines). It contains the DAG builder, the node executor, the main execution loop, and several helper functions.

#### 3.5.1 Data Structures

**`NodeSpec`** — a dataclass holding `node_id`, `node_type`, `config` for one node in a pipeline config.

**`EdgeSpec`** — a dataclass holding `src_id`, `src_port`, `dst_id`, `dst_port`, `condition` for one edge.

**`PipelineConfig`** — a dataclass holding `seed`, `nodes: list[NodeSpec]`, `edges: list[EdgeSpec]`. This is the internal representation used by `PipelineGraph` — it is derived from `GraphIR` via `_ir_to_pipeline_config()`.

**`_parse_pipeline_config(raw: dict)`** — parses a raw YAML dict into `PipelineConfig`. Supports both explicit-edge format (with `edges` key) and legacy linear format (auto-chains `output → input`). This is a legacy entry point; the primary path goes through `GraphIR`.

#### 3.5.2 `PipelineGraph` — DAG Builder

**Role:** Takes a `PipelineConfig`, instantiates all nodes, validates all edges, and computes execution order.

**Build sequence:**
1. For each `NodeSpec`: call `registry.get_class(node_type)`, compute a deterministic seed via `stable_hash(seed, node_type, index) % 2^32`, instantiate the node with `node_class(config=..., seed=..., observer=...)`.
2. For each `EdgeSpec`: validate that both endpoints exist, then call `CompatibilityChecker.check_connection()`.
3. Run Kahn's topological sort algorithm. Raises `PipelineGraphError` if a cycle is detected.
4. Compute execution waves via level-based BFS: each node's level = `max(predecessor_levels) + 1`. Nodes at the same level have no data dependency on each other and can run concurrently.

**Execution waves example:**
```
Graph: A → B → D
       A → C → D

Levels: A=0, B=1, C=1, D=2
Waves:  [["A"], ["B", "C"], ["D"]]
```

#### 3.5.3 `NodeExecutor` — Per-Node Lifecycle Driver

**Role:** Drives a single node through its full lifecycle with retry support.

**`execute(inputs)` sequence:**
```
For attempt in range(max_attempts):
    sleep(wait_before_attempt(attempt-1))  # skip for attempt 0
    node.on_start()
    observer.on_node_start()               # ← BUG: fires twice (on_start also calls observer)
    t0 = time.perf_counter()
    outputs = node.process(inputs)
    duration = time.perf_counter() - t0
    node.on_end()
    observer.on_node_end(duration, counts)
    return outputs

# After all attempts exhausted:
node.on_error(last_exc)
observer.on_node_error()                   # ← BUG: fires twice (last loop iter also called it)
self.teardown()
raise last_exc
```

**`execute_stream(inputs)`** — async generator that calls `node.process_stream(inputs)`. `on_end()` is called in a `finally` block so it fires even if the caller breaks out of the `async for` early.

#### 3.5.4 `run_pipeline_ir_async()` — Main Execution Entry Point

**Role:** The async implementation of the full pipeline execution loop. All four interfaces ultimately call this function (via the synchronous shim `run_pipeline_ir()` which calls `asyncio.run(run_pipeline_ir_async(...))`).

**Full execution sequence:**

```
1. Validate mutual exclusivity of parallel/event_driven flags
2. Create PipelineLogger (if not provided)
3. Create RunManager (if not provided) → creates run directory, writes initial meta.json
4. run.save_graph_ir(dump_ir(graph)) → writes graph.json, computes graph_hash
5. register_active_run(run) → enables pause/resume/cancel via API
6. _ir_to_pipeline_config(graph) → PipelineConfig
7. PipelineGraph(config) → validates edges, computes topo order + waves
8. Compute graph_hash (REDUNDANT — already done in step 4)
9. Resolve active_nodes (all, include_nodes, or exclude_nodes)
10. logger.pipeline_start(total_nodes)
11. Setup all NodeExecutors (calls node.setup() for each)
12. Build incoming-edge lookup: dst_id → [(src_id, src_port, dst_port)]
13. Build edge-condition lookup: (src_id, src_port, dst_id, dst_port) → condition
14. Load resume state if resume_run_id provided
15. Init resume_state.json if checkpoint=True

EXECUTION LOOP (sequential or parallel):

Sequential path (parallel=False):
  For each node_id in topo_order:
    - Skip if in completed_nodes (resume)
    - Skip if not in active_nodes (partial execution)
    - run.wait_if_paused() → blocks until resumed
    - Check run.is_cancelled → emit cancelled event, teardown, return
    - Assemble inputs from node_outputs[src_id][src_port]
    - Evaluate edge conditions via conditions.evaluate_condition()
    - Check PipelineCache → use cached outputs if hit
    - NodeExecutor.execute(inputs) → outputs
    - Save to PipelineCache (if cacheable)
    - Write checkpoint (if checkpoint=True)
    - run.update_resume_state(node_id)
    - run_manager.register_artifact() for each output port

Parallel path (parallel=True):
  For each wave in execution_waves:
    - Check run.is_cancelled
    - logger.wave_start(wave_idx, wave)
    - await ParallelExecutor.run_wave(wave, ...) → all nodes in wave concurrently
    - logger.wave_end(wave_idx, wave, duration)

16. run.save_metadata(stats) → writes final meta.json (status=completed)
17. run.save_logs(logger.logs)
18. deregister_active_run(run.run_id)
19. Return node_outputs[last_node_id]
```

**Error handling:** Any exception from a node propagates up through the executor, is caught in the execution loop, triggers `run.mark_failed(str(exc))`, `run.save_logs()`, `deregister_active_run()`, and then re-raises.


#### 3.5.5 `executor.py` — ParallelExecutor

**Role:** Executes all nodes in a single wave concurrently using `asyncio.gather` + `ThreadPoolExecutor`.

**Design:** One `ThreadPoolExecutor` is created per wave (not per node) and shared across all nodes in that wave. Sync nodes are offloaded via `loop.run_in_executor(pool, exec_.execute, inputs)`. Streaming nodes are awaited directly via `execute_stream()`. Results are gathered with `return_exceptions=True` — all tasks complete before the first exception is re-raised.

**Worker count:** `min(32, (os.cpu_count() or 1) + 4)` by default, or `max_workers` if provided.

**Limitation:** A new pool is created for every wave. For pipelines with many waves, this creates repeated pool creation/teardown overhead.

#### 3.5.6 `conditions.py` — Condition Evaluator

**Role:** Safely evaluates boolean expressions on a node's output dict for conditional edges.

**Security model:** Uses `ast.parse()` + AST whitelist validation before `eval()`. Allowed constructs: comparisons, boolean ops (`and`, `or`, `not`), arithmetic, `len()` calls, subscript access on `output`, and literals. All other constructs (imports, attribute access, function calls other than `len`, assignments, comprehensions) raise `ConditionEvaluationError`. The `__builtins__` passed to `eval()` is `{"len": len}` — no other builtins are available.

**Usage:** Called in the sequential execution loop when `edge_conditions[(src_id, src_port, dst_id, dst_port)]` is not `None`. If the condition evaluates to `False`, `inputs[dst_port] = None` (data is not transmitted on that edge).

#### 3.5.7 `events.py` — Event Sources

**Role:** Provides async generators that yield event payloads to trigger event-driven pipeline execution.

**Three implementations:**
- `FileWatcherSource` — watches a directory for new/modified files. Uses `watchfiles` library if available, falls back to polling.
- `TimerSource` — fires at a configurable interval using `asyncio.wait_for` with timeout.
- `QueueSource` — reads from an `asyncio.Queue`, useful for programmatic event injection.

**Factory:** `create_event_source(source_type, source_config)` validates config keys against the constructor signature before instantiation.

**Integration:** When `event_driven=True`, source nodes with `event_trigger` set in their `IRNode` are bound to an `EventSource`. The execution loop re-runs the pipeline on each event payload.


---

### 3.6 Backend Services Layer

These modules provide persistence, observability, and data management. They are used by the execution layer but do not depend on it.

#### 3.6.1 `run_manager.py` — RunManager

**Role:** Manages the lifecycle of a single pipeline run — directory creation, metadata persistence, pause/resume/cancel control, checkpoint management, artifact registration, and provenance tracking.

**Construction:** `RunManager.__init__()` creates a 16-char hex `run_id` (from a UUID4), creates `{runs_dir}/{run_id}/`, and writes an initial `meta.json` with `status: "running"`. This means every `RunManager` instantiation creates a run directory immediately, even if the pipeline never executes.

**Directory layout:**
```
workspace/runs/{run_id}/
├── meta.json           — run metadata (status, duration, node_stats, etc.)
├── graph.json          — the GraphIR JSON for this run
├── config.yaml         — YAML config (legacy, only written for YAML submissions)
├── logs.json           — structured log events
├── resume_state.json   — completed node IDs (written when checkpoint=True)
└── checkpoints/
    └── node_{node_id}/
        ├── manifest.json
        └── {i}.wav     — audio sample files
```

**Pause/resume/cancel:** Uses two `threading.Event` objects:
- `_pause_event` — set = running, clear = paused. `wait_if_paused()` blocks until set.
- `_cancel_event` — set = cancelled. Checked between nodes in the execution loop.

**Active run registry:** Module-level `_ACTIVE_RUNS: dict[str, RunManager]` protected by `_ACTIVE_RUNS_LOCK`. `register_active_run()` / `deregister_active_run()` / `get_active_run()` are module-level functions. This is process-local — multi-worker deployments cannot share this state.

**Meta file safety:** `_write_meta_field()` uses `_meta_lock` for the full read-modify-write cycle, preventing lost-update races when multiple threads update different fields concurrently.

**Artifact and provenance:** `register_artifact()` delegates to `ArtifactStore.register()` and `ProvenanceStore.record()`. The `_artifacts_lock` guards the internal `_artifacts` list for thread-safe appends during parallel wave execution.

**Resume:** `load_resume_state(run_id)` reads `resume_state.json` from a prior run. `find_latest_checkpoint(node_id)` scans all run directories to find the most recent checkpoint for a given node — an O(N) operation.

#### 3.6.2 `logger.py` — PipelineLogger

**Role:** Structured event emitter for pipeline execution. Maintains an in-memory log buffer and optionally forwards events to a `Queue` for streaming.

**Two emission paths:**
- `_emit(entry)` — for plain text log entries (INFO/WARNING/ERROR). Appends to `self.logs`, writes to Python logging, puts on queue.
- `_emit_structured(entry)` — for typed events (pipeline_start, node_start, etc.). Appends to `self.logs`, writes DEBUG to Python logging, puts on queue.

**Bounded buffer:** `self.logs` is a `deque(maxlen=10_000)`. Prevents unbounded memory growth for long-running pipelines.

**Event types emitted:** `pipeline_start`, `node_start`, `node_end`, `node_error`, `node_skip`, `done`, `error`, `pipeline_summary`, `wave_start`, `wave_end`, `pipeline_paused`, `pipeline_resumed`, `pipeline_cancelled`, `event_received`.

**Streaming integration:** When a `Queue` is provided (as in `POST /pipelines/run`), every event is put on the queue. The API endpoint reads from the queue in a generator and streams NDJSON to the client.

**Subscriber pattern (SDK):** `Pipeline.subscribe(callback)` creates a `_SubscriberLogger` subclass that overrides `_emit()` to forward events to registered callbacks. This is lazily initialized to avoid circular imports.


#### 3.6.3 `pipeline_cache.py` — PipelineCache

**Role:** SHA-256 keyed filesystem cache for node outputs. Avoids re-executing nodes whose inputs and config have not changed.

**Cache key:** `SHA-256(node_type + sorted_json(config) + input_hash)`. The `input_hash` is computed from the actual input values using type-specific strategies.

**Input hashing strategies (in priority order):**
1. `list[AudioSample]` → hash `path:sample_rate:shape` for each sample
2. `list[Pydantic models]` → `json.dumps([item.model_dump(mode="json") for item in inputs])`
3. Single Pydantic model → `json.dumps(model.model_dump(mode="json"))`
4. numpy ndarray → `hashlib.sha256(array.tobytes())`
5. JSON-serializable → `json.dumps(inputs, sort_keys=True)`
6. Fallback → `repr(inputs)` — **not stable across process restarts**

**Storage formats:**
- `port_{name}/manifest.json` + WAV files — for `list[AudioSample]` outputs (one subdirectory per port)
- `outputs.json` — for JSON-serializable outputs
- Legacy `manifest.json` at cache root — for old single-port AudioSample caches

**TOCTOU issue:** `has()` and `load()` are separate operations. The code in `executor.py` calls `cache.has()` then `cache.load()` — a race condition exists between them. The docstring documents this but the call site is not fixed.

**Cacheable flag:** The `IRCapabilityMetadata.cacheable` field (or `NodeMetadata.cacheable`) controls whether a node's outputs are saved to cache. Non-cacheable nodes (e.g., `AudioClassifierNode` with `cacheable=False`) always re-execute.

#### 3.6.4 `artifact_store.py` — ArtifactStore

**Role:** Content-addressed, typed artifact registry. Stores node outputs as persistent artifacts with deduplication.

**Directory layout:**
```
workspace/artifacts/
├── index.json              — {content_hash: artifact_id} deduplication index
├── by_run/
│   └── {run_id}.json       — [artifact_id, ...] per run
└── {artifact_id}/
    ├── record.json         — ArtifactRecord metadata
    └── data/
        ├── manifest.json   — for audio_samples
        ├── {i}.wav         — WAV files for audio_samples
        └── data.json       — for all other types
```

**Deduplication:** Before writing, `_compute_content_hash()` computes a SHA-256 of the data. If the hash exists in `index.json`, the existing `ArtifactRecord` is returned (stamped with the current run context) without re-serializing. This means identical audio processed by two different runs shares one copy on disk.

**Supported artifact types:** `audio_samples`, `model_artifact`, `tflite_artifact`, `prediction_result`, `feature_array`, `generic`.

**Thread safety:** `self._lock` guards the entire `register()` method including serialization — a bottleneck for parallel execution (see tech review §3.5).

**Secondary index:** `by_run/{run_id}.json` enables O(k) lookup for run-specific artifact queries without scanning all artifact directories.

#### 3.6.5 `provenance.py` — ProvenanceStore

**Role:** Records and queries artifact lineage — which node produced which artifact, from which inputs, in which run, with which graph.

**Directory layout:**
```
workspace/provenance/
├── {artifact_id}.json      — ProvenanceRecord per artifact
├── by_run/
│   └── {run_id}.json       — [artifact_id, ...] per run
└── by_graph_hash/
    └── {hash[:16]}.json    — [artifact_id, ...] per graph hash
```

**Lineage tree:** `get_lineage(artifact_id)` recursively resolves `input_artifact_ids` to build a tree. Cycle detection uses a `frozenset` of ancestors on the current path — siblings don't share ancestor state, so a node appearing in two branches is not falsely flagged as a cycle. Missing records return error nodes (`{"error": "no_provenance_record"}`) rather than raising.

**Reproducibility:** `find_reproducible(graph_hash)` uses the `by_graph_hash/` secondary index to find all artifacts produced by runs with the same graph structure.

#### 3.6.6 `ingestion.py` — IngestionService

**Role:** Downloads audio from URLs or HuggingFace datasets into the workspace input directory.

**Job model:** Each ingestion job is an `IngestionJob` (Pydantic model with a private `threading.Lock`). Jobs run in daemon threads. Progress events are appended to `job.progress` and streamed to clients via SSE.

**URL ingestion:** Downloads each URL with `httpx`, validates the file extension, writes to `workspace/datasets/input/{sanitized_label}/`, then validates the file with `soundfile` or `librosa`. Corrupted files are deleted.

**HuggingFace ingestion:** Streams a HuggingFace dataset using `datasets.load_dataset(..., streaming=True)`, saves each audio sample as a WAV file.

**Label sanitization:** `_sanitize_label()` strips non-alphanumeric/hyphen/underscore characters and truncates to 64 chars, preventing path traversal via label values.

**Job eviction:** Module-level `_jobs` dict is capped at 200 entries. Oldest completed/failed jobs are evicted when the limit is exceeded.


#### 3.6.7 `webhook.py` — WebhookService

**Role:** Fire-and-forget HTTP POST notifications to a configured webhook URL.

**Config persistence:** Webhook URL and event subscriptions are stored in `workspace/webhooks.json`. `save()` validates the URL scheme (http/https only) and host presence before writing.

**Delivery:** `notify(event, payload)` checks the in-memory config cache, filters by subscribed events, and spawns a daemon thread to POST the payload. Failures are logged as warnings and never raised. There is no retry or delivery guarantee.

**SSRF risk:** The URL validation checks scheme and host but does not block private/loopback IP addresses. See tech review §2.3.

#### 3.6.8 `quality_checker.py` and `project_manager.py`

**`quality_checker.py`** — Analyzes dataset quality: checks for class imbalance, audio duration distribution, sample rate consistency, and label coverage. Used by the projects API.

**`project_manager.py`** — Manages project lifecycle: create, update, delete, clone, list versions, taxonomy, contract, spec, annotations, quality reports, snapshots, curation decisions. Persists project metadata to `workspace/projects/`.

---

### 3.7 Plugin Ecosystem Layer — `app/core/plugins/`

**Role:** Manages the full lifecycle of plugin packages — installation, loading, enabling, disabling, and uninstallation. All 29 production nodes are delivered as plugins.

#### 3.7.1 `manager.py` — PluginManager

**Role:** Single entry point for all plugin operations. CLI, REST API, and SDK all delegate to this class. Never call `PluginLoader`, `PluginStore`, or `PluginInstaller` directly from outside this package.

**`install(source, upgrade=False)` sequence:**
1. Parse name from source (best-effort, pre-flight check)
2. Check `PluginStore` for existing installation; raise `PluginAlreadyInstalledError` if found and `upgrade=False`
3. If upgrading, call `uninstall()` first
4. `PluginInstaller.resolve(source)` → temp directory
5. `load_manifest(resolved_dir)` → authoritative name check (catches URL sources where pre-flight name was wrong)
6. `shutil.copytree(resolved_dir, {plugins_dir}/{manifest.name}/)` — atomic copy
7. Cleanup temp directory in `finally` block
8. `PluginLoader.load(install_path)` → validates compat/deps, registers node types
9. `PluginStore.save(PluginRecord)` → persists to `~/.graphyn/plugins/registry.json`
10. Return `PluginRecord`

If steps 8–9 fail, the install directory is removed (`shutil.rmtree`) to keep the registry consistent.

**`uninstall(name)` sequence:**
1. `PluginStore.get(name)` → raises `PluginNotFoundError` if absent
2. `_unload_node_types(record)` → unregisters all node types contributed by this plugin
3. `PluginStore.delete(name)` → removes from registry.json
4. `shutil.rmtree(record.install_path)` → removes plugin directory

**`_unload_node_types(record)`:** Uses `inspect.getfile(cls)` to find the source file of each registered class, then checks if it lives inside the plugin's install directory using an exact path-prefix comparison. This prevents false positives (e.g., plugin `audio` matching classes from `audio_denoiser`).

#### 3.7.2 `installer.py` — PluginInstaller

**Role:** Resolves source strings to local directories.

**Source types:**
- Local path → copy as-is (or use directly if already a directory)
- `git+URL` → `git clone` to a temp directory
- `http(s)://` URL → download archive, extract to temp directory
- `name[==version]` → `PluginIndexClient.lookup()` → download URL → extract

**Temp directory naming:** Uses `kiro_plugin_` prefix so `PluginManager` can identify and clean up the temp directory in its `finally` block.

#### 3.7.3 `loader.py` — PluginLoader

**Role:** Validates a manifest-based plugin and registers its node types.

**Load sequence:**
1. `load_manifest(plugin_dir)` → `PluginManifest`
2. `_check_platform_compat()` — checks `platform_version` specifier against `app.__version__`. If `app.__version__` is not set (dev/CI), skips with a WARNING.
3. `_check_python_compat()` — checks `min_python` against `sys.version_info`
4. `DependencyChecker.check(manifest.dependencies)` — verifies PEP 508 strings. If `GRAPHYN_PLUGIN_AUTO_INSTALL=1`, runs `pip install` for missing deps.
5. For each `entry_point` in manifest: `AutoDiscovery._import_file()` + `_process_module()` → registers node types
6. Returns sorted list of newly registered `node_type` strings

Individual entry-point failures are logged as WARNING and skipped — remaining entry points still load.

#### 3.7.4 `store.py` — PluginStore

**Role:** Persists `PluginRecord` objects to `~/.graphyn/plugins/registry.json`.

**`PluginRecord` fields:** `name`, `version`, `source`, `install_path`, `enabled`, `installed_at`, `manifest` (raw dict).

**Operations:** `save()`, `get(name)`, `delete(name)`, `list()`, `update_enabled(name, enabled)`. All operations read/write the full JSON file atomically.

#### 3.7.5 `manifest.py` — PluginManifest

**Role:** Pydantic model for `plugin.toml` / `plugin.json` manifests.

**Key fields:** `name`, `version`, `description`, `platform_version` (PEP 440 specifier), `min_python` (version string), `dependencies` (list of PEP 508 strings), `entry_points` (list of relative file paths).

**`load_manifest(plugin_dir)`:** Tries `plugin.toml` first (using `tomllib`/`tomli`), falls back to `plugin.json`. Raises `PluginManifestError` if neither exists or validation fails.


---

### 3.8 Interface Layer

All four interfaces share the same execution path: they construct a `GraphIR`, call `run_pipeline_ir()`, and handle the result.

#### 3.8.1 REST API — `app/api/`

**`app/api/main.py` — App Factory**

Creates the FastAPI application, configures CORS, sets up Bearer token auth, mounts static file directories, and includes all routers. The auth dependency `_auth_dep` is applied to all routers via `dependencies=_deps`. When `GRAPHYN_API_TOKEN` is unset, all requests are allowed.

**Static mounts:**
- `/files/` → `workspace/datasets/output/`
- `/input-files/` → `workspace/datasets/input/`
- `/run-files/` → `workspace/runs/`

These allow the frontend to directly fetch audio files and run artifacts without going through API endpoints.

**CORS:** Allows `localhost:3000`, `localhost:5173` (React dev servers) with credentials. `allow_headers=["*"]` is a minor misconfiguration (see tech review §2.2).

**Routers and their responsibilities:**

| Router | Prefix | Key Endpoints |
|---|---|---|
| `nodes.py` | `/api/v1/nodes` | List nodes, get metadata, config schema, port schema, validate config, find compatible |
| `pipelines.py` | `/api/v1/pipelines` | Validate, run (streaming), run-async, templates CRUD |
| `runs.py` | `/api/v1/runs` | List runs, get run, status, checkpoints, artifacts, provenance |
| `run_control.py` | `/api/v1/runs/{id}` | pause, resume, cancel |
| `data.py` | `/api/v1/data` | List/get input datasets, upload, list/get output datasets, stats, merge |
| `system.py` | `/api/v1/system` | Health, cleanup, projects registry, webhooks |
| `ingest.py` | `/api/v1/ingest` | URL ingestion, HuggingFace ingestion, SSE progress streams |
| `artifacts.py` | `/api/v1/artifacts` | List, get, lineage, replay |
| `projects.py` | `/api/v1/projects` | Full project lifecycle |
| `plugins.py` | `/api/v1/plugins` | List, install, enable, disable, uninstall, search |

**`pipelines.py` — Streaming Execution Pattern:**

```
POST /pipelines/run:
  1. Build Pipeline from payload (IR JSON or YAML)
  2. Create Queue()
  3. Create PipelineLogger(queue=queue)
  4. Start daemon thread: pipeline.run(logger=logger)
     → thread puts events on queue as they occur
  5. Return StreamingResponse(generator)
     → generator reads from queue, yields NDJSON lines
     → sentinel None signals end of stream
```

This pattern decouples the pipeline execution thread from the HTTP response thread. The queue is unbounded — a slow client can cause memory growth.

**`pipelines.py` — Async Execution Pattern:**

```
POST /pipelines/run-async:
  1. Build Pipeline from payload
  2. Create RunManager() → get run_id immediately
  3. Start daemon thread: pipeline.run(run_manager=run_mgr)
  4. Return {"run_id": run_id} immediately
  5. Client polls GET /runs/{run_id}/status
```

**Path safety:** `data.py` uses `_safe_child(root, *parts)` which calls `resolve()` and `is_relative_to(root)`. `runs.py` uses a weaker check (`run_id.replace("-", "").isalnum()`). `artifacts.py` validates artifact IDs with a regex.

#### 3.8.2 Python SDK — `app/core/sdk.py`

**Role:** Programmatic API for defining and running pipelines without the REST API.

**`PipelineNode`:** Wraps a node type and config. Validates config against the registry at construction time. Internally holds an `IRNode` with id `{node_type}_0` (a known bug — always `_0` regardless of position).

**`Pipeline`:** Holds a list of `PipelineNode` objects and builds a `GraphIR` internally via `_build_ir()`. Supports explicit edge routing via the `edges` parameter (list of 4-tuples: `(src_idx, src_port, dst_idx, dst_port)`). Default is linear auto-chaining.

**`Pipeline.run()` → `ArtifactCollection`:** Calls `run_with_manager()` and discards the manager. Returns an `ArtifactCollection` that wraps the raw outputs dict with typed artifact access.

**`ArtifactCollection`:** Backward-compatible dict-like wrapper. Supports `collection["node_id"]` (raw output), `collection.artifacts` (list of `ArtifactRecord`), `collection.get_by_type(artifact_type)`, `collection.lineage(artifact_id)`.

**Subscriber pattern:** `pipeline.subscribe(callback)` registers a callable that receives every log event. Returns an unsubscribe function. Implemented via a lazily-created `_SubscriberLogger` subclass that overrides `_emit()`.

**Pause/resume/cancel:** `pipeline.pause()`, `pipeline.resume()`, `pipeline.cancel()` look up the active `RunManager` via `get_active_run(self._last_run_id)` and delegate to it. No-ops if no run is active.

**`Pipeline.validate()` — known bug:** Calls `validate_pipeline(pipeline_cfg)` without the required `registry` argument, always raising `TypeError`.

#### 3.8.3 CLI — `app/cli/main.py`

**Role:** Command-line interface using argparse. Supports `run`, `validate`, `list-nodes`, `migrate`, `plugins`, and other commands.

**Execution path:** `graphyn run --graph pipeline.graph.json` → `load_ir_from_file()` → `run_pipeline_ir()` → prints structured output.

#### 3.8.4 MCP Server — `app/mcp/`

**Role:** Model Context Protocol server over stdio transport. Exposes 15 tools for AI agents to interact with the pipeline engine.

**`server.py`:** Thin dispatch shell. Registers tools via `_register()`, handles `list_tools` and `call_tool` MCP protocol messages. Auth is checked on every tool call via `check_auth(arguments)`.

**`auth.py`:** Reads `GRAPHYN_API_TOKEN` at module import time (known bug — see tech review §2.1). Expects token at `arguments["_meta"]["auth_token"]`.

**`tool_registry.py`:** Calls `register_all_tools(_register)` at startup, importing all handler modules and registering their tools with descriptions and JSON Schema input schemas.

**Handler modules** (`app/mcp/handlers/`):
- `discovery.py` — `list_nodes`: queries registry with filters
- `graph.py` — `generate_graph`, `validate_graph`, `get_graph_schema`, `get_graph_capability_summary`, `get_event_schema`
- `execution.py` — `execute_pipeline`: calls `run_pipeline_ir()` synchronously
- `artifacts.py` — `inspect_run`: filesystem-based run inspection
- `run_control.py` — `pause_run`, `resume_run`, `cancel_run`: delegates to `get_active_run()`
- `provenance.py` — `list_artifacts`, `get_artifact_lineage`, `replay_run`
- `optimization.py` — `optimize_execution`: analyzes graph capabilities

**Error contract:** All handlers return structured JSON dicts. Never raw exceptions. Error types are documented in the steering file.


---

### 3.9 Plugin Nodes — `PluginPackage/`

All 29 production nodes are delivered as manifest-based plugin packages. Each package contains `nodes.py`, `plugin.toml`, and `__init__.py` (with one exception: `audio_exporter` has no `__init__.py`).

#### Audio Nodes (18) — `PluginPackage/Audio/`

| Node Type | Class | Category | Key Dependencies |
|---|---|---|---|
| `speech_enhancer` | `SpeechEnhancerNode` | Enhancement | `noisereduce`, `deepfilternet`, `scipy`, `librosa` |
| `audio_classifier` | `AudioClassifierNode` | Inference | `tensorflow_hub`, `tflite_runtime`, `torch`, `onnxruntime` |
| `segmenter` | `SegmenterNode` | Preprocessing | `librosa`, `webrtcvad` |
| `speaker_separator` | `SpeakerSeparatorNode` | Separation | `pyannote.audio`, `speechbrain` |
| `alignment_node` | `AlignmentNode` | Alignment | `ctc-forced-aligner` |
| `audio_annotator` | `AudioAnnotatorNode` | Annotation | `librosa` |
| `audio_conditioner` | `AudioConditionerNode` | Conditioning | `librosa`, `scipy` |
| `audio_event_detector` | `AudioEventDetectorNode` | Detection | `librosa` |
| `audio_generator` | `AudioGeneratorNode` | Generation | `TTS` (Coqui), `audiocraft` |
| `augmentation_pipeline` | `AugmentationPipelineNode` | Augmentation | `audiomentations` |
| `dataset_ingest` | `DatasetIngestNode` | Ingestion | `librosa`, `soundfile` |
| `environment_simulator` | `EnvironmentSimulatorNode` | Simulation | `pyroomacoustics` |
| `feature_frontend` | `FeatureFrontendNode` | Features | `librosa`, `openl3` |
| `speech_synthesizer` | `SpeechSynthesizerNode` | Synthesis | `TTS` (Coqui) |
| `stream_ingest` | `StreamIngestNode` | Streaming | `sounddevice` |
| `stream_processor` | `StreamProcessorNode` | Streaming | `librosa` |
| `voice_converter` | `VoiceConverterNode` | Conversion | `speechbrain` |
| `audio_quality_gate` | `AudioQualityGateNode` | Quality | `librosa`, `pyloudnorm` |

**Note:** `document_processor/` directory exists but is empty — no implementation.

#### Common Nodes (11) — `PluginPackage/Common/`

| Node Type | Class | Category | Key Dependencies |
|---|---|---|---|
| `trainer` | `TrainerNode` | ML | `tensorflow`/`keras`, `torch` |
| `model_builder` | `ModelBuilderNode` | ML | `keras` |
| `dataset_builder` | `DatasetBuilderNode` | Data | `librosa`, `numpy` |
| `dataset_balancer` | `DatasetBalancerNode` | Data | `numpy` |
| `dataset_versioner` | `DatasetVersionerNode` | Data | — |
| `evaluator` | `EvaluatorNode` | Evaluation | `numpy` |
| `experiment_tracker` | `ExperimentTrackerNode` | Tracking | — |
| `embedding_generator` | `EmbeddingGeneratorNode` | Embeddings | `transformers`, `openl3` |
| `deployment_packager` | `DeploymentPackagerNode` | Deployment | `tensorflow` |
| `edge_optimizer` | `EdgeOptimizerNode` | Optimization | `tensorflow` |
| `realtime_inference` | `RealtimeInferenceNode` | Inference | `tflite_runtime` |
| `multimodal_fusion` | `MultimodalFusionNode` | Fusion | `numpy` |

#### Node Implementation Patterns

**Standard SISO node:**
```python
class SpeechEnhancerNode(Node):
    node_type: ClassVar[str] = "speech_enhancer"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(...)
    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=list[AudioSample], ...)
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=list[AudioSample], ...)
    }
    class Config(NodeConfig):
        backend: str = "auto"
        ...
    def setup(self) -> None:
        # Load models once
    def process(self, samples: list[AudioSample]) -> list[AudioSample]:
        # SISO shorthand — wrapped automatically
```

**Multi-port node:**
```python
class TrainerNode(Node):
    input_ports: ClassVar[dict] = {
        "model": InputPort(...),
        "dataset": InputPort(...),
    }
    output_ports: ClassVar[dict] = {
        "output": OutputPort(...)
    }
    def process(self, inputs: dict) -> dict:
        # Multi-port — NOT wrapped (second param named "inputs")
        model = inputs["model"]
        dataset = inputs["dataset"]
        ...
        return {"output": artifact}
```

**Lazy imports:** All heavy ML dependencies (`tensorflow`, `torch`, `librosa`, etc.) are imported inside `setup()` or `process()`, not at module level. This allows the plugin to load without its dependencies installed — the error only surfaces when the node is actually executed.


---

## 4. Cross-Cutting Concerns

### 4.1 Authentication

Two auth mechanisms exist, both reading from `GRAPHYN_API_TOKEN`:

**REST API:** `_auth_dep` in `app/api/main.py` is a FastAPI dependency applied to all routers. When the token is set, every request must include `Authorization: Bearer <token>`. When unset, all requests are allowed. The token is read at module import time — a known bug.

**MCP Server:** `check_auth(arguments)` in `app/mcp/auth.py` is called on every tool invocation. Expects the token at `arguments["_meta"]["auth_token"]`. Also read at import time.

**SDK/CLI:** No authentication — these are in-process calls.

### 4.2 Path Safety

Three levels of path safety are applied across the codebase:

1. **`_safe_child(root, *parts)`** (in `data.py`) — resolves the path and asserts `is_relative_to(root)`. Raises HTTP 400 if violated. Used for all user-supplied path components in the data API.

2. **Regex validation** — template names (`^[A-Za-z0-9_-]+$`), run IDs (alphanumeric), artifact IDs (`^[A-Za-z0-9_-]+$`). Weaker than `_safe_child` but sufficient for these identifiers.

3. **`os.path.realpath` + prefix check** — used in `_write_checkpoint()` and `find_latest_checkpoint()` to prevent path traversal via node IDs.

**Inconsistency:** `runs.py._run_dir()` uses the weaker regex check rather than `_safe_child()`.

### 4.3 Structured Logging

All execution events flow through `PipelineLogger`. Every event has a `type` field and a UTC ISO 8601 `timestamp`. The event stream is the primary observability mechanism — it is used for:
- Streaming NDJSON to REST API clients
- In-memory log buffer for `GET /runs/{id}` responses
- SDK subscriber callbacks
- MCP `inspect_run` tool

### 4.4 Dependency Injection

The system uses constructor injection throughout:
- `NodeExecutor(node, run_id)` — node and run_id injected
- `PipelineGraph(config, observer)` — observer injected
- `run_pipeline_ir_async(graph, logger, run_manager, ...)` — all services injectable
- `PluginManager(registry, base_dir)` — registry injectable for testing

This makes the system highly testable — all dependencies can be replaced with mocks.

### 4.5 Error Hierarchy

**Node errors** (`app/core/nodes/errors.py`):
- `NodeError` → `NodeNotFoundError`, `NodeTypeError`, `NodeMetadataError`, `DuplicateNodeTypeError`, `DuplicatePortTypeError`, `PipelineGraphError`

**Plugin errors** (`app/core/plugins/errors.py`):
- `PluginError` → `PluginManifestError`, `PluginCompatibilityError`, `PluginDependencyError`, `PluginInstallError`, `PluginNotFoundError`, `PluginAlreadyInstalledError`, `PluginIndexError`

**IR errors** (`app/core/ir/loader.py`):
- `IRVersionError`, `IRValidationError`

**Artifact errors** (`app/core/artifact_store.py`):
- `ArtifactNotFoundError` (subclasses `KeyError`), `ArtifactSerializationError`

**Condition errors** (`app/core/conditions.py`):
- `ConditionEvaluationError`

**Resume errors** (`app/core/pipeline.py`):
- `ResumeError`


---

## 5. Data Flow Walkthroughs

### 5.1 REST API Pipeline Execution (Streaming)

```
Client → POST /api/v1/pipelines/run
         Body: {"schema_version": "1.1", "metadata": {...}, "nodes": [...], "edges": [...]}

app/api/main.py
  └── _auth_dep() — validates Bearer token

app/api/routers/pipelines.py → run_pipeline_stream()
  1. _is_ir_payload(payload) → True (has schema_version)
  2. load_ir(payload) → GraphIR
  3. nodes = [PipelineNode(n.node_type, dict(n.config)) for n in graph.nodes]
  4. pipeline = Pipeline(nodes, seed, name, description)
  5. queue = Queue()
  6. logger = PipelineLogger(queue=queue)
  7. Thread(target=_run).start()
     └── pipeline.run(logger=logger)
         └── run_with_manager()
             └── _execute()
                 └── run_pipeline_ir(graph, logger=logger, ...)
                     └── run_pipeline_ir_async(...)
                         ├── RunManager() → creates workspace/runs/{id}/
                         ├── register_active_run(run)
                         ├── PipelineGraph(config) → validates, sorts
                         ├── For each node:
                         │   ├── NodeExecutor.execute(inputs)
                         │   │   └── node.process(inputs)
                         │   └── logger.node_end() → queue.put(event)
                         └── run.save_metadata() → meta.json
  8. Return StreamingResponse(stream())
     └── stream() reads from queue, yields NDJSON lines until sentinel None

Client receives:
  {"type": "pipeline_start", "total_nodes": 3, "timestamp": "..."}
  {"type": "node_start", "node_type": "DatasetIngestNode", ...}
  {"type": "node_end", "node_type": "DatasetIngestNode", "duration_s": 1.23, ...}
  ...
  {"type": "done", "timestamp": "..."}
```

### 5.2 SDK Pipeline Execution

```
Python code:
  pipeline = Pipeline([
      PipelineNode("dataset_ingest", {"path": "workspace/datasets/input/speech"}),
      PipelineNode("speech_enhancer", {"backend": "spectral"}),
      PipelineNode("audio_classifier", {"top_k": 3}),
  ], seed=42)

Pipeline.__init__():
  1. For each PipelineNode: validate config against registry
  2. _build_ir() → GraphIR with auto-chained edges

pipeline.run():
  1. run_with_manager()
  2. _execute()
  3. copy.deepcopy(self._graph_ir) → fresh copy for this run
  4. run_pipeline_ir(graph, ...)
     └── run_pipeline_ir_async(...)
         ├── RunManager() → workspace/runs/{id}/
         ├── PipelineGraph → instantiates 3 nodes
         ├── Node 0 (DatasetIngestNode):
         │   inputs = {}  (no incoming edges)
         │   outputs = {"output": [AudioSample(...), ...]}
         ├── Node 1 (SpeechEnhancerNode):
         │   inputs = {"input": [AudioSample(...), ...]}  (from node 0)
         │   outputs = {"output": [AudioSample(...), ...]}  (enhanced)
         └── Node 2 (AudioClassifierNode):
             inputs = {"input": [AudioSample(...), ...]}  (from node 1)
             outputs = {"output": [PredictionResult(...), ...]}
  5. Return ArtifactCollection(artifacts=[...], run_id="...", _raw={...})

result.artifacts  → list[ArtifactRecord]
result["audio_classifier_2"]  → {"output": [PredictionResult(...)]}
```

### 5.3 Plugin Installation Flow

```
POST /api/v1/plugins/install
  Body: {"source": "git+https://github.com/example/my-plugin.git"}

plugins.py → install_plugin()
  1. _is_remote_source(source) → True
  2. _parse_name_from_source(source) → "my-plugin"
  3. background_tasks.add_task(_bg_install)
  4. Return {"status": "installing", "name": "my-plugin"}

Background thread:
  PluginManager().install(source)
  1. PluginInstaller.resolve("git+https://...")
     └── git clone → /tmp/kiro_plugin_xxxxx/my-plugin/
  2. load_manifest(/tmp/kiro_plugin_xxxxx/my-plugin/)
     └── parse plugin.toml → PluginManifest(name="my-plugin", version="1.0.0", ...)
  3. shutil.copytree(temp_dir, ~/.graphyn/plugins/installed/my-plugin/)
  4. cleanup temp dir (finally block)
  5. PluginLoader.load(~/.graphyn/plugins/installed/my-plugin/)
     ├── check platform_version
     ├── check min_python
     ├── DependencyChecker.check(["librosa>=0.10"])
     └── AutoDiscovery._import_file(nodes.py) → _process_module()
         └── NodeRegistry.register("my_node", MyNode, metadata)
  6. PluginStore.save(PluginRecord(...))
     └── write ~/.graphyn/plugins/registry.json

Client polls: GET /api/v1/plugins/my-plugin
  → {"name": "my-plugin", "version": "1.0.0", "enabled": true, ...}
```

### 5.4 Artifact Lineage Query

```
GET /api/v1/artifacts/{artifact_id}/lineage

artifacts.py → get_artifact_lineage()
  1. Validate artifact_id format
  2. ArtifactStore().get(artifact_id) → ArtifactRecord (or 404)
  3. ProvenanceStore().get_lineage(artifact_id)
     └── _build_lineage_node(artifact_id, frozenset())
         ├── Load workspace/provenance/{artifact_id}.json → ProvenanceRecord
         ├── new_ancestors = {artifact_id}
         └── For each input_artifact_id:
             └── _build_lineage_node(input_id, new_ancestors)
                 ├── Check cycle: input_id in new_ancestors? → error node
                 ├── Load workspace/provenance/{input_id}.json
                 └── Recurse...

Returns:
  {
    "artifact_id": "abc123",
    "run_id": "run456",
    "node_id": "audio_classifier_2",
    "node_type": "AudioClassifierNode",
    "graph_hash": "sha256...",
    "inputs": [
      {
        "artifact_id": "def789",
        "node_id": "speech_enhancer_1",
        "inputs": [
          {
            "artifact_id": "ghi012",
            "node_id": "dataset_ingest_0",
            "inputs": []
          }
        ]
      }
    ]
  }
```


---

## 6. Architectural Patterns

### 6.1 Registry Pattern

The `NodeRegistry` is a classic registry/service-locator. It is a singleton populated at startup and queried at runtime. The registry decouples the execution engine from concrete node implementations — the engine only knows about `node_type` strings and the `Node` base class interface.

**Why:** Enables the plugin system. New node types can be added without modifying the engine. The registry is the only coupling point between the engine and node implementations.

### 6.2 Plugin Architecture (Manifest-Based)

Each plugin is a self-contained directory with a `plugin.toml` manifest declaring its name, version, compatibility requirements, Python dependencies, and entry point files. The `PluginLoader` validates and loads each plugin independently. This is similar to Python's entry_points mechanism but implemented in-process.

**Why:** Allows domain-specific node packages (audio, ML, etc.) to be developed, versioned, and distributed independently of the core engine.

### 6.3 Intermediate Representation (IR)

The `GraphIR` is a versioned, validated, serializable representation of a pipeline. All interfaces produce `GraphIR` before execution. This is the same pattern used by compilers (AST → IR → machine code).

**Why:** Decouples pipeline definition from execution. Enables serialization, versioning, migration, validation, and replay. The IR can be stored, transmitted, and reconstructed without losing information.

### 6.4 SISO Wrapper (Transparent Adapter)

The `_maybe_wrap_siso()` function is a transparent adapter applied at class definition time. It allows simple nodes to use a clean `process(self, data)` signature while the engine always uses the canonical `process(self, inputs: dict) -> dict` signature.

**Why:** Reduces boilerplate for the common case (single input, single output) without sacrificing the generality of the multi-port interface.

### 6.5 Content-Addressed Storage

`ArtifactStore` uses SHA-256 content hashing for deduplication. Two runs that produce identical audio will share one copy on disk. This is the same pattern used by Git and Docker.

**Why:** Reduces disk usage for iterative pipelines where early nodes produce the same output across multiple runs.

### 6.6 Wave-Based Parallel Execution

The execution engine groups topologically-sorted nodes into "waves" — sets of nodes with no data dependency on each other. All nodes in a wave execute concurrently. This is a level-synchronous BFS approach.

**Why:** Maximizes parallelism while respecting data dependencies. Simpler than a fully asynchronous task graph (no need to track individual node completion events).

### 6.7 Bounded Deque for Log Buffer

`PipelineLogger.logs` is a `deque(maxlen=10_000)`. When the buffer is full, the oldest entries are automatically discarded.

**Why:** Prevents unbounded memory growth for long-running pipelines without requiring explicit eviction logic.

### 6.8 Lazy Import Pattern

All heavy ML dependencies are imported inside `setup()` or `process()` methods, not at module level. This is consistent across all 29 plugin nodes.

**Why:** Allows the plugin to be loaded and registered without its dependencies installed. The error surfaces only when the node is actually executed, with a clear `ImportError` message.

### 6.9 Frozen Pydantic Models for IR

`GraphIR`, `IRNode`, `IREdge`, and `IRMetadata` all use `ConfigDict(frozen=True)`. This prevents accidental mutation of the graph after construction.

**Why:** The IR is the source of truth for a pipeline run. Mutating it after construction would create inconsistencies between the stored `graph.json` and the actual execution.

---

## 7. Extension Points

### 7.1 Adding a New Node Type

1. Create a new plugin package directory under `PluginPackage/Audio/` or `PluginPackage/Common/`
2. Implement `nodes.py` with a `Node` subclass declaring `node_type`, `metadata`, `input_ports`, `output_ports`, `Config`, and `process()`
3. Create `plugin.toml` with `name`, `version`, `entry_points = ["nodes.py"]`
4. Create `__init__.py`
5. The node is automatically discovered and registered at startup

No changes to the engine, registry, or any other file are required.

### 7.2 Adding a New Port Data Type

1. Create a new file in `app/models/` with a class that subclasses `PortDataType`
2. `AutoDiscovery` will register it in `TypeCatalogue` at startup
3. Use it as `data_type` in `InputPort` or `OutputPort` declarations

### 7.3 Adding a New API Endpoint

1. Create `app/api/routers/my_router.py` with `router = APIRouter()`
2. Import and include in `app/api/main.py`: `app.include_router(my_router, prefix="/api/v1", dependencies=_deps)`

### 7.4 Adding a New MCP Tool

1. Create a handler function in the appropriate `app/mcp/handlers/` file
2. Register it in `app/mcp/tool_registry.py` via `_register(name, description, schema, handler)`

### 7.5 Adding a New Event Source

1. Subclass `EventSource` in `app/core/events.py`
2. Implement `watch()` as an async generator
3. Register in `_SOURCE_REGISTRY` with a string key

### 7.6 Adding a New Execution Mode

The `run_pipeline_ir_async()` function accepts boolean flags (`parallel`, `streaming`, `event_driven`, `checkpoint`). New modes can be added as additional flags with corresponding logic in the execution loop.


---

## 8. Coupling and Abstraction Boundaries

### 8.1 Strong Boundaries (Well-Enforced)

**IR Layer ↔ Everything else:** `app/core/ir/` has zero imports from `app/core/pipeline.py`, `app/core/nodes/`, or `app/core/sdk.py`. It only uses Pydantic and the standard library. This is explicitly documented in the module docstring. This boundary is clean and well-maintained.

**Config Layer ↔ Everything else:** `app/core/config.py` has zero internal imports. All other modules import from it, never the reverse.

**Data Models ↔ Node System:** `app/models/` subclasses `PortDataType` from `app/core/nodes/ports.py`, but the node system does not import from `app/models/`. The coupling is one-directional.

### 8.2 Intentional Coupling

**SDK → Pipeline:** `app/core/sdk.py` imports `run_pipeline_ir` from `pipeline.py`. This is the intended coupling — the SDK is the primary programmatic interface to the execution engine.

**Pipeline → RunManager, Logger, Cache:** The execution loop directly instantiates and uses these services. They are injectable (passed as parameters) but the defaults are created inside the function.

**PluginLoader → AutoDiscovery:** `PluginLoader` uses `AutoDiscovery._import_file()` and `_process_module()` — private methods of `AutoDiscovery`. This is a tight coupling that bypasses the public `AutoDiscovery.run()` interface.

### 8.3 Problematic Coupling

**`pipeline.py` → `artifact_store.py`, `provenance.py`:** The execution loop directly calls `run_manager.register_artifact()` for every node output. This couples the execution loop to the artifact system. If artifact registration fails, it is silently logged and skipped — but the coupling means the execution loop must know about artifact types.

**`pipeline.py` → `_infer_artifact_type()`:** The artifact type inference function lives in `pipeline.py` but is also imported by `executor.py`. This creates a circular-ish dependency where the parallel executor imports from the sequential executor's module.

**`run_manager.py` → `pipeline.py`:** `RunManager.load_resume_state()` imports `ResumeError` from `pipeline.py` inside the method to avoid a circular import. This is a code smell — `ResumeError` should live in a separate errors module.

**`sdk.py` → `pipeline.py` → `run_manager.py` → `pipeline.py`:** `run_manager.py` imports `_load_checkpoint_outputs` from `pipeline.py` inside `find_latest_checkpoint()`. This creates a circular dependency that is resolved by lazy imports inside methods.

### 8.4 Shared Utilities

**`app/core/utils/hash.py` — `stable_hash()`:** Used by `PipelineGraph._build()` to compute deterministic per-node seeds from the pipeline seed, node type, and position. This ensures reproducibility — the same pipeline with the same seed always produces the same node seeds.

**`app/core/nodes/compat.py` — `_type_to_schema()`:** Used by `Node.port_schemas()` and `NodeRegistry.get_port_schema()` to convert Python types to JSON Schema dicts for API responses.

---

## 9. Lifecycle Flows

### 9.1 Application Startup

```
Process starts (uvicorn / python -m app.cli.main / graphyn mcp)
  │
  ├── import app.core.nodes
  │   └── app/core/nodes/__init__.py
  │       ├── from app.core.nodes.registry import NodeRegistry
  │       ├── registry = NodeRegistry()  ← singleton created
  │       ├── PluginManager(registry).load_enabled_plugins()
  │       │   └── For each enabled plugin in ~/.graphyn/plugins/registry.json:
  │       │       └── PluginLoader.load(install_path) → register node types
  │       └── AutoDiscovery(registry).run(
  │               nodes_dir="app/core/nodes",
  │               plugins_dir=plugins_home(),
  │               models_dir="app/models"
  │           )
  │           ├── scan app/core/nodes/*.py (framework files, no node impls)
  │           ├── scan app/models/*.py → TypeCatalogue
  │           └── scan plugins/{name}/ → PluginLoader.load() for each
  │
  └── Registry fully populated with all 29 node types
```

### 9.2 Node Execution Lifecycle

```
PipelineGraph._build()
  └── node = NodeClass(config=..., seed=..., observer=...)
      └── Config.model_validate(config)  ← Pydantic validation

NodeExecutor.setup()
  └── node.setup()  ← one-time init (load models, open files)

For each execution attempt:
  node.on_start()
  observer.on_node_start()  ← NOTE: fires twice (bug)
  outputs = node.process(inputs)
  node.on_end()
  observer.on_node_end()    ← NOTE: fires twice (bug)

On failure:
  node.on_error(exc)
  observer.on_node_error()  ← NOTE: fires twice on final failure (bug)
  [retry if attempts remaining]

NodeExecutor.teardown()
  └── node.teardown()  ← release resources
```

### 9.3 Plugin Installation Lifecycle

```
PluginManager.install(source)
  ├── PluginInstaller.resolve(source) → temp_dir
  ├── load_manifest(temp_dir) → PluginManifest
  ├── shutil.copytree(temp_dir, install_path)
  ├── cleanup temp_dir (finally)
  ├── PluginLoader.load(install_path)
  │   ├── check compat/deps
  │   └── register node types → NodeRegistry
  └── PluginStore.save(PluginRecord)

PluginManager.uninstall(name)
  ├── _unload_node_types(record) → NodeRegistry.unregister() for each
  ├── PluginStore.delete(name)
  └── shutil.rmtree(install_path)

PluginManager.disable(name)
  ├── _unload_node_types(record)
  └── PluginStore.update_enabled(name, False)

PluginManager.enable(name)
  ├── PluginLoader.load(install_path) → re-register node types
  └── PluginStore.update_enabled(name, True)
```

### 9.4 Run Lifecycle

```
RunManager.__init__()
  ├── run_id = uuid4()[:16]
  ├── mkdir workspace/runs/{run_id}/
  └── write meta.json {status: "running"}

run.save_graph_ir(graph_data)
  ├── write graph.json
  └── compute self._graph_hash

register_active_run(run)
  └── _ACTIVE_RUNS[run.run_id] = run

[pipeline executes]

On success:
  run.save_metadata({status: "completed", duration_s: ..., node_stats: ...})
  run.save_logs(logger.logs)
  deregister_active_run(run.run_id)

On failure:
  run.mark_failed(str(exc))
  run.save_logs(logger.logs)
  deregister_active_run(run.run_id)

On cancel:
  run.mark_cancelled()
  run.save_logs(logger.logs)
  deregister_active_run(run.run_id)
```


---

## 10. Inconsistencies Between Design Intent and Implementation

This section documents cases where the actual implementation diverges from the stated or implied design intent. All items are derived from reading the source code directly.

### 10.1 Dual `run_id` Variables

**Intent:** A single `run_id` identifies a run across all subsystems.

**Reality:** `RunManager` generates a 16-char hex `run_id`. `run_pipeline_ir_async()` creates a separate full UUID4 `run_id` and passes it to `NodeExecutor`. Observer events reference the UUID4; the persisted run directory uses the 16-char hex. These are different values.

**Impact:** Any tooling that correlates observer events with run metadata will fail silently.

### 10.2 `run_pipeline_ir_async` Defined Twice

**Intent:** One canonical async execution function.

**Reality:** The function appears twice in `pipeline.py` (lines ~450 and ~680). The second definition silently shadows the first. The first definition is dead code.

### 10.3 `Pipeline.validate()` Is Broken

**Intent:** `Pipeline.validate()` returns a list of validation error strings.

**Reality:** Calls `validate_pipeline(pipeline_cfg)` without the required `registry` argument, always raising `TypeError`, which is caught and returned as an error string. The method always returns a non-empty error list.

### 10.4 Observer Events Fire Twice Per Node

**Intent:** Each lifecycle event fires once per node execution.

**Reality:** `Node.on_start()` calls `observer.on_node_start()` internally. `NodeExecutor.execute()` also calls `observer.on_node_start()` directly after calling `node.on_start()`. Same for `on_end` and `on_error`. Every observer receives two events per lifecycle transition.

### 10.5 Hardcoded Workspace Paths in Two Routers

**Intent:** All workspace paths resolved via `app/core/config.py`.

**Reality:** `app/api/routers/system.py` uses `Path("workspace").resolve()` and `app/api/routers/pipelines.py` uses `Path("workspace/configs/templates")`. These are CWD-relative and ignore `GRAPHYN_PROJECT_DIR`.

### 10.6 `PipelineNode._ir_node` Always Has `_0` Suffix

**Intent:** Each node in a pipeline has a unique ID based on its position.

**Reality:** `PipelineNode.__init__()` creates `self._ir_node` with `id=f"{node_type}_0"` regardless of position. The correct ID is only assigned when `to_ir_node(node_index)` is called during `Pipeline._build_ir()`. The `_ir_node` attribute (used by `to_dict()`) is always wrong for non-first nodes of the same type.

### 10.7 Graph Hash Computed Twice Per Run

**Intent:** Compute the graph hash once and reuse it.

**Reality:** `run.save_graph_ir(dump_ir(graph))` computes and stores `run._graph_hash`. Then `run_pipeline_ir_async()` computes it again independently. The second computation is redundant.

### 10.8 `ArtifactStore` Serialization Inside Global Lock

**Intent:** Thread-safe artifact registration for parallel execution.

**Reality:** The entire `register()` method — including WAV file serialization which can take seconds — runs under `self._lock`. This serializes all artifact registrations, defeating the parallelism of wave-based execution.

### 10.9 MCP Auth Token Read at Import Time

**Intent:** Auth token is read from the environment at request time.

**Reality:** Both `app/mcp/auth.py` and `app/api/main.py` read `GRAPHYN_API_TOKEN` at module import time. If the env var is set after import (e.g., by a secrets manager), auth is bypassed for the entire process lifetime.

### 10.10 `document_processor` Plugin Is Empty

**Intent:** A document processing plugin node.

**Reality:** `PluginPackage/Audio/document_processor/` exists but contains no files. It is referenced in the directory structure but has no implementation.

### 10.11 `audio_exporter` Has No `__init__.py`

**Intent:** All plugin packages are proper Python packages.

**Reality:** `PluginPackage/Audio/audio_exporter/` has `nodes.py` and `plugin.toml` but no `__init__.py`. Inconsistent with all other plugins.

### 10.12 `setup.py` Uses Open Version Ranges

**Intent:** Reproducible dependency resolution.

**Reality:** `requirements.txt` pins exact versions (correct). `setup.py` uses open ranges (`fastapi>=0.100.0`, `numpy>=1.24.0`). When installed as a library, pip may resolve incompatible versions. The two files are not kept in sync.

### 10.13 `PipelineCache.has()` TOCTOU Not Fixed at Call Site

**Intent:** Cache lookups are atomic.

**Reality:** The `has()` docstring explicitly warns about TOCTOU. The call site in `executor.py` still calls `cache.has()` then `cache.load()` as two separate operations. The fix (call `load()` directly) is documented but not applied.

### 10.14 `_write_checkpoint` Only Saves First List Port

**Intent:** All node outputs are checkpointed for resume.

**Reality:** `_write_checkpoint()` iterates `outputs.values()` and breaks on the first `list` value. Multi-port nodes that produce lists on multiple ports will have all but the first silently dropped from the checkpoint.

### 10.15 `WebhookService._config_cache` Not Initialized in `__init__`

**Intent:** Clean object initialization.

**Reality:** `WebhookService` has no `__init__`. The `_config_cache` attribute is created lazily via `hasattr` in `notify()` and invalidated by setting it to `None` in `save()`. This is fragile — the attribute does not exist until `notify()` is first called.

---

*Document generated from source code analysis. Last updated: May 2026.*
*Cross-reference: `docs/DEEP_TECH_REVIEW.md` for severity ratings and fix recommendations.*
