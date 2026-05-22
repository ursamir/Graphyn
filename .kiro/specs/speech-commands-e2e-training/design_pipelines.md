# Design: Pipeline Compositions

---

## Training Pipeline

### Phase 1 — Data Preprocessing (run 6× with append)

Identical to Example 02. Runs once per label, appending to `output/dataset/`.

```yaml
# pipeline_train.yaml (yes label only — for CLI testing)
pipeline:
  seed: 42
  nodes:
    - type: file_input
      config:
        path: examples/06_speech_commands_e2e/data/yes
        recursive: false

    - type: clean
      config:
        sample_rate: 16000

    - type: trim
      config:
        threshold_db: -40.0

    - type: silence_detector
      config:
        threshold_db: -60.0
        action: remove

    - type: command_validator
      config:
        min_duration_ms: 200.0
        max_duration_ms: 1000.0
        action: flag
        log_stats: true

    - type: pitch_shift
      config:
        semitones: [-2.0, 2.0]
        copies_per_sample: 1

    - type: time_stretch
      config:
        rate: [0.9, 1.1]
        copies_per_sample: 1

    - type: duplicate
      config:
        target_count: 50
        strategy: balance

    - type: split
      config:
        train: 0.70
        val: 0.15

    - type: file_export
      config:
        output: examples/06_speech_commands_e2e/output/dataset
        project: speech_commands
        version: v1
        append: true
```

### Phase 2 — Feature Extraction + Training

The SDK script runs this as a second pipeline after all 6 labels are preprocessed.

```yaml
# Conceptual — embedded in run_train.py as SDK nodes
pipeline:
  seed: 42
  nodes:
    - type: file_input
      config:
        path: examples/06_speech_commands_e2e/output/dataset/speech_commands/v1
        recursive: true

    - type: feature_extractor
      config:
        feature_type: mfcc
        n_mfcc: 40
        n_fft: 512
        hop_length: 160
        fmax: 8000.0
        fixed_length: 101
        normalize: true

    - type: dataset_builder
      config: {}

    - type: model_builder
      config:
        architecture: ds_cnn
        filters: 64
        num_layers: 4
        dropout_rate: 0.25
        learning_rate: 0.001

    - type: model_trainer
      config:
        epochs: 30
        batch_size: 32
        output_path: examples/06_speech_commands_e2e/output
        patience: 5

    - type: model_evaluator
      config:
        output_path: examples/06_speech_commands_e2e/output
        plot_confusion_matrix: true
        plot_training_curves: true

    - type: tflite_exporter
      config:
        quantisation: int8
        output_path: examples/06_speech_commands_e2e/output/tflite
        representative_samples: 100
```

---

## Inference Pipeline

```yaml
# pipeline_infer.yaml
pipeline:
  seed: 42
  nodes:
    - type: file_input
      config:
        path: examples/06_speech_commands_e2e/data/yes   # overridden by run_infer.py
        recursive: false

    - type: clean
      config:
        sample_rate: 16000

    - type: trim
      config:
        threshold_db: -40.0

    - type: feature_extractor
      config:
        feature_type: mfcc
        n_mfcc: 40
        n_fft: 512
        hop_length: 160
        fmax: 8000.0
        fixed_length: 101
        normalize: true

    - type: inference
      config:
        model_path: examples/06_speech_commands_e2e/output/tflite/model.tflite
```

---

## `run_train.py` — SDK Script

