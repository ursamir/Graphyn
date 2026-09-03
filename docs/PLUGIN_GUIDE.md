# Plugin Guide

All 38 production nodes are implemented as plugins in `PluginPackage/`. This guide covers how to write new plugins, install them, and manage their lifecycle.

For the full node reference → **[PluginPackage/NODES.md](../PluginPackage/NODES.md)**  
For architecture and data flow → **[PluginPackage/ARCHITECTURE.md](../PluginPackage/ARCHITECTURE.md)**

---

## How Plugins Work

`AutoDiscovery` scans `plugins/` (or `GRAPHYN_PLUGINS_DIR`) at startup. Any directory with a `plugin.toml` manifest is loaded via `PluginLoader`, which validates the manifest, checks dependencies, imports entry points, and registers node types in `NodeRegistry`.

---

## Plugin Structure

```
my_plugin/
├── plugin.toml     # manifest
├── __init__.py     # exports node class(es) and custom types
├── types.py        # custom PortDataType subclasses — list FIRST in entry_points (optional)
└── nodes.py        # node implementation
```

If the plugin defines custom types, `types.py` must be listed before `nodes.py` in `entry_points` so the type is registered in `TypeCatalogue` before the node imports it.

**Rule: plugin-domain types belong in `types.py` inside the plugin, never in `app/models/`.**

---

## `plugin.toml` Schema

```toml
[plugin]
name             = "my-plugin"          # slug: ^[a-z][a-z0-9_-]*$
version          = "1.0.0"              # PEP 440
description      = "What it does."
author           = "Author Name"
platform_version = ">=0.0"
entry_points     = ["types.py", "nodes.py"]   # types.py first if plugin defines custom types
license          = "MIT"
tags             = ["audio"]

dependencies = ["numpy>=1.24", "librosa>=0.10"]   # pinned, no open ranges
optional_dependencies = ["torch>=2.0"]             # heavy deps — node must degrade gracefully
runtime = "inprocess"                              # or "isolated" for conflicting stacks
```

**Dependency rules:**
- Core deps (numpy, librosa, scipy) → `dependencies`
- Heavy deps (torch, tensorflow, transformers) → `optional_dependencies` only
- Never put heavy deps in `dependencies` — blocks CPU-only installs
- `runtime = "isolated"` — required **and** optional deps go to `~/.graphyn/plugins/venvs/<name>/` (or `$GRAPHYN_HOME/plugins/venvs/<name>/` in Docker); `process()` runs via `app.core.plugins.worker` (use for trainer / edge-optimizer / realtime-inference). Heavy extras stay out of the host API image.
- `torch` in `optional_dependencies` is skipped unless `GRAPHYN_ISOLATED_INSTALL_TORCH=1` (default isolated extras are TensorFlow CPU + Keras).
- Shared-env installs guarded by `PLATFORM_CONSTRAINTS`; UI/API: `GET|POST /plugins/{name}/dependencies`
- Existing Docker volumes created before optional extras were installed into isolated venvs:

  `docker exec graphyn-api /data/graphyn-home/plugins/venvs/trainer/bin/pip install 'tensorflow>=2.13' 'keras>=3.0'`

---

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

    def process(self, samples):   # SISO shorthand
        return samples
```

### Backend Pattern (Nodes with Optional Heavy Deps)

```python
def setup(self):
    # setup() MUST initialize all instance variables used by process()
    # hasattr() guards in process() are a fallback, not a substitute.
    self._model = None
    self._backend = "cpu"

    if self.config.backend in ("gpu", "auto"):
        try:
            import torch
            self._backend = "pytorch"
            self._model = load_model()
            return
        except ImportError:
            if self.config.backend == "gpu":
                raise ImportError("PyTorch required. venv/bin/pip install torch")
    # CPU fallback init here

def teardown(self):
    # teardown() MUST reset setup state so the node can be re-initialized
    del self._model
    self._model = None
    self._backend = "cpu"
```

### Metadata Propagation

Every node that transforms audio adds a key to `AudioSample.metadata`:

```python
sample.metadata.update({"my_node": {"key": "value"}})
```

### Custom Data Types

```python
from app.core.nodes.ports import PortDataType

