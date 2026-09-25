# Graphyn Plugin / Node Platform Catalog

> **Design-only.** Implementation waves later. Authoritative inventory + contract + ≥100 node_types.
> UI term: **Workspace**; API still **projects**. Do not break FaceRecognition / unrelated services.

**Total node_types enumerated:** 145  
**By status:** Existing=42, Alter=7, Proposed=96  
**By pack root:** Agents=8, Audio=19, Common=30, MLOps=12, RAG=21, TinyML=20, Video=10, Vision=20, WakeWord=5

Machine-readable twin: [`PLUGIN_NODE_PLATFORM_CATALOG.json`](./PLUGIN_NODE_PLATFORM_CATALOG.json).

**Refinements (additive):** see [`PLUGIN_NODE_REFINEMENTS.md`](./PLUGIN_NODE_REFINEMENTS.md) (+10 granularize atoms → **155** distinct node_types). Marketplace templates: [`PIPELINE_TEMPLATE_MARKETPLACE.md`](./PIPELINE_TEMPLATE_MARKETPLACE.md).

---

## 1. Purpose & status

This document is the implementable design for Graphyn’s plugin/node platform expansion. It:

1. Inventories **all 49 production** node types (Audio + Common) plus experimental gaps (WakeWord, Video).
2. Records the **canonical interface contract** aligned with real code (`plugin.toml`, `Node`, ports, artifacts, secrets).
3. Lists **actionable alterations** to existing plugins (trainer/model_builder, edge_optimizer, RAG-facing Common nodes, WakeWord promotion, Video fill, realtime multi-runtime).
4. Catalogues **145 distinct `node_type`s** (existing + alter + proposed) with ports, config, deps, and notes.

**Out of scope for this commit:** implementing the proposed nodes. **Honesty:** MCU flash/OTA and on-device metrics are **needs-API** — do not fake Devices APIs.

---

## 2. Canonical interface

Aligned with `docs/PLUGIN_GUIDE.md`, `PluginPackage/ARCHITECTURE.md`, and `app/core/nodes/*`.

### 2.1 `plugin.toml` fields

```toml
[plugin]
name             = "my-plugin"          # slug: ^[a-z][a-z0-9_-]*$
version          = "1.0.0"              # PEP 440
description      = "What it does."
author           = "Graphyn Plugins"
platform_version = ">=0.0"
entry_points     = ["types.py", "nodes.py"]  # types.py FIRST if custom PortDataType
license          = "MIT"
tags             = ["ml"]

dependencies = ["numpy>=1.24"]           # pinned; no open ranges; light deps only
optional_dependencies = ["torch>=2.0"]  # heavy: torch/tf/ultralytics/executorch/…
runtime = "isolated"                    # or "inprocess" (default)
node_types = ["my_node"]

[config_schema.my_node]
field = { type = "string", title = "Field", default = "", enum = ["a","b"],
          description = "…", ui = { group = "Basic" } }
```

**Rules (from real loader behavior):**

- Heavy stacks (`torch`, `tensorflow`, `ultralytics`, `executorch`, `transformers`) → `optional_dependencies` + usually `runtime = "isolated"`.
- Fail-fast when a **forced** backend is selected but the optional wheel is missing (`ImportError` with pip hint).
- `AutoDiscovery` scans `plugin.toml`; `Video/` has none today; `WakeWord/` has none today.

### 2.2 Node class contract

```python
class MyNode(Node):
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="my_node", label="My Node", description="…", category="ML",
        version="1.0.0", tags=["ml"],
        requires_gpu=False, supports_cpu=True, supports_edge=False,
        deterministic=True, cacheable=True,
        streaming_support=False, realtime_support=False,
    )
    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=list[AudioSample], required=True),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=ModelArtifact),
    }
    class Config(NodeConfig):  # extra='forbid'
        backend: str = "auto"

    def setup(self) -> None: ...
    def process(self, inputs: dict[str, Any]) -> dict[str, Any]: ...
    def teardown(self) -> None: ...
```

- `NodeConfig` forbids unknown fields; UI stamp keys (`project`, `output_dir`, `version_tag`) are sanitized when undeclared.
- Optional input ports must accept `None` (`T | None`).
- Plugin-domain types live in plugin `types.py`, **never** in `app/models/` (platform-core types are the exception).

### 2.3 Port typing / metadata propagation

| Layer | Types |
|---|---|
| Platform-core (`app/models/`) | `AudioSample`, `FeatureArray`, `ModelArtifact`, `TFLiteArtifact`, `DeploymentArtifact`, `PredictionResult`, `DataSample`, … |
| Plugin-owned | e.g. `Chunk`, `EmbeddingVector`, `ExperimentArtifact`, `Transcript`, `DatasetArtifact` |
| Proposed NEW (this catalog) | Marked `NEW` in port types — e.g. `McuSample`, `ImageSample`, `VideoSample`, `RetrievalHit`, `VectorStoreRef`, `RagAnswer`, … |

Audio transforms append keys under `AudioSample.metadata`. RAG/Vision should propagate `metadata` on samples/chunks similarly.

### 2.4 Capability flags

From `NodeMetadata`: `requires_gpu`, `supports_cpu`, `supports_edge`, `deterministic`, `cacheable`, `streaming_support`, `realtime_support`, plus extended `memory_requirements`, `dependency_requirements`, `batch_support`.

### 2.5 Artifact / model output conventions

| Artifact | Key fields | Typical producers |
|---|---|---|
| `ModelArtifact` | `model_path`, `labels`, `history`, `metrics` | `trainer`, `evaluator`, `yolo_train` |
| `TFLiteArtifact` | `tflite_path`, `labels`, `quantisation` ∈ {float32,float16,int8}, `file_size_bytes` | `edge_optimizer`, `tflm_quantize` |
| `DeploymentArtifact` | `artifact_path`, `model_format`, `target_hardware`, `quantization`, `labels`, shapes, `benchmark`, `metadata` | `edge_optimizer`, `deployment_packager`, `yolo_export`, `executorch_export` |

**Paths:** write under `workspace/artifacts/...` (models, optimized, packages, vectorstores, predictions). Datasets under `workspace/datasets/...`. UI **Workspace** ↔ API **projects**.

### 2.6 Secret / credential pattern

- Store: `GRAPHYN_HOME/secrets` via `graphyn secrets set NAME` / API `/api/v1/secrets` (names only on list).
- Resolve: `app.core.secrets.resolve_secret(name)` → store then process env.
- Node configs take **secret names** (e.g. `api_secret_name`, `auth_env`) — **never** hardcoded API keys.
- Exemplars: `structured_llm`, `asr_transcribe`, `http_request.auth_env`, `speaker_separator` HF token.
- vs n8n: n8n separates Credentials vs Parameters vs Execute; Graphyn keeps **typed ports + Config** and references Graphyn secrets for credentials.

### 2.7 Error / contract

- Config validation: Pydantic `extra='forbid'` → fail at graph stamp time.
- Missing optional heavy dep when `backend` is forced → **fail-fast** `ImportError` / `FileNotFoundError` with install hint.
- needs-API nodes (`mcu_flash_ota`, `mcu_ondevice_metrics`): default `dry_run=True`; live mode raises clear `NotImplementedError` until Devices APIs exist.

---

## 3. Existing inventory

Production: **49** node types (19 Audio plugins + 29 Common packages; `model_builder` ships inside `trainer`). Experimental: WakeWord (no `plugin.toml`), Video (empty placeholder).

| ID | node_type | Pack | Category | Status |
|---|---|---|---|---|
| N001 | `dataset_ingest` | `PluginPackage/Audio/dataset_ingest/` | Input | Existing |
| N002 | `stream_ingest` | `PluginPackage/Audio/stream_ingest/` | Input | Existing |
| N003 | `audio_conditioner` | `PluginPackage/Audio/audio_conditioner/` | Preprocessing | Existing |
| N004 | `audio_quality_gate` | `PluginPackage/Audio/audio_quality_gate/` | Preprocessing | Existing |
| N005 | `audio_annotator` | `PluginPackage/Audio/audio_annotator/` | Preprocessing | Existing |
| N006 | `alignment_node` | `PluginPackage/Audio/alignment_node/` | Preprocessing | Existing |
| N007 | `segmenter` | `PluginPackage/Audio/segmenter/` | Processing | Existing |
| N008 | `augmentation_pipeline` | `PluginPackage/Audio/augmentation_pipeline/` | Augmentation | Existing |
| N009 | `speech_enhancer` | `PluginPackage/Audio/speech_enhancer/` | Enhancement | Existing |
| N010 | `speaker_separator` | `PluginPackage/Audio/speaker_separator/` | Enhancement | Existing |
| N011 | `environment_simulator` | `PluginPackage/Audio/environment_simulator/` | Enhancement | Existing |
| N012 | `feature_frontend` | `PluginPackage/Audio/feature_frontend/` | Features | Existing |
| N013 | `stream_processor` | `PluginPackage/Audio/stream_processor/` | Streaming | Existing |
| N014 | `audio_event_detector` | `PluginPackage/Audio/audio_event_detector/` | Detection | Existing |
| N015 | `audio_classifier` | `PluginPackage/Audio/audio_classifier/` | Inference | Existing |
| N016 | `speech_synthesizer` | `PluginPackage/Audio/speech_synthesizer/` | Generation | Existing |
| N017 | `voice_converter` | `PluginPackage/Audio/voice_converter/` | Generation | Existing |
| N018 | `audio_generator` | `PluginPackage/Audio/audio_generator/` | Generation | Existing |
| N019 | `audio_exporter` | `PluginPackage/Audio/audio_exporter/` | Output | Existing |
| N020 | `dataset_builder` | `PluginPackage/Common/dataset_builder/` | ML | Existing |
| N021 | `model_builder` | `PluginPackage/Common/trainer/` | ML | Alter |
| N022 | `trainer` | `PluginPackage/Common/trainer/` | ML | Alter |
| N023 | `evaluator` | `PluginPackage/Common/evaluator/` | ML | Existing |
| N024 | `edge_optimizer` | `PluginPackage/Common/edge_optimizer/` | ML | Alter |
| N025 | `realtime_inference` | `PluginPackage/Common/realtime_inference/` | Inference | Alter |
| N026 | `dataset_balancer` | `PluginPackage/Common/dataset_balancer/` | ML | Existing |
| N027 | `dataset_versioner` | `PluginPackage/Common/dataset_versioner/` | ML | Existing |
| N028 | `experiment_tracker` | `PluginPackage/Common/experiment_tracker/` | ML | Existing |
| N029 | `deployment_packager` | `PluginPackage/Common/deployment_packager/` | ML | Alter |
| N030 | `embedding_generator` | `PluginPackage/Common/embedding_generator/` | Features | Alter |
| N031 | `multimodal_fusion` | `PluginPackage/Common/multimodal_fusion/` | Features | Existing |
| N032 | `asr_transcribe` | `PluginPackage/Common/asr_transcribe/` | Processing | Existing |
| N033 | `pii_redact` | `PluginPackage/Common/pii_redact/` | Processing | Existing |
| N034 | `structured_llm` | `PluginPackage/Common/structured_llm/` | Processing | Existing |
| N035 | `eval_gate` | `PluginPackage/Common/eval_gate/` | Quality | Existing |
| N036 | `http_webhook` | `PluginPackage/Common/http_webhook/` | Output | Existing |
| N037 | `doc_parse_chunk` | `PluginPackage/Common/doc_parse_chunk/` | Input | Alter |
| N038 | `caption_export` | `PluginPackage/Common/caption_export/` | Output | Existing |
| N039 | `object_store` | `PluginPackage/Common/object_store/` | Output | Existing |
| N040 | `http_request` | `PluginPackage/Common/http_request/` | Output | Existing |
| N041 | `if_switch` | `PluginPackage/Common/if_switch/` | Logic | Existing |
| N042 | `set_map` | `PluginPackage/Common/set_map/` | Transform | Existing |
| N043 | `json_transform` | `PluginPackage/Common/json_transform/` | Transform | Existing |
| N044 | `schedule_trigger` | `PluginPackage/Common/schedule_trigger/` | Input | Existing |
| N045 | `python_code` | `PluginPackage/Common/python_code/` | Transform | Existing |
| N046 | `error_catch` | `PluginPackage/Common/error_catch/` | Logic | Existing |
| N047 | `merge` | `PluginPackage/Common/merge/` | Transform | Existing |
| N048 | `wait_delay` | `PluginPackage/Common/wait_delay/` | Logic | Existing |
| N049 | `csv_table` | `PluginPackage/Common/csv_table/` | Output | Existing |

