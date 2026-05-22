#!/usr/bin/env bash
# Example 06 — Phase 2: Feature Extraction + Model Training (CLI version)
# =========================================================================
# Runs the ML pipeline on the assembled dataset from Phase 1.
# Uses pipeline_train_ml.graph.json (IR JSON — canonical format).
#
# Prerequisites:
#   bash examples/06_speech_commands_e2e/run_preprocess.sh
#
# Usage:
#   bash examples/06_speech_commands_e2e/run_train_ml.sh
#
# Output:
#   examples/06_speech_commands_e2e/output/
#     saved_model/          Keras SavedModel
#     tflite/model.tflite   INT8 TFLite model
#     tflite/labels.txt     Label list
#     metrics.json          Test accuracy + per-class metrics
#     confusion_matrix.png  Confusion matrix heatmap
#     training_curves.png   Loss and accuracy curves
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$WORKSPACE_ROOT"

export GRAPHYN_PLUGINS_DIR="$SCRIPT_DIR/plugins"

GRAPH_JSON="$SCRIPT_DIR/pipeline_train_ml.graph.json"
DATASET_DIR="$SCRIPT_DIR/output/dataset/speech_commands/v1"
OUTPUT_DIR="$SCRIPT_DIR/output"

echo "============================================================"
echo "Example 06 — Phase 2: Feature Extraction + Model Training"
echo "Plugin dir:  $GRAPHYN_PLUGINS_DIR"
echo "Graph:       $GRAPH_JSON"
echo "Dataset:     $DATASET_DIR"
echo "Output:      $OUTPUT_DIR"
echo "============================================================"
echo ""

# Check dataset exists
if [ ! -d "$DATASET_DIR" ]; then
    echo "ERROR: Dataset not found at $DATASET_DIR"
    echo "Run Phase 1 first: bash examples/06_speech_commands_e2e/run_preprocess.sh"
    exit 1
fi

echo "Validating ML pipeline..."
venv/bin/python -m app.cli.main validate --graph "$GRAPH_JSON"
echo ""

echo "Running ML pipeline..."
venv/bin/python -m app.cli.main run --graph "$GRAPH_JSON"

echo ""
echo "============================================================"
echo "Phase 2 complete!"
echo ""
echo "Outputs:"
echo "  SavedModel:       $OUTPUT_DIR/saved_model/"
echo "  TFLite model:     $OUTPUT_DIR/tflite/model.tflite"
echo "  Metrics:          $OUTPUT_DIR/metrics.json"
echo "  Confusion matrix: $OUTPUT_DIR/confusion_matrix.png"
echo "  Training curves:  $OUTPUT_DIR/training_curves.png"
echo ""
echo "Run inference:"
echo "  bash examples/06_speech_commands_e2e/run_infer.sh \\"
echo "      --input examples/06_speech_commands_e2e/data/yes"
echo "============================================================"