```python
#!/usr/bin/env python3
"""
Example 06 — Speech Commands End-to-End Training Pipeline
==========================================================
Usage:
    venv/bin/python examples/06_speech_commands_e2e/run_train.py

Output:
    examples/06_speech_commands_e2e/output/
        saved_model/          Keras SavedModel
        tflite/model.tflite   INT8 TFLite model
        tflite/labels.txt     Label list
        metrics.json          Test metrics
        confusion_matrix.png  Confusion matrix heatmap
        training_curves.png   Loss/accuracy curves
        feature_config.json   Feature extractor config (for inference)
"""
import os, sys, json, shutil
from pathlib import Path

WORKSPACE_ROOT = str(Path(__file__).parent.parent.parent)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

PLUGINS_DIR = str(Path(__file__).parent / "plugins")
os.environ["GRAPHYN_PLUGINS_DIR"] = PLUGINS_DIR

from app.core.sdk import PipelineNode, Pipeline

EXAMPLE_DIR = Path(__file__).parent
DATA_DIR    = EXAMPLE_DIR / "data"
OUTPUT_DIR  = EXAMPLE_DIR / "output"
COMMANDS    = ["yes", "no", "up", "down", "go", "stop"]

FEATURE_CONFIG = {
    "feature_type": "mfcc", "n_mfcc": 40, "n_fft": 512,
    "hop_length": 160, "fmax": 8000.0, "fixed_length": 101, "normalize": True,
}

def phase1_preprocess(command: str) -> None:
    """Run preprocessing pipeline for one command label."""
    Pipeline(nodes=[
        PipelineNode("file_input", {"path": str(DATA_DIR / command), "recursive": False}),
        PipelineNode("clean", {"sample_rate": 16000}),
        PipelineNode("trim", {"threshold_db": -40.0}),
        PipelineNode("silence_detector", {"threshold_db": -60.0, "action": "remove"}),
        PipelineNode("command_validator", {"min_duration_ms": 200.0, "max_duration_ms": 1000.0,
                                           "action": "flag", "log_stats": True}),
        PipelineNode("pitch_shift", {"semitones": [-2.0, 2.0], "copies_per_sample": 1}),
        PipelineNode("time_stretch", {"rate": [0.9, 1.1], "copies_per_sample": 1}),
        PipelineNode("duplicate", {"target_count": 50, "strategy": "balance"}),
        PipelineNode("split", {"train": 0.70, "val": 0.15}),
        PipelineNode("file_export", {
            "output": str(OUTPUT_DIR / "dataset"),
            "project": "speech_commands", "version": "v1", "append": True,
        }),
    ], seed=42).run()

def phase2_train() -> None:
    """Run feature extraction + training pipeline on assembled dataset."""
    dataset_path = str(OUTPUT_DIR / "dataset" / "speech_commands" / "v1")
    Pipeline(nodes=[
        PipelineNode("file_input", {"path": dataset_path, "recursive": True}),
        PipelineNode("feature_extractor", FEATURE_CONFIG),
        PipelineNode("dataset_builder", {}),
        PipelineNode("model_builder", {
            "architecture": "ds_cnn", "filters": 64, "num_layers": 4,
            "dropout_rate": 0.25, "learning_rate": 0.001,
        }),
        PipelineNode("model_trainer", {
            "epochs": 30, "batch_size": 32,
            "output_path": str(OUTPUT_DIR), "patience": 5,
        }),
        PipelineNode("model_evaluator", {
            "output_path": str(OUTPUT_DIR),
            "plot_confusion_matrix": True, "plot_training_curves": True,
        }),
        PipelineNode("tflite_exporter", {
            "quantisation": "int8",
            "output_path": str(OUTPUT_DIR / "tflite"),
            "representative_samples": 100,
        }),
    ], seed=42).run()

def main():
    print("=" * 60)
    print("Example 06 — Speech Commands E2E Training")
    print("=" * 60)

    # Clear previous output
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)

    # Phase 1: preprocess all 6 labels
    print("\nPhase 1: Data Preprocessing")
    for i, cmd in enumerate(COMMANDS, 1):
        print(f"  [{i}/{len(COMMANDS)}] {cmd}...")
        try:
            phase1_preprocess(cmd)
        except Exception as e:
            print(f"  ✗ {cmd} failed: {e}", file=sys.stderr)
            sys.exit(1)

    # Save feature config for inference
    with open(OUTPUT_DIR / "feature_config.json", "w") as f:
        json.dump(FEATURE_CONFIG, f, indent=2)

    # Phase 2: train
    print("\nPhase 2: Feature Extraction + Training")
    try:
        phase2_train()
    except Exception as e:
        print(f"  ✗ Training failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Print summary
    metrics_path = OUTPUT_DIR / "metrics.json"
    if metrics_path.exists():
        with open(metrics_path) as f:
            metrics = json.load(f)
        tflite_path = OUTPUT_DIR / "tflite" / "model.tflite"
        saved_model_path = OUTPUT_DIR / "saved_model"
        print("\n" + "=" * 60)
        print("Training complete!")
        print(f"  Test accuracy:   {metrics['test_accuracy']:.4f}")
        print(f"  SavedModel size: {sum(f.stat().st_size for f in saved_model_path.rglob('*') if f.is_file()) // 1024} KB")
        if tflite_path.exists():
            print(f"  TFLite size:     {tflite_path.stat().st_size // 1024} KB")

if __name__ == "__main__":
    main()
```