**Experimental (not in 49):**

| Item | Path | Status |
|---|---|---|
| Video placeholder | `PluginPackage/Video/` | Empty — no manifests; filled by Proposed Video nodes below |
| WakeWord toolkit | `PluginPackage/WakeWord/` | Experimental CLI/library — **not** auto-installed; promote via Proposed WakeWord nodes |

---

## 4. Alterations to existing

Concrete, implementable change list (do not break FaceRecognition or audio DS-CNN graphs).

### 4.1 `trainer` / `model_builder` — vision & TinyML backends

- Keep `architecture ∈ {ds_cnn, mobilenet, simple_cnn}` and Keras audio path **unchanged** as defaults.
- **Design choice:** primary YOLO/TinyML train lives in **new packs** (`Vision/yolo_train`, `TinyML/mcu_train`); `trainer` does not pull `ultralytics` into its isolated venv by default.
- Optional later: adapter hook `framework: keras|pytorch|ultralytics` only if a single Common graph must stay — not Wave 1 default.

### 4.2 `edge_optimizer` / `deployment_packager`

- `edge_optimizer.backend` += `tflm`, `executorch`, `ultralytics_export` (thin wrappers delegating to TinyML/Vision nodes when present).
- Quantization: document int16 path for TFLM; extend `TFLiteArtifact` validator when int16 lands (today: float32/float16/int8).
- `deployment_packager.target` += `cmsis_pack`, `arduino`, `zephyr`, `pte_bundle` (or call TinyML exporter nodes).
- YOLO formats (`onnx`/`engine`/`coreml`/`openvino`/`tflite`/`ncnn`/`rknn`) owned by `yolo_export` with `imgsz`/`half`/`int8`/`nms`.

### 4.3 `doc_parse_chunk` + `embedding_generator` → first-class RAG

- `doc_parse_chunk`: add `chunk_strategy: recursive|semantic|markdown|hierarchical`, `chunk_overlap`, `metadata_keys`; keep `max_chars`.
- Prefer **new RAG pack** for vector store / hybrid / rerank; alter Common to emit richer `Chunk.metadata` (source, page, headers).
- **Design choice:** keep `embedding_generator` audio-stable; new `text_embed` for RAG text modality.

### 4.4 WakeWord experimental → plugin packs

- Gap today: no `plugin.toml`, not auto-installed (`WakeWord/README.md`).
- Add manifests for `wakeword_*` wrapping existing subtrees; until then use Audio/Common templates + `realtime_inference` `mode=wake_word`.

### 4.5 Fill Video pack

- Replace placeholder with real `plugin.toml` plugins (§5 Video). Bridge to Audio via `av_align`.

### 4.6 `realtime_inference` multi-runtime

- Extend `backend`: `tflite|pytorch|onnx|ultralytics|tflm_host|auto`.
- Extend `mode`: add `detect|segment`; keep audio modes.
- Fail-fast when forced backend missing from isolated venv.

---

## 5. Proposed packs & full node catalogue

Each entry: ID, `node_type`, pack path, category, purpose, status, ports, config, deps/runtime, notes.

### Pack: `Audio`

#### N001 — `dataset_ingest` (Existing)

- **Path:** `PluginPackage/Audio/dataset_ingest/`
- **Category:** Input
- **Purpose:** Universal audio ingest (fs/HF/S3/zip/manifest)
- **Inputs:** _none (source)_
- **Outputs:** `output`: `list[AudioSample]`
- **Config:**
  - `source_type:str=filesystem`
  - `path:str`
  - `recursive:bool=True`
  - `limit:int=0`
  - `manifest_path:str`
  - `deduplicate:bool=False`
- **Deps / runtime:** deps:librosa,soundfile; opt:datasets,boto3

#### N002 — `stream_ingest` (Existing)

- **Path:** `PluginPackage/Audio/stream_ingest/`
- **Category:** Input
- **Purpose:** Live mic/websocket/file stream
- **Inputs:** _none (source)_
- **Outputs:** `output`: `list[AudioSample]`
- **Config:**
  - `source:str=microphone`
  - `chunk_ms:int=100`
  - `sample_rate:int=16000`
- **Deps / runtime:** opt:sounddevice,websockets

#### N003 — `audio_conditioner` (Existing)

- **Path:** `PluginPackage/Audio/audio_conditioner/`
- **Category:** Preprocessing
- **Purpose:** Resample/mono/normalize/compress
- **Inputs:** `input`: `list[AudioSample]`
- **Outputs:** `output`: `list[AudioSample]`
- **Config:**
  - `sample_rate:int=16000`
  - `normalize_method:str=peak`
  - `target_lufs:float=-23`
- **Deps / runtime:** deps:librosa,scipy; opt:pyloudnorm

#### N004 — `audio_quality_gate` (Existing)

- **Path:** `PluginPackage/Audio/audio_quality_gate/`
- **Category:** Preprocessing
- **Purpose:** SNR/clipping/duration gate
- **Inputs:** `input`: `list[AudioSample]`
- **Outputs:** `output`: `list[AudioSample]`, `rejected`: `list[AudioSample]`
- **Config:**
  - `min_snr_db:float=10`
  - `rejection_policy:str=skip`
- **Deps / runtime:** deps:librosa,scipy

#### N005 — `audio_annotator` (Existing)

- **Path:** `PluginPackage/Audio/audio_annotator/`
- **Category:** Preprocessing
- **Purpose:** Taxonomy/weak annotation
- **Inputs:** `input`: `list[AudioSample]`
- **Outputs:** `output`: `list[AudioSample]`
- **Config:**
  - `annotation_mode:str=passthrough`
  - `taxonomy:dict={}`
- **Deps / runtime:** deps:numpy

#### N006 — `alignment_node` (Existing)

- **Path:** `PluginPackage/Audio/alignment_node/`
- **Category:** Preprocessing
- **Purpose:** Forced alignment CTC/MFA
- **Inputs:** `audio`: `list[AudioSample]`, `transcripts`: `list[dict]`
- **Outputs:** `output`: `list[AudioSample]`
- **Config:**
  - `backend:str=auto`
  - `level:str=word`
- **Deps / runtime:** opt:ctc-forced-aligner,mfa

#### N007 — `segmenter` (Existing)

- **Path:** `PluginPackage/Audio/segmenter/`
- **Category:** Processing
- **Purpose:** Fixed/VAD/silence segments
- **Inputs:** `input`: `list[AudioSample]`
- **Outputs:** `output`: `list[AudioSample]`
- **Config:**
  - `mode:str=fixed`
  - `window_ms:int=1000`
  - `overlap:float=0`
- **Deps / runtime:** deps:librosa; opt:webrtcvad

#### N008 — `augmentation_pipeline` (Existing)

- **Path:** `PluginPackage/Audio/augmentation_pipeline/`
- **Category:** Augmentation
- **Purpose:** Probabilistic audio augments
- **Inputs:** `input`: `list[AudioSample]`
- **Outputs:** `output`: `list[AudioSample]`
- **Config:**
  - `copies_per_sample:int=1`
  - `augmentations:list`
- **Deps / runtime:** opt:audiomentations

#### N009 — `speech_enhancer` (Existing)

- **Path:** `PluginPackage/Audio/speech_enhancer/`
- **Category:** Enhancement
- **Purpose:** Denoise/dereverb
- **Inputs:** `input`: `list[AudioSample]`
- **Outputs:** `output`: `list[AudioSample]`
- **Config:**
  - `backend:str=auto`
  - `denoise:bool=True`
- **Deps / runtime:** deps:noisereduce; opt:deepfilternet

#### N010 — `speaker_separator` (Existing)

- **Path:** `PluginPackage/Audio/speaker_separator/`
- **Category:** Enhancement
- **Purpose:** Diarization/separation
- **Inputs:** `input`: `list[AudioSample]`
- **Outputs:** `output`: `list[AudioSample]`
- **Config:**
  - `backend:str=auto`
  - `auth_token:str  # resolve_secret HUGGINGFACE_TOKEN`
- **Deps / runtime:** opt:pyannote.audio,speechbrain

#### N011 — `environment_simulator` (Existing)

- **Path:** `PluginPackage/Audio/environment_simulator/`
- **Category:** Enhancement
- **Purpose:** Room RIR simulation
- **Inputs:** `input`: `list[AudioSample]`
- **Outputs:** `output`: `list[AudioSample]`
- **Config:**
  - `preset:str=room`
  - `rt60:float=0.4`
- **Deps / runtime:** deps:pyroomacoustics

#### N012 — `feature_frontend` (Existing)

- **Path:** `PluginPackage/Audio/feature_frontend/`
- **Category:** Features
- **Purpose:** MFCC/log-mel/raw features
- **Inputs:** `input`: `list[AudioSample]`
- **Outputs:** `output`: `list[FeatureArray]`
- **Config:**
  - `feature_type:str=mfcc`
  - `n_mfcc:int=40`
  - `n_mels:int=128`
- **Deps / runtime:** deps:librosa,numpy

#### N013 — `stream_processor` (Existing)

- **Path:** `PluginPackage/Audio/stream_processor/`
- **Category:** Streaming
- **Purpose:** Sliding window buffer
- **Inputs:** `input`: `list[AudioSample]`
- **Outputs:** `output`: `list[AudioSample]`
- **Config:**
  - `window_ms:int=1000`
  - `hop_ms:int=500`
- **Deps / runtime:** deps:numpy

#### N014 — `audio_event_detector` (Existing)

- **Path:** `PluginPackage/Audio/audio_event_detector/`
- **Category:** Detection
- **Purpose:** Temporal event detection
- **Inputs:** `input`: `list[AudioSample]`
- **Outputs:** `output`: `list[AudioSample]`, `events`: `list[dict]`
- **Config:**
  - `backend:str=auto`
  - `threshold:float=0.5`
- **Deps / runtime:** opt:tensorflow,torch

#### N015 — `audio_classifier` (Existing)

- **Path:** `PluginPackage/Audio/audio_classifier/`
- **Category:** Inference
- **Purpose:** Clip classification
- **Inputs:** `input`: `list[AudioSample]|list[FeatureArray]`
- **Outputs:** `output`: `list[PredictionResult]`
- **Config:**
  - `backend:str=auto`
  - `top_k:int=1`
- **Deps / runtime:** opt:tensorflow,torch

#### N016 — `speech_synthesizer` (Existing)

- **Path:** `PluginPackage/Audio/speech_synthesizer/`
- **Category:** Generation
- **Purpose:** TTS Coqui/espeak
- **Inputs:** `input`: `list[str]`
- **Outputs:** `output`: `list[AudioSample]`
- **Config:**
  - `backend:str=auto`
  - `language:str=en`
- **Deps / runtime:** opt:TTS

#### N017 — `voice_converter` (Existing)

- **Path:** `PluginPackage/Audio/voice_converter/`
- **Category:** Generation
- **Purpose:** Speaker conversion
- **Inputs:** `input`: `list[AudioSample]`
- **Outputs:** `output`: `list[AudioSample]`
- **Config:**
  - `backend:str=auto`
  - `conversion_type:str=timbre`
- **Deps / runtime:** opt:speechbrain,torch

#### N018 — `audio_generator` (Existing)

- **Path:** `PluginPackage/Audio/audio_generator/`
- **Category:** Generation
- **Purpose:** MusicGen/AudioGen
- **Inputs:** `input`: `list[str] optional`
- **Outputs:** `output`: `list[AudioSample]`
- **Config:**
  - `backend:str=auto`
  - `duration_s:float=5`
