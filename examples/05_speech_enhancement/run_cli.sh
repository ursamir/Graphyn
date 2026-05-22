#!/usr/bin/env bash
# Example 05 — Speech Enhancement (CLI version)
# Runs clean pass then degraded pass, appending to shared output.
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo "$(dirname "$0")/../..")"

echo "============================================================"
echo "Example 05 — Speech Enhancement"
echo "Dataset: Google Speech Commands v0.02 (test set)"
echo "============================================================"
echo ""

# ── Validate both pipeline graphs ─────────────────────────────────────────────
echo "Validating clean pipeline..."
venv/bin/python -m app.cli.main validate --graph examples/05_speech_enhancement/pipeline.graph.json
echo ""
echo "Validating degraded pipeline..."
venv/bin/python -m app.cli.main validate --graph examples/05_speech_enhancement/pipeline_degraded.graph.json
echo ""

# ── Clear previous output ─────────────────────────────────────────────────────
OUT_DIR="examples/05_speech_enhancement/output/speech_enhancement/v1"
if [ -d "$OUT_DIR" ]; then
    rm -rf "$OUT_DIR"
    echo "Cleared previous output: $OUT_DIR"
    echo ""
fi

# ── Pass 1: clean ─────────────────────────────────────────────────────────────
echo "[1/2] Running clean pass..."
venv/bin/python -m app.cli.main run --graph examples/05_speech_enhancement/pipeline.graph.json
echo ""

# ── Pass 2: degraded (append) ─────────────────────────────────────────────────
echo "[2/2] Running degraded pass (codec_degrade + noise_inject)..."
venv/bin/python -m app.cli.main run --graph examples/05_speech_enhancement/pipeline_degraded.graph.json
echo ""

echo "Output: examples/05_speech_enhancement/output/speech_enhancement/v1/"
echo "Note: Run run_sdk.py for the same result via the Python SDK."
