#!/usr/bin/env bash
# Example 04 — Speaker Verification (CLI version)
# Processes all 6 speakers and appends to shared output.
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo "$(dirname "$0")/../..")"

echo "============================================================"
echo "Example 04 — Speaker Verification"
echo "Dataset: Google Speech Commands v0.02 (training set)"
echo "============================================================"
echo ""

# ── Validate the pipeline graph ───────────────────────────────────────────────
echo "Validating pipeline..."
venv/bin/python -m app.cli.main validate --graph examples/04_speaker_verification/pipeline.graph.json
echo ""

# ── Clear previous output so all speakers start fresh ────────────────────────
OUT_DIR="examples/04_speaker_verification/output/speaker_verification/v1"
if [ -d "$OUT_DIR" ]; then
    rm -rf "$OUT_DIR"
    echo "Cleared previous output: $OUT_DIR"
    echo ""
fi

# ── Run pipeline for each speaker, appending to shared output ─────────────────
echo "[1/6] Processing speaker: speaker_001"
venv/bin/python -m app.cli.main run --graph examples/04_speaker_verification/pipeline.graph.json
echo ""

echo "[2/6] Processing speaker: speaker_002"
venv/bin/python -m app.cli.main run --graph examples/04_speaker_verification/pipeline_speaker_002.graph.json
echo ""

echo "[3/6] Processing speaker: speaker_003"
venv/bin/python -m app.cli.main run --graph examples/04_speaker_verification/pipeline_speaker_003.graph.json
echo ""

echo "[4/6] Processing speaker: speaker_004"
venv/bin/python -m app.cli.main run --graph examples/04_speaker_verification/pipeline_speaker_004.graph.json
echo ""

echo "[5/6] Processing speaker: speaker_005"
venv/bin/python -m app.cli.main run --graph examples/04_speaker_verification/pipeline_speaker_005.graph.json
echo ""

echo "[6/6] Processing speaker: speaker_006"
venv/bin/python -m app.cli.main run --graph examples/04_speaker_verification/pipeline_speaker_006.graph.json
echo ""

echo "Output: examples/04_speaker_verification/output/speaker_verification/v1/"
echo "Note: Run run_sdk.py for the same result via the Python SDK."