- **Deps / runtime:** opt:audiocraft,torch

#### N019 — `audio_exporter` (Existing)

- **Path:** `PluginPackage/Audio/audio_exporter/`
- **Category:** Output
- **Purpose:** WAV export splits
- **Inputs:** `input`: `list[AudioSample]`
- **Outputs:** `output`: `list[AudioSample]`
- **Config:**
  - `output_dir:str=workspace/datasets/output/audio_export`
  - `split_ratios:dict`
- **Deps / runtime:** deps:soundfile

### Pack: `Common`

#### N020 — `dataset_builder` (Existing)

- **Path:** `PluginPackage/Common/dataset_builder/`
- **Category:** ML
- **Purpose:** FeatureArray→DatasetArtifact
- **Inputs:** `input`: `list[FeatureArray]`
- **Outputs:** `output`: `DatasetArtifact`
- **Config:**
  - `split_ratios:dict`
  - `output_format:str=numpy`
- **Deps / runtime:** deps:numpy,scikit-learn

#### N021 — `model_builder` (Alter)

- **Path:** `PluginPackage/Common/trainer/`
- **Category:** ML
- **Purpose:** DS-CNN/MobileNet/SimpleCNN builder
- **Inputs:** `input`: `object`
- **Outputs:** `output`: `object`
- **Config:**
  - `architecture:str=ds_cnn`
  - `filters:int=64`
  - `backend:str=auto`
  - `output_path:str=workspace/artifacts/models`
- **Deps / runtime:** runtime=isolated; opt:tensorflow,keras,torch
- **Notes:** ALTER: keep audio DS-CNN; YOLO/TinyML via new packs

#### N022 — `trainer` (Alter)

- **Path:** `PluginPackage/Common/trainer/`
- **Category:** ML
- **Purpose:** Train Keras/PyTorch→ModelArtifact
- **Inputs:** `model`: `object`, `dataset`: `DatasetArtifact`
- **Outputs:** `output`: `ModelArtifact`
- **Config:**
  - `backend:str=auto`
  - `epochs:int=30`
  - `batch_size:int=32`
  - `output_path:str=workspace/artifacts/models`
  - `device:str=auto`
- **Deps / runtime:** runtime=isolated; opt:tensorflow,keras,torch
- **Notes:** ALTER: adapter hooks only; yolo_train/mcu_train own primary paths

#### N023 — `evaluator` (Existing)

- **Path:** `PluginPackage/Common/evaluator/`
- **Category:** ML
- **Purpose:** Metrics/plots on ModelArtifact
- **Inputs:** `model_artifact`: `ModelArtifact`, `dataset`: `DatasetArtifact`
- **Outputs:** `output`: `ModelArtifact`
- **Config:**
  - `output_path:str=workspace/artifacts/evaluation`
  - `plot_confusion_matrix:bool=True`
- **Deps / runtime:** deps:scikit-learn

#### N024 — `edge_optimizer` (Alter)

- **Path:** `PluginPackage/Common/edge_optimizer/`
- **Category:** ML
- **Purpose:** TFLite/ONNX quantize→DeploymentArtifact
- **Inputs:** `input`: `ModelArtifact`
- **Outputs:** `output`: `DeploymentArtifact`
- **Config:**
  - `backend:str=tflite`
  - `quantization:str=int8`
  - `output_path:str=workspace/artifacts/optimized`
  - `representative_samples:int=100`
- **Deps / runtime:** runtime=isolated; opt:tensorflow,onnx,onnxruntime,tf2onnx
- **Notes:** ALTER:+tflm|executorch|ultralytics_export backends

#### N025 — `realtime_inference` (Alter)

- **Path:** `PluginPackage/Common/realtime_inference/`
- **Category:** Inference
- **Purpose:** Low-latency TFLite/PyTorch/ONNX
- **Inputs:** `input`: `list[FeatureArray]`
- **Outputs:** `output`: `list[PredictionResult]`
- **Config:**
  - `model_path:str`
  - `backend:str=auto`
  - `mode:str=classification`
  - `wake_word_threshold:float=0.8`
- **Deps / runtime:** runtime=isolated; opt:tensorflow,torch,onnxruntime
- **Notes:** ALTER:+ultralytics|tflm_host; modes detect|segment

#### N026 — `dataset_balancer` (Existing)

- **Path:** `PluginPackage/Common/dataset_balancer/`
- **Category:** ML
- **Purpose:** Class balancing
- **Inputs:** `input`: `DatasetArtifact`
- **Outputs:** `output`: `DatasetArtifact`
- **Config:**
  - `strategy:str=oversample`
- **Deps / runtime:** deps:numpy

#### N027 — `dataset_versioner` (Existing)

- **Path:** `PluginPackage/Common/dataset_versioner/`
- **Category:** ML
- **Purpose:** Hash/version datasets
- **Inputs:** `input`: `DatasetArtifact`
- **Outputs:** `output`: `DatasetArtifact`
- **Config:**
  - `output_dir:str=workspace/datasets/versioned`
- **Deps / runtime:** stdlib

#### N028 — `experiment_tracker` (Existing)

- **Path:** `PluginPackage/Common/experiment_tracker/`
- **Category:** ML
- **Purpose:** JSON/MLflow logging
- **Inputs:** `input`: `ModelArtifact|DatasetArtifact`
- **Outputs:** `output`: `ExperimentArtifact`
- **Config:**
  - `backend:str=json`
  - `experiment_name:str=default`
- **Deps / runtime:** opt:mlflow

#### N029 — `deployment_packager` (Alter)

- **Path:** `PluginPackage/Common/deployment_packager/`
- **Category:** ML
- **Purpose:** mobile/mcu/docker/edge packages
- **Inputs:** `input`: `DeploymentArtifact`
- **Outputs:** `output`: `DeploymentArtifact`
- **Config:**
  - `target:str=mobile`
  - `output_path:str=workspace/artifacts/packages`
- **Deps / runtime:** deps:numpy
- **Notes:** ALTER:+cmsis_pack|arduino|zephyr|pte_bundle

#### N030 — `embedding_generator` (Alter)

- **Path:** `PluginPackage/Common/embedding_generator/`
- **Category:** Features
- **Purpose:** Audio SSL embeddings
- **Inputs:** `input`: `list[AudioSample]|list[FeatureArray]`
- **Outputs:** `output`: `list[EmbeddingVector]`
- **Config:**
  - `model:str=wav2vec2`
  - `pooling:str=mean`
  - `normalize:bool=True`
- **Deps / runtime:** runtime=isolated; opt:transformers,torch
- **Notes:** ALTER: keep audio; RAG uses text_embed

#### N031 — `multimodal_fusion` (Existing)

- **Path:** `PluginPackage/Common/multimodal_fusion/`
- **Category:** Features
- **Purpose:** Cross-modal fusion
- **Inputs:** `audio`: `list[EmbeddingVector]`, `text`: `list[EmbeddingVector] optional`
- **Outputs:** `output`: `list[EmbeddingVector]`
- **Config:**
  - `fusion_type:str=concat`
- **Deps / runtime:** opt:torch,transformers

#### N032 — `asr_transcribe` (Existing)

- **Path:** `PluginPackage/Common/asr_transcribe/`
- **Category:** Processing
- **Purpose:** Cloud ASR→Transcript
- **Inputs:** `input`: `list[AudioSample]`
- **Outputs:** `output`: `Transcript`
- **Config:**
  - `provider:str=openai_compat`
  - `language:str=en`
- **Deps / runtime:** opt:httpx; secrets:OPENAI_API_KEY|…

#### N033 — `pii_redact` (Existing)

- **Path:** `PluginPackage/Common/pii_redact/`
- **Category:** Processing
- **Purpose:** PII redaction
- **Inputs:** `transcript`: `Transcript`
- **Outputs:** `transcript`: `Transcript`, `audit`: `RedactionAudit`
- **Config:**
  - `engine:str=auto`
- **Deps / runtime:** opt:presidio

#### N034 — `structured_llm` (Existing)

- **Path:** `PluginPackage/Common/structured_llm/`
- **Category:** Processing
- **Purpose:** JSON-schema LLM extract
- **Inputs:** `input`: `Transcript|str`
- **Outputs:** `output`: `StructuredDocument`
- **Config:**
  - `provider:str=openai_compat`
  - `model:str=gpt-4o-mini`
  - `json_schema:dict={}`
- **Deps / runtime:** opt:httpx; resolve_secret(OPENAI_API_KEY)

#### N035 — `eval_gate` (Existing)

- **Path:** `PluginPackage/Common/eval_gate/`
- **Category:** Quality
- **Purpose:** Hard-fail quality gate
- **Inputs:** `input`: `Any`
- **Outputs:** `output`: `Any`, `report`: `EvalReport`
- **Config:**
  - `check_empty_transcript:bool=True`
- **Deps / runtime:** stdlib

#### N036 — `http_webhook` (Existing)

- **Path:** `PluginPackage/Common/http_webhook/`
- **Category:** Output
- **Purpose:** HMAC webhook
- **Inputs:** `input`: `Any`
- **Outputs:** `output`: `WebhookReceipt`
- **Config:**
  - `url:str`
  - `hmac_secret:str`
- **Deps / runtime:** opt:httpx

#### N037 — `doc_parse_chunk` (Alter)

- **Path:** `PluginPackage/Common/doc_parse_chunk/`
- **Category:** Input
- **Purpose:** Parse docs→list[Chunk]
- **Inputs:** `input`: `str optional`
- **Outputs:** `output`: `list[Chunk]`
- **Config:**
  - `path:str`
  - `max_chars:int=1200`
  - `use_unstructured:bool=False`
- **Deps / runtime:** opt:unstructured
- **Notes:** ALTER:+chunk_strategy|overlap|metadata_keys

#### N038 — `caption_export` (Existing)

- **Path:** `PluginPackage/Common/caption_export/`
- **Category:** Output
- **Purpose:** SRT/VTT/JSON captions
- **Inputs:** `input`: `Transcript`
- **Outputs:** `output`: `CaptionExportResult`
- **Config:**
  - `formats:list=[srt,vtt,json]`
- **Deps / runtime:** stdlib

#### N039 — `object_store` (Existing)

- **Path:** `PluginPackage/Common/object_store/`
- **Category:** Output
- **Purpose:** Local/S3 get/put/list
- **Inputs:** `input`: `Any optional`
- **Outputs:** `output`: `ObjectRef|list|ObjectList`
- **Config:**
  - `backend:str=local`
  - `operation:str=put`
- **Deps / runtime:** opt:boto3

#### N040 — `http_request` (Existing)

- **Path:** `PluginPackage/Common/http_request/`
- **Category:** Output
- **Purpose:** Generic HTTP
- **Inputs:** `input`: `Any optional`
- **Outputs:** `output`: `HttpResponse`
- **Config:**
  - `method:str=GET`
  - `url:str`
  - `auth_env:str`
- **Deps / runtime:** opt:httpx

#### N041 — `if_switch` (Existing)

- **Path:** `PluginPackage/Common/if_switch/`
- **Category:** Logic
- **Purpose:** Branch expression
- **Inputs:** `input`: `Any`
- **Outputs:** `true`: `Any`, `false`: `Any`, `output`: `BranchResult`
- **Config:**
  - `expression:str`
- **Deps / runtime:** stdlib

#### N042 — `set_map` (Existing)

- **Path:** `PluginPackage/Common/set_map/`
- **Category:** Transform
- **Purpose:** Copy/rename/drop
- **Inputs:** `input`: `Any`
- **Outputs:** `output`: `Any`
- **Config:**
  - `mappings:list=[]`
- **Deps / runtime:** stdlib

#### N043 — `json_transform` (Existing)

- **Path:** `PluginPackage/Common/json_transform/`
- **Category:** Transform
- **Purpose:** JSONPath transform
- **Inputs:** `input`: `Any`
- **Outputs:** `output`: `Any`
- **Config:**
  - `operations:list=[]`
- **Deps / runtime:** stdlib

#### N044 — `schedule_trigger` (Existing)

