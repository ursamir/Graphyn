# Example 04 — Speaker Verification

## Purpose

Build a speaker verification dataset for training speaker embedding
models. The model must learn to distinguish between speakers regardless
of what word they are saying (text-independent speaker verification).

**Task:** Speaker verification / speaker identification  
**Model target:** d-vector, x-vector, or ECAPA-TDNN with GE2E / ArcFace loss  
**Sample rate:** 16000 Hz  
**Clip duration:** ~1 second per utterance

---

## Dataset

**Source:** Google Speech Commands v0.02 (training set)

| Label | Speaker ID | Utterances | Words spoken |
|---|---|---|---|
| `speaker_001` | c50f55b8 | 20 | 14 different words |
| `speaker_002` | 893705bb | 20 | 10 different words |
| `speaker_003` | cce7416f | 20 | 12 different words |
| `speaker_004` | 2aca1e72 | 20 | 12 different words |
| `speaker_005` | ddedba85 | 20 | 14 different words |
| `speaker_006` | b5cf6ea8 | 20 | 14 different words |

**Key property:** Each speaker said multiple *different* words. The model
must learn speaker identity independent of linguistic content — the
defining challenge of text-independent speaker verification.

Speaker IDs are the 8-character hex prefixes from Speech Commands
filenames (e.g. `c50f55b8_nohash_0.wav`). See `data/speaker_manifest.txt`
for the full mapping.

---

## Pipeline

```
dataset_ingest (one speaker dir at a time)
    │
    ▼
audio_conditioner (16kHz, mono)
    │
    ▼
segmenter (mode=silence, threshold=-40dB)
    │  Speaker embeddings are sensitive to silence
    ▼
audio_conditioner (rms, -20dBFS)
    │  Equalizes loudness across speakers
    ▼
audio_annotator (passthrough — preserves speaker label)
    │
    ▼
audio_exporter (70% train / 15% val / 15% test, append) → output/speaker_verification/v1/
```

### Why each stage

| Stage | Reason |
|---|---|
| `segmenter` | Remove silence padding; speaker embeddings are sensitive to silence |
| `audio_conditioner` (rms) | Equalizes recording level differences across speakers |
| `audio_annotator` | Preserves speaker label from directory name (passthrough mode) |
| `audio_exporter` | Write WAV files split 70/15/15 train/val/test |

---

## Plugins Used

| Plugin | Node Type | Purpose |
|---|---|---|
| `Audio/dataset_ingest` | `dataset_ingest` | Load WAV files from filesystem |
| `Audio/audio_conditioner` | `audio_conditioner` | Resample to 16kHz, mono |
| `Audio/segmenter` | `segmenter` | Remove silence padding |
| `Audio/audio_conditioner` | `audio_conditioner` | RMS normalize to -20 dBFS |
| `Audio/audio_annotator` | `audio_annotator` | Passthrough — preserves speaker label |
| `Audio/audio_exporter` | `audio_exporter` | Write WAV files with train/val/test split |

---

## How to Run

```bash
# Prepare data (run once)
venv/bin/python examples/prepare_real_data.py

# Run pipeline (SDK — all 6 speakers)
venv/bin/python examples/04_speaker_verification/run_sdk.py

# Run pipeline (CLI — all 6 speakers)
bash examples/04_speaker_verification/run_cli.sh
```

---

## Expected Output

```
output/speaker_verification/v1/
├── train/{speaker_label}/   (14 files per speaker)
├── val/{speaker_label}/     (3 files per speaker)
├── test/{speaker_label}/    (3 files per speaker)
├── labels.csv               (120 rows total)
└── metadata.json            (120 entries with contrastive metadata)
```

**Speaker distribution:** 20 utterances per speaker (6 × 20 = 120 total)  
**Split:** 84 train / 18 val / 18 test

---

## ML Usage Notes

- **Model architecture:** ECAPA-TDNN, ResNet-34, or Thin-ResNet34
- **Loss function:** GE2E loss (N speakers × M utterances per batch)
  or ArcFace with speaker labels
- **Input features:** 80-dim log-mel filterbank, 25ms window, 10ms hop
- **Embedding dimension:** 192 or 256
- **Evaluation:** Equal Error Rate (EER) on verification trials
- **Training setup:** Use `contrastive_key` to group utterances by speaker;
  use `session_id` to form GE2E batches
- **Scale note:** This example uses 6 speakers for demonstration.
  Production models require thousands of speakers (VoxCeleb: 7000+)
