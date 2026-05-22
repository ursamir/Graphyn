#!/usr/bin/env bash
# Example 03 — Environmental Sound Classification (CLI version)
# Processes all 5 classes (dog, cat, bird, happy, house) and appends to shared output.
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo "$(dirname "$0")/../..")"

echo "============================================================"
echo "Example 03 — Environmental Sound Classification"
echo "Dataset: Google Speech Commands v0.02 (training set)"
echo "============================================================"
echo ""

# ── Validate the pipeline graph ───────────────────────────────────────────────
echo "Validating pipeline..."
venv/bin/python -m app.cli.main validate --graph examples/03_environmental_sounds/pipeline.graph.json
echo ""

# ── Clear previous output so all classes start fresh ─────────────────────────
OUT_DIR="examples/03_environmental_sounds/output/environmental_sounds/v1"
if [ -d "$OUT_DIR" ]; then
    rm -rf "$OUT_DIR"
    echo "Cleared previous output: $OUT_DIR"
    echo ""
fi

# ── Run pipeline for each class, appending to shared output ──────────────────
echo "[1/5] Processing class: dog"
venv/bin/python -m app.cli.main run --graph examples/03_environmental_sounds/pipeline.graph.json
echo ""

echo "[2/5] Processing class: cat"
venv/bin/python -m app.cli.main run --graph examples/03_environmental_sounds/pipeline_cat.graph.json
echo ""

echo "[3/5] Processing class: bird"
venv/bin/python -m app.cli.main run --graph examples/03_environmental_sounds/pipeline_bird.graph.json
echo ""

echo "[4/5] Processing class: happy"
venv/bin/python -m app.cli.main run --graph examples/03_environmental_sounds/pipeline_happy.graph.json
echo ""

echo "[5/5] Processing class: house"
venv/bin/python -m app.cli.main run --graph examples/03_environmental_sounds/pipeline_house.graph.json
echo ""

echo "Output: examples/03_environmental_sounds/output/environmental_sounds/v1/"
echo "Note: Run run_sdk.py for the same result via the Python SDK."