class MyOutputType(PortDataType):
    field_a: str = ""
    field_b: float = 0.0
```

List `types.py` before `nodes.py` in `entry_points`. Import from sibling file in `nodes.py`:

```python
from my_plugin.types import MyOutputType
```

### Lifecycle Hooks

```python
def setup(self):
    # Called once before first process(). MUST initialize all instance
    # variables that process() uses — hasattr() guards are a fallback only.
    self._model = load_model()

def teardown(self):
    # Called once after last process(). MUST reset setup state so the node
    # can be re-initialized (e.g. in test suites or pipeline restarts).
    del self._model
    self._model = None
```

### Retry Policy

```python
from app.core.nodes.retry import RetryPolicy

class MyNode(Node):
    retry_policy: ClassVar[RetryPolicy] = RetryPolicy(
        max_attempts=3, backoff_seconds=1.0, backoff_multiplier=2.0
    )
```

---

## Bundled auto-install (Docker / production)

On API startup, if `GRAPHYN_SKIP_PLUGIN_LOAD` is not set **and** (`GRAPHYN_AUTO_INSTALL_PLUGINS` is true — default when `GRAPHYN_ENV=production` — **or** no enabled plugins are installed), Graphyn installs every `PluginPackage/*/*/plugin.toml` via `PluginManager.install(upgrade=True)` then `load_enabled_plugins()`. Docker Compose sets `GRAPHYN_AUTO_INSTALL_PLUGINS=1` because the `GRAPHYN_HOME` volume starts empty.

## Installing a Plugin

```python
from app.core.plugins.manager import PluginManager

manager = PluginManager()
manager.install("PluginPackage/Audio/my_plugin/", upgrade=True)
manager.load_enabled_plugins()
```

```bash
graphyn plugin install PluginPackage/Audio/my_plugin/
graphyn plugin install git+https://github.com/org/my-plugin.git
graphyn plugin install https://example.com/my-plugin-1.0.0.zip
```

---

## Plugin Lifecycle

| Operation | CLI | REST API |
|---|---|---|
| Install | `graphyn plugin install SOURCE [--upgrade]` | `POST /api/v1/plugins/install` |
| Enable | `graphyn plugin enable NAME` | `POST /api/v1/plugins/{name}/enable` |
| Disable | `graphyn plugin disable NAME` | `POST /api/v1/plugins/{name}/disable` |
| Uninstall | `graphyn plugin remove NAME` | `DELETE /api/v1/plugins/{name}` |
| List | `graphyn plugin list [--enabled]` | `GET /api/v1/plugins` |
| Search | `graphyn plugin search QUERY` | `GET /api/v1/plugins/search?q=QUERY` |
| Info | `graphyn plugin info NAME` | `GET /api/v1/plugins/{name}` |

Remote sources (`git+`, `http://`, `https://`) install asynchronously — poll `GET /api/v1/plugins/{name}` for the result.

---

## Security

**Source allowlist (`GRAPHYN_PLUGIN_ALLOWED_SOURCES`):** Set this env var to a comma-separated list of URL prefixes to restrict which remote sources are permitted. When unset, all sources are allowed (backward-compatible default). When set, any remote source not matching a listed prefix is rejected with `PluginInstallError` before any network request is made.

```bash
# Only allow plugins from your org's GitHub and internal registry
export GRAPHYN_PLUGIN_ALLOWED_SOURCES="git+https://github.com/myorg/,https://plugins.internal.example.com/"
```

**Checksum verification (`expected_sha256`):** For HTTP archive sources, pass the expected SHA-256 hex digest to verify the downloaded archive before extraction. Mismatch raises `PluginInstallError`.

```python
manager.install(
    "https://plugins.example.com/my-plugin-1.0.0.zip",
    expected_sha256="abc123...",
)
```

Via REST API:
```json
{"source": "https://plugins.example.com/my-plugin-1.0.0.zip", "expected_sha256": "abc123..."}
```

**Never expose the plugin install endpoint publicly.** Auth (`GRAPHYN_API_TOKEN`) is the primary gate.

---

## `PluginManager` Reference