- **Path:** `PluginPackage/Common/schedule_trigger/`
- **Category:** Input
- **Purpose:** Cron/interval trigger
- **Inputs:** _none (source)_
- **Outputs:** `output`: `TriggerEvent`
- **Config:**
  - `cron:str`
  - `interval_s:int=0`
- **Deps / runtime:** stdlib

#### N045 — `python_code` (Existing)

- **Path:** `PluginPackage/Common/python_code/`
- **Category:** Transform
- **Purpose:** Trusted Python exec
- **Inputs:** `input`: `Any`
- **Outputs:** `output`: `Any`
- **Config:**
  - `code:str`
- **Deps / runtime:** stdlib; not a sandbox

#### N046 — `error_catch` (Existing)

- **Path:** `PluginPackage/Common/error_catch/`
- **Category:** Logic
- **Purpose:** Catch errors
- **Inputs:** `input`: `Any`
- **Outputs:** `output`: `Any`, `error`: `ErrorEnvelope`
- **Config:**
  - `continue_on_error:bool=True`
- **Deps / runtime:** stdlib

#### N047 — `merge` (Existing)

- **Path:** `PluginPackage/Common/merge/`
- **Category:** Transform
- **Purpose:** Merge multi inputs
- **Inputs:** `input`: `Any multi`
- **Outputs:** `output`: `Any`
- **Config:**
  - `strategy:str=concat`
- **Deps / runtime:** stdlib

#### N048 — `wait_delay` (Existing)

- **Path:** `PluginPackage/Common/wait_delay/`
- **Category:** Logic
- **Purpose:** Sleep/wait
- **Inputs:** `input`: `Any`
- **Outputs:** `output`: `Any`
- **Config:**
  - `delay_s:float=1`
- **Deps / runtime:** stdlib

#### N049 — `csv_table` (Existing)

- **Path:** `PluginPackage/Common/csv_table/`
- **Category:** Output
- **Purpose:** CSV read/write
- **Inputs:** `input`: `Any`
- **Outputs:** `output`: `CsvTableResult`
- **Config:**
  - `path:str`
  - `mode:str=write`
- **Deps / runtime:** stdlib

### Pack: `TinyML`

#### N050 — `mcu_dataset_ingest` (Proposed)

- **Path:** `PluginPackage/TinyML/mcu_dataset_ingest/`
- **Category:** Input
- **Purpose:** IMU/audio/image MCU dataset ingest
- **Inputs:** _none (source)_
- **Outputs:** `output`: `list[McuSample] NEW`
- **Config:**
  - `source_type:str=filesystem`
  - `modalities:list=[audio]`
  - `window_ms:int=1000`
  - `sample_rate:int=16000`
  - `path:str`
- **Deps / runtime:** deps:numpy,pandas
- **Notes:** Edge Impulse-style collector

#### N051 — `mcu_label_taxonomy` (Proposed)

- **Path:** `PluginPackage/TinyML/mcu_label_taxonomy/`
- **Category:** Preprocessing
- **Purpose:** MCU class taxonomy remap
- **Inputs:** `input`: `list[McuSample] NEW`
- **Outputs:** `output`: `list[McuSample] NEW`
- **Config:**
  - `taxonomy:dict={}`
  - `drop_unknown:bool=True`
- **Deps / runtime:** stdlib

#### N052 — `mcu_feature_pipeline` (Proposed)

- **Path:** `PluginPackage/TinyML/mcu_feature_pipeline/`
- **Category:** Features
- **Purpose:** MCU-RAM MFCC/spectrogram/IMU features
- **Inputs:** `input`: `list[McuSample] NEW`
- **Outputs:** `output`: `list[FeatureArray]`
- **Config:**
  - `feature_type:str=mfcc`
  - `n_mfcc:int=10`
  - `n_mels:int=40`
  - `fixed_length:int=49`
  - `max_ram_kb:int=256`
- **Deps / runtime:** deps:numpy,librosa
- **Notes:** Cortex-M RAM sized

#### N053 — `mcu_model_zoo` (Proposed)

- **Path:** `PluginPackage/TinyML/mcu_model_zoo/`
- **Category:** ML
- **Purpose:** DS-CNN/MobileNetTiny/MCUNet/KWS zoo
- **Inputs:** `input`: `DatasetArtifact|object`
- **Outputs:** `output`: `object`
- **Config:**
  - `architecture:str=ds_cnn`
  - `num_classes:int=12`
  - `input_shape:list=[49,10,1]`
  - `width_multiplier:float=0.25`
- **Deps / runtime:** runtime=isolated; opt:tensorflow,keras,torch
- **Notes:** Aligns with model_builder DS-CNN

#### N054 — `mcu_train` (Proposed)

- **Path:** `PluginPackage/TinyML/mcu_train/`
- **Category:** ML
- **Purpose:** MCU train + PTQ calib + optional QAT
- **Inputs:** `model`: `object`, `dataset`: `DatasetArtifact`
- **Outputs:** `output`: `ModelArtifact`
- **Config:**
  - `epochs:int=30`
  - `qat:bool=False`
  - `qat_epochs:int=5`
  - `calib_fraction:float=0.1`
  - `output_path:str=workspace/artifacts/models/mcu`
- **Deps / runtime:** runtime=isolated; opt:tensorflow,keras
- **Notes:** PTQ/QAT for TFLM

#### N055 — `tflm_quantize` (Proposed)

- **Path:** `PluginPackage/TinyML/tflm_quantize/`
- **Category:** ML
- **Purpose:** Int8/int16 TFLM-compatible quantize
- **Inputs:** `input`: `ModelArtifact`, `calib`: `DatasetArtifact optional`
- **Outputs:** `output`: `TFLiteArtifact`
- **Config:**
  - `quantization:str=int8`
  - `full_integer:bool=True`
  - `representative_samples:int=100`
  - `ensure_tflm_ops:bool=True`
  - `output_path:str=workspace/artifacts/optimized/tflm`
- **Deps / runtime:** runtime=isolated; opt:tensorflow
- **Notes:** TFLM quant specs; int16 activations

#### N056 — `tflm_convert` (Proposed)

- **Path:** `PluginPackage/TinyML/tflm_convert/`
- **Category:** ML
- **Purpose:** Convert→.tflite micro + CMSIS-NN metadata
- **Inputs:** `input`: `ModelArtifact|TFLiteArtifact`
- **Outputs:** `output`: `DeploymentArtifact`
- **Config:**
  - `cmsis_nn:bool=True`
  - `optimize_for:str=cortex_m55`
  - `output_path:str=workspace/artifacts/optimized/tflite_micro`
- **Deps / runtime:** runtime=isolated; opt:tensorflow
- **Notes:** CMSIS-NN optimize flag metadata

#### N057 — `tflm_op_support_check` (Proposed)

- **Path:** `PluginPackage/TinyML/tflm_op_support_check/`
- **Category:** Quality
- **Purpose:** Check ops vs TFLM kernel allowlist
- **Inputs:** `input`: `TFLiteArtifact|DeploymentArtifact`
- **Outputs:** `output`: `TflmSupportReport NEW`, `artifact`: `DeploymentArtifact`
- **Config:**
  - `tflm_version:str=latest`
  - `fail_on_unsupported:bool=True`
- **Deps / runtime:** stdlib
- **Notes:** Fail-fast missing kernels

#### N058 — `mcu_arena_estimator` (Proposed)

- **Path:** `PluginPackage/TinyML/mcu_arena_estimator/`
- **Category:** Quality
- **Purpose:** Tensor arena / peak RAM estimate
- **Inputs:** `input`: `TFLiteArtifact|DeploymentArtifact`
- **Outputs:** `output`: `ArenaEstimate NEW`
- **Config:**
  - `target_ram_kb:int=256`
  - `headroom_pct:float=15`
- **Deps / runtime:** stdlib

#### N059 — `ethos_u_vela_compile` (Proposed)

- **Path:** `PluginPackage/TinyML/ethos_u_vela_compile/`
- **Category:** ML
- **Purpose:** Arm Vela compile for Ethos-U (needs-tool)
- **Inputs:** `input`: `TFLiteArtifact`
- **Outputs:** `output`: `DeploymentArtifact`
- **Config:**
  - `accelerator:str=ethos-u55-128`
  - `system_config:str=Ethos_U55_High_End_Embedded`
  - `vela_bin:str=vela`
  - `output_path:str=workspace/artifacts/optimized/vela`
- **Deps / runtime:** needs-tool: Vela CLI; fail-fast if missing

#### N060 — `executorch_export` (Proposed)

- **Path:** `PluginPackage/TinyML/executorch_export/`
- **Category:** ML
- **Purpose:** ExecuTorch .pte + Arm TOSA path
- **Inputs:** `input`: `ModelArtifact`
- **Outputs:** `output`: `DeploymentArtifact`
- **Config:**
  - `backend:str=xnnpack`
  - `quantization:str=int8`
  - `output_path:str=workspace/artifacts/optimized/pte`
  - `pte_filename:str=model.pte`
- **Deps / runtime:** runtime=isolated; opt:torch,executorch
- **Notes:** ExecuTorch MCU / TOSA

#### N061 — `cmsis_pack_exporter` (Proposed)

- **Path:** `PluginPackage/TinyML/cmsis_pack_exporter/`
- **Category:** Output
- **Purpose:** CMSIS-Pack / static lib exporter
- **Inputs:** `input`: `DeploymentArtifact`
- **Outputs:** `output`: `DeploymentArtifact`
- **Config:**
  - `pack_vendor:str=Graphyn`
  - `target_rtos:str=none`
  - `include_cmsis_nn:bool=True`
  - `output_path:str=workspace/artifacts/packages/cmsis`
- **Deps / runtime:** stdlib

#### N062 — `mcu_glue_stubs` (Proposed)

- **Path:** `PluginPackage/TinyML/mcu_glue_stubs/`
- **Category:** Output
- **Purpose:** Arduino/Zephyr/FreeRTOS glue stubs
- **Inputs:** `input`: `DeploymentArtifact`
- **Outputs:** `output`: `DeploymentArtifact`
- **Config:**
  - `framework:str=arduino`
  - `board:str`
  - `output_path:str=workspace/artifacts/packages/glue`
- **Deps / runtime:** stdlib templates; no flash

#### N063 — `tflm_host_sim` (Proposed)

- **Path:** `PluginPackage/TinyML/tflm_host_sim/`
- **Category:** Inference
- **Purpose:** Host TFLM/TFLite interpreter eval
- **Inputs:** `model`: `TFLiteArtifact|DeploymentArtifact`, `dataset`: `DatasetArtifact`
- **Outputs:** `output`: `ModelArtifact`, `predictions`: `list[PredictionResult]`
- **Config:**
  - `interpreter:str=tflite_runtime`
  - `batch_limit:int=0`
- **Deps / runtime:** runtime=isolated; opt:tflite-runtime,tensorflow

#### N064 — `mcu_ondevice_metrics` (Proposed)

- **Path:** `PluginPackage/TinyML/mcu_ondevice_metrics/`
- **Category:** Quality
- **Purpose:** On-device metrics placeholder (needs-API)
- **Inputs:** `input`: `DeploymentArtifact`
- **Outputs:** `output`: `OnDeviceMetrics NEW`
- **Config:**
  - `device_id:str`
  - `dry_run:bool=True`
- **Deps / runtime:** needs-API: no Devices metrics API

#### N065 — `mcu_flash_ota` (Proposed)

- **Path:** `PluginPackage/TinyML/mcu_flash_ota/`
- **Category:** Output
- **Purpose:** Flash/OTA to MCU (needs-API honesty)
- **Inputs:** `input`: `DeploymentArtifact`
- **Outputs:** `output`: `FlashReceipt NEW`
- **Config:**
  - `transport:str=swd`
  - `device_id:str`
  - `dry_run:bool=True`
- **Deps / runtime:** needs-API: do NOT fake device APIs; dry_run default

#### N066 — `mcu_dataset_health` (Proposed)

