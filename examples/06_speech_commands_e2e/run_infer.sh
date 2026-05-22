#!/usr/bin/env bash
# Example 06 — Inference Pipeline (CLI version)
# ===============================================
# Runs inference on a directory of WAV files using the trained TFLite model.
# Uses pipeline_infer.graph.json (IR JSON — canonical format).
# Patches input path and model path at runtime via Python.
#
# Prerequisites:
#   bash examples/06_speech_commands_e2e/run_train_ml.sh
#
# Usage:
#   bash examples/06_speech_commands_e2e/run_infer.sh --input <dir> [--model <path>]
#
# Examples:
#   bash examples/06_speech_commands_e2e/run_infer.sh \
#       --input examples/06_speech_commands_e2e/data/yes
#
#   bash examples/06_speech_commands_e2e/run_infer.sh \
#       --input examples/02_speech_commands/data/no \
#       --model examples/06_speech_commands_e2e/output/tflite/model.tflite
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$WORKSPACE_ROOT"

export GRAPHYN_PLUGINS_DIR="$SCRIPT_DIR/plugins"

GRAPH_JSON="$SCRIPT_DIR/pipeline_infer.graph.json"
MODEL_PATH="$SCRIPT_DIR/output/tflite/model.tflite"
INPUT_DIR=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --input)
            INPUT_DIR="$2"
            shift 2
            ;;
        --model)
            MODEL_PATH="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 --input <dir> [--model <path>]"
            exit 1
            ;;
    esac
done

if [ -z "$INPUT_DIR" ]; then
    echo "ERROR: --input is required"
    echo "Usage: $0 --input <dir> [--model <path>]"
    exit 1
fi

if [ ! -f "$MODEL_PATH" ]; then
    echo "ERROR: TFLite model not found: $MODEL_PATH"
    echo "Run training first: bash examples/06_speech_commands_e2e/run_train_ml.sh"
    exit 1
fi

if [ ! -d "$INPUT_DIR" ]; then
    echo "ERROR: Input directory not found: $INPUT_DIR"
    exit 1
fi

echo "============================================================"
echo "Example 06 — Inference"
echo "Graph:      $GRAPH_JSON"
echo "Model:      $MODEL_PATH"
echo "Input:      $INPUT_DIR"
echo "Plugin dir: $GRAPHYN_PLUGINS_DIR"
echo "============================================================"
echo ""

# Patch the graph JSON in-memory and run via SDK
venv/bin/python - "$GRAPH_JSON" "$INPUT_DIR" "$MODEL_PATH" <<'PYEOF'
import sys, json, os
sys.path.insert(0, os.getcwd())
os.environ.setdefault("GRAPHYN_PLUGINS_DIR", os.environ.get("GRAPHYN_PLUGINS_DIR", ""))

graph_path, input_dir, model_path = sys.argv[1], sys.argv[2], sys.argv[3]

with open(graph_path) as f:
    graph = json.load(f)

# Patch dataset_ingest path and realtime_inference model_path
for node in graph["nodes"]:
    if node["node_type"] == "dataset_ingest":
        node["config"]["path"] = input_dir
    elif node["node_type"] == "realtime_inference":
        node["config"]["model_path"] = model_path

from app.core.ir.loader import load_ir
from app.core.sdk import Pipeline, PipelineNode

ir = load_ir(graph)
nodes = [PipelineNode(n.node_type, dict(n.config)) for n in ir.nodes]
pipeline = Pipeline(nodes=nodes, seed=ir.metadata.seed)
pipeline.run(use_cache=False)
PYEOF

echo ""
echo "============================================================"
echo "Inference complete."
echo "============================================================"
