#!/usr/bin/env bash
# Example 06 — Phase 1: Data Preprocessing (CLI version)
# One run processes all six command labels (recursive ingest of
# workspace/datasets/input/speech-commands; the label is the folder name).
# Dataset versions are immutable: every run writes the next free version
# (v1, v2, …) under workspace/datasets/output/audio_export/. Phase 2
# (pipeline_train_ml.graph.json) reads audio_export/latest, which
# dataset_ingest resolves to the newest version.
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo "$(dirname "$0")/../..")"

GRAPH=examples/06_speech_commands_e2e/pipeline_preprocess.graph.json

if [ ! -d workspace/datasets/input/speech-commands/yes ]; then
    echo "Missing workspace/datasets/input/speech-commands/{yes,no,up,down,go,stop}."
    echo "Run first: venv/bin/python examples/prepare_real_data.py"
    exit 1
fi

echo "============================================================"
echo "Example 06 — Phase 1: Data Preprocessing (all six labels)"
echo "============================================================"
venv/bin/python -m app.cli.main validate --graph "$GRAPH"
venv/bin/python -m app.cli.main run --graph "$GRAPH"

echo "============================================================"
echo "Phase 1 complete!"
echo "Dataset: newest version under workspace/datasets/output/audio_export/ ({train,val,test}/<label>/)"
echo ""
echo "Next step: bash examples/06_speech_commands_e2e/run_train_ml.sh"
echo "============================================================"
