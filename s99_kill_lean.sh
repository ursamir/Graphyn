#!/usr/bin/env bash
pkill -9 -f 'app.cli.main plugin install' || true
pkill -9 -f mcp_agentic_selftest || true
pkill -9 -f 'python -m app.mcp.server' || true
pkill -9 -f s99_bootstrap_lean || true
sleep 1
cd /home/meritech/Desktop/newAudio3
# trash old homes in background
for d in .graphyn-mcp-lean .graphyn-mcp-agentic; do
  if [ -d "$d" ]; then
    mv "$d" "$d.trash.$$" 2>/dev/null || true
  fi
done
nohup bash -c 'rm -rf /home/meritech/Desktop/newAudio3/.graphyn-mcp-*.trash.*' >/tmp/rm_lean_trash.log 2>&1 &
df -h / | tail -1
ps aux | grep -E 'plugin install|mcp_agentic|app.mcp' | grep -v grep || echo stopped