---

## `run_infer.py` — SDK Script

```python
#!/usr/bin/env python3
"""
Example 06 — Speech Commands Inference Pipeline
================================================
Usage:
    venv/bin/python examples/06_speech_commands_e2e/run_infer.py \\
        --model examples/06_speech_commands_e2e/output/tflite/model.tflite \\
        --input examples/06_speech_commands_e2e/data/yes
"""
import argparse, json, os, sys
from pathlib import Path

WORKSPACE_ROOT = str(Path(__file__).parent.parent.parent)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

PLUGINS_DIR = str(Path(__file__).parent / "plugins")
os.environ["GRAPHYN_PLUGINS_DIR"] = PLUGINS_DIR

from app.core.sdk import PipelineNode, Pipeline

EXAMPLE_DIR = Path(__file__).parent

def main():
    parser = argparse.ArgumentParser(description="Speech command inference")
    parser.add_argument("--model", required=True, help="Path to .tflite model")
    parser.add_argument("--input", required=True, help="Directory of WAV files")
    args = parser.parse_args()

    # Load feature config written by run_train.py
    feature_config_path = EXAMPLE_DIR / "output" / "feature_config.json"
    if feature_config_path.exists():
        with open(feature_config_path) as f:
            feature_config = json.load(f)
    else:
        # Fallback defaults
        feature_config = {
            "feature_type": "mfcc", "n_mfcc": 40, "n_fft": 512,
            "hop_length": 160, "fmax": 8000.0, "fixed_length": 101, "normalize": True,
        }

    try:
        Pipeline(nodes=[
            PipelineNode("file_input", {"path": args.input, "recursive": False}),
            PipelineNode("clean", {"sample_rate": 16000}),
            PipelineNode("trim", {"threshold_db": -40.0}),
            PipelineNode("feature_extractor", feature_config),
            PipelineNode("inference", {"model_path": args.model}),
        ], seed=42).run()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
```

**Note:** The `InferenceNode.process()` prints results directly to stdout in the format
`<filename>  →  <predicted_label>  (<confidence>%)` as it processes each clip.

---

## Data Symlink / Copy Strategy

Example 06 reuses Example 02's data directory. Rather than duplicating 1200 WAV files,
`run_train.py` checks for data in `examples/06_speech_commands_e2e/data/` first, then
falls back to `examples/02_speech_commands/data/` with a clear error message directing
the user to run `venv/bin/python examples/prepare_real_data.py`.

The `README.md` documents this clearly.

---

## `feature_config.json` — Feature Consistency Contract

`run_train.py` writes this file after Phase 1 completes:

```json
{
  "feature_type": "mfcc",
  "n_mfcc": 40,
  "n_fft": 512,
  "hop_length": 160,
  "fmax": 8000.0,
  "fixed_length": 101,
  "normalize": true
}
```

`run_infer.py` reads this file to guarantee the inference pipeline uses identical
feature extraction parameters to the training pipeline.
