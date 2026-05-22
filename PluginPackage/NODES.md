# Plugin Nodes — Complete Reference

29 plugins total. All complete. For architecture, data types, and install patterns → `ARCHITECTURE.md`.

---

## Audio Plugins — `PluginPackage/Audio/` (18 nodes)

### `dataset_ingest` — Universal Audio Ingestion
**Category:** Input | **Version:** v1.1.0

```python
source_type: str = "filesystem"  # "filesystem" | "huggingface" | "s3" | "zip" | "tar" | "manifest"
path: str = ""                   # local path, S3 URI (s3://bucket/prefix/), HF dataset ID, or archive path
manifest_path: str = ""          # CSV/JSON with path + label columns (overrides path scanning)
recursive: bool = True
limit: int = 0                   # 0 = no limit
label_override: str = ""
hf_split: str = "train"
hf_audio_column: str = "audio"
hf_label_column: str = "label"
resume_from: str = ""            # path to checkpoint file for resumable ingest
validate_integrity: bool = False # SHA256 checksum validation against .sha256 sidecar
deduplicate: bool = False        # skip duplicate waveforms (hash-based)
```

**Ports:** none → `output: list[AudioSample]`

---

### `stream_ingest` — Live Streaming Ingestion
**Category:** Input | **Version:** v1.0.0

```python
source: str = "microphone"   # "microphone" | "websocket" | "file_stream"
device_id: int = 0
websocket_url: str = ""
chunk_ms: int = 100
sample_rate: int = 16000
channels: int = 1
buffer_size: int = 10
```

**Ports:** none → `output: list[AudioSample]` (streaming chunks)
**Capabilities:** `streaming_support=True`, `realtime_support=True`, `cacheable=False`

---

### `audio_conditioner` — Conditioning & Normalization
**Category:** Preprocessing | **Version:** v1.1.0

```python
sample_rate: int = 16000
mono: bool = True
normalize_method: str = "peak"   # "peak" | "rms" | "lufs"
target_lufs: float = -23.0       # EBU R128 (used when normalize_method="lufs")
compress: bool = False
compress_threshold_db: float = -20.0
compress_ratio: float = 4.0
batch_size: int = 0              # 0 = process all at once
```

**Ports:** `input: list[AudioSample]` → `output: list[AudioSample]`
**Metadata set:** `conditioned`, `conditioning` (dict), `clipped`

---

### `audio_quality_gate` — Quality Validation
**Category:** Preprocessing | **Version:** v1.0.0

```python
min_snr_db: float = 10.0
max_clipping_ratio: float = 0.01
min_duration_s: float = 0.1
max_duration_s: float = 60.0
min_lufs: float = -70.0
max_lufs: float = -10.0
min_bandwidth_hz: float = 1000.0
rejection_policy: str = "skip"   # "skip" | "warn" | "raise"
```

**Ports:** `input: list[AudioSample]` → `output: list[AudioSample]` + `rejected: list[AudioSample]`
**Metadata set:** `quality` (dict: snr_db, clipping_ratio, lufs, passed), `quality_rejection_reasons`

---

### `audio_annotator` — Semantic Annotation
**Category:** Preprocessing | **Version:** v1.0.0

```python
annotation_mode: str = "passthrough"  # "passthrough" | "auto" | "taxonomy" | "weak"
taxonomy: dict = {}                   # raw_label → canonical_label
confidence_threshold: float = 0.5
auto_rules: list = []                 # [{"field": "duration", "op": ">", "value": 1.0, "label": "long"}]
```

**Ports:** `input: list[AudioSample]` → `output: list[AudioSample]`

---

### `alignment_node` — Forced Alignment
**Category:** Preprocessing | **Version:** v1.0.0

```python
backend: str = "auto"   # "ctc" | "mfa" | "auto"
language: str = "en"
level: str = "word"     # "word" | "phoneme" | "char"
model_path: str = ""
```

