# Example 05 — Speech Enhancement

## Purpose

Build a paired clean/degraded speech dataset for training speech
enhancement models. Each clean clip has exactly one degraded counterpart
produced by a realistic degradation chain.

**Task:** Speech enhancement (denoising, dereverberation, bandwidth extension)  
**Model target:** U-Net, SEGAN, DCCRN, or FullSubNet  
**Sample rate:** 16000 Hz  
**Clip duration:** ~1 second

---

## Dataset

**Source:** Google Speech Commands v0.02 (test set + background noise)

| Directory | Source | Files | Description |
|---|---|---|---|
| `data/clean_speech/` | `test/yes/` + `test/no/` | 200 | Clean speech clips |
| `data/noise/` | `train/_background_noise_/` | 6 | Real background noise WAVs |

**Noise files used for reference:**
- `pink_noise.wav` (60s) — 1/f noise, common in electronics
- `white_noise.wav` (60s) — flat spectrum noise
- `running_tap.wav` (61s) — water/plumbing noise
- `exercise_bike.wav` (61s) — mechanical noise
- `doing_the_dishes.wav` (95s) — kitchen ambient noise
- `dude_miaowing.wav` (62s) — animal/ambient noise

---

## Pipeline

Two passes over the same clean_speech/ directory, appending to shared output:

**Pass 1 — clean:**
```
dataset_ingest (clean_speech/) → audio_conditioner(16kHz) → segmenter →
audio_conditioner(compress) → audio_exporter (label=clean_speech, append=false)
```

**Pass 2 — degraded:**
```
dataset_ingest (clean_speech/, label_override=degraded) → audio_conditioner(16kHz) →
segmenter → audio_conditioner(compress) →
augmentation_pipeline(codec_degrade + noise_inject) →
audio_exporter (label=degraded, append=true)
```

Output: `output/speech_enhancement/v1/`

### Why each stage

| Stage | Reason |
|---|---|
| `audio_conditioner` (compress) | Reduces dynamic range before degradation |
| `augmentation_pipeline` (codec_degrade) | Simulates VoIP/telephony codec artifacts |
| `augmentation_pipeline` (noise_inject) | Adds background noise at 10–20 dB SNR |
| `audio_exporter` | Writes paired clean/degraded WAV files |

---

## Plugins Used

| Plugin | Node Type | Purpose |
|---|---|---|
| `Audio/dataset_ingest` | `dataset_ingest` | Load clean speech WAV files |
| `Audio/audio_conditioner` | `audio_conditioner` | Resample, normalize, compress |
| `Audio/segmenter` | `segmenter` | Remove silence padding |
| `Audio/augmentation_pipeline` | `augmentation_pipeline` | codec_degrade + noise_inject |
| `Audio/audio_exporter` | `audio_exporter` | Write paired WAV files |

Note: `environment_simulator` requires `pyroomacoustics` (not installed).
Noise injection via `augmentation_pipeline` provides equivalent degradation.

---

## How to Run

```bash
# Prepare data (run once)
venv/bin/python examples/prepare_real_data.py

# Run pipeline (SDK)
venv/bin/python examples/05_speech_enhancement/run_sdk.py

# Run pipeline (CLI — clean + degraded passes)
bash examples/05_speech_enhancement/run_cli.sh
```

---

## Expected Output

```
output/speech_enhancement/v1/
├── train/
│   ├── clean_speech/   (154 WAV files)
│   └── degraded/       (298 WAV files)
├── val/
│   ├── clean_speech/   (25 WAV files)
│   └── degraded/       (58 WAV files)
├── test/
│   ├── clean_speech/   (36 WAV files)
│   └── degraded/       (74 WAV files)
├── labels.csv          (645 rows: 215 clean + 430 degraded)
└── metadata.json       (645 entries)
```

**Labels:** 215 clean_speech + 430 degraded (2 degraded copies per clean clip)  
**Split:** 452 train / 83 val / 110 test

---

## ML Usage Notes

- **Model architecture:** U-Net (time-domain), DCCRN (complex-domain),
  or FullSubNet (full-band + sub-band)
- **Loss function:** SI-SNR + PESQ perceptual loss, or MSE in STFT domain
- **Input:** Degraded waveform or complex STFT
- **Target:** Clean waveform or clean STFT
- **Pair matching:** Use `metadata["pair_id"]` to match clean/degraded
  samples in the DataLoader
- **Evaluation metrics:** PESQ, STOI, SI-SNR, DNSMOS
- **Scale note:** This example uses 186 pairs for demonstration.
  Production models require tens of thousands of pairs (DNS Challenge: 500k+)
- **Extending degradations:** Add `noise_dir` config to `degradation_pipeline`
  to mix real background noise at a controlled SNR
