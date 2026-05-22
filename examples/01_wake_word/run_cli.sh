#!/usr/bin/env bash
# Example 01 — Wake Word Detection (CLI version)
# Processes both labels (wake_word + background) and appends to shared output.
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo "$(dirname "$0")/../..")"

echo "============================================================"
echo "Example 01 — Wake Word Detection"
echo "Dataset: Google Speech Commands v0.02 (test set)"
echo "============================================================"
echo ""

# ── Validate the pipeline graph ───────────────────────────────────────────────
echo "Validating pipeline..."
venv/bin/python -m app.cli.main validate --graph examples/01_wake_word/pipeline.graph.json
echo ""

# ── Clear previous output so both labels start fresh ─────────────────────────
OUT_DIR="examples/01_wake_word/output/wake_word_detection/v1"
if [ -d "$OUT_DIR" ]; then
    rm -rf "$OUT_DIR"
    echo "Cleared previous output: $OUT_DIR"
    echo ""
fi

# ── Run pipeline for each label, appending to shared output ──────────────────
# Label 1: wake_word (fresh write, append=false)
echo "[1/2] Processing label: wake_word"
venv/bin/python -m app.cli.main run --graph examples/01_wake_word/pipeline.graph.json
echo ""

# Label 2: background (append=true — merge into same output directory)
echo "[2/2] Processing label: background"
venv/bin/python -m app.cli.main run --graph examples/01_wake_word/pipeline_background.graph.json
echo ""

echo "Output: examples/01_wake_word/output/wake_word_detection/v1/"
echo "Note: Run run_sdk.py for the same result via the Python SDK."
