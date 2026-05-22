---
inclusion: fileMatch
fileMatchPattern: "app/models/**"
---

# Data Models

All types in `app/models/` extend `PortDataType`. Import from `app.models`. These are platform-core types — registered at startup, always available. Plugin-domain types belong in the plugin's `types.py`, never here.

## Platform Types

| Type | Key Fields | Produced by |
|---|---|---|
| `DataSample` | `id`, `source`, `metadata` | Base type — subclass for new domains |
| `AudioSample` | `path`, `sample_rate`, `data` (numpy float32), `label`, `metadata` | `dataset_ingest`, `stream_ingest` |
| `FeatureArray` | `data` (float32 [T,F]), `label`, `sample_rate`, `source_path`, `feature_type`, `metadata` | `feature_frontend` |
| `TensorBatch` | `data` (float32 [N,...]), `labels`, `split`, `source_ids`, `metadata` | Dataset assembly nodes |
| `ModelArtifact` | `model_path`, `labels`, `history`, `metrics` | `trainer`, `evaluator` |
| `TFLiteArtifact` | `tflite_path`, `labels`, `quantisation`, `file_size_bytes` | `edge_optimizer` (TFLite backend) |
| `PredictionResult` | `source_path`, `predicted_label`, `probabilities`, `metadata` | `realtime_inference`, `audio_classifier` |
| `DeploymentArtifact` | `artifact_path`, `model_format`, `target_hardware`, `quantization`, `labels`, `benchmark`, `metadata` | `deployment_packager`, `edge_optimizer` |

## Plugin-Owned Types

Registered only when the owning plugin is installed:

| Type | Plugin | Key Fields |
|---|---|---|
| `DatasetArtifact` | `Common/dataset_builder` | `X_train/val/test`, `y_train/val/test`, `labels`, `input_shape`, `n_classes`, `version`, `hash` |
| `EmbeddingVector` | `Common/embedding_generator` | `embedding` (float32 [D]), `source_path`, `label`, `embedding_model`, `pooling` |
| `ExperimentArtifact` | `Common/experiment_tracker` | `run_id`, `experiment_name`, `parameters`, `metrics`, `artifact_paths`, `backend` |

## `AudioSample.metadata` Conventions

Every plugin that transforms audio adds a key to `metadata` describing what it did.

| Key | Set by | Value |
|---|---|---|
| `parent`, `start`, `end`, `segment_id` | `segmenter` | str, float, float, int |
| `augmented`, `gain_db`, `augmentation_id` | `augmentation_pipeline` | bool, float, int |
| `conditioned`, `conditioning`, `clipped` | `audio_conditioner` | bool, dict, bool |
| `quality` | `audio_quality_gate` | dict: snr_db, clipping_ratio, lufs, passed |
| `speaker_id`, `speaker_segments` | `speaker_separator` | str, list[dict] |
| `alignment` | `alignment_node` | dict: words [{word, start, end}], backend, language |
| `events` | `audio_event_detector` | list[{event, start, end, confidence}] |
| `room_simulation` | `environment_simulator` | dict: preset, rt60, room_dimensions |
| `embedding_model` | `embedding_generator` | str |
| `split` | dataset split nodes | `"train"` \| `"val"` \| `"test"` |

## Workspace Layout

```
workspace/
├── datasets/
│   ├── input/{label}/*.wav|mp3
│   └── output/{project}/{version}/
│       ├── train|val|test/{label}/{hash}.wav
│       ├── labels.csv          # id,path,label,split
│       └── metadata.json
├── runs/{run_id}/
│   ├── meta.json, logs.json, graph.json
│   ├── resume_state.json       # when checkpoint=True
│   └── checkpoints/node_{id}/*.wav + manifest.json
├── artifacts/{artifact_id}/record.json + data/
├── provenance/{artifact_id}.json + by_run/{run_id}.json
├── cache/{sha256}/*.wav + manifest.json
└── webhooks.json
```

## Security Boundaries

- Input paths must be inside `workspace/datasets/input/`
- Output paths must be inside `workspace/datasets/output/`; `project`/`version` match `^[a-zA-Z0-9_\-]+`
- API: `_safe_child()` on all path components; template names `^[A-Za-z0-9_-]+`; run IDs alphanumeric
- Upload filenames are replaced with timestamped names