- **Path:** `PluginPackage/TinyML/mcu_dataset_health/`
- **Category:** Quality
- **Purpose:** MCU dataset class balance health
- **Inputs:** `input`: `list[McuSample] NEW|DatasetArtifact`
- **Outputs:** `output`: `DatasetHealthReport NEW`
- **Config:**
  - `min_per_class:int=50`
  - `max_imbalance_ratio:float=5`
- **Deps / runtime:** deps:numpy

#### N067 — `tinyml_ptq_calib_builder` (Proposed)

- **Path:** `PluginPackage/TinyML/tinyml_ptq_calib_builder/`
- **Category:** ML
- **Purpose:** Build PTQ representative set
- **Inputs:** `input`: `DatasetArtifact`
- **Outputs:** `output`: `DatasetArtifact`
- **Config:**
  - `max_samples:int=100`
  - `stratify:bool=True`
  - `seed:int=42`
- **Deps / runtime:** deps:numpy

#### N068 — `micro_speech_pipeline` (Proposed)

- **Path:** `PluginPackage/TinyML/micro_speech_pipeline/`
- **Category:** ML
- **Purpose:** Opinionated KWS→int8 tflite helper
- **Inputs:** `input`: `list[AudioSample]|list[McuSample] NEW`
- **Outputs:** `output`: `DeploymentArtifact`
- **Config:**
  - `labels:list=[yes,no,up,down]`
  - `architecture:str=ds_cnn`
  - `quantize:str=int8`
- **Deps / runtime:** runtime=isolated; opt:tensorflow,keras
- **Notes:** May expand to subgraph Wave 2

#### N069 — `cmsis_nn_optimize_flag` (Proposed)

- **Path:** `PluginPackage/TinyML/cmsis_nn_optimize_flag/`
- **Category:** ML
- **Purpose:** Stamp CMSIS-NN optimize metadata
- **Inputs:** `input`: `DeploymentArtifact`
- **Outputs:** `output`: `DeploymentArtifact`
- **Config:**
  - `enable:bool=True`
  - `kernel_variant:str=auto`
- **Deps / runtime:** metadata only

### Pack: `Vision`

#### N070 — `vision_dataset_ingest` (Proposed)

- **Path:** `PluginPackage/Vision/vision_dataset_ingest/`
- **Category:** Input
- **Purpose:** COCO/YOLO/folder image ingest
- **Inputs:** _none (source)_
- **Outputs:** `output`: `list[ImageSample] NEW`
- **Config:**
  - `source_type:str=folder`
  - `path:str`
  - `split:str=train`
- **Deps / runtime:** deps:pillow; opt:datasets

#### N071 — `vision_label_convert` (Proposed)

- **Path:** `PluginPackage/Vision/vision_label_convert/`
- **Category:** Preprocessing
- **Purpose:** COCO↔YOLO↔VOC label convert
- **Inputs:** `input`: `list[ImageSample] NEW`
- **Outputs:** `output`: `list[ImageSample] NEW`
- **Config:**
  - `from_format:str=coco`
  - `to_format:str=yolo`
  - `class_map:dict={}`
- **Deps / runtime:** stdlib

#### N072 — `vision_train_val_split` (Proposed)

- **Path:** `PluginPackage/Vision/vision_train_val_split/`
- **Category:** ML
- **Purpose:** Vision stratified splits
- **Inputs:** `input`: `list[ImageSample] NEW`
- **Outputs:** `output`: `VisionDatasetArtifact NEW`
- **Config:**
  - `split_ratios:dict={train:0.8,val:0.1,test:0.1}`
  - `seed:int=42`
- **Deps / runtime:** deps:numpy

#### N073 — `vision_augment` (Proposed)

- **Path:** `PluginPackage/Vision/vision_augment/`
- **Category:** Augmentation
- **Purpose:** Mosaic/HSV/flip YOLO-style aug
- **Inputs:** `input`: `list[ImageSample] NEW`
- **Outputs:** `output`: `list[ImageSample] NEW`
- **Config:**
  - `mosaic:bool=True`
  - `hsv_h:float=0.015`
  - `fliplr:float=0.5`
  - `degrees:float=0`
- **Deps / runtime:** runtime=isolated; opt:ultralytics,albumentations

#### N074 — `yolo_train` (Proposed)

- **Path:** `PluginPackage/Vision/yolo_train/`
- **Category:** ML
- **Purpose:** Ultralytics YOLO train
- **Inputs:** `dataset`: `VisionDatasetArtifact NEW`
- **Outputs:** `output`: `ModelArtifact`
- **Config:**
  - `task:str=detect`
  - `model:str=yolov8n.pt`
  - `epochs:int=100`
  - `imgsz:int=640`
  - `batch:int=16`
  - `device:str=auto`
  - `project:str=workspace/artifacts/models/yolo`
- **Deps / runtime:** runtime=isolated; opt:ultralytics,torch
- **Notes:** Ultralytics train; tasks detect|segment|pose|obb|classify

#### N075 — `yolo_val` (Proposed)

- **Path:** `PluginPackage/Vision/yolo_val/`
- **Category:** ML
- **Purpose:** Ultralytics YOLO validation
- **Inputs:** `model`: `ModelArtifact`, `dataset`: `VisionDatasetArtifact NEW`
- **Outputs:** `output`: `ModelArtifact`
- **Config:**
  - `task:str=detect`
  - `imgsz:int=640`
  - `conf:float=0.001`
  - `iou:float=0.6`
- **Deps / runtime:** runtime=isolated; opt:ultralytics,torch

#### N076 — `yolo_predict` (Proposed)

- **Path:** `PluginPackage/Vision/yolo_predict/`
- **Category:** Inference
- **Purpose:** YOLO predict images/video
- **Inputs:** `model`: `ModelArtifact`, `images`: `list[ImageSample] NEW|list[str]`
- **Outputs:** `output`: `list[DetectionResult] NEW`
- **Config:**
  - `task:str=detect`
  - `imgsz:int=640`
  - `conf:float=0.25`
  - `iou:float=0.7`
  - `max_det:int=300`
- **Deps / runtime:** runtime=isolated; opt:ultralytics,torch

#### N077 — `yolo_export` (Proposed)

- **Path:** `PluginPackage/Vision/yolo_export/`
- **Category:** ML
- **Purpose:** Export onnx/engine/coreml/openvino/tflite/ncnn/rknn
- **Inputs:** `input`: `ModelArtifact`
- **Outputs:** `output`: `DeploymentArtifact`
- **Config:**
  - `format:str=onnx`
  - `imgsz:int=640`
  - `half:bool=False`
  - `int8:bool=False`
  - `nms:bool=True`
  - `output_path:str=workspace/artifacts/optimized/yolo`
- **Deps / runtime:** runtime=isolated; opt:ultralytics,onnx
- **Notes:** Ultralytics export; nms=True

#### N078 — `yolo_nms_postprocess` (Proposed)

- **Path:** `PluginPackage/Vision/yolo_nms_postprocess/`
- **Category:** Processing
- **Purpose:** Standalone NMS postprocess
- **Inputs:** `input`: `list[DetectionResult] NEW`
- **Outputs:** `output`: `list[DetectionResult] NEW`
- **Config:**
  - `iou:float=0.45`
  - `conf:float=0.25`
  - `max_det:int=300`
- **Deps / runtime:** deps:numpy

#### N079 — `yolo_track` (Proposed)

- **Path:** `PluginPackage/Vision/yolo_track/`
- **Category:** Inference
- **Purpose:** ByteTrack-style multi-object track
- **Inputs:** `detections`: `list[DetectionResult] NEW`
- **Outputs:** `output`: `list[TrackResult] NEW`
- **Config:**
  - `tracker:str=bytetrack`
  - `track_high_thresh:float=0.5`
- **Deps / runtime:** runtime=isolated; opt:ultralytics

#### N080 — `vision_dataset_health` (Proposed)

- **Path:** `PluginPackage/Vision/vision_dataset_health/`
- **Category:** Quality
- **Purpose:** Class balance / box size health
- **Inputs:** `input`: `list[ImageSample] NEW|VisionDatasetArtifact NEW`
- **Outputs:** `output`: `DatasetHealthReport NEW`
- **Config:**
  - `min_per_class:int=20`
  - `flag_empty_images:bool=True`
- **Deps / runtime:** deps:numpy

#### N081 — `vision_hard_negative_mine` (Proposed)

- **Path:** `PluginPackage/Vision/vision_hard_negative_mine/`
- **Category:** ML
- **Purpose:** Hard-negative mining from preds
- **Inputs:** `predictions`: `list[DetectionResult] NEW`, `dataset`: `VisionDatasetArtifact NEW`
- **Outputs:** `output`: `list[ImageSample] NEW`
- **Config:**
  - `iou_thresh:float=0.5`
  - `max_negatives:int=500`
- **Deps / runtime:** deps:numpy

#### N082 — `onnx_runtime_infer` (Proposed)

- **Path:** `PluginPackage/Vision/onnx_runtime_infer/`
- **Category:** Inference
- **Purpose:** ONNX Runtime vision infer
- **Inputs:** `model`: `DeploymentArtifact`, `images`: `list[ImageSample] NEW`
- **Outputs:** `output`: `list[DetectionResult] NEW|list[PredictionResult]`
- **Config:**
  - `providers:list=[CPUExecutionProvider]`
  - `imgsz:int=640`
  - `task:str=detect`
- **Deps / runtime:** runtime=isolated; opt:onnxruntime

#### N083 — `tensorrt_infer` (Proposed)

- **Path:** `PluginPackage/Vision/tensorrt_infer/`
- **Category:** Inference
- **Purpose:** TensorRT engine infer
- **Inputs:** `model`: `DeploymentArtifact`, `images`: `list[ImageSample] NEW`
- **Outputs:** `output`: `list[DetectionResult] NEW`
- **Config:**
  - `device:int=0`
  - `fp16:bool=True`
  - `imgsz:int=640`
- **Deps / runtime:** runtime=isolated; opt:tensorrt; requires_gpu

#### N084 — `annotation_export_coco` (Proposed)

- **Path:** `PluginPackage/Vision/annotation_export_coco/`
- **Category:** Output
- **Purpose:** Export COCO JSON
- **Inputs:** `input`: `list[ImageSample] NEW|VisionDatasetArtifact NEW`
- **Outputs:** `output`: `AnnotationExport NEW`
- **Config:**
  - `output_path:str=workspace/datasets/vision/coco.json`
- **Deps / runtime:** stdlib

#### N085 — `annotation_export_yolo` (Proposed)

- **Path:** `PluginPackage/Vision/annotation_export_yolo/`
- **Category:** Output
- **Purpose:** Export YOLO labels + data.yaml
- **Inputs:** `input`: `list[ImageSample] NEW|VisionDatasetArtifact NEW`
- **Outputs:** `output`: `AnnotationExport NEW`
- **Config:**
  - `output_dir:str=workspace/datasets/vision/yolo`
  - `create_data_yaml:bool=True`
- **Deps / runtime:** stdlib

#### N086 — `yolo_task_detect` (Proposed)

- **Path:** `PluginPackage/Vision/yolo_task_detect/`
- **Category:** Inference
- **Purpose:** Detect-task wrapper
- **Inputs:** `model`: `ModelArtifact`, `images`: `list[ImageSample] NEW`
- **Outputs:** `output`: `list[DetectionResult] NEW`
- **Config:**
  - `imgsz:int=640`
  - `conf:float=0.25`
- **Deps / runtime:** runtime=isolated; opt:ultralytics
- **Notes:** task=detect fixed

#### N087 — `yolo_task_segment` (Proposed)

- **Path:** `PluginPackage/Vision/yolo_task_segment/`
- **Category:** Inference
- **Purpose:** Segment-task wrapper
- **Inputs:** `model`: `ModelArtifact`, `images`: `list[ImageSample] NEW`
- **Outputs:** `output`: `list[DetectionResult] NEW`
- **Config:**
  - `imgsz:int=640`
  - `retina_masks:bool=False`
- **Deps / runtime:** runtime=isolated; opt:ultralytics

#### N088 — `yolo_task_pose` (Proposed)

