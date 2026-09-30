#!/usr/bin/env bash
set -euo pipefail
cd /home/meritech/Desktop/newAudio3

set -a
source .env
set +a

GRAPHYN_TIP="$(git rev-parse --short HEAD)"
export GRAPHYN_TIP
export GRAPHYN_SELFTEST_PROJECT=mcp-agentic-selftest
export GRAPHYN_SELFTEST_PLUGIN_SRC="$(pwd)/plugins/_agent_selftest_echo"
export GRAPHYN_SELFTEST_OUT="$(pwd)/docs/_gen/MCP_AGENTIC_SELFTEST.md"
export GRAPHYN_AUTO_INSTALL_PLUGINS=0
export GRAPHYN_ISOLATED_BOOT_HEAVY=0
export GRAPHYN_SMTP_DRY_RUN=1
export GRAPHYN_HOME="$(pwd)/.graphyn-mcp-agentic"
export GRAPHYN_PLUGINS_DIR="$(pwd)/plugins"
mkdir -p "$GRAPHYN_HOME"
if [ -d "$(pwd)/workspace" ]; then
  export GRAPHYN_PROJECT_DIR="$(pwd)/workspace"
fi

echo "Seeding plugin store from live graphyn-api GRAPHYN_HOME..."
# Copy installed plugin records + any existing venvs refs (not full reinstall)
docker cp graphyn-api:/data/graphyn-home/plugins "$GRAPHYN_HOME/" 2>/dev/null || true
# Ensure our selftest plugin source is present on bind mount
test -f plugins/_agent_selftest_echo/plugin.toml

echo "GRAPHYN_HOME=$GRAPHYN_HOME tip=$GRAPHYN_TIP"

curl -sS -o /tmp/proj.json -w "create_project_http=%{http_code}\n" \
  -X POST "http://127.0.0.1:8001/api/v1/projects" \
  -H "Authorization: Bearer ${GRAPHYN_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: mcp-agentic-selftest-v1" \
  -d '{"name":"mcp-agentic-selftest","description":"MCP agentic selftest project"}' || true

./venv/bin/python -c 'from mcp import ClientSession; from mcp.client.stdio import stdio_client; print("host_mcp_client_ok")'

# Run with a timeout so a plugin storm cannot hang forever
timeout 240 ./venv/bin/python mcp_agentic_selftest.py
echo "REPORT_LINES=$(wc -l < docs/_gen/MCP_AGENTIC_SELFTEST.md)"
head -150 docs/_gen/MCP_AGENTIC_SELFTEST.md