| Method | Returns | Raises |
|---|---|---|
| `install(source, upgrade=False)` | `PluginRecord` | `PluginAlreadyInstalledError`, `PluginManifestError`, `PluginCompatibilityError`, `PluginDependencyError`, `PluginInstallError` |
| `uninstall(name)` | `None` | `PluginNotFoundError` |
| `enable(name)` | `PluginRecord` | `PluginNotFoundError` |
| `disable(name)` | `PluginRecord` | `PluginNotFoundError` |
| `list_installed()` | `list[PluginRecord]` | — |
| `load_enabled_plugins()` | `None` | — (failures logged, not raised) |

---

## Quality Checklist

- [ ] `plugin.toml` with pinned dependencies
- [ ] All `NodeMetadata` capability flags set
- [ ] `backend` config field on nodes with optional heavy deps
- [ ] Graceful `ImportError` with install hint when optional dep absent
- [ ] `AudioSample.metadata` enriched
- [ ] Installs and runs via `PluginManager.install()`
- [ ] `setup()` initializes all instance variables used by `process()`
- [ ] `teardown()` resets setup state so node can be re-initialized
- [ ] Empty/None input guards at the top of `process()` — log warnings for skipped inputs, raise errors for invalid config
- [ ] No silent failures — every error path either logs a warning or raises
- [ ] Atomic file writes (write to tmp, then `os.replace()`) for any file output
- [ ] Thread-safe model caching (cache keyed on model ID, not just `is None`)

---

## Error Handling

| Error | Cause | Behavior |
|---|---|---|
| `DuplicateNodeTypeError` | Two classes claim the same `node_type` | Propagates immediately — server fails to start |
| `NodeMetadataError` | Class missing `metadata` ClassVar | Logged as warning, node skipped |
| Import error | Syntax error or missing dependency | Logged as warning, file skipped |

---

## Testing a Plugin

```python
from app.core.plugins.manager import PluginManager
from app.core.nodes import registry

manager = PluginManager()
manager.install("PluginPackage/Audio/my_plugin/", upgrade=True)
manager.load_enabled_plugins()

node_class = registry.get_class("my_node")
node = node_class(config={"backend": "cpu"}, seed=42)
node.setup()
outputs = node.process({"input": my_samples})
node.teardown()
```

---

## Registered Plugins

All 38 plugins are complete. See `plugin-development.md` steering file for the full table, or `PluginPackage/NODES.md` for config fields and capabilities.

### Audio (`PluginPackage/Audio/`) — 18 nodes
`dataset_ingest`, `stream_ingest`, `audio_conditioner`, `audio_quality_gate`, `audio_annotator`, `alignment_node`, `segmenter`, `augmentation_pipeline`, `speech_enhancer`, `speaker_separator`, `environment_simulator`, `feature_frontend`, `stream_processor`, `audio_event_detector`, `audio_classifier`, `speech_synthesizer`, `voice_converter`, `audio_generator`

### Common (`PluginPackage/Common/`) — 20 nodes
`dataset_builder`, `model_builder`, `trainer`, `evaluator`, `edge_optimizer`, `realtime_inference`, `dataset_balancer`, `dataset_versioner`, `experiment_tracker`, `deployment_packager`, `embedding_generator`, `multimodal_fusion`, `asr_transcribe`, `pii_redact`, `structured_llm`, `eval_gate`, `http_webhook`, `doc_parse_chunk`, `caption_export`, `object_store`

**Trainer / ModelBuilder (Keras):** `select_keras_device()` picks `/GPU:0` or `/CPU:0`. GPUs with compute capability ≥12 (Blackwell, e.g. RTX 5070 Ti) default to CPU because this TensorFlow build cannot run Keras training on them (missing CUDA kernels / libdevice). GPU is also refused when free VRAM is below `GRAPHYN_TF_GPU_MIN_FREE_MIB` (default 4096 MiB) so other apps keep the card. CPU `fit` uses soft placement off + `tf.device("/CPU:0")`. Set `GRAPHYN_TF_FORCE_GPU=1` only to attempt unsupported CC; it does not ignore the VRAM gate. `GRAPHYN_TF_DEVICE`: `auto`|`cpu`|`gpu`. `trainer.config.device`: `auto`|`cpu`|`gpu`.