**Ports:** `audio: list[AudioSample]` + `transcripts: list[dict]` → `output: list[AudioSample]`
**Metadata set:** `alignment` (dict: words [{word, start, end}], backend, language)

---

### `segmenter` — Audio Segmentation
**Category:** Processing | **Version:** v1.1.0

```python
mode: str = "fixed"              # "fixed" | "vad" | "silence" | "speaker_turn" | "event"
window_ms: int = 1000            # fixed mode
overlap: float = 0.0             # overlap ratio [0, 1)
vad_aggressiveness: int = 2      # webrtcvad 0–3
silence_threshold_db: float = 40.0
min_segment_ms: int = 100
max_segment_ms: int = 30000
event_threshold_db: float = -40.0
event_min_gap_ms: float = 100.0
```

**Ports:** `input: list[AudioSample]` → `output: list[AudioSample]`
**Metadata set:** `parent`, `start`, `end`, `segment_id`, `segmentation_mode`

---

### `augmentation_pipeline` — Probabilistic Augmentation
**Category:** Augmentation | **Version:** v1.1.0

```python
copies_per_sample: int = 1
augmentations: list = [
    {"type": "gain",         "apply_prob": 0.5, "gain_db": [-6, 6]},
    {"type": "pitch_shift",  "apply_prob": 0.3, "semitones": [-2, 2]},
    {"type": "time_stretch", "apply_prob": 0.3, "rate": [0.9, 1.1]},
    {"type": "speed_perturb","apply_prob": 0.3, "speed_factor": [0.9, 1.1]},
    {"type": "reverb",       "apply_prob": 0.3, "impulse_response_path": ""},
    {"type": "noise_inject", "apply_prob": 0.5, "snr_db": [5, 20]},
    {"type": "codec_degrade","apply_prob": 0.2, "codec": "mp3", "bitrate": 32},
    {"type": "eq",           "apply_prob": 0.2, "bands": [{"freq": 1000, "gain_db": 3}]},
]
```

**Ports:** `input: list[AudioSample]` → `output: list[AudioSample]`
**Metadata set:** `augmented`, `gain_db`, `augmentation_id`

---

### `speech_enhancer` — Denoising & Enhancement
**Category:** Enhancement | **Version:** v1.0.0

```python
backend: str = "auto"        # "spectral" | "deepfilter" | "auto"
denoise: bool = True
dereverb: bool = False
vocal_isolation: bool = False
telephony_mode: bool = False  # 300–3400 Hz bandpass (ITU-T G.712)
prop_decrease: float = 1.0   # spectral backend strength
```

**Ports:** `input: list[AudioSample]` → `output: list[AudioSample]`

---

### `speaker_separator` — Diarization & Separation
**Category:** Enhancement | **Version:** v1.0.0

```python
backend: str = "auto"              # "pyannote" | "speechbrain" | "auto"
num_speakers: int = 0              # 0 = auto-detect
min_speakers: int = 1
max_speakers: int = 10
output_mode: str = "per_speaker"   # "per_speaker" | "diarization_only"
min_segment_s: float = 0.5
auth_token: str = ""               # HuggingFace token for pyannote (or HUGGINGFACE_TOKEN env)
```

**Ports:** `input: list[AudioSample]` → `output: list[AudioSample]`
**Metadata set:** `speaker_id`, `speaker_segments`, `start`, `end`, `parent`

---

### `environment_simulator` — Room Acoustics Simulation
**Category:** Enhancement | **Version:** v1.0.0

```python
preset: str = "room"                    # "room" | "car" | "office" | "outdoor" | "custom"
room_dimensions: list = [5.0, 4.0, 3.0]
rt60: float = 0.4
mic_position: list = [2.0, 2.0, 1.0]
source_position: list = [1.0, 1.0, 1.0]
snr_db: float = 20.0
copies_per_sample: int = 1
max_rir_length_ms: float = 500.0
```

**Ports:** `input: list[AudioSample]` → `output: list[AudioSample]`
**Metadata set:** `room_simulation` (dict: preset, rt60, room_dimensions)

