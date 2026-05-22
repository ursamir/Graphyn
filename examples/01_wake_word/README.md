# Example 01 — Wake Word Detection

## Purpose

Build a binary classification dataset for training a wake word detector
(e.g. "Hey Assistant", "OK Google" style). The model must distinguish
the target wake word from background speech and silence.

**Task:** Binary classification  
**Model target:** MobileNet-based keyword spotter, TFLite deployment  
**Sample rate:** 16000 Hz  
**Clip duration:** ~1 second

---

## Dataset

**Source:** Google Speech Commands v0.02 (test set)

| Label | Source | Files | Description |
|---|---|---|---|
| `wake_word` | `test/yes/` | 200 | Target wake word utterances |
| `background` | `test/no/` + `test/_silence_/` | 200 | Non-target speech + silence |
| `noise` | `train/_background_noise_/` | 6 | Real background noise WAVs |

**Noise files:** `pink_noise.wav`, `white_noise.wav`, `running_tap.wav`,
`exercise_bike.wav`, `doing_the_dishes.wav`, `dude_miaowing.wav`

---

## Pipeline

```
dataset_ingest (wake_word/)
    │
    ▼
audio_conditioner (16kHz, peak normalize)
    │
    ▼
segmenter (mode=silence, threshold=-40dB)
    │
    ▼
augmentation_pipeline (gain ±6dB + speed_perturb 0.9–1.1x + noise_inject 5–20dB SNR, 2 copies)
    │
    ▼
audio_exporter (70% train / 15% val / 15% test) → output/wake_word_detection/v1/
```

Run twice — once for `wake_word/`, once for `background/` — both
append to the same output directory.

### Why each stage

| Stage | Reason |
|---|---|
| `audio_conditioner` | Normalize sample rate and amplitude across speakers |
| `segmenter` | Remove silence padding common in Speech Commands clips |
| `augmentation_pipeline` | Simulate gain variation, speaking rate, and noisy environments |
| `audio_exporter` | Write WAV files split 70/15/15 train/val/test |

---

## Plugins Used

| Plugin | Node Type | Purpose |
|---|---|---|
| `Audio/dataset_ingest` | `dataset_ingest` | Load WAV files from filesystem |
| `Audio/audio_conditioner` | `audio_conditioner` | Resample, normalize, trim silence |
| `Audio/segmenter` | `segmenter` | Silence-based segmentation |
| `Audio/augmentation_pipeline` | `augmentation_pipeline` | Gain, speed perturbation, noise injection |
| `Audio/audio_exporter` | `audio_exporter` | Write WAV files with train/val/test split |

---

## How to Run

```bash
# Prepare data (run once)
venv/bin/python examples/prepare_real_data.py

# Run pipeline (SDK — processes both labels)
venv/bin/python examples/01_wake_word/run_sdk.py

# Run pipeline (CLI — wake_word label only)
bash examples/01_wake_word/run_cli.sh
```---

## Expected Output

```
output/wake_word_detection/v1/
├── train/
│   ├── wake_word/   (2352 WAV files)
│   └── background/  (2352 WAV files... wait, balanced)
├── val/
│   ├── wake_word/
│   └── background/
├── test/
│   ├── wake_word/
│   └── background/
├── labels.csv       (4800 rows)
└── metadata.json    (4800 entries with augmentation metadata)
```

**Label distribution:** 2400 wake_word + 2400 background (balanced)  
**Split:** 3360 train / 720 val / 720 test

---

## ML Usage Notes

- **Model architecture:** MobileNet-V2 or EfficientNet-Lite with mel-spectrogram input
- **Input features:** 40-bin log-mel spectrogram, 1s window, 10ms hop
- **Training:** Binary cross-entropy loss, Adam optimizer
- **Deployment:** TFLite INT8 quantization for edge devices
- **Key metric:** False Reject Rate (FRR) at 1% False Accept Rate (FAR)
- **Augmentation metadata:** Each sample has `augmented`, `gain_db`, `speed_factor`,
  `noise_file`, `snr_db` fields in `metadata.json` for analysis
