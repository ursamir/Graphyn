# Design Document: Speech Commands End-to-End Training Pipeline (Example 06)

## Overview

Example 06 extends Example 02 into a complete end-to-end ML system. It reuses the
same 6-class dataset pipeline (yes/no/up/down/go/stop) and adds feature extraction,
model training, evaluation, TFLite export, and inference — all as plugin nodes that
auto-discover into the existing `NodeRegistry`.

The implementation lives entirely under `examples/06_speech_commands_e2e/` and
introduces no changes to the core `app/` package.

---

## Sub-Documents

Detailed design is split across four focused documents:

| Document | Contents |
|---|---|
| [design_data_types.md](design_data_types.md) | New `PortDataType` subclasses and their field contracts |
| [design_plugin_nodes.md](design_plugin_nodes.md) | All 10 plugin node class designs with signatures, configs, and data flow |
| [design_pipelines.md](design_pipelines.md) | Training and inference pipeline compositions, YAML configs, SDK scripts |
| [design_testing.md](design_testing.md) | Property-based testing strategy and correctness properties |

---

## Directory Structure

```
examples/06_speech_commands_e2e/
├── plugins/
│   ├── data_types.py            # FeatureArray, ModelArtifact, TFLiteArtifact, PredictionResult
│   ├── feature_extractor.py     # FeatureExtractorNode
│   ├── dataset_builder.py       # DatasetBuilderNode
│   ├── model_builder.py         # ModelBuilderNode
│   ├── model_trainer.py         # ModelTrainerNode
│   ├── model_evaluator.py       # ModelEvaluatorNode
│   ├── tflite_exporter.py       # TFLiteExporterNode
│   ├── inference_node.py        # InferenceNode
│   ├── feature_visualizer.py    # FeatureVisualizerNode
│   ├── confusion_matrix_node.py # ConfusionMatrixNode
│   └── training_curves_node.py  # TrainingCurvesNode
├── pipeline_train.yaml          # Training pipeline YAML (yes label only, for CLI)
├── pipeline_infer.yaml          # Inference pipeline YAML
├── run_train.py                 # SDK script — all 6 labels, full training run
├── run_infer.py                 # SDK script — inference with --model / --input args
├── README.md                    # Usage guide
└── output/                      # Generated at runtime
    ├── saved_model/             # Keras SavedModel
    ├── tflite/
    │   ├── model.tflite
    │   └── labels.txt
    ├── metrics.json
    ├── confusion_matrix.png
    ├── training_curves.png
    └── features/                # Feature visualizations (optional)
```

---

## Data Flow

### Training Pipeline (per-label preprocessing → single training run)

```
Phase 1 — Data Preprocessing (run 6× with append, same as Example 02)
─────────────────────────────────────────────────────────────────────
file_input(data/{label})
  → clean(16kHz)
  → trim(-40dB)
  → silence_detector(remove)
  → command_validator(flag, 200ms–1000ms)
  → pitch_shift(±2 semitones, 1 copy)
  → time_stretch(0.9–1.1×, 1 copy)
  → duplicate(target=50, balance)
  → split(70/15/15)
  → file_export(append → output/dataset/)

Phase 2 — Feature Extraction + Training (run once on full dataset)
──────────────────────────────────────────────────────────────────
file_input(output/dataset/)
  → feature_extractor(mfcc, 40 bins, 101 frames)
  → dataset_builder                    # list[FeatureArray] → dict{X_train,...}
  → model_builder(ds_cnn)              # dict → keras.Model
  → model_trainer(30 epochs)           # (Model, dict) → ModelArtifact
  → model_evaluator                    # (ModelArtifact, dict) → ModelArtifact+metrics
  → tflite_exporter(int8)              # ModelArtifact → TFLiteArtifact
```

### Inference Pipeline

```
file_input(input_dir/)
  → clean(16kHz)
  → trim(-40dB)
  → feature_extractor(mfcc, 40 bins, 101 frames)   ← same config as training
  → inference(model_path=output/tflite/model.tflite)
  → [stdout: filename → label (confidence%)]
```

---

## Key Design Decisions

### 1. Two-phase training script

The training script (`run_train.py`) runs in two phases:
- **Phase 1**: Loops over 6 labels, runs the preprocessing pipeline with `append=True`
  (identical to Example 02's `run_sdk.py`). Output goes to `output/dataset/`.
- **Phase 2**: Runs the ML pipeline once on the full assembled dataset.

This mirrors Example 02's pattern and keeps each pipeline linear (no branching).

### 2. Multi-port nodes for training stages

`ModelBuilderNode`, `ModelTrainerNode`, and `ModelEvaluatorNode` are multi-port nodes
(not SISO) because they need two inputs each:
- `ModelBuilderNode`: `dataset` port (dict with shape metadata) + produces `model` port
- `ModelTrainerNode`: `model` port (keras.Model) + `dataset` port (dict with arrays)
- `ModelEvaluatorNode`: `model_artifact` port (ModelArtifact) + `dataset` port

The pipeline executor passes these as a `dict` keyed by port name.

### 3. PortDataType for ML artifacts

`ModelArtifact`, `TFLiteArtifact`, and `PredictionResult` are `PortDataType` subclasses
so they appear in the `TypeCatalogue` and can be used for port compatibility checking.
The Keras `Model` object itself is passed as a plain Python object (not a PortDataType)
since it cannot be serialised to Pydantic.

### 4. Lifecycle hook usage

All nodes with expensive initialisation use `setup()`:
- `ModelEvaluatorNode.setup()`: loads SavedModel via `keras.saving.load_model`
- `InferenceNode.setup()`: loads TFLite flatbuffer, allocates tensors
- `ModelTrainerNode.setup()`: verifies TensorFlow is importable

### 5. Feature consistency between training and inference

The `feature_extractor` config (feature_type, n_mfcc, fixed_length, normalize) must
be identical in both pipelines. The `run_infer.py` script reads the config from a
`feature_config.json` file written by `run_train.py` to `output/feature_config.json`.

### 6. Seed propagation

The pipeline executor passes `seed` to every node's `__init__`. Nodes that need
determinism (`ModelBuilderNode`, `ModelTrainerNode`) call `keras.utils.set_random_seed(seed)`
at the start of their `process()` method.

---

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| `tensorflow` | ≥2.15 | Keras 3 backend, TFLite conversion |
| `keras` | ≥3.0 | Model building, training, saving |
| `librosa` | ≥0.10 | MFCC, mel spectrogram |
| `numpy` | ≥1.24 | Array operations |
| `matplotlib` | ≥3.7 | Training curves, feature plots |
| `seaborn` | ≥0.12 | Confusion matrix heatmap |
| `scikit-learn` | ≥1.3 | Precision/recall/F1 metrics |
| `soundfile` | ≥0.12 | Already in project |

All are installed via `venv/bin/pip install <package>`.
