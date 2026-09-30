#!/usr/bin/env bash
set -euo pipefail
pkill -9 -f s99_lean_mcp_run.sh || true
pkill -9 -f mcp_agentic_selftest || true
pkill -9 -f 'python -m app.mcp.server' || true
pkill -9 -f 'app.cli.main plugin' || true
sleep 1
# trash lean home if huge
cd /home/meritech/Desktop/newAudio3
if [ -d .graphyn-mcp-lean ]; then
  mv .graphyn-mcp-lean .graphyn-mcp-lean.trash.$$ || true
  rm -rf .graphyn-mcp-lean.trash.$$ &
fi
df -h / | tail -1
ps aux | grep -E 'mcp_agentic|app.mcp|lean_mcp' | grep -v grep || echo stopped
