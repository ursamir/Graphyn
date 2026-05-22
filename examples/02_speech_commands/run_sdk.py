#!/usr/bin/env python3
"""
Example 02 — Speech Command Recognition Dataset Pipeline (Python SDK)
======================================================================
Dataset: Google Speech Commands v0.02 (test set)
  data/yes/, no/, up/, down/, go/, stop/  (200 clips each, 1s, 16kHz)

Purpose:
  6-class spoken command recognition dataset. Produces WAV files organised
  by split (train/val/test) and label for training CNN/LSTM classifiers.

Pipeline (run once per command, all 6 append to shared output):
  dataset_ingest → audio_conditioner → segmenter →
  audio_quality_gate(snr) → audio_quality_gate(duration) →
  augmentation_pipeline(pitch_shift + time_stretch, 2 copies) →
  audio_exporter(train/val/test WAV files)

Output:
  examples/02_speech_commands/output/speech_commands/v1/
    train/{label}/   ← WAV files
    val/{label}/
    test/{label}/
    labels.csv
    metadata.json

Usage:
  venv/bin/python examples/02_speech_commands/run_sdk.py
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
manager.install("PluginPackage/Audio/segmenter/")
manager.install("PluginPackage/Audio/audio_quality_gate/")
manager.install("PluginPackage/Audio/augmentation_pipeline/")
manager.install("PluginPackage/Audio/audio_exporter/")
manager.load_enabled_plugins()

EXAMPLE_DIR = Path(__file__).parent
DATA_DIR    = EXAMPLE_DIR / "data"
OUTPUT_DIR  = EXAMPLE_DIR / "output" / "speech_commands"

COMMANDS = ["yes", "no", "up", "down", "go", "stop"]


def check_inputs() -> bool:
    ok = True
    for cmd in COMMANDS:
        p = DATA_DIR / cmd
        if not p.exists():
            print(f"  ✗ Missing: {p}")
            ok = False
        else:
            n = len(list(p.glob("*.wav")))
            print(f"  ✓ data/{cmd}/: {n} WAV files")
    return ok


def run_command(command: str, append: bool) -> None:
    """Run the full pipeline for one command label."""
    Pipeline(
        nodes=[
            PipelineNode("dataset_ingest", {
                "path": str(DATA_DIR / command),
                "source_type": "filesystem",
                "recursive": False,
            }),
            PipelineNode("audio_conditioner", {
                "target_sample_rate": 16000,
                "mono": True,
                "normalize": True,
                "normalize_method": "peak",
            }),
            PipelineNode("segmenter", {
                "mode": "silence",
                "silence_threshold_db": 40.0,
            }),
            # Quality gate: reject clips with SNR below 5 dB (silent/corrupted).
            # min_snr_db=-60.0 would never reject anything; 5.0 dB is a real threshold.
            PipelineNode("audio_quality_gate", {
                "min_snr_db": 5.0,
                "rejection_policy": "skip",
            }),
            # Validate duration: 200ms–1000ms
            PipelineNode("audio_quality_gate", {
                "min_duration_s": 0.2,
                "max_duration_s": 1.0,
                "rejection_policy": "skip",
            }),
            # Augmentation: pitch shift ±2 semitones + time stretch 0.9–1.1x
            PipelineNode("augmentation_pipeline", {
                "copies_per_sample": 2,
                "augmentations": [
                    {"type": "pitch_shift", "apply_prob": 1.0, "semitones": [-2.0, 2.0]},
                    {"type": "time_stretch", "apply_prob": 1.0, "rate": [0.9, 1.1]},
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
    print("Example 02 — Speech Command Recognition")
    print("Dataset: Google Speech Commands v0.02 (test set)")
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

    print(f"\nCommands: {', '.join(COMMANDS)}\n")

    for i, cmd in enumerate(COMMANDS, 1):
        append = (i > 1)
        print(f"[{i}/{len(COMMANDS)}] Processing '{cmd}'...")
        try:
            run_command(cmd, append=append)
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
