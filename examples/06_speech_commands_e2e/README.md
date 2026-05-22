# Example 06 — Speech Commands End-to-End Training

A complete machine learning pipeline from raw audio to a trained TFLite model — data preprocessing, feature extraction, DS-CNN training, evaluation, and INT8 export. Built on top of Example 02.

**Task:** 6-class spoken command recognition (yes / no / up / down / go / stop)
**Architecture:** DS-CNN (Depthwise Separable CNN) — lightweight, edge-deployable
**Features:** 40-bin MFCC, 101 frames (~1 second at 16 kHz)
**Deployment target:** TFLite INT8

---

## Prerequisites

### 1. Install dependencies

```bash
venv/bin/pip install tensorflow keras scikit-learn seaborn matplotlib
```

### 2. Prepare data

This example uses the same data as Example 02. If you haven't already:

```bash
venv/bin/python examples/prepare_real_data.py
```

The pipeline automatically falls back to `examples/02_speech_commands/data/` if
`examples/06_speech_commands_e2e/data/` doesn't exist.

---

## How to Run

```bash
# Phase 1 + Phase 2 end-to-end (SDK)
venv/bin/python examples/06_speech_commands_e2e/run_train.py

# Inference on a directory of WAV files (requires trained model)
venv/bin/python examples/06_speech_commands_e2e/run_infer.py \
    --model examples/06_speech_commands_e2e/output/tflite/model.tflite \
    --input examples/02_speech_commands/data/yes
```

---

## Pipeline Architecture

Training is split into two sequential phases.

### Phase 1 — Data Preprocessing (runs 6× — once per label)

```
dataset_ingest(data/{label}/)
    │  Load 200 WAV clips
    ▼
audio_conditioner
    │  Resample to 16 kHz, mono, peak-normalise
    ▼
segmenter
    │  Remove leading/trailing silence (threshold: -40 dB)
    ▼
audio_quality_gate  (SNR filter)
    │  Drop clips with SNR < -60 dB
    ▼
audio_quality_gate  (duration filter)
    │  Keep clips between 0.2 s and 1.0 s
    ▼
augmentation_pipeline
    │  pitch_shift ±2 semitones + time_stretch 0.9×–1.1×
    │  copies_per_sample=2 → ~3× more samples
    ▼
audio_exporter(output/dataset/speech_commands/, append=True)
    │  Writes WAV files split 70/15/15 train/val/test
    └─ Appends each label's output to the same directory
```

### Phase 2 — Feature Extraction + Training (runs once)

Uses explicit edge routing because `trainer` and `evaluator` have named input ports.

```
dataset_ingest(output/dataset/speech_commands/v1/, recursive=True)
    │  Load all preprocessed WAV files
    ▼
feature_frontend
    │  MFCC: 40 coefficients, 101 frames, hop=160, fmax=8000 Hz
    ▼
dataset_builder
    │  Assembles X_train/X_val/X_test numpy arrays
    │  Infers splits from directory path (/train/, /val/, /test/)
    ▼
model_builder  ◄── receives dataset (port: "input")
    │  DS-CNN: Conv2D → 4× DepthwiseConv2D → GAP → Dropout → Dense(6)
    │  ~22K parameters, Adam(lr=0.001)
    ▼
trainer  ◄── receives model (port: "model") + dataset (port: "dataset")
    │  Up to 30 epochs, batch_size=32, EarlyStopping(patience=5)
    │  Saves: output/saved_model/, output/checkpoints/
    ▼
evaluator  ◄── receives model_artifact + dataset
    │  Test accuracy, per-class precision/recall/F1, confusion matrix
    │  Saves: output/metrics.json, confusion_matrix.png, training_curves.png
    ▼
edge_optimizer
    │  TFLite INT8 conversion with representative calibration data
    └─ Saves: output/tflite/model.tflite, output/tflite/labels.txt
```

### Inference Pipeline

```
dataset_ingest(input_dir/)
    ▼
audio_conditioner → segmenter
    ▼
feature_frontend  (config loaded from output/feature_config.json)
    ▼
realtime_inference
    │  Loads TFLite model + labels.txt
    └─ Prints: <filename> → <label> (<confidence>%)
```

---

## What This Demonstrates

- Two-phase pipeline execution (preprocessing + training as separate pipelines)
- Explicit edge routing for multi-port nodes (`trainer.model`, `trainer.dataset`, `evaluator.model_artifact`, `evaluator.dataset`)
- `audio_exporter` with `append=True` — accumulating outputs from 6 separate pipeline runs into one dataset
- `feature_config.json` written by training, read by inference — ensuring feature consistency
- `edge_optimizer` with INT8 quantisation for TFLite export

---

## Output Directory

```
output/
├── dataset/speech_commands/v1/
│   ├── train/{label}/*.wav
│   ├── val/{label}/*.wav
│   └── test/{label}/*.wav
├── checkpoints/          Best checkpoint during training
├── saved_model/          TF SavedModel (for TFLite conversion)
├── tflite/
│   ├── model.tflite      INT8 TFLite model
│   └── labels.txt
├── metrics.json          Test accuracy + per-class metrics
├── confusion_matrix.png
├── training_curves.png
└── feature_config.json   Feature extractor config (read by run_infer.py)
```

---

## Design Notes

**Why two phases?** Training requires all 6 labels preprocessed first, then assembled into one dataset. Splitting into two phases keeps each pipeline linear and allows Phase 1 to be re-run independently.

**Why explicit edges in Phase 2?** `model_builder`, `trainer`, and `evaluator` have named input ports (`model`, `dataset`, `model_artifact`) rather than the default `input`. The SDK's `edges=` parameter routes data to the correct ports.

**Feature consistency:** `run_train.py` writes `output/feature_config.json` after Phase 1. `run_infer.py` reads this file to guarantee identical feature extraction at inference time.
