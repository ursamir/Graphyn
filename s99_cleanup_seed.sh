#!/usr/bin/env bash
set -euo pipefail
pkill -f s99_host_mcp_run.sh || true
pkill -f s99_lean_mcp_run.sh || true
pkill -f mcp_agentic_selftest || true
pkill -f 'python -m app.mcp.server' || true
sleep 1
rm -rf /home/meritech/Desktop/newAudio3/.graphyn-mcp-agentic
echo removed_home
df -h / | tail -1
