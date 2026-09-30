#!/usr/bin/env bash
set -euo pipefail
cd /home/meritech/Desktop/newAudio3
set -a
source .env
set +a
GRAPHYN_TIP="$(git rev-parse --short HEAD)"
export GRAPHYN_TIP
PROJECT=mcp-agentic-selftest

# kill any leftover via helper
docker cp /tmp/s99_kill_mcp.py graphyn-api:/tmp/s99_kill_mcp.py || true
docker exec graphyn-api python /tmp/s99_kill_mcp.py || true

curl -sS -o /tmp/proj.json -w "create_project_http=%{http_code}\n" \
  -X POST "http://127.0.0.1:8001/api/v1/projects" \
  -H "Authorization: Bearer ${GRAPHYN_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: mcp-agentic-selftest-v1" \
  -d "{\"name\":\"${PROJECT}\",\"description\":\"MCP agentic selftest project\"}" || true

docker cp mcp_agentic_selftest.py graphyn-api:/tmp/mcp_agentic_selftest.py

# Critical: same GRAPHYN_HOME as API, NO auto-install of all PluginPackage
docker exec \
  -e GRAPHYN_API_TOKEN \
  -e GRAPHYN_TIP \
  -e GRAPHYN_SELFTEST_OUT=/tmp/MCP_AGENTIC_SELFTEST.md \
  -e GRAPHYN_SELFTEST_PLUGIN_SRC=/app/plugins/_agent_selftest_echo \
  -e GRAPHYN_SELFTEST_PROJECT="${PROJECT}" \
  -e GRAPHYN_AUTH_REQUIRED \
  -e GRAPHYN_ENV \
  -e GRAPHYN_HOME=/data/graphyn-home \
  -e GRAPHYN_PLUGINS_DIR \
  -e GRAPHYN_PROJECT_DIR \
  -e GRAPHYN_SMTP_DRY_RUN=1 \
  -e GRAPHYN_AUTO_INSTALL_PLUGINS=0 \
  -e GRAPHYN_ISOLATED_BOOT_HEAVY=0 \
  -e OLLAMA_BASE_URL \
  -e OLLAMA_MODEL \
  graphyn-api \
  python /tmp/mcp_agentic_selftest.py

docker cp graphyn-api:/tmp/MCP_AGENTIC_SELFTEST.md docs/_gen/MCP_AGENTIC_SELFTEST.md
docker cp graphyn-api:/tmp/MCP_AGENTIC_SELFTEST.json docs/_gen/MCP_AGENTIC_SELFTEST.json || true
wc -l docs/_gen/MCP_AGENTIC_SELFTEST.md
head -80 docs/_gen/MCP_AGENTIC_SELFTEST.md
