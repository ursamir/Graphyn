#!/usr/bin/env python3
"""
Example 04 — Speaker Verification Dataset Pipeline (Python SDK)
================================================================
Dataset: Google Speech Commands v0.02 (training set)
  data/speaker_001/ … data/speaker_006/  (20 utterances each, ~1s, 16kHz)
  Each speaker said multiple different words — word-independent speaker ID.

Purpose:
  Speaker verification dataset for training d-vector / x-vector / ECAPA-TDNN
  models. Produces WAV files organised by speaker label (train/val/test).

Pipeline (run once per speaker, all 6 append to shared output):
  dataset_ingest → audio_conditioner(16kHz) → segmenter →
  audio_conditioner(rms, -20dBFS) → audio_annotator(auto: duration rules) →
  audio_exporter(train/val/test WAV files)

Output:
  examples/04_speaker_verification/output/speaker_verification/v1/
    train/{speaker_label}/   ← WAV files
    val/{speaker_label}/
    test/{speaker_label}/
    labels.csv
    metadata.json

Usage:
  venv/bin/python examples/04_speaker_verification/run_sdk.py
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
manager.install("PluginPackage/Audio/audio_annotator/")
manager.install("PluginPackage/Audio/audio_exporter/")
manager.load_enabled_plugins()

EXAMPLE_DIR = Path(__file__).parent
DATA_DIR    = EXAMPLE_DIR / "data"
OUTPUT_DIR  = EXAMPLE_DIR / "output" / "speaker_verification"

SPEAKERS = [
    "speaker_001", "speaker_002", "speaker_003",
    "speaker_004", "speaker_005", "speaker_006",
]


def check_inputs() -> bool:
    ok = True
    manifest = DATA_DIR / "speaker_manifest.txt"
    if manifest.exists():
        print(f"  ✓ data/speaker_manifest.txt")
    for spk in SPEAKERS:
        p = DATA_DIR / spk
        if not p.exists():
            print(f"  ✗ Missing: {p}")
            ok = False
        else:
            n = len(list(p.glob("*.wav")))
            print(f"  ✓ data/{spk}/: {n} utterances")
    return ok


def run_speaker(speaker: str, append: bool) -> None:
    """Run the full pipeline for one speaker."""
    Pipeline(
        nodes=[
            PipelineNode("dataset_ingest", {
                "path": str(DATA_DIR / speaker),
                "source_type": "filesystem",
                "recursive": False,
            }),
            # Resample to 16kHz, mono
            PipelineNode("audio_conditioner", {
                "target_sample_rate": 16000,
                "mono": True,
            }),
            # Remove silence padding — speaker embeddings are sensitive to silence
            PipelineNode("segmenter", {
                "mode": "silence",
                "silence_threshold_db": 40.0,
            }),
            # RMS normalization — equalizes loudness across speakers
            PipelineNode("audio_conditioner", {
                "normalize": True,
                "normalize_method": "rms",
                "target_level_db": -20.0,
            }),
            # Annotator: auto mode assigns a "short_utterance" or "normal_utterance"
            # label based on clip duration, demonstrating rule-based annotation.
            # The speaker label from the directory name is preserved in metadata.
            PipelineNode("audio_annotator", {
                "annotation_mode": "auto",
                "auto_rules": [
                    {
                        "field": "duration",
                        "op": "<",
                        "value": 0.5,
                        "label": "short_utterance",
                        "confidence": 0.9,
                    },
                    {
                        "field": "duration",
                        "op": ">=",
                        "value": 0.5,
                        "label": "normal_utterance",
                        "confidence": 1.0,
                    },
                ],
            }),
            # Export WAV files organised by split/speaker
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
    print("Speaker distribution:")
    for label, count in sorted(labels.items()):
        print(f"  {label}: {count} utterances")
    print(f"Total: {len(rows)} samples → {out_dir}/")
    for split in sorted(splits.keys()):
        for lbl in sorted(labels.keys()):
            d = out_dir / split / lbl
            if d.exists():
                n = len(list(d.glob("*.wav")))
                print(f"  {split}/{lbl}/: {n} WAV files")


def main() -> None:
    print("=" * 60)
    print("Example 04 — Speaker Verification")
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

    print(f"\nSpeakers: {', '.join(SPEAKERS)}\n")

    for i, spk in enumerate(SPEAKERS, 1):
        append = (i > 1)
        print(f"[{i}/{len(SPEAKERS)}] Processing '{spk}'...")
        try:
            run_speaker(spk, append=append)
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