---

### `feature_frontend` — Feature Extraction
**Category:** Features | **Version:** v1.1.0

```python
feature_type: str = "mfcc"   # "mfcc" | "log_mel" | "zcr" | "spectral_centroid" | "spectral_rolloff" | "raw"
n_mfcc: int = 40
n_mels: int = 128
n_fft: int = 2048
hop_length: int = 512
fixed_length: int = 0        # 0 = variable; N = pad/truncate to N frames
delta: bool = False
delta_delta: bool = False
```

**Ports:** `input: list[AudioSample]` → `output: list[FeatureArray]`

---

### `stream_processor` — Streaming Window Management
**Category:** Streaming | **Version:** v1.0.0

```python
window_ms: int = 1000
hop_ms: int = 500
target_latency_ms: int = 200
max_buffer_size: int = 100
```

**Ports:** `input: list[AudioSample]` → `output: list[AudioSample]`
**Capabilities:** `streaming_support=True`, `realtime_support=True`

---

### `audio_event_detector` — Temporal Event Detection
**Category:** Detection | **Version:** v1.0.0

```python
model_path: str = ""          # empty = built-in YAMNet (521 classes)
backend: str = "auto"         # "tflite" | "pytorch" | "yamnet" | "auto"
threshold: float = 0.5
event_types: list = []        # empty = all; or ["cough", "gunshot", ...]
min_event_duration_ms: float = 100.0
```

**Ports:** `input: list[AudioSample]` → `output: list[AudioSample]` + `events: list[dict]`
**Metadata set:** `events` (list[{event, start, end, confidence}])

---

### `audio_classifier` — Audio Classification
**Category:** Inference | **Version:** v1.0.0

```python
model_path: str = ""   # empty = built-in YAMNet
backend: str = "auto"  # "tflite" | "pytorch" | "yamnet" | "auto"
top_k: int = 1
```

**Ports:** `input: list[AudioSample]` or `list[FeatureArray]` → `output: list[PredictionResult]`

---

### `speech_synthesizer` — Text-to-Speech
**Category:** Generation | **Version:** v1.0.0

```python
backend: str = "auto"    # "coqui" | "espeak" | "auto"
model_name: str = "tts_models/en/ljspeech/tacotron2-DDC"
language: str = "en"
speaker: str = ""
reference_audio: str = ""   # path to reference audio for voice cloning
sample_rate: int = 22050
```

**Ports:** `input: list[str]` → `output: list[AudioSample]`

---

### `voice_converter` — Speaker Identity Conversion
**Category:** Generation | **Version:** v1.0.0

```python
backend: str = "auto"              # "speechbrain" | "knnvc" | "pitch_only" | "auto"
conversion_type: str = "timbre"    # "timbre" | "accent" | "gender" | "style"
target_speaker: str = ""
pitch_shift_semitones: float = 0.0
```

**Ports:** `input: list[AudioSample]` → `output: list[AudioSample]`

---

### `audio_generator` — Audio Content Generation
**Category:** Generation | **Version:** v1.0.0

```python
backend: str = "auto"         # "musicgen" | "audiogen" | "auto"
model_size: str = "small"     # "small" | "medium" | "large"
duration_s: float = 5.0
prompt: str = ""
conditioning_audio: str = ""  # path to melody/style reference
temperature: float = 1.0
top_k: int = 250
guidance_scale: float = 3.0
```

**Ports:** `input: list[str]` (optional prompts) → `output: list[AudioSample]`
**Capabilities:** `requires_gpu=True`, `supports_edge=False`

---

## Common Plugins — `PluginPackage/Common/` (11 nodes)

### `dataset_builder` — ML Dataset Assembly
**Category:** ML | **Version:** v1.0.0

```python
split_ratios: dict = {"train": 0.7, "val": 0.15, "test": 0.15}
shuffle: bool = True
stratify: bool = True
output_format: str = "numpy"   # "numpy" | "tensorflow" | "pytorch" | "tfrecord"
fixed_length: int = 0          # 0 = variable; N = pad/truncate to N frames
random_seed: int = 42
```

