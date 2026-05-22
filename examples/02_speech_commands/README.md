# Example 02 — Speech Command Recognition

## Purpose

Build a 6-class spoken command recognition dataset. The model must
classify short spoken commands for device control (smart home, robotics,
accessibility interfaces).

**Task:** Multi-class classification (6 classes)  
**Model target:** CNN/LSTM classifier for edge deployment (TFLite, ONNX)  
**Sample rate:** 16000 Hz  
**Clip duration:** ~1 second (after trim: 200ms–1000ms)

---

## Dataset

**Source:** Google Speech Commands v0.02 (test set)

| Label | Source | Files | Description |
|---|---|---|---|
| `yes` | `test/yes/` | 200 | Affirmative command |
| `no` | `test/no/` | 200 | Negative command |
| `up` | `test/up/` | 200 | Directional command |
| `down` | `test/down/` | 200 | Directional command |
| `go` | `test/go/` | 200 | Motion command |
| `stop` | `test/stop/` | 200 | Stop command |

---

## Pipeline

```
dataset_ingest (one command dir at a time)
    │
    ▼
audio_conditioner (16kHz, peak normalize)
    │
    ▼
segmenter (mode=silence, threshold=-40dB)
    │
    ▼
audio_quality_gate (min_snr_db=-60, skip silent/corrupted clips)
    │
    ▼
audio_quality_gate (min_duration_s=0.2, max_duration_s=1.0, skip out-of-range)
    │
    ▼
augmentation_pipeline (pitch_shift ±2 semitones + time_stretch 0.9–1.1x, 2 copies)
    │
    ▼
audio_exporter (70% train / 15% val / 15% test, append) → output/speech_commands/v1/
```

Run once per command (6 runs total), all appending to the same output.

### Why each stage

| Stage | Reason |
|---|---|
| `segmenter` | Speech Commands clips have variable silence padding |
| `audio_quality_gate` (SNR) | Remove corrupted or empty clips |
| `audio_quality_gate` (duration) | Ensure clips are within model's expected input range |
| `augmentation_pipeline` | Simulate different speakers (pitch) and speaking rates (stretch) |
| `audio_exporter` | Write WAV files split 70/15/15 train/val/test |

---

## Plugins Used

| Plugin | Node Type | Purpose |
|---|---|---|
| `Audio/dataset_ingest` | `dataset_ingest` | Load WAV files from filesystem |
| `Audio/audio_conditioner` | `audio_conditioner` | Resample, normalize, trim silence |
| `Audio/segmenter` | `segmenter` | Silence-based segmentation |
| `Audio/audio_quality_gate` | `audio_quality_gate` | Filter by SNR and duration |
| `Audio/augmentation_pipeline` | `augmentation_pipeline` | Pitch shift + time stretch |
| `Audio/audio_exporter` | `audio_exporter` | Write WAV files with train/val/test split |

---

## How to Run

```bash
# Prepare data (run once)
venv/bin/python examples/prepare_real_data.py

# Run pipeline (SDK — all 6 commands)
venv/bin/python examples/02_speech_commands/run_sdk.py

# Run pipeline (CLI — all 6 commands)
bash examples/02_speech_commands/run_cli.sh
```

---

## Expected Output

```
output/speech_commands/v1/
├── train/{label}/   (560 files per label)
├── val/{label}/     (120 files per label)
├── test/{label}/    (120 files per label)
├── labels.csv       (4800 rows total)
└── metadata.json    (4800 entries)
```

**Label distribution:** 800 samples per command (6 × 800 = 4800 total)  
**Split:** 3360 train / 720 val / 720 test

---

## ML Usage Notes

- **Model architecture:** DS-CNN (Depthwise Separable CNN) or MobileNet-V2
- **Input features:** 40-bin MFCC or log-mel spectrogram, 1s window
- **Training:** Categorical cross-entropy, label smoothing 0.1
- **Deployment:** TFLite INT8 for microcontrollers (Cortex-M4+)
- **Key metric:** Top-1 accuracy on the canonical test set
- **Augmentation metadata:** `pitch_shift_semitones`, `time_stretch_rate`,
  `duration_ms`, `duration_out_of_range` fields available for analysis
