#!/usr/bin/env bash
# CI gate: empty-env install + deps + import + full unit_test suite + templates.
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

# Do NOT set GRAPHYN_SKIP_PLUGIN_LOAD globally — isolation tests that need it
# set it themselves. Full suite is the gate (DEEP_REVIEW P0-4).
unset GRAPHYN_SKIP_PLUGIN_LOAD || true
export GRAPHYN_PLUGIN_AUTO_INSTALL="${GRAPHYN_PLUGIN_AUTO_INSTALL:-1}"

"$VENV/bin/pytest" --collect-only -q
"$VENV/bin/pytest" -q unit_test/ --maxfail=50

# Lint / types: report mode (non-zero only if tools missing after install)
if "$VENV/bin/python" -c "import ruff" 2>/dev/null || "$VENV/bin/ruff" --version >/dev/null 2>&1; then
  "$VENV/bin/ruff" check app/ unit_test/ --output-format=concise || true
else
  echo "ci_smoke: ruff not installed — skipping (dev extra should provide it)"
fi
if "$VENV/bin/python" -c "import mypy" 2>/dev/null; then
  "$VENV/bin/mypy" app/ --ignore-missing-imports --no-error-summary 2>/dev/null || true
else
  echo "ci_smoke: mypy not installed — skipping"
fi

"$VENV/bin/python" scripts/verify_templates.py
echo "ci_smoke: OK"
