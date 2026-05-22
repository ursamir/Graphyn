#!/usr/bin/env python3
"""
Example 03 — Environmental Sound Classification Dataset Pipeline (Python SDK)
==============================================================================
Dataset: Google Speech Commands v0.02 (training set)
  data/dog/, cat/, bird/, happy/, house/  (200 clips each, ~1s, 16kHz)

Purpose:
  5-class ambient sound classification dataset at 22050 Hz (ESC-50 style).
  Produces WAV files organised by split (train/val/test) and label.

Pipeline (run once per class, all 5 append to shared output):
  dataset_ingest → audio_conditioner(22050Hz) → audio_conditioner(rms, -20dBFS) →
  audio_quality_gate(500ms–1200ms) →
  augmentation_pipeline(gain ±3dB + pitch_shift ±1.5 semitones, 1 copy) →
  audio_exporter(train/val/test WAV files)

Output:
  examples/03_environmental_sounds/output/environmental_sounds/v1/
    train/{label}/   ← WAV files at 22050 Hz
    val/{label}/
    test/{label}/
    labels.csv
    metadata.json

Usage:
  venv/bin/python examples/03_environmental_sounds/run_sdk.py
"""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

WORKSPACE_ROOT = str(Path(__file__).parent.parent.parent)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from app.core.plugins.manager import PluginManager  # noqa: E402
from app.core.sdk import PipelineNode, Pipeline      # noqa: E402

# ── Install required plugins ──────────────────────────────────────────────────
manager = PluginManager()
manager.install("PluginPackage/Audio/dataset_ingest/")
manager.install("PluginPackage/Audio/audio_conditioner/")
manager.install("PluginPackage/Audio/audio_quality_gate/")
manager.install("PluginPackage/Audio/augmentation_pipeline/")
manager.install("PluginPackage/Audio/audio_exporter/")
manager.load_enabled_plugins()

EXAMPLE_DIR = Path(__file__).parent
DATA_DIR    = EXAMPLE_DIR / "data"
OUTPUT_DIR  = EXAMPLE_DIR / "output" / "environmental_sounds"

SOUND_CLASSES = ["dog", "cat", "bird", "happy", "house"]


def check_inputs() -> bool:
    ok = True
    for cls in SOUND_CLASSES:
        p = DATA_DIR / cls
        if not p.exists():
            print(f"  ✗ Missing: {p}")
            ok = False
        else:
            n = len(list(p.glob("*.wav")))
            print(f"  ✓ data/{cls}/: {n} WAV files")
    return ok


def run_class(sound_class: str, append: bool) -> None:
    """Run the full pipeline for one sound class."""
    Pipeline(
        nodes=[
            PipelineNode("dataset_ingest", {
                "path": str(DATA_DIR / sound_class),
                "source_type": "filesystem",
                "recursive": False,
            }),
            # Resample to 22050 Hz (ESC-50 standard)
            PipelineNode("audio_conditioner", {
                "target_sample_rate": 22050,
                "mono": True,
            }),
            # RMS normalization — equalizes loudness across classes.
            # target_sample_rate must be set explicitly to preserve 22050 Hz;
            # omitting it would resample back to the default 16000 Hz.
            PipelineNode("audio_conditioner", {
                "target_sample_rate": 22050,
                "normalize": True,
                "normalize_method": "rms",
                "target_level_db": -20.0,
            }),
            # Filter clips outside 500ms–1200ms
            PipelineNode("audio_quality_gate", {
                "min_duration_s": 0.5,
                "max_duration_s": 1.2,
                "rejection_policy": "skip",
            }),
            # Gain ±3dB + pitch shift ±1.5 semitones, 1 copy each
            PipelineNode("augmentation_pipeline", {
                "copies_per_sample": 1,
                "augmentations": [
                    {"type": "gain", "apply_prob": 1.0, "gain_db": [-3.0, 3.0]},
                    {"type": "pitch_shift", "apply_prob": 1.0, "semitones": [-1.5, 1.5]},
                ],
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
    for split in sorted(splits.keys()):
        for lbl in sorted(labels.keys()):
            d = out_dir / split / lbl
            if d.exists():
                n = len(list(d.glob("*.wav")))
                print(f"  {split}/{lbl}/: {n} WAV files")


def main() -> None:
    print("=" * 60)
    print("Example 03 — Environmental Sound Classification")
    print("Dataset: Google Speech Commands v0.02 (training set)")
    print("=" * 60)

    print("\nChecking input data...")
    if not check_inputs():
        print("\nRun first: venv/bin/python examples/prepare_real_data.py")
        sys.exit(1)

    # Clear previous output so appends start fresh
    out_versioned = OUTPUT_DIR / "v1"
    if out_versioned.exists():
        shutil.rmtree(out_versioned)
        print(f"\nCleared previous output: {out_versioned}")

    print(f"\nSound classes: {', '.join(SOUND_CLASSES)}\n")

    for i, cls in enumerate(SOUND_CLASSES, 1):
        append = (i > 1)
        print(f"[{i}/{len(SOUND_CLASSES)}] Processing '{cls}'...")
        try:
            run_class(cls, append=append)
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
