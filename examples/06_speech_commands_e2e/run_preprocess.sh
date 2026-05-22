#!/usr/bin/env bash
# Example 06 — Phase 1: Data Preprocessing (CLI version)
# Processes all 6 command labels and appends to shared output.
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo "$(dirname "$0")/../..")"

# Data directory — fall back to Example 02 if own data dir doesn't exist
DATA_DIR="examples/06_speech_commands_e2e/data"
if [ ! -d "$DATA_DIR/yes" ]; then
    DATA_DIR="examples/02_speech_commands/data"
    echo "Using data from Example 02: $DATA_DIR"
fi

echo "============================================================"
echo "Example 06 — Phase 1: Data Preprocessing"
echo "Data dir: $DATA_DIR"
echo "============================================================"
echo ""

# ── Validate the pipeline graph ───────────────────────────────────────────────
echo "Validating preprocess pipeline..."
venv/bin/python -m app.cli.main validate --graph examples/06_speech_commands_e2e/pipeline_preprocess.graph.json
echo ""

# ── Clear previous dataset output ────────────────────────────────────────────
OUT_DIR="examples/06_speech_commands_e2e/output/dataset/speech_commands/v1"
if [ -d "$OUT_DIR" ]; then
    rm -rf "$OUT_DIR"
    echo "Cleared previous dataset: $OUT_DIR"
    echo ""
fi

# ── Run pipeline for each command ─────────────────────────────────────────────
echo "[1/6] Processing command: yes"
venv/bin/python -m app.cli.main run --graph examples/06_speech_commands_e2e/pipeline_preprocess.graph.json
echo ""

echo "[2/6] Processing command: no"
venv/bin/python -m app.cli.main run --graph examples/06_speech_commands_e2e/pipeline_preprocess_no.graph.json
echo ""

echo "[3/6] Processing command: up"
venv/bin/python -m app.cli.main run --graph examples/06_speech_commands_e2e/pipeline_preprocess_up.graph.json
echo ""

echo "[4/6] Processing command: down"
venv/bin/python -m app.cli.main run --graph examples/06_speech_commands_e2e/pipeline_preprocess_down.graph.json
echo ""

echo "[5/6] Processing command: go"
venv/bin/python -m app.cli.main run --graph examples/06_speech_commands_e2e/pipeline_preprocess_go.graph.json
echo ""

echo "[6/6] Processing command: stop"
venv/bin/python -m app.cli.main run --graph examples/06_speech_commands_e2e/pipeline_preprocess_stop.graph.json
echo ""

echo "============================================================"
echo "Phase 1 complete!"
echo "Dataset: examples/06_speech_commands_e2e/output/dataset/speech_commands/v1/"
echo ""
echo "Next step: bash examples/06_speech_commands_e2e/run_train_ml.sh"
echo "============================================================"
