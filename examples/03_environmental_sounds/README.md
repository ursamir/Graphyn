# Example 03 — Environmental Sound Classification

## Purpose

Build a 5-class ambient sound classification dataset at 22050 Hz,
compatible with the ESC-50 benchmark format. The model must classify
short audio clips into environmental/ambient sound categories.

**Task:** Multi-class classification (5 classes)  
**Model target:** CNN with mel-spectrogram or log-mel input  
**Sample rate:** 22050 Hz (ESC-50 standard)  
**Clip duration:** ~1 second (after duration filter)

---

## Dataset

**Source:** Google Speech Commands v0.02 (training set)

| Label | Source | Files | Description |
|---|---|---|---|
| `dog` | `train/dog/` | 200 | Dog barking / vocalisation |
| `cat` | `train/cat/` | 200 | Cat meowing / vocalisation |
| `bird` | `train/bird/` | 200 | Bird chirping / vocalisation |
| `happy` | `train/happy/` | 200 | Happy emotional speech |
| `house` | `train/house/` | 200 | Domestic ambient speech |

These classes from Speech Commands serve as proxies for environmental
sound categories: animal vocalisations (dog/cat/bird) and human ambient
sounds (happy/house).

---

## Pipeline

```
dataset_ingest (one class dir at a time)
    │
    ▼
audio_conditioner (22050Hz, mono)
    │  ESC-50 standard sample rate
    ▼
audio_conditioner (rms, -20dBFS)
    │  Environmental sounds vary widely in loudness
    ▼
audio_quality_gate (500ms–1200ms, skip out-of-range)
    │
    ▼
augmentation_pipeline (gain ±3dB + pitch_shift ±1.5 semitones, 1 copy)
    │
    ▼
audio_exporter (70% train / 15% val / 15% test, append) → output/environmental_sounds/v1/
```

### Why each stage

| Stage | Reason |
|---|---|
| `audio_conditioner` (22050Hz) | ESC-50 uses 22050 Hz; mel-spectrograms computed at this rate |
| `audio_conditioner` (rms) | Dog barks and bird chirps have very different loudness levels |
| `audio_quality_gate` | Ensures all clips fit a fixed-size spectrogram window |
| `augmentation_pipeline` (gain) | Simulate microphone distance and recording level variation |
| `augmentation_pipeline` (pitch_shift) | Animal vocalisations vary in pitch across individuals |
| `audio_exporter` | Write WAV files split 70/15/15 train/val/test |

---

## Plugins Used

| Plugin | Node Type | Purpose |
|---|---|---|
| `Audio/dataset_ingest` | `dataset_ingest` | Load WAV files from filesystem |
| `Audio/audio_conditioner` | `audio_conditioner` | Resample to 22050 Hz, mono |
| `Audio/audio_conditioner` | `audio_conditioner` | RMS normalize to -20 dBFS |
| `Audio/audio_quality_gate` | `audio_quality_gate` | Filter by duration (500ms–1200ms) |
| `Audio/augmentation_pipeline` | `augmentation_pipeline` | Gain variation + pitch shift |
| `Audio/audio_exporter` | `audio_exporter` | Write WAV files with train/val/test split |

---

## How to Run

```bash
# Prepare data (run once)
venv/bin/python examples/prepare_real_data.py

# Run pipeline (SDK — all 5 classes)
venv/bin/python examples/03_environmental_sounds/run_sdk.py

# Run pipeline (CLI — all 5 classes)
bash examples/03_environmental_sounds/run_cli.sh
```

---

## Expected Output

```
output/environmental_sounds/v1/
├── train/{label}/   (560 files per label)
├── val/{label}/     (120 files per label)
├── test/{label}/    (120 files per label)
├── labels.csv       (4000 rows total)
└── metadata.json    (4000 entries)
```

**Label distribution:** 800 samples per class (5 × 800 = 4000 total)  
**Split:** 2800 train / 600 val / 600 test  
**Sample rate:** 22050 Hz

---

## ML Usage Notes

- **Model architecture:** VGGish, PANNs (CNN14), or EfficientNet-B0
- **Input features:** 128-bin log-mel spectrogram, 1s window, 10ms hop
- **Training:** Categorical cross-entropy, mixup augmentation
- **Benchmark:** ESC-50 uses 5-fold cross-validation; adapt splits accordingly
- **Key metric:** Top-1 accuracy (ESC-50 human baseline: 81.3%)
- **Augmentation metadata:** `gain_db`, `pitch_shift_semitones`,
  `duration_ms`, `duration_filtered` fields in `metadata.json`
