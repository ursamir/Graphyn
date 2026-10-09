# Plugin Guide

Branch `test/example-06-plugins` keeps the Example 06 speech-commands plugins and deploy: `dataset-ingest`, `audio-conditioner`, `segmenter`, `audio-quality-gate`, `augmentation-pipeline`, `audio-exporter`, `feature-frontend`, `dataset-builder`, `trainer` (includes `model_builder`), `evaluator`, `edge-optimizer`, `realtime-inference`, `deployment-packager`, `python-code`.

By user request the **workflow-automation set** is restored on top of that (20 plugins, plus the `webhook-trigger` source): Common `schedule-trigger`, `if-switch`, `merge`, `wait-delay`, `error-catch`, `json-transform`, `set-map`, `csv-table`, `http-request`, `http-webhook`, `send-email`, `object-store`, `credential-probe`, `eval-gate`, `structured-llm`; Agents `hitl-approve`, `llm-chat`, `prompt-template`, `output-schema-validate`, `guardrail-filter`. `docker-compose.yml` lists them in `GRAPHYN_BUNDLED_PLUGIN_ALLOWLIST`. Still removed on this branch: `agent_loop`, `tool_router`, `mcp_tool_call`, `memory_store`, `pii_redact`, the MLOps / RAG / Vision / TinyML packs and the other Audio / Common extras. Templates were not removed.

