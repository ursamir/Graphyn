#!/usr/bin/env python3
"""
Example 06 — Speech Commands Inference Pipeline (Python SDK)
=============================================================
Loads a trained TFLite model and classifies audio clips from a directory.

Usage:
  venv/bin/python examples/06_speech_commands_e2e/run_infer.py \\
      --model examples/06_speech_commands_e2e/output/tflite/model.tflite \\
      --input examples/06_speech_commands_e2e/data/yes

Output (per file):
  <filename>  →  <predicted_label>  (<confidence>%)

The feature extractor config is loaded from output/feature_config.json
(written by run_train.py) to ensure consistency with the training pipeline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ── path setup ────────────────────────────────────────────────────────────────
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
manager.install("PluginPackage/Audio/feature_frontend/", upgrade=True)
manager.install("PluginPackage/Common/realtime_inference/")
manager.load_enabled_plugins()

EXAMPLE_DIR = Path(__file__).parent
OUTPUT_DIR = EXAMPLE_DIR / "output"

# Default feature config (fallback if feature_config.json not found)
DEFAULT_FEATURE_CONFIG = {
    "feature_type": "mfcc",
    "n_mfcc": 40,
    "n_fft": 512,
    "hop_length": 160,
    "fmax": 8000.0,
    "fixed_length": 101,
    "normalize": True,
}


def load_feature_config() -> dict:
    """Load feature config from output/feature_config.json, or use defaults."""
    config_path = OUTPUT_DIR / "feature_config.json"
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
        print(f"  Feature config loaded from: {config_path}")
        return config
    else:
        print(
            f"  WARNING: feature_config.json not found at {config_path}. "
            "Using default feature config. Run run_train.py first for best results."
        )
        return DEFAULT_FEATURE_CONFIG


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Speech command inference using a trained TFLite model."
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Path to the .tflite model file",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Directory containing WAV files to classify",
    )
    args = parser.parse_args()

    model_path = Path(args.model)
    input_path = Path(args.input)

    if not model_path.exists():
        print(f"Error: model file not found: {model_path}", file=sys.stderr)
        sys.exit(1)

    if not input_path.exists():
        print(f"Error: input directory not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    wav_files = list(input_path.glob("*.wav"))
    if not wav_files:
        print(f"Warning: no WAV files found in {input_path}")
        sys.exit(0)

    print("=" * 60)
    print("Example 06 — Speech Commands Inference")
    print("=" * 60)
    print(f"  Model:  {model_path}")
    print(f"  Input:  {input_path} ({len(wav_files)} WAV files)")
    print()

    feature_config = load_feature_config()

    try:
        Pipeline(
            nodes=[
                PipelineNode("dataset_ingest", {
                    "path": str(input_path),
                    "recursive": False,
                    "source_type": "filesystem",
                }),
                PipelineNode("audio_conditioner", {"target_sample_rate": 16000}),
                PipelineNode("segmenter", {
                    "silence_threshold_db": 40.0,
                    "mode": "silence",
                }),
                PipelineNode("feature_frontend", feature_config),
                # fixed_length is now supported by feature_frontend directly
                PipelineNode("realtime_inference", {
                    "model_path": str(model_path),
                }),
            ],
            seed=42,
        ).run(use_cache=False)
    except Exception as exc:
        print(f"\nInference failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print("\nDone.")


if __name__ == "__main__":
    main()
