# Plugin Package — Architecture

## Directory Structure

```
PluginPackage/
├── ARCHITECTURE.md     ← this file — structure, anatomy, data flow, types
├── NODES.md            ← all 29 nodes — config, ports, capabilities
│
├── Audio/              ← 18 audio-domain plugins
│   ├── dataset_ingest/
│   ├── stream_ingest/
│   ├── audio_conditioner/
│   ├── audio_quality_gate/
│   ├── audio_annotator/
│   ├── alignment_node/
│   ├── segmenter/
│   ├── augmentation_pipeline/
│   ├── speech_enhancer/
│   ├── speaker_separator/
│   ├── environment_simulator/
│   ├── feature_frontend/
│   ├── stream_processor/
│   ├── audio_event_detector/
│   ├── audio_classifier/
│   ├── speech_synthesizer/
│   ├── voice_converter/
│   └── audio_generator/
│
├── Common/             ← 11 cross-domain plugins (reusable for any data domain)
│   ├── dataset_builder/
│   ├── trainer/
│   ├── evaluator/
│   ├── edge_optimizer/
│   ├── realtime_inference/
│   ├── dataset_balancer/
│   ├── dataset_versioner/
│   ├── experiment_tracker/
│   ├── deployment_packager/
│   ├── embedding_generator/
│   └── multimodal_fusion/
│
└── Video/              ← future domain (out of scope)
```

## Plugin Anatomy

Every plugin follows this exact structure:

```
plugin_name/
├── __init__.py     # exports node class(es) and any custom types
├── types.py        # custom PortDataType subclasses — list FIRST in entry_points (optional)
├── nodes.py        # node implementation
└── plugin.toml     # manifest: name, version, deps, entry_points
```

If the plugin defines custom types, `types.py` must be listed before `nodes.py` in `entry_points` so the type is registered in `TypeCatalogue` before the node imports it.

**Rule: plugin-domain types belong in `types.py` inside the plugin, never in `app/models/`.**

### `plugin.toml` template

```toml
[plugin]
name             = "plugin-name"          # slug: ^[a-z][a-z0-9_-]*$
version          = "1.0.0"
description      = "One-line description."
author           = "Graphyn Plugins"
platform_version = ">=0.0"
entry_points     = ["types.py", "nodes.py"]   # types.py first if plugin defines custom types
license          = "MIT"
tags             = ["audio"]

dependencies = ["numpy>=1.24", "librosa>=0.10"]   # pinned, no open ranges
optional_dependencies = ["torch>=2.0"]             # heavy deps — node must degrade gracefully
```

### `nodes.py` template

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
        node_type="my_node", label="My Node",
        description="What it does.", category="Processing",
        version="1.0.0", tags=["audio"],
        requires_gpu=False, supports_cpu=True, supports_edge=True,
        deterministic=True, cacheable=True,
        streaming_support=False, realtime_support=False,
    )
    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=list[AudioSample], required=True)
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=list[AudioSample])
    }
    class Config(NodeConfig):
        backend: str = "auto"   # "cpu" | "gpu" | "auto"

    def process(self, samples):   # SISO shorthand
        return samples
```

### Backend pattern (nodes with optional heavy deps)

```python
def setup(self):
    if self.config.backend in ("gpu", "auto"):
        try:
            import torch
            self._backend = "pytorch"
            return
        except ImportError:
            if self.config.backend == "gpu":
                raise ImportError("PyTorch required. venv/bin/pip install torch")
    self._backend = "cpu"
```

### Metadata propagation

Every node that transforms audio adds a key to `AudioSample.metadata`:

```python
sample.metadata.update({"my_node": {"key": "value"}})
```

## Data Flow

```
AudioSample (raw)
    │
    ├── audio_conditioner ──────────── conditioned AudioSample
    │       │
    │       ├── segmenter ─────────── segmented chunks
    │       │       │
    │       │       ├── audio_quality_gate ── validated AudioSample
    │       │       ├── augmentation_pipeline ── augmented AudioSample
    │       │       └── feature_frontend ──── FeatureArray
    │       │               │
    │       │               ├── embedding_generator ── EmbeddingVector
    │       │               └── dataset_builder ────── DatasetArtifact
    │       │                       │
    │       │                       ├── trainer ──────── ModelArtifact
    │       │                       │       └── evaluator ── ModelArtifact (+ metrics)
    │       │                       │               └── edge_optimizer ── DeploymentArtifact
    │       │                       │                       └── deployment_packager ── package
    │       │                       └── dataset_balancer / dataset_versioner / experiment_tracker
    │       │
    │       ├── speech_enhancer ────── cleaned AudioSample
    │       ├── speaker_separator ──── per-speaker AudioSample
    │       └── environment_simulator ─ room-simulated AudioSample
    │
    └── stream_ingest ──────────────── streaming AudioSample chunks
            │
            └── stream_processor ───── windowed chunks
                    └── realtime_inference ── PredictionResult stream
```

## Data Types

### Platform-core types (`app/models/`) — always available

| Type | Key Fields | Produced by |
|---|---|---|
| `AudioSample` | `path`, `sample_rate`, `data` (float32), `label`, `metadata` | `dataset_ingest`, `stream_ingest` |
| `FeatureArray` | `data` (float32 [T,F]), `label`, `sample_rate`, `feature_type`, `metadata` | `feature_frontend` |
| `ModelArtifact` | `model_path`, `labels`, `history`, `metrics` | `trainer`, `evaluator` |
| `TFLiteArtifact` | `tflite_path`, `labels`, `quantisation`, `file_size_bytes` | `edge_optimizer` (TFLite) |
| `PredictionResult` | `source_path`, `predicted_label`, `probabilities`, `metadata` | `realtime_inference`, `audio_classifier` |
| `DeploymentArtifact` | `artifact_path`, `model_format`, `target_hardware`, `quantization`, `labels`, `metadata` | `deployment_packager`, `edge_optimizer` |
| `DataSample` | `id`, `source`, `metadata` | Base type |

### Plugin-owned types — registered only when the owning plugin is installed

| Type | Plugin | Key Fields |
|---|---|---|
| `DatasetArtifact` | `Common/dataset_builder` | `X_train/val/test`, `y_train/val/test`, `labels`, `input_shape`, `n_classes`, `version`, `hash` |
| `EmbeddingVector` | `Common/embedding_generator` | `embedding` (float32 [D]), `source_path`, `label`, `embedding_model`, `pooling` |
| `ExperimentArtifact` | `Common/experiment_tracker` | `run_id`, `experiment_name`, `parameters`, `metrics`, `artifact_paths`, `backend` |

## Install and Use

```python
from app.core.plugins.manager import PluginManager
from app.core.sdk import Pipeline, PipelineNode

manager = PluginManager()
manager.install("PluginPackage/Audio/audio_conditioner/", upgrade=True)
manager.install("PluginPackage/Audio/segmenter/", upgrade=True)
manager.load_enabled_plugins()

pipeline = Pipeline([
    PipelineNode("dataset_ingest", {"path": "workspace/datasets/input/speech"}),
    PipelineNode("audio_conditioner", {"sample_rate": 16000}),
    PipelineNode("segmenter", {"mode": "vad"}),
])
pipeline.run()
```

Reference demo: `PluginPackage/Audio/demo.py`
