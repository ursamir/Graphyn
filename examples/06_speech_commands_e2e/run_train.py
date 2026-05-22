#!/usr/bin/env python3
"""
Example 06 — Speech Commands End-to-End Training Pipeline (Python SDK)
=======================================================================
Dataset: Google Speech Commands v0.02 (test set)
  data/yes/, no/, up/, down/, go/, stop/  (200 clips each, 1s, 16kHz)

Purpose:
  Complete end-to-end pipeline from raw audio to trained TFLite model.
  Extends Example 02 with feature extraction, DS-CNN training, evaluation,
  and INT8 TFLite export.

Two-phase execution:
  Phase 1 (×6 labels): dataset_ingest → audio_conditioner → segmenter →
                        audio_quality_gate(snr) → audio_quality_gate(duration) →
                        augmentation_pipeline → audio_exporter(append)
  Phase 2 (×1):        dataset_ingest → feature_frontend → dataset_builder →
                        [build Keras DS-CNN model] → trainer → evaluator → edge_optimizer

Usage:
  venv/bin/python examples/06_speech_commands_e2e/run_train.py

Output:
  examples/06_speech_commands_e2e/output/
    dataset/speech_commands/v1/  Preprocessed WAV files (from Phase 1)
    saved_model/                 Keras SavedModel
    checkpoints/                 Best checkpoint during training
    tflite/
      model.tflite               INT8 quantised TFLite model
      labels.txt                 Label list (one per line)
    metrics.json                 Test accuracy + per-class metrics
    confusion_matrix.png         Confusion matrix heatmap
    training_curves.png          Loss and accuracy curves
    feature_config.json          Feature extractor config (used by run_infer.py)
"""
from __future__ import annotations

import json
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
manager.install("PluginPackage/Audio/feature_frontend/", upgrade=True)
manager.install("PluginPackage/Common/dataset_builder/")
manager.install("PluginPackage/Common/trainer/", upgrade=True)  # also registers model_builder
manager.install("PluginPackage/Common/evaluator/")
manager.install("PluginPackage/Common/edge_optimizer/")
manager.load_enabled_plugins()

EXAMPLE_DIR = Path(__file__).parent
DATA_DIR = EXAMPLE_DIR / "data"
OUTPUT_DIR = EXAMPLE_DIR / "output"
COMMANDS = ["yes", "no", "up", "down", "go", "stop"]

FEATURE_CONFIG = {
    "feature_type": "mfcc",
    "n_mfcc": 40,
    "n_fft": 512,
    "hop_length": 160,
    "fmax": 8000.0,
    "fixed_length": 101,
    "normalize": True,
}


def check_inputs() -> bool:
    fallback = EXAMPLE_DIR.parent / "02_speech_commands" / "data"
    ok = True
    for cmd in COMMANDS:
        p = DATA_DIR / cmd
        if not p.exists():
            p = fallback / cmd
        if not p.exists():
            print(f"  ✗ Missing: data/{cmd}/")
            ok = False
        else:
            n = len(list(p.glob("*.wav")))
            print(f"  ✓ data/{cmd}/: {n} WAV files")
    return ok


def _resolve_data_dir(command: str) -> Path:
    p = DATA_DIR / command
    if p.exists():
        return p
    fallback = EXAMPLE_DIR.parent / "02_speech_commands" / "data" / command
    if fallback.exists():
        return fallback
    raise FileNotFoundError(f"Data not found for '{command}'. Run prepare_real_data.py first.")


# ── Phase 1: preprocessing ────────────────────────────────────────────────────

