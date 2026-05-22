# Graphyn Platform — Team Takeover Document

**Date:** 2026-05-18  
**Prepared by:** Incoming Engineering Team  
**Purpose:** Complete mental model, current state, open work, and operating guide for the new team taking ownership of this project.

---

## Table of Contents

1. [What This Project Is](#1-what-this-project-is)
2. [Mental Model — How Everything Fits Together](#2-mental-model)
3. [Codebase Map](#3-codebase-map)
4. [Data Flow — End to End](#4-data-flow-end-to-end)
5. [The 29 Plugin Nodes](#5-the-29-plugin-nodes)
6. [Current State Assessment](#6-current-state-assessment)
7. [Open Work Items](#7-open-work-items)
8. [How to Run the System](#8-how-to-run-the-system)
9. [How to Add a New Node](#9-how-to-add-a-new-node)
10. [How to Add a New API Endpoint](#10-how-to-add-a-new-api-endpoint)
11. [Key Conventions and Rules](#11-key-conventions-and-rules)
12. [Where to Find Things](#12-where-to-find-things)

---

## 1. What This Project Is

**Graphyn** is a general-purpose AI/workflow execution platform. Its primary domain is **audio ML** — the full lifecycle from raw audio ingestion through feature extraction, model training, evaluation, and edge deployment.

The platform is built around a **DAG pipeline engine**. Users compose pipelines from typed, pluggable nodes and execute them through any of four equal interfaces:

| Interface | Entry Point | Audience |
|---|---|---|
| REST API | `app/api/main.py` → `http://localhost:8001/api/v1/` | Backend engineers, integrations |
| Python SDK | `app/core/sdk.py` | Data scientists, ML engineers |
| CLI | `app/cli/main.py` (`graphyn` command) | DevOps, automation, CI/CD |
| MCP Server | `app/mcp/server.py` (stdio JSON-RPC) | AI agents (Claude, GPT-4, etc.) |

All four interfaces share **one execution engine** in `app/core/`. There is no translation layer.

**The Visual UI (`audiobuilder/`) has been deprecated.** It is not maintained and has known API mismatches. Ignore it.


---

## 2. Mental Model

Think of Graphyn in five concentric layers. Each layer depends only on the layers below it.

```
┌─────────────────────────────────────────────────────────────────────┐
│  INTERFACE LAYER                                                    │
│  REST API · Python SDK · CLI · MCP Server                          │
│  All call run_pipeline_ir() — nothing else                         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  EXECUTION LAYER                                                    │
│  pipeline.py — DAG builder, topo sort, sequential/parallel executor │
│  executor.py — wave-based asyncio + ThreadPool (parallel mode)     │
│  conditions.py — safe AST evaluator for conditional edges          │
│  events.py — FileWatcher / Timer / Queue sources (event-driven)    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  NODE LAYER                                                         │
│  nodes/base.py — Node base class, SISO wrapper, lifecycle hooks    │
│  nodes/registry.py — singleton: node_type string → Node class      │
│  nodes/discovery.py — AutoDiscovery: scans plugins/ at startup     │
│  nodes/metadata.py — NodeMetadata with 10 capability fields        │
│  nodes/ports.py — InputPort, OutputPort, PortDataType base         │
│  nodes/compat.py — CompatibilityChecker for port type validation   │
│  PluginPackage/ — 29 node implementations (none in app/core/nodes/)│
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  IR LAYER (Intermediate Representation)                             │
│  ir/models.py — GraphIR, IRNode, IREdge, IRMetadata (Pydantic)     │
│  ir/loader.py — load_ir(), dump_ir(), version check                │
│  ir/yaml_shim.py — YAML → GraphIR (deprecated input path)         │
│  ir/migrate.py — YAML file → .graph.json file (migration tool)    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│  BACKEND SERVICES LAYER                                             │
│  run_manager.py — run lifecycle, pause/resume/cancel, checkpoints  │
│  artifact_store.py — content-addressed storage, SHA-256 dedup      │
│  provenance.py — lineage tracking, get_lineage() recursive tree    │
│  pipeline_cache.py — SHA-256 keyed node output cache               │
│  logger.py — structured JSON event emission                        │
│  ingestion.py — URL + HuggingFace dataset download                 │
│  project_manager.py — project lifecycle                            │
└─────────────────────────────────────────────────────────────────────┘
```

### The Single Most Important Fact

**`run_pipeline_ir(graph: GraphIR)` in `app/core/pipeline.py` is the only execution entry point.**

Every interface — REST API, SDK, CLI, MCP — ultimately calls this one function. If you understand what it does, you understand the whole system.

What it does, in order:
1. Converts `GraphIR` → `PipelineConfig` (internal data structure)
2. Builds `PipelineGraph`: instantiates nodes, validates edge types, runs Kahn's topological sort, computes parallel execution waves
3. Creates a `RunManager` (writes `workspace/runs/{run_id}/meta.json`)
4. For each node in topological order: assemble inputs from upstream outputs → check cache → `NodeExecutor.execute()` → save cache → write checkpoint → register artifact
5. Writes final `meta.json` (status=completed), returns outputs dict

### The GraphIR Is the Canonical Format

All pipelines are stored and transmitted as `GraphIR` JSON (`.graph.json`). YAML is a deprecated legacy format — the system accepts it via `yaml_shim.py` but emits a `DeprecationWarning`. Never generate new YAML pipelines.

```json
{
  "schema_version": "1.1",
  "metadata": {"name": "my-pipeline", "seed": 42},
  "nodes": [
    {"id": "ingest_0", "node_type": "dataset_ingest", "config": {"path": "workspace/datasets/input/speech"}},
    {"id": "cond_1",   "node_type": "audio_conditioner", "config": {"sample_rate": 16000}}
  ],
  "edges": [
    {"src_id": "ingest_0", "src_port": "output", "dst_id": "cond_1", "dst_port": "input"}
  ]
}
```


---

## 3. Codebase Map

```
newAudio3/
├── app/
│   ├── api/
│   │   ├── main.py                  ← FastAPI app factory (thin — no logic here)
│   │   └── routers/                 ← 10 routers, all under /api/v1/
│   │       ├── nodes.py             ← GET /nodes, GET /nodes/{type}, etc.
│   │       ├── pipelines.py         ← POST /pipelines/run (NDJSON stream)
│   │       ├── runs.py              ← GET /runs, GET /runs/{id}/status, etc.
│   │       ├── run_control.py       ← POST /runs/{id}/pause|resume|cancel
│   │       ├── data.py              ← GET/POST /data/inputs|outputs
│   │       ├── system.py            ← GET /system/health, webhooks
│   │       ├── projects.py          ← full project lifecycle
│   │       ├── ingest.py            ← POST /ingest/url|huggingface (SSE)
│   │       ├── artifacts.py         ← GET /artifacts, lineage, replay
│   │       └── plugins.py           ← install/enable/disable/uninstall
│   ├── cli/
│   │   └── main.py                  ← argparse CLI, 14 subcommands
│   ├── core/
│   │   ├── pipeline.py              ← ★ PRIMARY EXECUTOR — read this first
│   │   ├── executor.py              ← parallel wave executor (asyncio + ThreadPool)
│   │   ├── sdk.py                   ← Pipeline, PipelineNode, ArtifactCollection
│   │   ├── run_manager.py           ← run lifecycle, pause/resume/cancel
│   │   ├── artifact_store.py        ← content-addressed artifact storage
│   │   ├── provenance.py            ← lineage tracking
│   │   ├── pipeline_cache.py        ← SHA-256 keyed cache
│   │   ├── logger.py                ← structured event emission
│   │   ├── ingestion.py             ← URL + HuggingFace ingestion
│   │   ├── project_manager.py       ← project lifecycle
│   │   ├── conditions.py            ← safe condition expression evaluator
│   │   ├── events.py                ← FileWatcher / Timer / Queue sources
│   │   ├── config.py                ← reads all env vars (use this, not os.environ)
│   │   ├── registry_runtime.py      ← get_registry() singleton accessor
│   │   ├── validation.py            ← pipeline validation helpers
│   │   ├── webhook.py               ← outbound webhook delivery
│   │   ├── quality_checker.py       ← dataset quality analysis
│   │   ├── runtime_backend.py       ← RuntimeBackend ABC + LocalPythonBackend
│   │   ├── ir/
│   │   │   ├── models.py            ← GraphIR, IRNode, IREdge (Pydantic, frozen)
│   │   │   ├── loader.py            ← load_ir(), dump_ir(), version check
│   │   │   ├── yaml_shim.py         ← YAML → GraphIR (deprecated)
│   │   │   └── migrate.py           ← YAML file → .graph.json
│   │   ├── nodes/
│   │   │   ├── base.py              ← Node base class, SISO wrapper
│   │   │   ├── registry.py          ← NodeRegistry singleton
│   │   │   ├── discovery.py         ← AutoDiscovery (scans plugins/ at startup)
│   │   │   ├── metadata.py          ← NodeMetadata + capability fields
│   │   │   ├── ports.py             ← InputPort, OutputPort, PortDataType
│   │   │   ├── config.py            ← NodeConfig (Pydantic base)
│   │   │   ├── compat.py            ← CompatibilityChecker
│   │   │   ├── catalogue.py         ← TypeCatalogue (FQN → type)
│   │   │   ├── retry.py             ← RetryPolicy (exponential backoff)
│   │   │   ├── observers.py         ← NodeObserver / LoggingObserver
│   │   │   └── errors.py            ← exception hierarchy
│   │   └── plugins/
│   │       ├── manager.py           ← PluginManager (single entry point)
│   │       ├── installer.py         ← source resolver (local/git/http/index)
│   │       ├── loader.py            ← manifest load + node registration
│   │       ├── store.py             ← PluginRecord persistence
│   │       ├── manifest.py          ← PluginManifest Pydantic model
│   │       ├── index.py             ← PluginIndexClient (remote index)
│   │       ├── dependencies.py      ← DependencyChecker
│   │       └── errors.py            ← plugin exception hierarchy
│   ├── mcp/
│   │   ├── server.py                ← stdio JSON-RPC server
│   │   ├── auth.py                  ← token auth middleware
│   │   ├── tool_registry.py         ← 15 tool registrations
│   │   └── handlers/                ← one file per tool group
│   └── models/                      ← platform-core PortDataType subclasses
│       ├── audio_sample.py          ← AudioSample (float32 waveform)
│       ├── feature_array.py         ← FeatureArray (float32 [T,F])
│       ├── tensor_batch.py          ← TensorBatch (float32 [N,...])
│       ├── model_artifact.py        ← ModelArtifact (Keras SavedModel)
│       ├── tflite_artifact.py       ← TFLiteArtifact (.tflite flatbuffer)
│       ├── prediction_result.py     ← PredictionResult (inference output)
│       ├── deployment_artifact.py   ← DeploymentArtifact (packaged model)
│       └── data_sample.py           ← DataSample (domain-agnostic base)
├── PluginPackage/
│   ├── Audio/                       ← 18 audio plugin nodes
│   ├── Common/                      ← 11 cross-domain plugin nodes
│   ├── Video/                       ← empty placeholder (future)
│   ├── ARCHITECTURE.md              ← plugin architecture reference
│   └── NODES.md                     ← full node capability matrix
├── plugins/                         ← install target (managed by PluginManager)
├── tests/                           ← 35 test files
├── docs/                            ← 17 documentation files
├── requirements.txt                 ← pinned core deps
└── workspace/                       ← runtime data (created on first run)
```


---

## 4. Data Flow — End to End

### A. SDK / CLI path

```
User code: Pipeline([PipelineNode("dataset_ingest", {...}), ...]).run()
    │
    ▼
sdk.Pipeline._build_ir()
    └── builds GraphIR from PipelineNode list (auto-chains edges linearly,
        or uses explicit edges for multi-port nodes)
    │
    ▼
sdk.Pipeline.run()
    └── creates RunManager()
    └── calls run_pipeline_ir(graph, run_manager=run_manager)
    │
    ▼
pipeline.run_pipeline_ir()  [sync shim]
    └── asyncio.run(run_pipeline_ir_async(...))
    │
    ▼
pipeline.run_pipeline_ir_async()
    ├── run.save_graph_ir(dump_ir(graph))   → workspace/runs/{id}/graph.json
    ├── register_active_run(run)            → enables pause/resume/cancel
    ├── _ir_to_pipeline_config(graph)       → PipelineConfig
    ├── PipelineGraph(config)               → topo sort + execution waves
    │
    └── For each node in topo order:
        ├── assemble inputs from node_outputs[upstream_id]
        ├── evaluate edge conditions (conditions.py)
        ├── cache.has(key)?  → use cached outputs
        │   else → NodeExecutor.execute(inputs)
        │           └── node.setup() [once]
        │           └── node.on_start()
        │           └── node.process(inputs)  ← actual work
        │           └── node.on_end()
        │           └── retry on failure (RetryPolicy)
        ├── cache.save(key, outputs)
        ├── _write_checkpoint(...)           → workspace/runs/{id}/checkpoints/
        └── run.register_artifact(...)       → ArtifactStore + ProvenanceStore
    │
    ▼
run.save_metadata(stats)    → workspace/runs/{id}/meta.json (status=completed)
deregister_active_run(run_id)
    │
    ▼
Returns: ArtifactCollection(artifacts=[...], run_id="...", _raw={node_id: outputs})
```

### B. REST API path

```
POST /api/v1/pipelines/run  {body: GraphIR JSON or {"yaml": "..."}}
    │
    ▼
routers/pipelines.py
    ├── detect format (schema_version key → IR JSON; yaml key → YAML)
    ├── load_ir(data) or yaml_config_to_ir(raw)
    ├── create PipelineLogger(queue=asyncio.Queue())
    ├── create RunManager()
    │
    └── StreamingResponse(content=_stream_pipeline(...))
            └── run_pipeline_ir(graph, logger=logger, run_manager=run_manager)
            └── yield NDJSON events from logger queue
```

### C. Data types flowing between nodes

```
dataset_ingest  →  [AudioSample]  →  audio_conditioner
                                           │
                                    [AudioSample]
                                           │
                                      segmenter
                                           │
                                    [AudioSample]  (with metadata.split set)
                                           │
                                    feature_frontend
                                           │
                                    [FeatureArray]
                                           │
                                    dataset_builder
                                           │
                                    DatasetArtifact  (plugin-owned type)
                                           │
                                       trainer
                                           │
                                    ModelArtifact
                                           │
                                      evaluator
                                           │
                                    ModelArtifact  (with .metrics populated)
                                           │
                                    edge_optimizer
                                           │
                                    TFLiteArtifact / DeploymentArtifact
```


---

## 5. The 29 Plugin Nodes

All nodes live in `PluginPackage/`. None are in `app/core/nodes/` — that directory contains only the framework (base class, registry, discovery). Nodes are loaded at startup by `AutoDiscovery` scanning `plugins/` (the install target).

### Audio Plugins — 18 nodes (`PluginPackage/Audio/`)

| node_type | Category | What it does |
|---|---|---|
| `dataset_ingest` | Input | Load audio from filesystem, S3, HuggingFace, archives, manifests |
| `stream_ingest` | Input | Capture live audio from mic, WebSocket, RTP, RTSP |
| `audio_conditioner` | Preprocessing | Resample, normalize (LUFS/peak/RMS), silence trim, mono, DC removal |
| `audio_quality_gate` | Preprocessing | Reject audio failing SNR, clipping, silence, loudness, bandwidth checks |
| `audio_annotator` | Preprocessing | Attach labels, taxonomy, confidence scores to audio |
| `alignment_node` | Preprocessing | Forced alignment: phoneme/word/subtitle timing (CTC or MFA) |
| `segmenter` | Processing | Split by fixed windows, VAD, silence, speaker turns, events |
| `augmentation_pipeline` | Augmentation | Probabilistic chain: noise, reverb, pitch shift, codec, EQ, time stretch |
| `speech_enhancer` | Enhancement | Denoise (RNNoise/DeepFilterNet), dereverberate, vocal isolation |
| `speaker_separator` | Enhancement | Separate speakers from mixed audio |
| `environment_simulator` | Enhancement | Simulate room/car/outdoor acoustics via RIR |
| `feature_frontend` | Features | Log-mel, MFCC, spectrogram, chroma, raw waveform extraction |
| `stream_processor` | Streaming | Rolling windows, overlap-add, latency management |
| `audio_event_detector` | Detection | Detect and timestamp acoustic events (gunshot, cough, alarm, etc.) |
| `audio_classifier` | Inference | Classify audio scenes, emotions, languages, commands |
| `speech_synthesizer` | Generation | TTS, voice cloning (Coqui TTS), multilingual synthesis |
| `voice_converter` | Generation | Voice/accent/timbre/style/gender conversion |
| `audio_generator` | Generation | Music, ambience, Foley generation (AudioCraft) |

### Common Plugins — 11 nodes (`PluginPackage/Common/`)

| node_type | Category | What it does |
|---|---|---|
| `dataset_builder` | ML | Assemble features into train/val/test splits (NumPy/TF/PyTorch) |
| `dataset_balancer` | ML | Fix class imbalance via oversampling, undersampling, weighting |
| `dataset_versioner` | ML | SHA-256 hash datasets, immutable snapshots, lineage metadata |
| `trainer` | ML | Train Keras/PyTorch models with checkpointing, early stopping |
| `evaluator` | ML | Accuracy, F1, ROC, confusion matrix, fairness metrics |
| `experiment_tracker` | ML | Log params/metrics/artifacts to JSON or MLflow |
| `edge_optimizer` | ML | Quantize to INT8/float16 via TFLite or ONNX |
| `deployment_packager` | ML | Package for mobile ZIP, MCU C header, Docker, edge TAR |
| `realtime_inference` | Inference | Low-latency streaming inference (TFLite/PyTorch/ONNX) |
| `embedding_generator` | Features | wav2vec2, HuBERT, CLAP, YAMNet, x-vector, OpenL3 embeddings |
| `multimodal_fusion` | Features | Fuse audio + text + video via concatenation, attention, cross-attention |

### The 52 Documented Use-Case Pipelines

`PluginPackage/Audio/audioml_usecase.csv` documents 52 complete pipeline recipes covering: speech command training, wake word detection, speaker verification, diarization, meeting transcription, speech enhancement, ASR, acoustic event detection, emotion recognition, language ID, scene classification, semantic audio search, podcast processing, voice cloning, TTS, music generation, synthetic data, dataset curation, telephony AI, call center analytics, audio moderation, edge deployment, TinyML, multimodal agents, and more.


---

## 6. Current State Assessment

### What is complete and production-quality

| Area | Status | Notes |
|---|---|---|
| Core execution engine | ✅ Complete | All 6 execution modes: sequential, parallel, streaming, event-driven, resumable, partial |
| Graph IR (v1.0 + v1.1) | ✅ Complete | Versioned, validated, migration tool included |
| All 29 plugin nodes | ✅ Complete | 18 Audio + 11 Common, all with accurate capability metadata |
| REST API (10 routers) | ✅ Complete | 50+ endpoints, NDJSON streaming, SSE ingestion |
| Python SDK | ✅ Complete | `Pipeline`, `PipelineNode`, `ArtifactCollection` |
| CLI (14 commands) | ✅ Complete | Including Phase 3 flags (parallel, resume, partial, event-driven) |
| MCP Server (15 tools) | ✅ Complete | All tools, auth middleware, correct error contract |
| ArtifactStore | ✅ Complete | Content-addressed, SHA-256 dedup, 6 artifact types |
| ProvenanceStore | ✅ Complete | Lineage tracking, recursive `get_lineage()`, never raises |
| Plugin ecosystem | ✅ Complete | PluginManager, installer, loader, store, manifest validation |
| Test suite | ✅ Complete | 35 test files, Hypothesis property-based testing |
| Documentation | ✅ Complete | 17 docs files, all substantive |

### What is incomplete or has known issues

| Area | Severity | Detail |
|---|---|---|
| `run-async` dual status tracking | 🟠 High | In-memory `_async_runs` dict lost on server restart. See `KNOWN_ISSUES.md` #1. |
| `PluginPackage/Audio/audio_utils/` | 🟠 High | Empty directory — intent unknown. See `GAP_ANALYSIS.md` #4. |
| `PluginPackage/Video/` | 🟢 Low | Empty placeholder for future Video domain. No action needed. |
| Visual UI (`audiobuilder/`) | ❌ Deprecated | Wrong API paths, YAML-only, linear pipelines only. Do not maintain. |

### Phase history (what was built when)

| Phase | Key additions |
|---|---|
| 1 | Node base, typed ports, NodeRegistry, AutoDiscovery, SISO wrapper |
| 2 | Graph IR v1.0, YAML shim, SDK, CLI |
| 3 | Parallel executor, streaming, event-driven, conditional edges, partial execution, resumability, pause/resume/cancel |
| 4 | ArtifactStore, ProvenanceStore, ArtifactCollection, artifact replay |
| 5 | Plugin ecosystem: PluginManager, PluginInstaller, PluginLoader, PluginStore, PluginIndexClient |
| 6–8 | All 29 plugin nodes implemented |

---

## 7. Open Work Items

### Priority 1 — Fix `run-async` status tracking (Gap #5)

**File:** `app/api/routers/pipelines.py`  
**Problem:** `POST /api/v1/pipelines/run-async` maintains an in-memory `_async_runs` dict that is lost on server restart. Any code polling this dict after a restart sees stale/missing state.  
**Fix:** Remove `_async_runs` entirely. Route all status reads through `RunManager` / `meta.json`. The `run_id` returned by `run-async` is sufficient to query `GET /api/v1/runs/{run_id}/status`.

### Priority 2 — Resolve `audio_utils/` ambiguity (Gap #4)

**File:** `PluginPackage/Audio/audio_utils/` (empty directory)  
**Problem:** Directory exists with no files. Not referenced in `NODES.md` or the capability matrix. Intent unknown.  
**Options:** (a) implement the node if it was planned, (b) delete the directory if it is a leftover, (c) add a `README.md` if it is a future placeholder. Update `PluginPackage/NODES.md` accordingly.

### Priority 3 — Roadmap items (from `PRODUCT_OVERVIEW.md`)

These are planned but not started:

1. **Web UI** — browser-based pipeline management. The REST API is complete; this is purely a frontend build. No backend changes required.
2. **Environment isolation per node** — each node runs in its own Python runtime with separate deps and resource limits. Enables conflicting deps (TF vs PyTorch) side by side and distributed execution.
3. **Video Processing domain** — new `PluginPackage/Video/` plugin package covering the full video ML lifecycle. Placeholder directory already exists.
4. **Document Processing domain** — new plugin package for PDF/DOCX/HTML/OCR workflows, composable with Audio and Video plugins.


---

## 8. How to Run the System

### Prerequisites

```bash
# Create and activate venv
python3.10 -m venv venv
source venv/bin/activate

# Install core deps
venv/bin/pip install -r requirements.txt

# Install the SDK package (makes `graphyn` CLI available)
venv/bin/pip install -e .
```

### Start the API server

```bash
venv/bin/uvicorn app.api.main:app --reload --port 8001
# API available at http://localhost:8001/api/v1/
# Health check: curl http://localhost:8001/api/v1/system/health
```

### Run a pipeline via CLI

```bash
# IR JSON (canonical)
graphyn run --graph examples/01_wake_word/pipeline.graph.json

# With parallel execution
graphyn run --graph my_pipeline.graph.json --parallel

# Resume a failed run
graphyn run --graph my_pipeline.graph.json --resume <run_id>

# Validate before running
graphyn validate --graph my_pipeline.graph.json

# Migrate YAML to IR JSON
graphyn migrate --config old_pipeline.yaml
```

### Run a pipeline via SDK

```python
from app.core.sdk import Pipeline, PipelineNode

# Install plugins first (only needed once)
from app.core.plugins.manager import PluginManager
manager = PluginManager()
manager.install("PluginPackage/Audio/dataset_ingest/", upgrade=True)
manager.install("PluginPackage/Audio/audio_conditioner/", upgrade=True)
manager.install("PluginPackage/Audio/feature_frontend/", upgrade=True)
manager.install("PluginPackage/Common/dataset_builder/", upgrade=True)
manager.load_enabled_plugins()

# Build and run
pipeline = Pipeline([
    PipelineNode("dataset_ingest",    {"path": "workspace/datasets/input/speech"}),
    PipelineNode("audio_conditioner", {"sample_rate": 16000}),
    PipelineNode("feature_frontend",  {"feature_type": "mfcc"}),
    PipelineNode("dataset_builder",   {}),
], seed=42)

result = pipeline.run(use_cache=True, checkpoint=True)
print(f"Run ID: {result.run_id}")
print(f"Artifacts: {result.artifacts}")
```

### Start the MCP server (for AI agents)

```bash
graphyn mcp
# or
venv/bin/python -m app.mcp.server
```

### Run tests

```bash
venv/bin/pytest                          # all tests
venv/bin/pytest tests/ -x -q            # fail fast, quiet
venv/bin/pytest tests/mcp/ -v           # MCP tests only
venv/bin/pytest tests/test_pipeline_dag.py -v  # specific file
```

### Environment variables

```bash
export GRAPHYN_API_TOKEN="my-secret-token"   # enable API auth
export GRAPHYN_PROJECT_DIR="workspace"        # runtime data root
export GRAPHYN_HOME="~/.graphyn"              # platform home
export GRAPHYN_PLUGINS_DIR="plugins"          # plugin install dir
export GRAPHYN_PLUGIN_AUTO_INSTALL="1"        # auto-pip-install plugin deps
```

**Always read env vars through `app/core/config.py` — never call `os.environ` directly.**


---

## 9. How to Add a New Node

This is the most common development task. Follow these steps exactly.

### Step 1 — Create the plugin directory

```
PluginPackage/Audio/my_node/        (or PluginPackage/Common/my_node/)
├── plugin.toml
├── __init__.py
├── types.py                        (only if you define custom PortDataType subclasses)
└── nodes.py
```

### Step 2 — Write `plugin.toml`

```toml
[plugin]
name             = "my-node"
version          = "1.0.0"
description      = "What it does."
author           = "Your Name"
platform_version = ">=0.0"
entry_points     = ["types.py", "nodes.py"]   # types.py MUST come first if it exists
license          = "MIT"
tags             = ["audio"]

dependencies = ["numpy>=1.24", "librosa>=0.10"]
optional_dependencies = ["torch>=2.0"]         # heavy deps go here, NOT in dependencies
```

### Step 3 — Write `nodes.py`

```python
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
        description="What it does.",
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
    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=list[AudioSample], required=True)
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=list[AudioSample])
    }

    class Config(NodeConfig):
        my_param: float = 1.0

    def process(self, samples):   # SISO shorthand — framework handles dict wrapping
        result = []
        for sample in samples:
            # ... transform sample ...
            sample.metadata.update({"my_node": {"my_param": self.config.my_param}})
            result.append(sample)
        return result
```

**SISO shorthand rule:** if your node has exactly one input port named `"input"` and one output port named `"output"`, define `process(self, data)` — the framework auto-wraps it. For multi-port nodes, define `process(self, inputs: dict) -> dict`.

### Step 4 — Write `__init__.py`

```python
from .nodes import MyNode
__all__ = ["MyNode"]
```

### Step 5 — Install and test

```python
from app.core.plugins.manager import PluginManager
from app.core.nodes import registry

manager = PluginManager()
manager.install("PluginPackage/Audio/my_node/", upgrade=True)
manager.load_enabled_plugins()

node_class = registry.get_class("my_node")
node = node_class(config={"my_param": 2.0}, seed=42)
node.setup()
outputs = node.process({"input": my_samples})
node.teardown()
```

### Step 6 — Update documentation (required by update-protocol.md)

1. Add a row to the Registered Plugins table in `.kiro/steering/plugin-development.md`
2. Update `PluginPackage/NODES.md` capability matrix
3. Update `docs/PLUGIN_GUIDE.md`


---

## 10. How to Add a New API Endpoint

### Step 1 — Create or extend a router file

```python
# app/api/routers/my_router.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/my-resource")
async def list_my_resource():
    return {"items": []}

@router.post("/my-resource")
async def create_my_resource(body: dict):
    return {"created": True}
```

### Step 2 — Register in `app/api/main.py`

```python
from app.api.routers.my_router import router as my_router
# ...
app.include_router(my_router, prefix="/api/v1", dependencies=_deps)
```

### Step 3 — Update documentation (required by update-protocol.md)

1. Add rows to `.kiro/steering/api-endpoints.md`
2. Add rows to `docs/API_REFERENCE.md`
3. Update `.kiro/steering/api-structure.md` Active Routers table (if new router file)

---

## 11. Key Conventions and Rules

### Never break these

| Rule | Why |
|---|---|
| Always use `venv/bin/python` | Never use system Python — see `.kiro/steering/python-venv.md` |
| Read env vars via `app/core/config.py` | Never call `os.environ` directly in app code |
| Plugin-domain types go in `types.py` inside the plugin | Never add plugin-specific types to `app/models/` |
| Heavy deps (`torch`, `tensorflow`) go in `optional_dependencies` | Never in `dependencies` — blocks CPU-only installs |
| `from __future__ import annotations` is BANNED in `app/models/` files | Breaks Pydantic v2 `model_rebuild()` when loaded via importlib |
| All new pipelines use IR JSON format | Never generate new YAML pipelines |
| `plugins/` directory is managed by PluginManager | Never edit it directly |
| All API paths are under `/api/v1/` | No root-path endpoints |

### SISO vs multi-port nodes

- **SISO** (single input `"input"`, single output `"output"`): define `process(self, data)` — framework wraps automatically
- **Multi-port**: define `process(self, inputs: dict[str, Any]) -> dict[str, Any]` — you handle all port names

### Capability flags matter

Set all `NodeMetadata` capability flags accurately. They are used by:
- `get_graph_capability_summary` MCP tool (hardware routing)
- `PipelineCache` (respects `cacheable=False`)
- `ParallelExecutor` (respects `cacheable` flag)
- API `GET /nodes?capability=...` filtering
- CLI `graphyn nodes --capability requires_gpu=false`

### Metadata propagation

Every node that transforms audio must add a key to `AudioSample.metadata`:
```python
sample.metadata.update({"my_node": {"key": "value"}})
```
See `.kiro/steering/data-models.md` for the established metadata key conventions.

### Update protocol

After any code change, update the matching steering file AND the matching `docs/` file. See `.kiro/steering/update-protocol.md` for the exact mapping table. This is enforced by the steering system.


---

## 12. Where to Find Things

| I need to... | Go to |
|---|---|
| Understand the full architecture | `docs/ARCHITECTURE.md` |
| See all REST endpoints | `docs/API_REFERENCE.md` or `.kiro/steering/api-endpoints.md` |
| See all 29 nodes with config fields | `PluginPackage/NODES.md` |
| Understand the node base class | `app/core/nodes/base.py` + `.kiro/steering/node-base.md` |
| Understand pipeline execution | `app/core/pipeline.py` + `docs/PIPELINE_EXECUTION.md` |
| Write a new plugin node | `docs/PLUGIN_GUIDE.md` + `.kiro/steering/plugin-development.md` |
| Understand the IR format | `app/core/ir/models.py` + `docs/PIPELINE_EXECUTION.md` |
| Use the SDK | `docs/SDK_AND_CLI.md` + `app/core/sdk.py` |
| Use the CLI | `docs/SDK_AND_CLI.md` + `app/cli/main.py` |
| Use the MCP server | `docs/MCP_SERVER.md` + `app/mcp/` |
| Understand artifact lineage | `docs/BACKEND_CORE.md` + `app/core/artifact_store.py` |
| Understand workspace layout | `docs/DATA_FLOW_AND_WORKSPACE.md` |
| See known issues | `docs/KNOWN_ISSUES.md` |
| See gap analysis | `docs/GAP_ANALYSIS.md` |
| See the product pitch | `docs/PRODUCT_OVERVIEW.md` |
| See 52 use-case pipeline recipes | `PluginPackage/Audio/audioml_usecase.csv` |
| See all node capabilities in CSV | `PluginPackage/Audio/audioml_nodes.csv` |
| Understand plugin architecture | `PluginPackage/ARCHITECTURE.md` |
| Find steering rules for a file | `.kiro/steering/` (auto-loaded based on file being edited) |

### Key files to read first (in this order)

1. `docs/OVERVIEW.md` — system overview
2. `app/core/pipeline.py` — the execution engine (most important file)
3. `app/core/nodes/base.py` — the Node base class
4. `app/core/sdk.py` — the Python SDK
5. `PluginPackage/NODES.md` — all 29 nodes
6. `docs/KNOWN_ISSUES.md` — what's broken

---

*This document was prepared by the incoming engineering team on 2026-05-18 based on a full codebase review. It supersedes any prior onboarding notes. For the authoritative technical reference on any specific subsystem, follow the "Where to Find Things" table above.*
