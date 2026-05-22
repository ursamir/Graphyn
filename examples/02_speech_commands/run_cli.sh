#!/usr/bin/env bash
# Example 02 — Speech Command Recognition (CLI version)
# Processes all 6 commands (yes, no, up, down, go, stop) and appends to shared output.
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo "$(dirname "$0")/../..")"

echo "============================================================"
echo "Example 02 — Speech Command Recognition"
echo "Dataset: Google Speech Commands v0.02 (test set)"
echo "============================================================"
echo ""

# ── Validate the pipeline graph ───────────────────────────────────────────────
echo "Validating pipeline..."
venv/bin/python -m app.cli.main validate --graph examples/02_speech_commands/pipeline.graph.json
echo ""

# ── Clear previous output so all labels start fresh ──────────────────────────
OUT_DIR="examples/02_speech_commands/output/speech_commands/v1"
if [ -d "$OUT_DIR" ]; then
    rm -rf "$OUT_DIR"
    echo "Cleared previous output: $OUT_DIR"
    echo ""
fi

# ── Run pipeline for each command, appending to shared output ─────────────────
echo "[1/6] Processing command: yes"
venv/bin/python -m app.cli.main run --graph examples/02_speech_commands/pipeline.graph.json
echo ""

echo "[2/6] Processing command: no"
venv/bin/python -m app.cli.main run --graph examples/02_speech_commands/pipeline_no.graph.json
echo ""

echo "[3/6] Processing command: up"
venv/bin/python -m app.cli.main run --graph examples/02_speech_commands/pipeline_up.graph.json
echo ""

echo "[4/6] Processing command: down"
venv/bin/python -m app.cli.main run --graph examples/02_speech_commands/pipeline_down.graph.json
echo ""

echo "[5/6] Processing command: go"
venv/bin/python -m app.cli.main run --graph examples/02_speech_commands/pipeline_go.graph.json
echo ""

echo "[6/6] Processing command: stop"
venv/bin/python -m app.cli.main run --graph examples/02_speech_commands/pipeline_stop.graph.json
echo ""

echo "Output: examples/02_speech_commands/output/speech_commands/v1/"
echo "Note: Run run_sdk.py for the same result via the Python SDK."
