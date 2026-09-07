#!/usr/bin/env bash
# Lightweight CI smoke: empty-env install + import + targeted pytest.
# Usage (from repo root): bash scripts/ci_smoke.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VENV="${GRAPHYN_CI_VENV:-/tmp/graphyn-ci-venv}"
rm -rf "$VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install -U pip
"$VENV/bin/pip" install -e ".[dev]"
"$VENV/bin/python" scripts/check_deps.py --inventory
"$VENV/bin/python" scripts/_import_smoke.py
export GRAPHYN_SKIP_PLUGIN_LOAD=1
"$VENV/bin/pytest" --collect-only -q
"$VENV/bin/pytest" -q \
  unit_test/core/test_conditions.py \
  unit_test/models/test_audio_sample.py \
  unit_test/test_suite_bootstrap.py \
  unit_test/core/plugins/test_manifest.py \
  --maxfail=5
echo "ci_smoke: OK"