- **Path:** `PluginPackage/Vision/yolo_task_pose/`
- **Category:** Inference
- **Purpose:** Pose-task wrapper
- **Inputs:** `model`: `ModelArtifact`, `images`: `list[ImageSample] NEW`
- **Outputs:** `output`: `list[DetectionResult] NEW`
- **Config:**
  - `imgsz:int=640`
  - `kpt_shape:list=[17,3]`
- **Deps / runtime:** runtime=isolated; opt:ultralytics

#### N089 — `yolo_task_obb_classify` (Proposed)

- **Path:** `PluginPackage/Vision/yolo_task_obb_classify/`
- **Category:** Inference
- **Purpose:** OBB or classify task wrapper
- **Inputs:** `model`: `ModelArtifact`, `images`: `list[ImageSample] NEW`
- **Outputs:** `output`: `list[DetectionResult] NEW|list[PredictionResult]`
- **Config:**
  - `task:str=obb`
  - `imgsz:int=640`
- **Deps / runtime:** runtime=isolated; opt:ultralytics
- **Notes:** task enum obb|classify

### Pack: `RAG`

#### N090 — `rag_fs_connector` (Proposed)

- **Path:** `PluginPackage/RAG/rag_fs_connector/`
- **Category:** Input
- **Purpose:** Filesystem docs connector
- **Inputs:** _none (source)_
- **Outputs:** `output`: `list[RawDocument] NEW`
- **Config:**
  - `path:str`
  - `recursive:bool=True`
  - `extensions:list=[pdf,html,md,txt,docx]`
- **Deps / runtime:** opt:pypdf,unstructured

#### N091 — `rag_url_crawl` (Proposed)

- **Path:** `PluginPackage/RAG/rag_url_crawl/`
- **Category:** Input
- **Purpose:** URL crawl for RAG ingest
- **Inputs:** _none (source)_
- **Outputs:** `output`: `list[RawDocument] NEW`
- **Config:**
  - `urls:list=[]`
  - `max_pages:int=20`
  - `same_host_only:bool=True`
- **Deps / runtime:** opt:httpx,beautifulsoup4; egress policy

#### N092 — `rag_notion_connector` (Proposed)

- **Path:** `PluginPackage/RAG/rag_notion_connector/`
- **Category:** Input
- **Purpose:** Notion connector (secret)
- **Inputs:** _none (source)_
- **Outputs:** `output`: `list[RawDocument] NEW`
- **Config:**
  - `secret_name:str=NOTION_API_TOKEN`
  - `database_id:str`
- **Deps / runtime:** opt:httpx; resolve_secret

#### N093 — `rag_slack_connector` (Proposed)

- **Path:** `PluginPackage/RAG/rag_slack_connector/`
- **Category:** Input
- **Purpose:** Slack history connector (secret)
- **Inputs:** _none (source)_
- **Outputs:** `output`: `list[RawDocument] NEW`
- **Config:**
  - `secret_name:str=SLACK_BOT_TOKEN`
  - `channel_ids:list=[]`
- **Deps / runtime:** opt:httpx; resolve_secret

#### N094 — `chunk_recursive` (Proposed)

- **Path:** `PluginPackage/RAG/chunk_recursive/`
- **Category:** Processing
- **Purpose:** Recursive char/token chunker
- **Inputs:** `input`: `list[RawDocument] NEW|list[Chunk]`
- **Outputs:** `output`: `list[Chunk]`
- **Config:**
  - `chunk_size:int=1000`
  - `chunk_overlap:int=200`
  - `length_fn:str=chars`
- **Deps / runtime:** stdlib
- **Notes:** LlamaIndex/LangChain recursive

#### N095 — `chunk_semantic` (Proposed)

- **Path:** `PluginPackage/RAG/chunk_semantic/`
- **Category:** Processing
- **Purpose:** Semantic breakpoint chunker
- **Inputs:** `input`: `list[RawDocument] NEW`
- **Outputs:** `output`: `list[Chunk]`
- **Config:**
  - `embedding_model:str=sentence-transformers/all-MiniLM-L6-v2`
  - `breakpoint_percentile:float=95`
- **Deps / runtime:** runtime=isolated; opt:sentence-transformers,torch

#### N096 — `chunk_markdown` (Proposed)

- **Path:** `PluginPackage/RAG/chunk_markdown/`
- **Category:** Processing
- **Purpose:** Markdown header-aware chunker
- **Inputs:** `input`: `list[RawDocument] NEW`
- **Outputs:** `output`: `list[Chunk]`
- **Config:**
  - `headers_to_split_on:list=[#,##,###]`
  - `chunk_size:int=1200`
- **Deps / runtime:** stdlib

#### N097 — `chunk_hierarchical` (Proposed)

- **Path:** `PluginPackage/RAG/chunk_hierarchical/`
- **Category:** Processing
- **Purpose:** Parent/child hierarchical chunks
- **Inputs:** `input`: `list[RawDocument] NEW`
- **Outputs:** `output`: `list[Chunk]`, `parents`: `list[Chunk]`
- **Config:**
  - `parent_size:int=2000`
  - `child_size:int=400`
- **Deps / runtime:** stdlib

#### N098 — `text_embed` (Proposed)

- **Path:** `PluginPackage/RAG/text_embed/`
- **Category:** Features
- **Purpose:** Text embeddings for chunks
- **Inputs:** `input`: `list[Chunk]|list[str]`
- **Outputs:** `output`: `list[EmbeddingVector]`
- **Config:**
  - `backend:str=sentence_transformers`
  - `model_name_or_path:str=sentence-transformers/all-MiniLM-L6-v2`
  - `normalize:bool=True`
  - `api_secret_name:str=OPENAI_API_KEY`
- **Deps / runtime:** runtime=isolated; opt:sentence-transformers,torch,httpx
- **Notes:** Complements embedding_generator

#### N099 — `multimodal_caption_embed` (Proposed)

- **Path:** `PluginPackage/RAG/multimodal_caption_embed/`
- **Category:** Features
- **Purpose:** Caption then embed images/pages
- **Inputs:** `input`: `list[ImageSample] NEW|list[RawDocument] NEW`
- **Outputs:** `output`: `list[EmbeddingVector]`, `captions`: `list[str]`
- **Config:**
  - `caption_model:str=blip`
  - `embed_model:str=sentence-transformers/all-MiniLM-L6-v2`
- **Deps / runtime:** runtime=isolated; opt:transformers,torch,pillow

#### N100 — `vector_store_write` (Proposed)

- **Path:** `PluginPackage/RAG/vector_store_write/`
- **Category:** Output
- **Purpose:** Write to faiss/chroma/pgvector
- **Inputs:** `embeddings`: `list[EmbeddingVector]`, `chunks`: `list[Chunk] optional`
- **Outputs:** `output`: `VectorStoreRef NEW`
- **Config:**
  - `backend:str=faiss`
  - `persist_path:str=workspace/artifacts/vectorstores/default`
  - `collection:str=default`
  - `pg_dsn_secret:str=PGVECTOR_DSN`
- **Deps / runtime:** runtime=isolated; opt:faiss-cpu,chromadb,psycopg
- **Notes:** Local-first

#### N101 — `vector_store_query` (Proposed)

- **Path:** `PluginPackage/RAG/vector_store_query/`
- **Category:** Processing
- **Purpose:** Dense vector similarity query
- **Inputs:** `store`: `VectorStoreRef NEW`, `query`: `str|EmbeddingVector`
- **Outputs:** `output`: `list[RetrievalHit] NEW`
- **Config:**
  - `top_k:int=5`
  - `backend:str=faiss`
  - `persist_path:str=workspace/artifacts/vectorstores/default`
- **Deps / runtime:** runtime=isolated; opt:faiss-cpu,chromadb

#### N102 — `hybrid_retrieve` (Proposed)

- **Path:** `PluginPackage/RAG/hybrid_retrieve/`
- **Category:** Processing
- **Purpose:** BM25+dense hybrid with RRF
- **Inputs:** `store`: `VectorStoreRef NEW`, `corpus`: `list[Chunk]`, `query`: `str`
- **Outputs:** `output`: `list[RetrievalHit] NEW`
- **Config:**
  - `top_k:int=10`
  - `dense_weight:float=0.5`
  - `bm25_weight:float=0.5`
  - `rrf_k:int=60`
- **Deps / runtime:** deps:numpy; opt:rank-bm25

#### N103 — `rag_rerank` (Proposed)

- **Path:** `PluginPackage/RAG/rag_rerank/`
- **Category:** Processing
- **Purpose:** Cross-encoder/LLM rerank
- **Inputs:** `hits`: `list[RetrievalHit] NEW`, `query`: `str`
- **Outputs:** `output`: `list[RetrievalHit] NEW`
- **Config:**
  - `backend:str=cross_encoder`
  - `model_name_or_path:str=cross-encoder/ms-marco-MiniLM-L-6-v2`
  - `top_n:int=5`
- **Deps / runtime:** runtime=isolated; opt:sentence-transformers,torch

#### N104 — `query_rewrite` (Proposed)

- **Path:** `PluginPackage/RAG/query_rewrite/`
- **Category:** Processing
- **Purpose:** Rewrite/HyDE/multi-query
- **Inputs:** `query`: `str`
- **Outputs:** `output`: `list[str]`
- **Config:**
  - `strategy:str=rewrite`
  - `n_queries:int=3`
  - `model:str=gpt-4o-mini`
  - `api_secret_name:str=OPENAI_API_KEY`
- **Deps / runtime:** opt:httpx; resolve_secret

#### N105 — `contextual_compress` (Proposed)

- **Path:** `PluginPackage/RAG/contextual_compress/`
- **Category:** Processing
- **Purpose:** Compress context to query-relevant spans
- **Inputs:** `hits`: `list[RetrievalHit] NEW`, `query`: `str`
- **Outputs:** `output`: `list[RetrievalHit] NEW`
- **Config:**
  - `backend:str=extractive`
  - `max_chars:int=2000`
- **Deps / runtime:** opt:httpx

#### N106 — `prompt_assemble` (Proposed)

- **Path:** `PluginPackage/RAG/prompt_assemble/`
- **Category:** Processing
- **Purpose:** Assemble RAG prompt slots
- **Inputs:** `query`: `str`, `hits`: `list[RetrievalHit] NEW`
- **Outputs:** `output`: `AssembledPrompt NEW`
- **Config:**
  - `system_template:str`
  - `context_template:str`
  - `max_context_chars:int=8000`
- **Deps / runtime:** stdlib

#### N107 — `rag_generate` (Proposed)

- **Path:** `PluginPackage/RAG/rag_generate/`
- **Category:** Processing
- **Purpose:** Generate answer (wrap structured_llm pattern)
- **Inputs:** `prompt`: `AssembledPrompt NEW`
- **Outputs:** `output`: `RagAnswer NEW`
- **Config:**
  - `provider:str=openai_compat`
  - `model:str=gpt-4o-mini`
  - `temperature:float=0`
  - `api_secret_name:str=OPENAI_API_KEY`
- **Deps / runtime:** opt:httpx; resolve_secret like structured_llm

#### N108 — `citation_attach` (Proposed)

- **Path:** `PluginPackage/RAG/citation_attach/`
- **Category:** Processing
- **Purpose:** Attach citations to RagAnswer
- **Inputs:** `answer`: `RagAnswer NEW`, `hits`: `list[RetrievalHit] NEW`
- **Outputs:** `output`: `RagAnswer NEW`
- **Config:**
  - `style:str=numeric`
  - `min_overlap:float=0.2`
- **Deps / runtime:** stdlib

#### N109 — `rag_eval` (Proposed)

- **Path:** `PluginPackage/RAG/rag_eval/`
- **Category:** Quality
- **Purpose:** Ragas-style faithfulness/relevancy/precision
- **Inputs:** `answer`: `RagAnswer NEW`, `hits`: `list[RetrievalHit] NEW`, `ground_truth`: `str optional`
- **Outputs:** `output`: `RagEvalReport NEW`
- **Config:**
  - `metrics:list=[faithfulness,answer_relevancy,context_precision,context_recall]`
  - `judge_model:str=gpt-4o-mini`
  - `fail_below:dict={}`
