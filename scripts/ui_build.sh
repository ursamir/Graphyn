#!/usr/bin/env bash
# Build the Graphyn console (graphyn-ui).
# Usage (from repo root): bash scripts/ui_build.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UI_DIR="$ROOT/graphyn-ui"
cd "$UI_DIR"
npm ci
npm run build
echo "ui_build: OK → $UI_DIR/dist"
