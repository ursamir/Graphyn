#!/usr/bin/env bash
set -euo pipefail
cd /home/meritech/Desktop/newAudio3

set -a
# shellcheck disable=SC1091
source .env
set +a

export GRAPHYN_TIP
GRAPHYN_TIP="$(git rev-parse --short HEAD)"
export GRAPHYN_SELFTEST_OUT="/home/meritech/Desktop/newAudio3/docs/_gen/MCP_AGENTIC_SELFTEST.md"
export GRAPHYN_SELFTEST_PLUGIN_SRC="/app/plugins/_agent_selftest_echo"
export GRAPHYN_SELFTEST_PROJECT="mcp-agentic-selftest"
mkdir -p docs/_gen

echo "== tip ${GRAPHYN_TIP} =="
ls -la plugins/_agent_selftest_echo/plugin.toml

# Ensure project exists on live API (MCP save_pipeline requires it)
curl -sS -o /tmp/proj.json -w "create_project_http=%{http_code}\n" \
  -X POST "http://127.0.0.1:8001/api/v1/projects" \
  -H "Authorization: Bearer ${GRAPHYN_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: mcp-agentic-selftest-v1" \
  -d '{"name":"mcp-agentic-selftest","description":"MCP agentic selftest project"}' || true
head -c 300 /tmp/proj.json; echo

docker cp mcp_agentic_selftest.py graphyn-api:/tmp/mcp_agentic_selftest.py

# Confirm MCP SDK import
docker exec graphyn-api python -c 'from mcp import ClientSession; from mcp.client.stdio import stdio_client; print("mcp_client_ok")'

docker exec \
  -e GRAPHYN_API_TOKEN \
  -e GRAPHYN_TIP \
  -e GRAPHYN_SELFTEST_OUT=/tmp/MCP_AGENTIC_SELFTEST.md \
  -e GRAPHYN_SELFTEST_PLUGIN_SRC \
  -e GRAPHYN_SELFTEST_PROJECT \
  -e GRAPHYN_AUTH_REQUIRED \
  -e GRAPHYN_ENV \
  -e GRAPHYN_HOME \
  -e GRAPHYN_PLUGINS_DIR \
  -e GRAPHYN_PROJECT_DIR \
  -e GRAPHYN_SMTP_DRY_RUN \
  -e OLLAMA_BASE_URL \
  -e OLLAMA_MODEL \
  graphyn-api \
  python /tmp/mcp_agentic_selftest.py

docker cp graphyn-api:/tmp/MCP_AGENTIC_SELFTEST.md docs/_gen/MCP_AGENTIC_SELFTEST.md
docker cp graphyn-api:/tmp/MCP_AGENTIC_SELFTEST.json docs/_gen/MCP_AGENTIC_SELFTEST.json 2>/dev/null || true
echo "REPORT_LINES=$(wc -l < docs/_gen/MCP_AGENTIC_SELFTEST.md)"
head -60 docs/_gen/MCP_AGENTIC_SELFTEST.md