- **Deps / runtime:** opt:httpx,ragas
- **Notes:** Ragas-style metrics as config

#### N110 — `kg_light_extract` (Proposed)

- **Path:** `PluginPackage/RAG/kg_light_extract/`
- **Category:** Processing
- **Purpose:** Light entity/relation extract
- **Inputs:** `input`: `list[Chunk]|RagAnswer NEW`
- **Outputs:** `output`: `KnowledgeGraphFragment NEW`
- **Config:**
  - `backend:str=llm`
  - `schema:dict={}`
  - `api_secret_name:str=OPENAI_API_KEY`
- **Deps / runtime:** opt:httpx,spacy

### Pack: `Video`

#### N111 — `video_ingest` (Proposed)

- **Path:** `PluginPackage/Video/video_ingest/`
- **Category:** Input
- **Purpose:** Ingest video files/folders
- **Inputs:** _none (source)_
- **Outputs:** `output`: `list[VideoSample] NEW`
- **Config:**
  - `path:str`
  - `recursive:bool=True`
  - `extensions:list=[mp4,mov,mkv,webm]`
- **Deps / runtime:** deps:opencv-python-headless; runtime=isolated
- **Notes:** Fills empty Video pack

#### N112 — `frame_sample` (Proposed)

- **Path:** `PluginPackage/Video/frame_sample/`
- **Category:** Processing
- **Purpose:** Sample frames fps/every-N/keyframe
- **Inputs:** `input`: `list[VideoSample] NEW`
- **Outputs:** `output`: `list[ImageSample] NEW`
- **Config:**
  - `mode:str=fps`
  - `fps:float=1`
  - `every_n:int=30`
  - `output_dir:str=workspace/datasets/video/frames`
- **Deps / runtime:** deps:opencv-python-headless

#### N113 — `scene_detect` (Proposed)

- **Path:** `PluginPackage/Video/scene_detect/`
- **Category:** Processing
- **Purpose:** Scene boundary detection
- **Inputs:** `input`: `list[VideoSample] NEW`
- **Outputs:** `output`: `list[SceneBoundary] NEW`
- **Config:**
  - `threshold:float=27`
  - `min_scene_len_s:float=1`
  - `backend:str=content`
- **Deps / runtime:** opt:scenedetect,opencv-python-headless

#### N114 — `clip_segment` (Proposed)

- **Path:** `PluginPackage/Video/clip_segment/`
- **Category:** Processing
- **Purpose:** Cut clips from scenes/fixed windows
- **Inputs:** `video`: `list[VideoSample] NEW`, `scenes`: `list[SceneBoundary] NEW optional`
- **Outputs:** `output`: `list[VideoSample] NEW`
- **Config:**
  - `mode:str=scenes`
  - `window_s:float=10`
  - `output_dir:str=workspace/datasets/video/clips`
- **Deps / runtime:** deps:opencv; opt:ffmpeg-python

#### N115 — `video_caption` (Proposed)

- **Path:** `PluginPackage/Video/video_caption/`
- **Category:** Generation
- **Purpose:** VL caption for clips/frames
- **Inputs:** `input`: `list[VideoSample] NEW|list[ImageSample] NEW`
- **Outputs:** `output`: `list[str]`, `captions`: `list[CaptionRecord] NEW`
- **Config:**
  - `backend:str=blip`
  - `api_secret_name:str=OPENAI_API_KEY`
  - `max_frames:int=8`
- **Deps / runtime:** runtime=isolated; opt:transformers,torch,httpx

#### N116 — `action_classify` (Proposed)

- **Path:** `PluginPackage/Video/action_classify/`
- **Category:** Inference
- **Purpose:** Action/activity classify
- **Inputs:** `input`: `list[VideoSample] NEW`
- **Outputs:** `output`: `list[PredictionResult]`
- **Config:**
  - `model_path:str`
  - `backend:str=auto`
  - `num_frames:int=16`
- **Deps / runtime:** runtime=isolated; opt:torch,onnxruntime

#### N117 — `av_align` (Proposed)

- **Path:** `PluginPackage/Video/av_align/`
- **Category:** Processing
- **Purpose:** Align video with AudioSample streams
- **Inputs:** `video`: `list[VideoSample] NEW`, `audio`: `list[AudioSample]`
- **Outputs:** `output`: `list[AvAlignedSample] NEW`
- **Config:**
  - `method:str=timestamp`
  - `max_offset_ms:int=500`
- **Deps / runtime:** deps:numpy
- **Notes:** Bridge Video↔Audio

#### N118 — `video_embed` (Proposed)

- **Path:** `PluginPackage/Video/video_embed/`
- **Category:** Features
- **Purpose:** Clip-level video embeddings
- **Inputs:** `input`: `list[VideoSample] NEW`
- **Outputs:** `output`: `list[EmbeddingVector]`
- **Config:**
  - `model:str=xclip`
  - `num_frames:int=8`
- **Deps / runtime:** runtime=isolated; opt:transformers,torch

#### N119 — `video_quality_gate` (Proposed)

- **Path:** `PluginPackage/Video/video_quality_gate/`
- **Category:** Quality
- **Purpose:** Reject corrupt/short videos
- **Inputs:** `input`: `list[VideoSample] NEW`
- **Outputs:** `output`: `list[VideoSample] NEW`, `rejected`: `list[VideoSample] NEW`
- **Config:**
  - `min_duration_s:float=0.5`
  - `max_duration_s:float=600`
  - `rejection_policy:str=skip`
- **Deps / runtime:** deps:opencv-python-headless

#### N120 — `video_exporter` (Proposed)

- **Path:** `PluginPackage/Video/video_exporter/`
- **Category:** Output
- **Purpose:** Export clips/annotated video
- **Inputs:** `input`: `list[VideoSample] NEW`, `overlays`: `list[DetectionResult] NEW optional`
- **Outputs:** `output`: `list[VideoSample] NEW`
- **Config:**
  - `output_dir:str=workspace/datasets/output/video`
  - `draw_boxes:bool=False`
- **Deps / runtime:** deps:opencv-python-headless

### Pack: `Agents`

#### N121 — `tool_router` (Proposed)

- **Path:** `PluginPackage/Agents/tool_router/`
- **Category:** Agents
- **Purpose:** Route tool-calls to registered tools
- **Inputs:** `input`: `ToolCallRequest NEW`
- **Outputs:** `output`: `ToolCallResult NEW`, `unmatched`: `ToolCallRequest NEW`
- **Config:**
  - `tools:list=[]`
  - `strict:bool=True`
- **Deps / runtime:** stdlib
- **Notes:** Aligns with Graphyn MCP

#### N122 — `agent_loop` (Proposed)

- **Path:** `PluginPackage/Agents/agent_loop/`
- **Category:** Agents
- **Purpose:** Multi-step plan→tool→observe loop
- **Inputs:** `goal`: `str`, `context`: `Any optional`
- **Outputs:** `output`: `AgentResult NEW`
- **Config:**
  - `max_steps:int=8`
  - `model:str=gpt-4o-mini`
  - `api_secret_name:str=OPENAI_API_KEY`
  - `tool_allowlist:list=[]`
- **Deps / runtime:** opt:httpx; resolve_secret

#### N123 — `mcp_tool_call` (Proposed)

- **Path:** `PluginPackage/Agents/mcp_tool_call/`
- **Category:** Agents
- **Purpose:** Invoke Graphyn MCP tool by name
- **Inputs:** `tool_name`: `str`, `arguments`: `dict`
- **Outputs:** `output`: `ToolCallResult NEW`
- **Config:**
  - `timeout_s:float=60`
  - `server:str=graphyn`
- **Deps / runtime:** inprocess MCP registry

#### N124 — `memory_store` (Proposed)

- **Path:** `PluginPackage/Agents/memory_store/`
- **Category:** Agents
- **Purpose:** Short/long-term agent memory
- **Inputs:** `input`: `MemoryOp NEW`
- **Outputs:** `output`: `MemoryRecord NEW`
- **Config:**
  - `backend:str=json`
  - `persist_path:str=workspace/artifacts/agent_memory`
  - `namespace:str=default`
- **Deps / runtime:** stdlib; opt:faiss-cpu

#### N125 — `guardrail_filter` (Proposed)

- **Path:** `PluginPackage/Agents/guardrail_filter/`
- **Category:** Quality
- **Purpose:** PII/jailbreak/toxicity guardrails
- **Inputs:** `input`: `Any`
- **Outputs:** `output`: `Any`, `violations`: `list[GuardrailHit] NEW`
- **Config:**
  - `policies:list=[pii,prompt_injection,toxicity]`
  - `action:str=block`
- **Deps / runtime:** opt:presidio

#### N126 — `llm_chat` (Proposed)

- **Path:** `PluginPackage/Agents/llm_chat/`
- **Category:** Processing
- **Purpose:** Multi-turn chat completion
- **Inputs:** `messages`: `list[dict]`
- **Outputs:** `output`: `ChatMessage NEW`
- **Config:**
  - `model:str=gpt-4o-mini`
  - `temperature:float=0.2`
  - `api_secret_name:str=OPENAI_API_KEY`
- **Deps / runtime:** opt:httpx; resolve_secret

#### N127 — `prompt_template` (Proposed)

- **Path:** `PluginPackage/Agents/prompt_template/`
- **Category:** Transform
- **Purpose:** Jinja/f-string prompt render
- **Inputs:** `variables`: `dict`
- **Outputs:** `output`: `str`
- **Config:**
  - `template:str`
  - `engine:str=fstring`
- **Deps / runtime:** opt:jinja2

#### N128 — `output_schema_validate` (Proposed)

- **Path:** `PluginPackage/Agents/output_schema_validate/`
- **Category:** Quality
- **Purpose:** Validate LLM JSON vs schema
- **Inputs:** `input`: `Any`
- **Outputs:** `output`: `Any`, `errors`: `list[str]`
- **Config:**
  - `json_schema:dict={}`
  - `strict:bool=True`
- **Deps / runtime:** deps:jsonschema|pydantic

### Pack: `MLOps`

#### N129 — `dataset_diff` (Proposed)

- **Path:** `PluginPackage/MLOps/dataset_diff/`
- **Category:** MLOps
- **Purpose:** Diff two DatasetArtifacts
- **Inputs:** `left`: `DatasetArtifact`, `right`: `DatasetArtifact`
- **Outputs:** `output`: `DatasetDiffReport NEW`
- **Config:**
  - `hash_fields:list=[path,label]`
  - `fail_on_drift:bool=False`
- **Deps / runtime:** stdlib

#### N130 — `drift_detect` (Proposed)

- **Path:** `PluginPackage/MLOps/drift_detect/`
- **Category:** MLOps
- **Purpose:** Feature/prediction drift
- **Inputs:** `reference`: `DatasetArtifact|list[FeatureArray]`, `current`: `DatasetArtifact|list[FeatureArray]`
- **Outputs:** `output`: `DriftReport NEW`
- **Config:**
  - `method:str=psi`
  - `threshold:float=0.2`
- **Deps / runtime:** deps:numpy,scipy

#### N131 — `model_card` (Proposed)

- **Path:** `PluginPackage/MLOps/model_card/`
- **Category:** MLOps
- **Purpose:** Generate model card md/json
- **Inputs:** `model`: `ModelArtifact`, `eval`: `ModelArtifact optional`
- **Outputs:** `output`: `ModelCardArtifact NEW`
- **Config:**
  - `output_path:str=workspace/artifacts/model_cards`
  - `include_confusion:bool=True`
- **Deps / runtime:** stdlib

#### N132 — `ab_assign` (Proposed)

- **Path:** `PluginPackage/MLOps/ab_assign/`
- **Category:** MLOps
- **Purpose:** Deterministic A/B assignment
- **Inputs:** `input`: `Any`
- **Outputs:** `output`: `AbAssignment NEW`
- **Config:**
  - `experiment_key:str=default`
  - `variants:list=[control,treatment]`
  - `weights:list=[0.9,0.1]`
