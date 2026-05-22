---
inclusion: fileMatch
fileMatchPattern: "plugins/**,app/core/plugins/**,PluginPackage/**"
---

# Plugin Development

All 29 plugins are complete. For node specs and capabilities → `PluginPackage/NODES.md`. For architecture and data flow → `PluginPackage/ARCHITECTURE.md`.

## Locations

| Location | Purpose |
|---|---|
| `PluginPackage/Audio/` | 18 audio-domain plugins — develop here |
| `PluginPackage/Common/` | 11 cross-domain plugins — develop here |
| `plugins/` | Install target — managed by `PluginManager`, never edit directly |

## Plugin Structure

```
PluginPackage/{Audio|Common}/plugin_name/
├── plugin.toml     # manifest
├── __init__.py     # exports node class(es) and custom types
├── types.py        # custom PortDataType subclasses — list FIRST in entry_points (if any)
└── nodes.py        # node implementation — list SECOND in entry_points
```

If the plugin defines custom types, `types.py` must be listed before `nodes.py` in `entry_points` so the type is registered in `TypeCatalogue` before the node imports it. Plugin-domain types belong in `types.py` — never in `app/models/`.

## `plugin.toml` Schema

```toml
[plugin]
name             = "my-plugin"          # slug: ^[a-z][a-z0-9_-]*$
version          = "1.0.0"
description      = "What it does."
author           = "Graphyn Plugins"
platform_version = ">=0.0"
entry_points     = ["types.py", "nodes.py"]
license          = "MIT"
tags             = ["audio"]

dependencies = ["numpy>=1.24", "librosa>=0.10"]   # pinned, no open ranges
optional_dependencies = ["torch>=2.0"]             # heavy deps — node must degrade gracefully
```

Core deps (numpy, librosa, scipy) → `dependencies`. Heavy deps (torch, tensorflow, transformers) → `optional_dependencies` only. Never put heavy deps in `dependencies` — it blocks CPU-only installs.

## Node Template

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

    def process(self, samples):   # SISO shorthand — framework unpacks/repacks automatically
        return samples
```

## Backend Pattern (Nodes with Heavy Optional Deps)

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

## Metadata Propagation

Every node that transforms audio must add a key to `AudioSample.metadata`:

```python
sample.metadata.update({"my_node": {"key": "value"}})
```

Established metadata keys → `data-models.md` § AudioSample.metadata Conventions.

## Install

```python
from app.core.plugins.manager import PluginManager
manager = PluginManager()
manager.install("PluginPackage/Audio/my_plugin/", upgrade=True)
manager.load_enabled_plugins()
```

```bash
graphyn plugin install PluginPackage/Audio/my_plugin/
```

## `PluginManager` Reference

| Method | Description |
|---|---|
| `install(source, upgrade=False)` | Copy to `plugins/<name>/` → load → persist record |
| `uninstall(name)` | Unload types → delete record → remove directory |
| `enable(name)` / `disable(name)` | Reload or unload node types from registry |
| `list_installed()` | Return all `PluginRecord` objects |
| `load_enabled_plugins()` | Called at startup — loads all enabled plugins |

Full method signatures, return types, and exceptions → `plugin-ecosystem.md`.

## Demo Pattern

```python
from app.core.plugins.manager import PluginManager
from app.core.sdk import Pipeline, PipelineNode

manager = PluginManager()
manager.install("PluginPackage/Audio/my_plugin/", upgrade=True)
manager.load_enabled_plugins()

pipeline = Pipeline([
    PipelineNode("dataset_ingest", {"path": str(INPUT_DIR)}),
    PipelineNode("my_node", {"param": value}),
])
pipeline.run(use_cache=False)
```

Reference: `PluginPackage/Audio/demo.py`

## Quality Checklist

- [ ] `plugin.toml` with pinned dependencies
- [ ] All `NodeMetadata` capability flags set
- [ ] `backend` config field on nodes with optional heavy deps
- [ ] Graceful `ImportError` with install hint when optional dep absent
- [ ] `AudioSample.metadata` enriched
- [ ] Installs and runs via `PluginManager.install()`
- [ ] Row added to Registered Plugins table below
- [ ] `PluginPackage/NODES.md` capability matrix updated
- [ ] **Config validators** added for all constrained fields (ranges, enums, cross-field ordering)
- [ ] **Installed copy synced**: after editing `PluginPackage/*/nodes.py`, copy to `plugins/<name>/nodes.py`

## Registered Plugins

### Audio (`PluginPackage/Audio/`) — 18 nodes

| node_type | Plugin Name | Category | Version |
|---|---|---|---|
| `dataset_ingest` | `dataset-ingest` | Input | v1.1.0 |
| `stream_ingest` | `stream-ingest` | Input | v1.0.0 |
| `audio_conditioner` | `audio-conditioner` | Preprocessing | v1.1.0 |
| `audio_quality_gate` | `audio-quality-gate` | Preprocessing | v1.0.0 |
| `audio_annotator` | `audio-annotator` | Preprocessing | v1.0.0 |
| `alignment_node` | `alignment-node` | Preprocessing | v1.0.0 |
| `segmenter` | `segmenter` | Processing | v1.1.0 |
| `augmentation_pipeline` | `augmentation-pipeline` | Augmentation | v1.1.0 |
| `speech_enhancer` | `speech-enhancer` | Enhancement | v1.0.0 |
| `speaker_separator` | `speaker-separator` | Enhancement | v1.0.0 |
| `environment_simulator` | `environment-simulator` | Enhancement | v1.0.0 |
| `feature_frontend` | `feature-frontend` | Features | v1.1.0 |
| `stream_processor` | `stream-processor` | Streaming | v1.0.0 |
| `audio_event_detector` | `audio-event-detector` | Detection | v1.0.0 |
| `audio_classifier` | `audio-classifier` | Inference | v1.0.0 |
| `speech_synthesizer` | `speech-synthesizer` | Generation | v1.0.0 |
| `voice_converter` | `voice-converter` | Generation | v1.0.0 |
| `audio_generator` | `audio-generator` | Generation | v1.0.0 |

### Common (`PluginPackage/Common/`) — 11 nodes

| node_type | Plugin Name | Category | Version |
|---|---|---|---|
| `dataset_builder` | `dataset-builder` | ML | v1.0.0 |
| `trainer` | `trainer` | ML | v1.0.0 |
| `evaluator` | `evaluator` | ML | v1.0.0 |
| `edge_optimizer` | `edge-optimizer` | ML | v1.0.0 |
| `realtime_inference` | `realtime-inference` | Inference | v1.1.0 |
| `dataset_balancer` | `dataset-balancer` | ML | v1.0.0 |
| `dataset_versioner` | `dataset-versioner` | ML | v1.0.0 |
| `experiment_tracker` | `experiment-tracker` | ML | v1.0.0 |
| `deployment_packager` | `deployment-packager` | ML | v1.0.0 |
| `embedding_generator` | `embedding-generator` | Features | v1.0.0 |
| `multimodal_fusion` | `multimodal-fusion` | Features | v1.0.0 |

When adding a plugin: add a row here and update `PluginPackage/NODES.md` capability matrix.
