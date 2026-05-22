#!/usr/bin/env python3
"""
Example 05 — Speech Enhancement Dataset Pipeline (Python SDK)
=============================================================
Dataset: Google Speech Commands v0.02 (test set + background noise)
  data/clean_speech/ ← yes/ + no/ from test set (186 clips, 1s, 16kHz)
  data/noise/        ← _background_noise_/ (6 real noise WAVs)

Purpose:
  Paired clean/degraded speech dataset for training speech enhancement
  models (denoising, dereverberation, bandwidth extension).

  Pass 1 — clean: ingest → condition → segment → compress → export (label=clean_speech)
  Pass 2 — degraded: same + codec_degrade + noise_inject → export (label=degraded, append)

Output:
  examples/05_speech_enhancement/output/speech_enhancement/v1/
    train/clean_speech/   ← clean WAV files
    train/degraded/       ← degraded WAV files
    val/clean_speech/
    val/degraded/
    test/clean_speech/
    test/degraded/
    labels.csv
    metadata.json

Usage:
  venv/bin/python examples/05_speech_enhancement/run_sdk.py
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
manager.install("PluginPackage/Audio/augmentation_pipeline/")
manager.install("PluginPackage/Audio/audio_exporter/")
manager.load_enabled_plugins()

EXAMPLE_DIR = Path(__file__).parent
DATA_DIR    = EXAMPLE_DIR / "data"
OUTPUT_DIR  = EXAMPLE_DIR / "output" / "speech_enhancement"


def check_inputs() -> bool:
    ok = True
    for name, path in [
        ("clean_speech", DATA_DIR / "clean_speech"),
        ("noise",        DATA_DIR / "noise"),
    ]:
        if not path.exists():
            print(f"  ✗ Missing: {path}")
            ok = False
        else:
            n = len(list(path.glob("*.wav")))
            print(f"  ✓ data/{name}/: {n} WAV files")
    return ok


def _base_nodes(label_override: str = "") -> list:
    """Shared preprocessing nodes for both clean and degraded passes."""
    ingest_cfg = {
        "path": str(DATA_DIR / "clean_speech"),
        "source_type": "filesystem",
        "recursive": False,
    }
    if label_override:
        ingest_cfg["label_override"] = label_override
    return [
        PipelineNode("dataset_ingest", ingest_cfg),
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
        # Dynamic range compression before degradation
        PipelineNode("audio_conditioner", {
            "compress": True,
            "compress_threshold_db": -20.0,
            "compress_ratio": 3.0,
        }),
    ]


def run_clean() -> None:
    """Pass 1: export clean speech (no degradation)."""
    Pipeline(
        nodes=_base_nodes() + [
            PipelineNode("audio_exporter", {
                "output_dir": str(OUTPUT_DIR),
                "split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15},
                "version_tag": "v1",
                "random_seed": 42,
                "append": False,
            }),
        ],
        seed=42,
    ).run(use_cache=False)


def run_degraded() -> None:
    """Pass 2: apply codec + noise degradation, export as degraded."""
    # Note: codec_degrade with codec="mp3" falls back to OGG/Vorbis encoding
    # because soundfile does not support MP3 encoding natively. The degradation
    # is real (lossy codec round-trip + Gaussian noise injection) but the codec
    # used is OGG, not MP3. For true MP3 simulation install pydub+ffmpeg.
    Pipeline(
        nodes=_base_nodes(label_override="degraded") + [
            # Codec degradation + noise injection
            # (environment_simulator requires pyroomacoustics which is not installed)
            PipelineNode("augmentation_pipeline", {
                "copies_per_sample": 1,
                "augmentations": [
                    {"type": "codec_degrade", "apply_prob": 1.0, "codec": "mp3", "bitrate": 8},
                    {"type": "noise_inject",  "apply_prob": 1.0, "snr_db": [10.0, 20.0]},
                ],
            }),
            PipelineNode("audio_exporter", {
                "output_dir": str(OUTPUT_DIR),
                "split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15},
                "version_tag": "v1",
                "random_seed": 42,
                "append": True,
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

    # Verify clean and degraded files actually differ in content
    import soundfile as sf
    import numpy as np
    clean_dir = out_dir / "train" / "clean_speech"
    degraded_dir = out_dir / "train" / "degraded"
    clean_wavs = sorted(clean_dir.glob("*.wav")) if clean_dir.exists() else []
    degraded_wavs = sorted(degraded_dir.glob("*.wav")) if degraded_dir.exists() else []
    if clean_wavs and degraded_wavs:
        # Compare the first matching stem
        clean_stems = {f.stem: f for f in clean_wavs}
        degraded_stems = {f.stem: f for f in degraded_wavs}
        common = set(clean_stems) & set(degraded_stems)
        if common:
            stem = next(iter(sorted(common)))
            c_data, _ = sf.read(str(clean_stems[stem]), dtype="float32")
            d_data, _ = sf.read(str(degraded_stems[stem]), dtype="float32")
            min_len = min(len(c_data), len(d_data))
            if min_len > 0:
                diff = float(np.mean(np.abs(c_data[:min_len] - d_data[:min_len])))
                print(f"\nDegradation verification (sample '{stem}'):")
                print(f"  Mean absolute difference (clean vs degraded): {diff:.6f}")
                if diff > 1e-4:
                    print("  ✓ Degradation confirmed — files differ in content")
                else:
                    print("  ✗ WARNING: clean and degraded files appear identical")
        else:
            print("\n  (no matching stems between clean and degraded — cannot compare)")
    else:
        print("\n  (clean or degraded directory missing — cannot verify degradation)")


def main() -> None:
    print("=" * 60)
    print("Example 05 — Speech Enhancement")
    print("Dataset: Google Speech Commands v0.02 (test set)")
    print("=" * 60)

    print("\nChecking input data...")
    if not check_inputs():
        print("\nRun first: venv/bin/python examples/prepare_real_data.py")
        sys.exit(1)

    # Clear previous output
    out_versioned = OUTPUT_DIR / "v1"
    if out_versioned.exists():
        shutil.rmtree(out_versioned)
        print(f"\nCleared previous output: {out_versioned}")

    print("\n[1/2] Running clean pass...")
    try:
        run_clean()
        print("  ✓ done")
    except Exception as exc:
        print(f"  ✗ failed: {exc}", file=sys.stderr)
        import traceback; traceback.print_exc()
        sys.exit(1)

    print("\n[2/2] Running degraded pass (codec_degrade + noise_inject)...")
    try:
        run_degraded()
        print("  ✓ done")
    except Exception as exc:
        print(f"  ✗ failed: {exc}", file=sys.stderr)
        import traceback; traceback.print_exc()
        sys.exit(1)

    print("\n" + "=" * 60)
    print("Done!")
    print_summary(out_versioned)


if __name__ == "__main__":
    main()
