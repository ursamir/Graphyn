#!/usr/bin/env bash
# CI smoke: empty-env install + deps gate + import + focused pytest + templates.
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

# Core isolation suite (no plugin install required)
export GRAPHYN_SKIP_PLUGIN_LOAD=1
"$VENV/bin/pytest" --collect-only -q
"$VENV/bin/pytest" -q \
  unit_test/core/test_conditions.py \
  unit_test/models/test_audio_sample.py \
  unit_test/test_suite_bootstrap.py \
  unit_test/core/plugins/test_manifest.py \
  unit_test/core/test_secret_policy.py \
  unit_test/core/test_http_egress.py \
  unit_test/core/test_schedules.py \
  --maxfail=5

# Plugin registry smoke (requires load; auto-install declared plugin deps)
unset GRAPHYN_SKIP_PLUGIN_LOAD || true
export GRAPHYN_PLUGIN_AUTO_INSTALL=1
"$VENV/bin/pytest" -q \
  unit_test/plugins/audio/test_all_audio_plugins.py \
  unit_test/plugins/common/test_all_common_plugins.py \
  --maxfail=5

"$VENV/bin/python" scripts/verify_templates.py
echo "ci_smoke: OK"
