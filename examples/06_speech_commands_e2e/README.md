# Example 06 — Speech Commands End-to-End Training

A complete machine learning pipeline from raw audio to a trained TFLite model — data preprocessing, feature extraction, DS-CNN training, evaluation, and INT8 export. Built on top of Example 02.

**Task:** 6-class spoken command recognition (yes / no / up / down / go / stop)
**Architecture:** DS-CNN (Depthwise Separable CNN) — lightweight, edge-deployable
**Features:** 40-bin MFCC, 101 frames (~1 second at 16 kHz)
**Deployment target:** TFLite INT8

---

## Known caveats

- **Trainer / TF GPU:** Example 06 uses the GPU when available, with **memory growth** so other GPU apps are not closed or starved. XLA/Triton GEMM is disabled to avoid autotune crashes. Force CPU with `GRAPHYN_TF_DEVICE=cpu`. Trainer config `device`: `auto` | `cpu` | `gpu`.

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
    │  Resample to 16 kHz, mono, DC removal, trim edges quieter than peak-40 dB,
    │  peak-normalise to -1 dBFS
    ▼
segmenter  (mode=silence, silence_threshold_db=40 → "40 dB below peak")
    │  Splits each clip on silence; a clip can yield >1 segment (≈1.1 per clip)
    ▼
audio_quality_gate  (quality: SNR ≥ 5 dB, clipping ≤ 1 %, RMS ≥ 0.001,
    │                 85 % rolloff ≥ 1 kHz; duration check off)
    ▼
audio_quality_gate  (duration only: 0.2 s ≤ d ≤ 1.0 s)
    ▼
augmentation_pipeline
    │  pitch_shift ±2 semitones + time_stretch 0.9×–1.1× (both always applied)
    │  copies_per_sample=2 → original + 2 copies = 3× samples
    ▼
audio_exporter(workspace/artifacts/speech-commands/dataset/speech_commands, v1)
    │  Writes WAV files split 70/15/15 train/val/test, one split per source
    │  clip (group_by_source) so augmented copies never leak into test
    └─ "yes" runs with append=false (fresh v1), the other five with append=true
```

### Phase 2 — Feature Extraction + Training (runs once)

Uses explicit edge routing because `trainer` and `evaluator` have named input ports.

```
dataset_ingest(workspace/artifacts/speech-commands/dataset/speech_commands/v1, recursive=True)
    │  Load all preprocessed WAV files. If Phase 1 has not run the ingest
    │  fails with "has not been produced yet" — set
    │  GRAPHYN_INGEST_EXAMPLE_FALLBACK=1 to train on the bundled raw clips
    │  in examples/02_speech_commands/data instead (opt-in)
    ▼
feature_frontend
    │  MFCC: 40 coefficients × 101 frames (T×F = 101×40), n_fft=512, hop=160, fmax=8000 Hz
    ▼
dataset_builder
    │  Assembles X_train/X_val/X_test numpy arrays
    │  Infers splits from directory path (/train/, /val/, /test/)
    ▼
model_builder  ◄── receives dataset (port: "input")
    │  DS-CNN: Conv2D → 4× DepthwiseConv2D → GAP → Dropout → Dense(6)
    │  ~22K parameters, Adam(lr=0.001) — trainer keeps this LR unless
    │  trainer.learning_rate is set
    ▼
trainer  ◄── receives model (port: "model") + dataset (port: "dataset")
    │  Up to 50 epochs, batch_size=32, EarlyStopping(val_accuracy, patience=15)
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

### Console (template `ex-06-speech-commands-e2e`)

The Builder template is **Phase 2** (`pipeline_train_ml.graph.json`). Run the
six `pipeline_preprocess*.graph.json` graphs first (CLI `run_preprocess.sh`, or
paste each into the Editor) — otherwise training falls back to the raw clips.
Picking a workspace in the console stamps `audio_exporter` with
`project=<workspace>`, which moves the Phase-1 output to
`workspace/datasets/output/<workspace>/v1`; in that case point the template's
`dataset_ingest.path` at that folder. Coverage, live run results and known
limitations: [`docs/EXAMPLE_06_COVERAGE.md`](../../docs/EXAMPLE_06_COVERAGE.md).

## What This Demonstrates

- Two-phase pipeline execution (preprocessing + training as separate pipelines)
- Explicit edge routing for multi-port nodes (`trainer.model`, `trainer.dataset`, `evaluator.model_artifact`, `evaluator.dataset`)
- `audio_exporter` with `append=True` — accumulating outputs from 6 separate pipeline runs into one dataset
- `feature_config.json` written by training, read by inference — ensuring feature consistency
- `edge_optimizer` with INT8 quantisation for TFLite export

---

## Output Directory

Console / Docker Compose training writes **models and plots** under the bind-mounted
workspace (`./workspace:/app/workspace`), so they show up on the host and in the
Runs → Artifacts download tab:

```
workspace/artifacts/speech-commands/
├── model.keras
├── saved_model/
├── checkpoints/
├── metrics.json
├── confusion_matrix.png
├── roc_curves.png
├── training_curves.png
└── tflite/
    ├── model.tflite
    └── labels.txt
```

**Dataset ingest is unchanged.** Phase 2 still reads preprocessed WAVs from
`examples/06_speech_commands_e2e/output/dataset/speech_commands/v1/` (written by
Phase 1). CLI `run_train.py` also still writes under `examples/06_speech_commands_e2e/output/`
when run on the host; that legacy tree is listed by the download API when files exist.

```
examples/06_speech_commands_e2e/output/   # Phase 1 dataset + legacy CLI artifacts
└── dataset/speech_commands/v1/
    ├── train/{label}/*.wav
    ├── val/{label}/*.wav
    └── test/{label}/*.wav
```

---

## Design Notes

**Why two phases?** Training requires all 6 labels preprocessed first, then assembled into one dataset. Splitting into two phases keeps each pipeline linear and allows Phase 1 to be re-run independently.

**Why explicit edges in Phase 2?** `model_builder`, `trainer`, and `evaluator` have named input ports (`model`, `dataset`, `model_artifact`) rather than the default `input`. The SDK's `edges=` parameter routes data to the correct ports.

**Feature consistency:** `run_train.py` writes `output/feature_config.json` after Phase 1. `run_infer.py` reads this file to guarantee identical feature extraction at inference time.