def phase1_preprocess(command: str, append: bool) -> None:
    """Run preprocessing pipeline for one command label."""
    data_path = _resolve_data_dir(command)
    Pipeline(
        nodes=[
            PipelineNode("dataset_ingest", {
                "path": str(data_path),
                "recursive": False,
                "source_type": "filesystem",
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
            PipelineNode("audio_quality_gate", {
                "min_snr_db": 5.0,
                "rejection_policy": "skip",
            }),
            PipelineNode("audio_quality_gate", {
                "min_duration_s": 0.2,
                "max_duration_s": 1.0,
                "rejection_policy": "skip",
            }),
            PipelineNode("augmentation_pipeline", {
                "copies_per_sample": 2,
                "augmentations": [
                    {"type": "pitch_shift", "apply_prob": 1.0, "semitones": [-2.0, 2.0]},
                    {"type": "time_stretch", "apply_prob": 1.0, "rate": [0.9, 1.1]},
                ],
            }),
            PipelineNode("audio_exporter", {
                "output_dir": str(OUTPUT_DIR / "dataset" / "speech_commands"),
                "split_ratios": {"train": 0.70, "val": 0.15, "test": 0.15},
                "version_tag": "v1",
                "random_seed": 42,
                "append": append,
            }),
        ],
        seed=42,
    ).run(use_cache=False)


# ── Phase 2: feature extraction + training ────────────────────────────────────

def phase2_train() -> None:
    """Feature extraction + model build + training + evaluation + TFLite export.

    Uses a Pipeline with explicit edge routing to wire the multi-port nodes
    (trainer requires both 'model' and 'dataset' inputs; evaluator requires
    both 'model_artifact' and 'dataset' inputs).

    Pipeline topology:
        [0] dataset_ingest  → [1] feature_frontend → [2] dataset_builder
        [2] dataset_builder → [3] model_builder    (dataset → model_builder.input)
        [2] dataset_builder → [4] trainer.dataset
        [3] model_builder   → [4] trainer.model
        [4] trainer         → [5] evaluator.model_artifact
        [2] dataset_builder → [5] evaluator.dataset
        [5] evaluator       → [6] edge_optimizer
    """
    dataset_path = str(OUTPUT_DIR / "dataset" / "speech_commands" / "v1")
    ff_cfg = {k: v for k, v in FEATURE_CONFIG.items() if k != "fixed_length"}

    Pipeline(
        nodes=[
            # [0] Load preprocessed WAV files
            PipelineNode("dataset_ingest", {
                "path": dataset_path,
                "recursive": True,
                "source_type": "filesystem",
            }),
            # [1] Extract MFCC features
            PipelineNode("feature_frontend", ff_cfg),
            # [2] Assemble train/val/test numpy arrays
            PipelineNode("dataset_builder", {
                "fixed_length": FEATURE_CONFIG["fixed_length"],
            }),
            # [3] Build DS-CNN Keras model from dataset shape
            PipelineNode("model_builder", {
                "architecture": "ds_cnn",
                "filters": 64,
                "num_layers": 4,
                "dropout_rate": 0.25,
                "learning_rate": 0.001,
                "backend": "keras",
            }),
            # [4] Train the model
            PipelineNode("trainer", {
                "backend": "keras",
                "epochs": 30,
                "batch_size": 32,
                "output_path": str(OUTPUT_DIR),
                "patience": 5,
            }),
            # [5] Evaluate on test set
            PipelineNode("evaluator", {
                "output_path": str(OUTPUT_DIR),
                "plot_confusion_matrix": True,
                "plot_training_curves": True,
            }),
            # [6] Export INT8 TFLite model
            PipelineNode("edge_optimizer", {
                "backend": "tflite",
                "quantization": "int8",
                "output_path": str(OUTPUT_DIR / "tflite"),
                "representative_samples": 100,
            }),
        ],
        edges=[
            # Linear chain: ingest → features → dataset
            (0, "output", 1, "input"),
            (1, "output", 2, "input"),
            # dataset_builder feeds model_builder, trainer.dataset, evaluator.dataset
            (2, "output", 3, "input"),
            (2, "output", 4, "dataset"),
            (2, "output", 5, "dataset"),
            # model_builder feeds trainer.model
            (3, "output", 4, "model"),
            # trainer feeds evaluator.model_artifact
            (4, "output", 5, "model_artifact"),
            # evaluator feeds edge_optimizer
            (5, "output", 6, "input"),
        ],
        seed=42,
    ).run(use_cache=False)


def print_summary() -> None:
    print("\n" + "=" * 60)
    print("Training complete!")
    metrics_path = OUTPUT_DIR / "metrics.json"
    if metrics_path.exists():
        with open(metrics_path) as f:
            metrics = json.load(f)
        acc = metrics.get("test_accuracy", metrics.get("accuracy", "?"))
        print(f"  Test accuracy:   {acc}")
    tflite_path = OUTPUT_DIR / "tflite" / "model.tflite"
    if tflite_path.exists():
        print(f"  TFLite size:     {tflite_path.stat().st_size // 1024} KB")
    print(f"  Outputs in: {OUTPUT_DIR}/")
    print("=" * 60)


def main() -> None:
    print("=" * 60)
    print("Example 06 — Speech Commands End-to-End Training")
    print("=" * 60)

    print("\nChecking input data...")
    if not check_inputs():
        print("\nRun first: venv/bin/python examples/prepare_real_data.py")
        sys.exit(1)

    # Clear previous output
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
        print(f"\nCleared previous output: {OUTPUT_DIR}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\nCommands: {', '.join(COMMANDS)}\n")

    # Phase 1: preprocess all 6 labels
    print("Phase 1: Data Preprocessing")
    print("-" * 40)
    for i, cmd in enumerate(COMMANDS, 1):
        append = (i > 1)
        print(f"\n[{i}/{len(COMMANDS)}] Processing '{cmd}'...")
        try:
            phase1_preprocess(cmd, append=append)
            print(f"  ✓ '{cmd}' done")
        except Exception as exc:
            print(f"\nError processing '{cmd}': {exc}", file=sys.stderr)
            import traceback; traceback.print_exc()
            sys.exit(1)

    # Save feature config for inference pipeline
    feature_config_path = OUTPUT_DIR / "feature_config.json"
    with open(feature_config_path, "w") as f:
        json.dump(FEATURE_CONFIG, f, indent=2)
    print(f"\nFeature config saved to: {feature_config_path}")

    # Phase 2: feature extraction + training
    print("\nPhase 2: Feature Extraction + Training")
    print("-" * 40)
    try:
        phase2_train()
    except Exception as exc:
        print(f"\nTraining failed: {exc}", file=sys.stderr)
        import traceback; traceback.print_exc()
        sys.exit(1)

    print_summary()


if __name__ == "__main__":
    main()