**Branch nodes emit only the active port.** `if_switch`, `hitl_approve`, `output_schema_validate` and `guardrail_filter` (`violations`) omit the inactive port key instead of returning `None`. The executor treats an omitted port as *unproduced* and skips the downstream branch (see [PIPELINE_EXECUTION.md § Skip semantics](./PIPELINE_EXECUTION.md#skip-semantics-g1)). New branch-style plugins must do the same: `{"approved": None}` counts as produced and runs the branch.

**Egress plugins record external calls.** A node that talks to the network calls `self.record_external_call(kind, method, url, status, request_sha256=…, response_sha256=…, duration_ms=…, connection_id=…)` once per attempt. The URL is redacted (no userinfo / query / fragment) and bodies are stored only as `sha256:` hashes. The executor writes them to run meta and the sealed `prove.json` as `external_calls`. `http_request`, `http_webhook`, `send_email`, `llm_chat` and `structured_llm` do this.

**Not in the default catalog:** `PluginPackage/Video/` is a placeholder (no manifests). `PluginPackage/WakeWord/` is experimental source-only — it is **not** auto-installed and is not importable as a full plugin pack until its training subtree is wired to a manifest; use Audio/Common wake-word templates for runnable graphs.

For the full node reference → **[PluginPackage/NODES.md](../PluginPackage/NODES.md)**  
For architecture and data flow → **[PluginPackage/ARCHITECTURE.md](../PluginPackage/ARCHITECTURE.md)**

---

## How Plugins Work

`AutoDiscovery` scans `plugins/` (or `GRAPHYN_PLUGINS_DIR`) at startup. Any directory with a `plugin.toml` manifest is loaded via `PluginLoader`, which validates the manifest, checks dependencies, imports entry points, and registers node types in `NodeRegistry`.

`NodeRegistry.register` fills empty `NodeMetadata.input_ports` / `output_ports` from the node class when callers pass bare metadata (isolated stubs historically omitted ports on meta). The Builder catalog (`GET /nodes`) therefore advertises the same named handles for catalog-drag as for template-imported graphs.

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

**Config schema (Builder form contract):** one `[config_schema.<node_type>]` table per node; each
field is an inline table using JSON-Schema keywords. Keep it in sync with the node's Pydantic
`Config` (same names, defaults, `Literal` ↔ `enum`, `Field(ge/le/gt/lt)` ↔
`minimum/maximum/exclusiveMinimum/exclusiveMaximum`, `Field(pattern=…)` ↔ `pattern`) —
`unit_test/plugins/test_example06_schema.py` enforces this for the Example 06 plugins.
`ui.visible_if` hides a field unless every listed field matches (value, or any value of a list):

```toml
[config_schema.audio_conditioner]
normalize_method = { type = "string", default = "peak", enum = ["peak", "rms", "lufs"], ui = { visible_if = { normalize = true } } }
target_lufs      = { type = "number", default = -23.0, minimum = -70, maximum = 0, ui = { visible_if = { normalize = true, normalize_method = "lufs" } } }
target_level_db  = { type = "number", default = -1.0, minimum = -96, maximum = 0, ui = { visible_if = { normalize_method = ["peak", "rms"] } } }
```

**Inspector text (what users read):** `description` is shown in the Builder inspector — write it
for the person configuring the node. No environment-variable names, internal file names
(`X_train_repr.npy`, `compiled_<uuid>.keras`), library calls (`librosa top_db`, `tf.lite.Optimize`)
or implementation notes there; put those in `ui.help_advanced` (rendered as the field's
"advanced help", passed through unchanged by `plugin_ui.py`). Output-location fields
(`output_path`, `output_dir`, `checkpoint_path`) go in `ui.group = "Advanced"`; a **required**
input path (e.g. `realtime_inference.model_path`) stays visible.
`unit_test/plugins/test_ux_plugins_schema_ux.py` enforces this for the bundled plugins.

```toml
device      = { type = "string", default = "auto", enum = ["auto", "cpu", "gpu"],
                description = "auto = use a GPU when one is available, else CPU; cpu = always CPU; gpu = prefer GPU (falls back to CPU with a warning).",
                ui = { group = "Basic", help_advanced = "auto honours GRAPHYN_TF_DEVICE, CUDA_VISIBLE_DEVICES and GRAPHYN_ML_FORCE_CPU." } }
output_path = { type = "string", default = "workspace/artifacts/models",
                description = "Folder for the trained model and checkpoints.",
                ui = { group = "Advanced", help_advanced = "Relative to the Graphyn workspace; runs are scoped to runs/<run_id>/." } }
```

**model_builder architectures** (`PluginPackage/Common/trainer/`):

| `architecture` | Source | Tunables (topology fixed) |
|---|---|---|
| `ds_cnn` | Hello Edge / DS-CNN (Zhang et al., 2017) | `filters`, `num_layers`, `dropout_rate`, `learning_rate` |
| `mobilenet` | MobileNetV2 (Sandler et al., 2018) | `filters`, `num_layers`, `expansion_factor` (default 6), `stem_stride` (default 2), dropout/LR |
| `simple_cnn` | Non-paper baseline | `filters`, dropout/LR |
| `custom` | User-owned | `layers` JSON list (`widget = "json"`); Builder **Load layers from preset** seeds from a paper body |

Layer `type` values for `custom`: `conv2d`, `depthwise_conv2d`, `batch_norm`, `relu`, `relu6`, `max_pool2d`, `avg_pool2d`, `global_avg_pool2d`, `dropout`, `dense`, `inverted_residual`, `ds_separable_block`. Implementation: `model_architecture.py` (`export_layer_specs` / `build_keras_model`). Preset fixtures live under `trainer/presets/*.layers.json`.

**Builder JSON widgets (`widget = "json"`):** use for open or nested shapes, but prefer a **known field name** the console already structures — `layers`, `augmentations`, `split_ratios`, `allowed_paths` open dedicated form/list editors (with Edit as JSON as secondary). Unknown `widget=json` fields still get a compact JSON textarea. Do not force forms for freeform artifact dumps (those stay tree viewers).

**Credentials:** declare kinds the plugin consumes; graphs bind by connection id only.

```toml
credential_kinds = ["openai_compat", "smtp"]   # optional; see docs/ops/CREDENTIAL_STORE.md
```

Node config should expose `connection_id` (string). Runtime precedence:
explicit connection id → workspace default for kind → env bootstrap. Never
embed raw secrets in Graph IR.

**Dependency rules:**
- Core deps (numpy, librosa, scipy) → `dependencies`
- Heavy deps (torch, tensorflow, transformers) → `optional_dependencies` only
- Never put heavy deps in `dependencies` — blocks CPU-only installs
- `runtime = "isolated"` — **required** deps go to `~/.graphyn/plugins/venvs/<name>/` (or `$GRAPHYN_HOME/plugins/venvs/<name>/` in Docker); `process()` runs via `app.core.plugins.worker`. Optional TensorFlow/Keras/ONNX from the boot allowlist install at load by default (API still binds first via background registry init). Set `GRAPHYN_ISOLATED_BOOT_HEAVY=0` to defer them to Plugins → **Install optional (venv)**. Other optionals (TTS, audiocraft, tflite-runtime, transformers, …) stay on-demand. Set `GRAPHYN_ISOLATED_INSTALL_ALL_OPTIONAL=1` to install every optional at load (may fail boot).
- `runtime = "inprocess"` (default) — deps install into the **shared API Python**. Heavy optional wheels often fail here; the Plugins UI labels this **shared env**. Install progress lists the actual package names being pip-installed (not a generic “PyTorch” stub).
- `torch` in `optional_dependencies` is skipped at boot unless `GRAPHYN_ISOLATED_INSTALL_TORCH=1`.
- API Docker/uvicorn: `/health` binds immediately; plugin catalog loads in a background thread. Poll `/api/v1/system/readiness` (`registry_ready`) until the Builder catalog is populated. `docker logs` shows `graphyn: plugin '…' installing …` progress (pip stdout is captured).
- Local ASR (`asr_transcribe` with `local_whisper` / `faster_whisper`): `faster-whisper` is on the isolated boot allowlist, so it installs into the plugin venv at load. Host extra `pip install -e ".[asr]"` is only for in-process use.
- Shared-env installs guarded by `PLATFORM_CONSTRAINTS`; UI/API: `GET|POST /plugins/{name}/dependencies`
- Optional **Install optional** installs packages **one-by-one**. `tflite-runtime` is skipped (and shown satisfied) when TensorFlow is already in the venv — nodes use `tensorflow.lite` as fallback. A single missing wheel no longer aborts the whole optional batch.
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

### Live progress (`emit_node_progress`)

Long-running nodes report progress to the Runs view. Import it defensively so the
plugin still loads on hosts without the progress channel:

```python
try:
    from app.core.nodes.progress import emit_node_progress
except ImportError:  # older host — progress is simply not shown
    def emit_node_progress(payload: dict) -> None:
        return None
```

Payloads are plain JSON dicts; the host adds `node_id` / `node_type` / timestamps, a human
`message`, and throttles to ≤ 2 events/s (a payload with `pct >= 100` or `final: true` always
goes through). In-process nodes deliver through a context variable; isolated workers write
`@@GRAPHYN_PROGRESS@@ <json>` lines to stderr that the host forwards. Conventions used by the
bundled plugins:

| Node | Payload |
|---|---|
| `trainer` | `{"phase": "train", "epoch": n, "epochs": N, "loss", "accuracy", "val_loss", "val_accuracy", "pct"}` per epoch (`epoch: 0` at start); early stop → `{"phase": "train", "event": "early_stopping", "epoch", "epochs", "best_val_accuracy", "pct": 100, "message"}` |
| `evaluator` | `{"phase": "evaluate", "n_test", "pct": 0}` then `{…, "test_accuracy", "roc_auc", "pct": 100, "message"}` |
| `edge_optimizer` | `{"phase": "convert", "pct": 0}`, `{"phase": "calibrate", "done", "total", "pct"}` (int8), `{"phase": "convert", "file_size_bytes", "pct": 100, "message"}` |
| `feature_frontend` / `dataset_builder` / `augmentation_pipeline` / `audio_exporter` | `{"phase": "features" \| "dataset" \| "augment" \| "export", "done", "total", "pct"}` — ~20 steps per run |

Never let progress fail a node (wrap the call or rely on the host's no-raise contract), keep
floats finite (`NaN` → `None`) and call it from the thread that runs `process()`.
Tests: `unit_test/plugins/test_ux_plugins_progress.py` (fake emitter via `monkeypatch`).

### Model artifacts: labels and display names

Any node that writes a classifier file also writes `labels.txt` (one label per line, **class-index
order**, no trailing newline) in the same folder — `trainer` beside `model.keras`, inside
`saved_model/` and `checkpoints/`; `evaluator` beside the model and `metrics.json`;
`edge_optimizer` beside `model.tflite` / `model.onnx`. The order is `DatasetArtifact.labels`
(sorted by `dataset_builder`), never a hand-typed list — deploy steps must read it from
`labels.txt` or the artifact. File names stay unique (`compiled_<uuid>.keras`); the human name is
`ModelArtifact.metrics["display_name"]` (e.g. `DS-CNN (30 epochs)`, `DS-CNN (21 of 50 epochs)` when
stopped early) / `DeploymentArtifact.metadata["display_name"]` (`… · TFLite INT8`), next to
`labels` and `labels_path`. `metrics.json` itself stays numeric.

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

On API startup, if `GRAPHYN_SKIP_PLUGIN_LOAD` is not set **and** (`GRAPHYN_AUTO_INSTALL_PLUGINS` is true — default when `GRAPHYN_ENV=production` — **or** no *loadable* enabled plugins remain), Graphyn installs every `PluginPackage/*/*/plugin.toml` via `PluginManager.install(upgrade=True)` then `load_enabled_plugins()`. Enabled registry rows whose `install_path` vanished (e.g. leftover `/tmp/pytest-of-*` paths) are healed against `{GRAPHYN_HOME}/plugins/installed/<name>` or pruned so they cannot leave the Builder catalog empty. Docker Compose sets `GRAPHYN_AUTO_INSTALL_PLUGINS=1` because the `GRAPHYN_HOME` volume starts empty.

**Same-version code drift.** Every startup (auto-install on or off) also compares each already-installed bundled plugin with its `PluginPackage/` source (`PluginManager._sync_bundled_plugin`):

| Source vs installed | Action |
|---|---|
| different `version` | full `install(upgrade=True)` (isolated venv removed + rebuilt) |
| same version, same content hash | skipped (no copy, no venv work) |
| same version, different content hash, same requirements | **code-only refresh** — tree recopied into `plugins/installed/<name>`, `__pycache__` cleared, the isolated venv is **kept**; logs `WARNING Bundled plugin '<name>' v<ver>: source code changed at the same version … reinstalling code` |
| same version, different hash **and** different `dependencies` / `optional_dependencies` / `runtime` / `min_python` | full reinstall (venv rebuilt) |

The content hash (`app.core.plugins.content_hash.plugin_tree_hash`) is a SHA-256 over sorted relative paths + file digests, excluding `__pycache__`, `*.pyc`/`*.pyo`, VCS dirs and virtualenv dirs. It is stored as `source_hash` on the `PluginRecord` at install time; records written before that field existed are compared by hashing the installed tree (then backfilled). `install_bundled_plugins(force=True)` keeps the old always-reinstall behaviour. You do **not** need to bump a plugin's version for a rebuilt image to pick up edited plugin code.

### Environment variables (plugin catalog)

| Variable | Default | Role |
|---|---|---|
| `GRAPHYN_HOME` | `~/.graphyn/` | Platform home: `plugins/registry.json`, `plugins/installed/`, venvs |
| `GRAPHYN_PLUGINS_DIR` | `{GRAPHYN_HOME}/plugins/installed/` | Override install root scanned/loaded at startup |
| `GRAPHYN_PROJECT_DIR` | `workspace/` | Project runtime data (runs, artifacts) — not the plugin install root |
| `GRAPHYN_PLUGIN_PACKAGE_DIR` | `<repo>/PluginPackage` | Bundled plugin sources for auto-install |
| `GRAPHYN_AUTO_INSTALL_PLUGINS` | on when `GRAPHYN_ENV=production` | Force/skip bundled install at startup |
| `GRAPHYN_SKIP_PLUGIN_LOAD` | unset | Set `1` only in tests — skips install+load (API catalog will be empty) |
| `GRAPHYN_ISOLATED_DETERMINISTIC` | on | Isolated workers get `PYTHONHASHSEED=<node seed>`, `TF_DETERMINISTIC_OPS=1`, `TF_CUDNN_DETERMINISTIC=1`, `GRAPHYN_NODE_SEED`, and `random`/`np.random` seeded before `process()`. `0` disables (faster non-deterministic GPU kernels). |

For a normal `uvicorn app.api.main:app` session, leave `GRAPHYN_SKIP_PLUGIN_LOAD` unset and point `GRAPHYN_HOME` at a home that contains installed plugins (or enable auto-install).

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

**Source allowlist (`GRAPHYN_PLUGIN_ALLOWED_SOURCES`):** Set this env var to a comma-separated list of base URLs to restrict which remote sources are permitted. Matching is structural (`urllib.parse`): host must match (GitHub/GitLab CDN aliases included), and the path must be an exact match or a path-segment subpath of the base (`https://github.com/org/repo` does **not** authorize `.../repo-evil` or `.../repo2`). Raw string-prefix matching is not used. When unset, all sources are allowed (backward-compatible default). When set, any remote source that does not structurally match a listed base is rejected with `PluginInstallError` before any network request is made.

**Redirect policy:** HTTP downloads and plugin-index fetches re-validate every redirect hop and the final URL against the same allowlist and fail closed if any hop is off-list.

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

**<!-- count:plugins -->75<!-- /count --> plugins / <!-- count:node_types -->76<!-- /count --> node types in <!-- count:packs -->5<!-- /count --> packs** ship today (table generated by `scripts/sync_doc_counts.py`). See `PluginPackage/NODES.md` for config fields and capabilities.

<!-- count-block:pack_table -->
| Pack | Plugins | Node types |
|---|---:|---|
| Agents | 9 | `agent_loop`, `guardrail_filter`, `hitl_approve`, `llm_chat`, `mcp_tool_call`, `memory_store`, `output_schema_validate`, `prompt_template`, `tool_router` |
| Audio | 19 | `alignment_node`, `audio_annotator`, `audio_classifier`, `audio_conditioner`, `audio_event_detector`, `audio_exporter`, `audio_generator`, `audio_quality_gate`, `augmentation_pipeline`, `dataset_ingest`, `environment_simulator`, `feature_frontend`, `segmenter`, `speaker_separator`, `speech_enhancer`, `speech_synthesizer`, `stream_ingest`, `stream_processor`, `voice_converter` |
| Common | 32 | `asr_transcribe`, `caption_export`, `credential_probe`, `csv_table`, `dataset_balancer`, `dataset_builder`, `dataset_versioner`, `deployment_packager`, `doc_parse_chunk`, `edge_optimizer`, `embedding_generator`, `error_catch`, `eval_gate`, `evaluator`, `experiment_tracker`, `http_request`, `http_webhook`, `if_switch`, `json_transform`, `merge`, `multimodal_fusion`, `object_store`, `pii_redact`, `python_code`, `realtime_inference`, `schedule_trigger`, `send_email`, `set_map`, `structured_llm`, `trainer`, `model_builder`, `wait_delay`, `webhook_trigger` |
| Video | 10 | `action_classify`, `av_align`, `clip_segment`, `frame_sample`, `scene_detect`, `video_caption`, `video_embed`, `video_exporter`, `video_ingest`, `video_quality_gate` |
| WakeWord | 5 | `wakeword_data_gen`, `wakeword_export_onnx`, `wakeword_feature_extract`, `wakeword_infer`, `wakeword_train` |
| **Total** | **75** | **76** |
<!-- /count-block -->

(`dataset_versioner` hashes a dataset and writes manifest + lineage; `audio_exporter` + `app.core.mlops.dataset_versions` remain the on-disk version store for exported audio.)

**Trainer / ModelBuilder (Keras):** `select_keras_device()` picks `/GPU:0` or `/CPU:0`. GPUs with compute capability ≥12 (Blackwell, e.g. RTX 5070 Ti) default to CPU because this TensorFlow build cannot run Keras training on them (missing CUDA kernels / libdevice). GPU is also refused when free VRAM is below `GRAPHYN_TF_GPU_MIN_FREE_MIB` (default 4096 MiB) so other apps keep the card. CPU `fit` uses soft placement off + `tf.device("/CPU:0")`. Set `GRAPHYN_TF_FORCE_GPU=1` only to attempt unsupported CC; it does not ignore the VRAM gate. `GRAPHYN_TF_DEVICE`: `auto`|`cpu`|`gpu`. `trainer.config.device`: `auto`|`cpu`|`gpu`.

---

## Agent create-plugin path (MCP)

Agents can extend Graphyn without leaving MCP:

1. **Discover** — `list_packs` / `describe_pack` / `list_nodes` / `get_node_spec`
2. **Scaffold locally** — create `PluginPackage/<Pack>/<slug>/` with `plugin.toml`, `nodes.py`, optional `types.py` (see structure above). Declare `credential_kinds` when the node needs secrets; expose `connection_id` in config (never embed secrets in Graph IR).
3. **Install** — `install_plugin` with a path or allowlisted URL; then `list_plugins` / `manage_plugin`
4. **Prove** — `validate_graph` → `execute_pipeline` (real node implementations run by default) → `inspect_run`
5. **Template** — optional: add a marketplace family via `scripts/generate_pipeline_template_catalog.py` + seed under `examples/templates/marketplace/`

**Honesty:** MCU flash / OAuth mail connectors remain needs-api / needs-credentials — do not invent them in a plugin just to look complete.