- **Deps / runtime:** stdlib hashlib

#### N133 — `canary_gate` (Proposed)

- **Path:** `PluginPackage/MLOps/canary_gate/`
- **Category:** Quality
- **Purpose:** Canary promote/hold gate
- **Inputs:** `metrics`: `dict|ModelArtifact`
- **Outputs:** `output`: `CanaryDecision NEW`
- **Config:**
  - `metric_key:str=test_accuracy`
  - `min_value:float=0`
  - `max_regression:float=0.02`
- **Deps / runtime:** stdlib

#### N134 — `ship_package_create` (Proposed)

- **Path:** `PluginPackage/MLOps/ship_package_create/`
- **Category:** Ship
- **Purpose:** Create ship package (REST semantics)
- **Inputs:** `deployment`: `DeploymentArtifact optional`
- **Outputs:** `output`: `ShipPackageRef NEW`
- **Config:**
  - `project:str`
  - `model_name:str`
  - `model_stage_or_version:str=latest`
  - `target:dict={runtime:tflite,arch:cortex-m55}`
  - `env:str=draft`
  - `unsigned_allowed:bool=True`
- **Deps / runtime:** inprocess→ship_packages; UI Workspace / API projects

#### N135 — `ship_package_transition` (Proposed)

- **Path:** `PluginPackage/MLOps/ship_package_transition/`
- **Category:** Ship
- **Purpose:** Transition ship status
- **Inputs:** `package`: `ShipPackageRef NEW`
- **Outputs:** `output`: `ShipPackageRef NEW`
- **Config:**
  - `action:str=validate`
  - `resource_version:str`
- **Deps / runtime:** validate|build|sign|publish|deploy|fail|supersede

#### N136 — `ship_package_promote` (Proposed)

- **Path:** `PluginPackage/MLOps/ship_package_promote/`
- **Category:** Ship
- **Purpose:** Promote draft→staging→prod
- **Inputs:** `package`: `ShipPackageRef NEW`
- **Outputs:** `output`: `ShipPackageRef NEW`
- **Config:**
  - `to_env:str=staging`
  - `approve:bool=False`
- **Deps / runtime:** inprocess ship promote

#### N137 — `feature_store_write` (Proposed)

- **Path:** `PluginPackage/MLOps/feature_store_write/`
- **Category:** MLOps
- **Purpose:** Light feature store write
- **Inputs:** `features`: `list[FeatureArray]|list[EmbeddingVector]`
- **Outputs:** `output`: `FeatureStoreRef NEW`
- **Config:**
  - `persist_path:str=workspace/artifacts/feature_store`
  - `entity_keys:list=[id]`
- **Deps / runtime:** deps:numpy; opt:pyarrow

#### N138 — `feature_store_read` (Proposed)

- **Path:** `PluginPackage/MLOps/feature_store_read/`
- **Category:** MLOps
- **Purpose:** Light feature store read
- **Inputs:** `store`: `FeatureStoreRef NEW`, `keys`: `list[str]`
- **Outputs:** `output`: `list[FeatureArray]`
- **Config:**
  - `persist_path:str=workspace/artifacts/feature_store`
  - `as_of:str`
- **Deps / runtime:** deps:numpy; opt:pyarrow

#### N139 — `artifact_checksum` (Proposed)

- **Path:** `PluginPackage/MLOps/artifact_checksum/`
- **Category:** MLOps
- **Purpose:** SHA256 checksum + sidecar
- **Inputs:** `input`: `ModelArtifact|DeploymentArtifact|TFLiteArtifact`
- **Outputs:** `output`: `ChecksumRecord NEW`
- **Config:**
  - `algo:str=sha256`
  - `write_sidecar:bool=True`
- **Deps / runtime:** stdlib hashlib

#### N140 — `run_metadata_stamp` (Proposed)

- **Path:** `PluginPackage/MLOps/run_metadata_stamp/`
- **Category:** MLOps
- **Purpose:** Stamp git/versions/seed metadata
- **Inputs:** `input`: `Any`
- **Outputs:** `output`: `Any`
- **Config:**
  - `include_git:bool=True`
  - `seed:int=0`
- **Deps / runtime:** stdlib

### Pack: `WakeWord`

#### N141 — `wakeword_data_gen` (Proposed)

- **Path:** `PluginPackage/WakeWord/wakeword_data_gen/`
- **Category:** Input
- **Purpose:** Promote data_generator→plugin
- **Inputs:** _none (source)_
- **Outputs:** `output`: `list[AudioSample]`
- **Config:**
  - `phrases:list=[]`
  - `sample_rate:int=16000`
  - `output_dir:str=workspace/datasets/wakeword`
- **Deps / runtime:** runtime=isolated
- **Notes:** Gap: add plugin.toml; currently experimental

#### N142 — `wakeword_feature_extract` (Proposed)

- **Path:** `PluginPackage/WakeWord/wakeword_feature_extract/`
- **Category:** Features
- **Purpose:** WakeWord feature_extractor node
- **Inputs:** `input`: `list[AudioSample]`
- **Outputs:** `output`: `list[FeatureArray]`
- **Config:**
  - `n_mfcc:int=40`
  - `n_fft:int=512`
  - `hop_length:int=160`
- **Deps / runtime:** wire existing subtree

#### N143 — `wakeword_train` (Proposed)

- **Path:** `PluginPackage/WakeWord/wakeword_train/`
- **Category:** ML
- **Purpose:** WakeWord training as plugin
- **Inputs:** `dataset`: `DatasetArtifact`
- **Outputs:** `output`: `ModelArtifact`
- **Config:**
  - `epochs:int=30`
  - `output_path:str=workspace/artifacts/models/wakeword`
- **Deps / runtime:** runtime=isolated; opt:tensorflow,torch
- **Notes:** Promote WakeWord/training

#### N144 — `wakeword_export_onnx` (Proposed)

- **Path:** `PluginPackage/WakeWord/wakeword_export_onnx/`
- **Category:** ML
- **Purpose:** WakeWord ONNX exporter node
- **Inputs:** `input`: `ModelArtifact`
- **Outputs:** `output`: `DeploymentArtifact`
- **Config:**
  - `opset:int=13`
  - `output_path:str=workspace/artifacts/optimized/wakeword`
- **Deps / runtime:** opt:onnx,torch
- **Notes:** Promote WakeWord/exporter

#### N145 — `wakeword_infer` (Proposed)

- **Path:** `PluginPackage/WakeWord/wakeword_infer/`
- **Category:** Inference
- **Purpose:** WakeWord realtime infer node
- **Inputs:** `input`: `list[FeatureArray]|list[AudioSample]`
- **Outputs:** `output`: `list[PredictionResult]`
- **Config:**
  - `model_path:str`
  - `threshold:float=0.8`
  - `backend:str=auto`
- **Deps / runtime:** opt:onnxruntime,tflite-runtime
- **Notes:** May share realtime_inference wake_word mode

---

## 6. Summary count table

| Pack root | Existing | Alter | Proposed | Total |
|---|---:|---:|---:|---:|
| Agents | 0 | 0 | 8 | 8 |
| Audio | 19 | 0 | 0 | 19 |
| Common | 23 | 7 | 0 | 30 |
| MLOps | 0 | 0 | 12 | 12 |
| RAG | 0 | 0 | 21 | 21 |
| TinyML | 0 | 0 | 20 | 20 |
| Video | 0 | 0 | 10 | 10 |
| Vision | 0 | 0 | 20 | 20 |
| WakeWord | 0 | 0 | 5 | 5 |
| **TOTAL** | **42** | **7** | **96** | **145** |

**Proof:** 145 ≥ 100 distinct `node_type` values. **Unique:** 145 (no duplicates).

---

## 7. Implementation roadmap

| Wave | Scope |
|---|---|
| **Wave 1** | Interface alterations (§4); RAG pack; Vision YOLO train/val/predict/export |
| **Wave 2** | TinyML TFLM/CMSIS path; ExecuTorch `.pte`; Vela needs-tool |
| **Wave 3** | Video pack fill; Agents; WakeWord `plugin.toml` promotion |
| **Wave 4** | Device flash/OTA + on-device metrics when Devices APIs exist; keep `dry_run` / needs-API until then |

---

## 8. NEW PortDataType registry (proposed)

Declare in owning plugin `types.py` (list before `nodes.py` in `entry_points`):

| Type | Owning pack | Key fields (sketch) |
|---|---|---|
| `McuSample` | TinyML | `path`, `modality`, `data`, `label`, `metadata` |
| `TflmSupportReport` | TinyML | `supported`, `missing_ops`, `tflm_version` |
| `ArenaEstimate` | TinyML | `arena_bytes`, `peak_ram_bytes`, `fits` |
| `OnDeviceMetrics` | TinyML | `latency_ms`, `energy_mj`, `device_id`, `dry_run` |
| `FlashReceipt` | TinyML | `ok`, `dry_run`, `transport`, `artifact_path` |
| `DatasetHealthReport` | TinyML/Vision | `per_class_counts`, `warnings` |
| `ImageSample` | Vision | `path`, `width`, `height`, `boxes`, `label`, `metadata` |
| `VisionDatasetArtifact` | Vision | splits, class_names, paths |
| `DetectionResult` | Vision | `boxes`, `scores`, `classes`, `masks?`, `keypoints?` |
| `TrackResult` | Vision | `track_id`, `box`, `score`, `class_id` |
| `AnnotationExport` | Vision | `path`, `format` |
| `RawDocument` | RAG | `source`, `text`, `mime`, `metadata` |
| `VectorStoreRef` | RAG | `backend`, `persist_path`, `collection` |
| `RetrievalHit` | RAG | `chunk_id`, `text`, `score`, `metadata` |
| `AssembledPrompt` | RAG | `system`, `context`, `user`, `messages` |
| `RagAnswer` | RAG | `text`, `citations`, `raw` |
| `RagEvalReport` | RAG | `metrics`, `passed` |
| `KnowledgeGraphFragment` | RAG | `entities`, `relations` |
| `VideoSample` | Video | `path`, `fps`, `duration_s`, `metadata` |
| `SceneBoundary` | Video | `start_s`, `end_s`, `score` |
| `AvAlignedSample` | Video | `video_path`, `audio_path`, `offset_ms` |
| `CaptionRecord` | Video | `text`, `start_s`, `end_s` |
| `ToolCallRequest` / `ToolCallResult` | Agents | `name`, `arguments`, `result` |
| `AgentResult` | Agents | `answer`, `steps`, `tool_trace` |
| `MemoryOp` / `MemoryRecord` | Agents | `op`, `key`, `value`, `namespace` |
| `GuardrailHit` | Agents | `policy`, `span`, `action` |
| `ChatMessage` | Agents | `role`, `content` |
| `DatasetDiffReport` / `DriftReport` | MLOps | counts / distances |
| `ModelCardArtifact` | MLOps | `path`, `markdown` |
| `AbAssignment` / `CanaryDecision` | MLOps | variant / promote\|hold |
| `ShipPackageRef` | MLOps | `package_id`, `status`, `env`, `resource_version` |
| `FeatureStoreRef` / `ChecksumRecord` | MLOps | paths / digests |

---

## 9. References (standards)

- **TFLM / CMSIS-NN / Ethos-U:** TensorFlow Lite for Microcontrollers kernels; CMSIS-NN optimize; Arm Vela for Ethos-U.
- **ExecuTorch / TOSA:** `.pte` export; Arm TOSA backend path.
- **YOLO:** Ultralytics train/val/predict/export (`onnx`, `engine`, `coreml`, `openvino`, `tflite`, `ncnn`, `rknn`); `imgsz` / `half` / `int8` / `nms=True`.
- **RAG:** ingest→chunk→embed→store; query→retrieve→(hybrid/BM25)→rerank→prompt→generate→eval; LlamaIndex/LangChain patterns on Graphyn typed ports.
- **Ship:** `app/api/routers/ship.py` + `app.core.ship_packages` status machine.

---

*Generated for branch `cursor/usecase-plugins-workflows`. Design-only — implementation follows Waves 1–4.*
