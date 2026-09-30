#!/usr/bin/env bash
set -x
# kill anything touching the home
pkill -9 -f s99_host_mcp_run.sh || true
pkill -9 -f s99_lean_mcp_run.sh || true
pkill -9 -f mcp_agentic_selftest || true
pkill -9 -f 'python -m app.mcp.server' || true
pkill -9 -f 'docker cp graphyn-api:/data/graphyn-home/plugins' || true
sleep 1
# rename then delete to avoid races
HOME_DIR=/home/meritech/Desktop/newAudio3/.graphyn-mcp-agentic
if [ -e "$HOME_DIR" ]; then
  mv "$HOME_DIR" "${HOME_DIR}.trash.$$" || true
  rm -rf "${HOME_DIR}.trash.$$" || chmod -R u+w "${HOME_DIR}.trash.$$" 2>/dev/null || true
  rm -rf "${HOME_DIR}.trash.$$" || true
fi
# if still there, find-delete
if [ -e "$HOME_DIR" ] || ls -d ${HOME_DIR}.trash.* >/dev/null 2>&1; then
  find /home/meritech/Desktop/newAudio3 -maxdepth 1 -name '.graphyn-mcp-agentic*' -exec rm -rf {} + || true
fi
df -h / | tail -1
du -sh /home/meritech/Desktop/newAudio3/.graphyn-mcp-agentic* 2>/dev/null || echo cleaned
ps aux | grep -E 'graphyn-mcp|mcp_agentic|docker cp' | grep -v grep || echo no_procs
