#!/usr/bin/env python3
"""
Example 01 — Wake Word Detection Dataset Pipeline (Python SDK)
==============================================================
Dataset: Google Speech Commands v0.02 (test set)
  data/wake_word/  ← yes/ (200 clips, 1s, 16kHz)
  data/background/ ← no/ + _silence_/ (200 clips, 1s, 16kHz)
  data/noise/      ← _background_noise_/ (6 real noise WAVs)

Purpose:
  Binary classification dataset for training a "Hey Assistant" style
  wake word detector. Positive class = "yes" (wake word), negative
  class = background speech + silence.

Pipeline (run once per label, both append to same output directory):
  dataset_ingest → audio_conditioner → segmenter →
  augmentation_pipeline(gain + speed_perturb + noise_inject) →
  audio_exporter(train/val/test WAV files)

Output:
  examples/01_wake_word/output/wake_word_detection/v1/
    train/wake_word/   ← WAV files
    train/background/  ← WAV files
    val/wake_word/
    val/background/
    test/wake_word/
    test/background/
    labels.csv
    metadata.json

Usage:
  venv/bin/python examples/01_wake_word/run_sdk.py
"""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

# ── Workspace root on sys.path ────────────────────────────────────────────────
WORKSPACE_ROOT = str(Path(__file__).parent.parent.parent)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from app.core.plugins.manager import PluginManager  # noqa: E402
from app.core.sdk import PipelineNode, Pipeline      # noqa: E402

# ── Install required plugins ──────────────────────────────────────────────────
manager = PluginManager()
manager.install("PluginPackage/Audio/dataset_ingest/")
manager.install("PluginPackage/Audio/audio_conditioner/")
manager.install("PluginPackage/Audio/segmenter/")
manager.install("PluginPackage/Audio/augmentation_pipeline/")
manager.install("PluginPackage/Audio/audio_exporter/")
manager.load_enabled_plugins()

EXAMPLE_DIR = Path(__file__).parent
DATA_DIR    = EXAMPLE_DIR / "data"
OUTPUT_DIR  = EXAMPLE_DIR / "output" / "wake_word_detection"

LABELS = ["wake_word", "background"]


def check_inputs() -> bool:
    required = {
        "wake_word":  DATA_DIR / "wake_word",
        "background": DATA_DIR / "background",
        "noise":      DATA_DIR / "noise",
    }
    ok = True
    for name, path in required.items():
        if not path.exists():
            print(f"  ✗ Missing: {path}")
            ok = False
        else:
            n = len(list(path.glob("*.wav")))
            print(f"  ✓ data/{name}/: {n} WAV files")
    return ok


def run_label(label: str, append: bool) -> None:
    """Run the full pipeline for one label and append to shared output."""
    Pipeline(
        nodes=[
            PipelineNode("dataset_ingest", {
                "path": str(DATA_DIR / label),
                "source_type": "filesystem",
                "recursive": False,
            }),
            PipelineNode("audio_conditioner", {"target_sample_rate": 16000}),
            PipelineNode("segmenter", {
                "silence_threshold_db": 40.0,
                "mode": "silence",
            }),
            # Augmentation: gain ±6 dB, speed 0.9–1.1x, Gaussian noise inject 5–20 dB SNR
            # Note: noise_inject adds Gaussian noise (not file-based noise).
            # The data/noise/ directory is not used by this augmentation type.
            PipelineNode("augmentation_pipeline", {
                "augmentations": [
                    {"type": "gain",         "apply_prob": 1.0, "gain_db": [-6.0, 6.0]},
                    {"type": "speed_perturb","apply_prob": 1.0, "speed_factor": [0.9, 1.1]},
                    {"type": "noise_inject", "apply_prob": 1.0, "snr_db": [5.0, 20.0]},
                ],
                "copies_per_sample": 2,
            }),
            # Export WAV files organised by split/label
            PipelineNode("audio_exporter", {
                "output_dir": str(OUTPUT_DIR),
                "split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15},
                "version_tag": "v1",
                "random_seed": 42,
                "append": append,
            }),
        ],
        seed=42,
    ).run(use_cache=False)


def print_summary(out_dir: Path) -> None:
    labels_csv = out_dir / "labels.csv"
    if not labels_csv.exists():
        print(f"  (no labels.csv found at {labels_csv})")
        return
    with open(labels_csv) as f:
        rows = list(csv.DictReader(f))
    splits: dict[str, int] = {}
    labels: dict[str, int] = {}
    for row in rows:
        splits[row["split"]] = splits.get(row["split"], 0) + 1
        labels[row["label"]] = labels.get(row["label"], 0) + 1
    print("Split distribution:")
    for split, count in sorted(splits.items()):
        print(f"  {split}: {count} samples")
    print("Label distribution:")
    for label, count in sorted(labels.items()):
        print(f"  {label}: {count} samples")
    print(f"Total: {len(rows)} samples → {out_dir}/")

    # Show WAV file counts
    for split in sorted(splits.keys()):
        for lbl in sorted(labels.keys()):
            d = out_dir / split / lbl
            if d.exists():
                n = len(list(d.glob("*.wav")))
                print(f"  {split}/{lbl}/: {n} WAV files")


def main() -> None:
    print("=" * 60)
    print("Example 01 — Wake Word Detection")
    print("Dataset: Google Speech Commands v0.02 (test set)")
    print("=" * 60)

    print("\nChecking input data...")
    if not check_inputs():
        print("\nRun first: venv/bin/python examples/prepare_real_data.py")
        sys.exit(1)

    # Clear previous output so append starts fresh
    out_versioned = OUTPUT_DIR / "v1"
    if out_versioned.exists():
        shutil.rmtree(out_versioned)
        print(f"\nCleared previous output: {out_versioned}")

    print(f"\nLabels: {', '.join(LABELS)}\n")

    for i, label in enumerate(LABELS, 1):
        # First label: fresh write; subsequent labels: append
        append = (i > 1)
        print(f"[{i}/{len(LABELS)}] Processing '{label}'...")
        try:
            run_label(label, append=append)
            print(f"  ✓ done")
        except Exception as exc:
            print(f"  ✗ failed: {exc}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)

    print("\n" + "=" * 60)
    print("Done!")
    print_summary(out_versioned)


if __name__ == "__main__":
    main()