**Ports:** `input: list[FeatureArray]` → `output: DatasetArtifact`

---

### `trainer` — Model Training
**Category:** ML | **Version:** v1.0.0

```python
backend: str = "auto"        # "keras" | "pytorch" | "auto"
epochs: int = 30
batch_size: int = 32
output_path: str = "workspace/artifacts/models"
patience: int = 5
mixed_precision: bool = False
min_val_accuracy: float = 0.0
checkpoint_path: str = ""
```

**Ports:** `model` (Keras/PyTorch model) + `dataset: DatasetArtifact` → `output: ModelArtifact`

---

### `evaluator` — Model Evaluation
**Category:** ML | **Version:** v1.0.0

```python
output_path: str = "workspace/artifacts/evaluation"
plot_confusion_matrix: bool = True
plot_training_curves: bool = True
compute_roc: bool = True
compute_fairness: bool = False
fairness_attribute_key: str = "speaker_id"
```

**Ports:** `model_artifact: ModelArtifact` + `dataset: DatasetArtifact` → `output: ModelArtifact` (with metrics)

---

### `edge_optimizer` — Model Quantization & Optimization
**Category:** ML | **Version:** v1.0.0

```python
backend: str = "auto"          # "tflite" | "onnx" | "auto"
quantization: str = "int8"     # "float32" | "float16" | "int8"
output_path: str = "workspace/artifacts/optimized"
representative_samples: int = 100
operator_fusion: bool = True
prune: bool = False
prune_sparsity: float = 0.5
```

**Ports:** `input: ModelArtifact` → `output: DeploymentArtifact`

---

### `realtime_inference` — Low-Latency Inference
**Category:** Inference | **Version:** v1.1.0

```python
model_path: str               # required
backend: str = "auto"         # "tflite" | "pytorch" | "onnx" | "auto"
mode: str = "classification"  # "classification" | "wake_word" | "streaming_asr"
wake_word_threshold: float = 0.8
batch_size: int = 1
adaptive: bool = False        # skip frames under CPU load
streaming_buffer_size: int = 10
adaptive_skip_ratio: float = 0.0
```

**Ports:** `input: list[FeatureArray]` → `output: list[PredictionResult]`
**Capabilities:** `streaming_support=True`, `realtime_support=True`

---

### `dataset_balancer` — Class Balancing
**Category:** ML | **Version:** v1.0.0

```python
strategy: str = "oversample"   # "oversample" | "undersample" | "weighted" | "synthetic"
target_count: int = 0          # 0 = match majority class
balance_by: str = "class"      # "class" | "speaker" | "duration"
speaker_key: str = "speaker_id"
```

**Ports:** `input: DatasetArtifact` → `output: DatasetArtifact`

---

### `dataset_versioner` — Dataset Versioning
**Category:** ML | **Version:** v1.0.0

```python
output_dir: str = "workspace/datasets/versioned"
version_tag: str = ""          # auto-generated from SHA256 hash if empty
include_metadata: bool = True
create_snapshot: bool = False  # copy files to versioned dir
```

**Ports:** `input: DatasetArtifact` → `output: DatasetArtifact` (with `version`, `hash`, `manifest_path`)

---

### `experiment_tracker` — Experiment Logging
**Category:** ML | **Version:** v1.0.0

```python
backend: str = "json"          # "json" | "mlflow"
experiment_name: str = "default"
tracking_uri: str = ""         # MLflow tracking URI
log_artifacts: bool = True
```

**Ports:** `input: ModelArtifact | DatasetArtifact` → `output: ExperimentArtifact`

JSON backend writes to `workspace/runs/{run_id}/experiment.json`. Auto-captures git hash, Python version, platform.

---

### `deployment_packager` — Deployment Packaging
**Category:** ML | **Version:** v1.0.0

