#!/usr/bin/env bash
set -euo pipefail
cd /home/meritech/Desktop/newAudio3

# Install only missing MCP deps without upgrading fastapi/starlette/pydantic
docker exec graphyn-api pip install --no-deps 'mcp==1.27.0' 'httpx-sse==0.4.3' 'pydantic-settings==2.15.0' || \
  docker exec graphyn-api pip install 'httpx-sse==0.4.3'

# Verify imports without breaking API
docker exec graphyn-api python -c 'import fastapi,starlette,mcp; from mcp.server.lowlevel import Server; from mcp import ClientSession; print(fastapi.__version__, starlette.__version__, mcp.__version__)'
curl -sS http://127.0.0.1:8001/api/v1/system/health; echo

bash ./s99_run_mcp2.sh