```python
target: str = "mobile"         # "mobile" | "mcu" | "docker" | "edge"
output_path: str = "workspace/artifacts/packages"
include_inference_script: bool = True
include_metadata: bool = True
```

**Ports:** `input: DeploymentArtifact` → `output: DeploymentArtifact`

Package formats:
- `mobile` — ZIP: `.tflite` + `labels.txt` + `metadata.json` + Android snippet
- `mcu` — C header: model as byte array + labels array
- `docker` — TAR: `Dockerfile` + model + FastAPI inference server
- `edge` — TAR: model + `run_inference.py` + `requirements.txt`

---

### `embedding_generator` — Audio Embeddings
**Category:** Features | **Version:** v1.0.0

```python
model: str = "wav2vec2"        # "wav2vec2" | "hubert" | "clap" | "yamnet" | "openl3" | "xvector"
model_name_or_path: str = ""   # HuggingFace model ID or local path (overrides model)
pooling: str = "mean"          # "mean" | "cls" | "last" | "none"
normalize: bool = True
layer: int = -1                # transformer layer to extract (-1 = last)
```

**Ports:** `input: list[AudioSample]` or `list[FeatureArray]` → `output: list[EmbeddingVector]`
**Metadata set:** `embedding_model`

---

### `multimodal_fusion` — Cross-Modal Fusion
**Category:** Features | **Version:** v1.0.0

```python
fusion_type: str = "concat"    # "concat" | "attention" | "late" | "cross_attention"
audio_dim: int = 768
text_dim: int = 768
output_dim: int = 512
```

**Ports:** `audio: list[EmbeddingVector]` + `text: list[EmbeddingVector]` (opt) + `video: list[EmbeddingVector]` (opt) → `output: list[EmbeddingVector]`

---

## Capability Matrix

| Node | GPU Req | Edge | Streaming | Realtime | Deterministic | Cacheable |
|---|---|---|---|---|---|---|
| `dataset_ingest` | No | No | Yes | No | Yes | Yes |
| `stream_ingest` | No | Yes | Yes | Yes | No | No |
| `audio_conditioner` | No | Yes | No | Yes | Yes | Yes |
| `audio_quality_gate` | No | Yes | No | No | Yes | Yes |
| `audio_annotator` | No | Yes | No | No | Yes | Yes |
| `alignment_node` | No | No | No | No | Yes | Yes |
| `segmenter` | No | Yes | Yes | Yes | Yes | Yes |
| `augmentation_pipeline` | No | Yes | No | No | No | No |
| `speech_enhancer` | Optional | Yes (CPU) | No | Yes | No | Yes |
| `speaker_separator` | Optional | No | No | Yes | No | No |
| `environment_simulator` | No | No | No | No | No | No |
| `feature_frontend` | No | Yes | No | Yes | Yes | Yes |
| `stream_processor` | No | Yes | Yes | Yes | Yes | No |
| `audio_event_detector` | Optional | Yes (TFLite) | Yes | Yes | Yes | No |
| `audio_classifier` | Optional | Yes (TFLite) | No | Yes | Yes | No |
| `speech_synthesizer` | Optional | No | No | Yes | No | No |
| `voice_converter` | Optional | No | No | Yes | No | No |
| `audio_generator` | Yes | No | No | No | No | No |
| `dataset_builder` | No | No | No | No | Yes | Yes |
| `trainer` | Optional | No | No | No | No | No |
| `evaluator` | No | No | No | No | Yes | No |
| `edge_optimizer` | No | No | No | No | Yes | Yes |
| `realtime_inference` | Optional | Yes (TFLite) | Yes | Yes | Yes | No |
| `dataset_balancer` | No | No | No | No | No | No |
| `dataset_versioner` | No | No | No | No | Yes | Yes |
| `experiment_tracker` | No | No | No | No | Yes | Yes |
| `deployment_packager` | No | No | No | No | Yes | Yes |
| `embedding_generator` | Optional | No | No | No | Yes | Yes |
| `multimodal_fusion` | Optional | No | No | Yes | No | No |
