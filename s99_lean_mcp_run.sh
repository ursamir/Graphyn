#!/usr/bin/env bash
set -euo pipefail
cd /home/meritech/Desktop/newAudio3

set -a
source .env
set +a


# Fresh lean home
rm -rf .graphyn-mcp-lean
mkdir -p .graphyn-mcp-lean docs/_gen workspace

export GRAPHYN_TIP="$(git rev-parse --short HEAD)"
export GRAPHYN_HOME="$(pwd)/.graphyn-mcp-lean"
unset GRAPHYN_PLUGINS_DIR || true
export GRAPHYN_PROJECT_DIR="$(pwd)/.graphyn-mcp-lean/workspace"
mkdir -p "$GRAPHYN_PROJECT_DIR"
export GRAPHYN_AUTO_INSTALL_PLUGINS=0
export GRAPHYN_ISOLATED_BOOT_HEAVY=0
export GRAPHYN_SKIP_PLUGIN_LOAD=0
export GRAPHYN_SMTP_DRY_RUN=1
export GRAPHYN_ENV=development
export GRAPHYN_SELFTEST_PROJECT=mcp-agentic-selftest
export GRAPHYN_SELFTEST_PLUGIN_SRC="$(pwd)/plugins/_agent_selftest_echo"
export GRAPHYN_SELFTEST_OUT="$(pwd)/docs/_gen/MCP_AGENTIC_SELFTEST.md"

mkdir -p "$GRAPHYN_PROJECT_DIR/projects/mcp-agentic-selftest"
# ensure local project dir for MCP save_pipeline (API project is separate)
echo "Bootstrap lean plugins..."
./venv/bin/python s99_bootstrap_lean.py

curl -sS -o /tmp/proj.json -w "create_project_http=%{http_code}\n" \
  -X POST "http://127.0.0.1:8001/api/v1/projects" \
  -H "Authorization: Bearer ${GRAPHYN_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: mcp-agentic-selftest-v1" \
  -d '{"name":"mcp-agentic-selftest","description":"MCP agentic selftest"}' || true

./venv/bin/python -c 'from mcp import ClientSession; from mcp.client.stdio import stdio_client; print("host_mcp_client_ok")'

# MCP child must load the lean installed plugins (SKIP_PLUGIN_LOAD=0) but never mass-install
export GRAPHYN_SKIP_PLUGIN_LOAD=0
timeout 180 ./venv/bin/python mcp_agentic_selftest.py
echo "REPORT_LINES=$(wc -l < docs/_gen/MCP_AGENTIC_SELFTEST.md)"
./venv/bin/python - <<'PY'
import json
from pathlib import Path
p=Path('docs/_gen/MCP_AGENTIC_SELFTEST.json')
data=json.loads(p.read_text()) if p.exists() else []
ok=sum(1 for x in data if x.get('ok'))
fail=[x for x in data if not x.get('ok')]
print(f'SUMMARY calls={len(data)} ok={ok} fail={len(fail)}')
for x in fail[:30]:
    print('FAIL', x.get('tool'), x.get('error'), str(x.get('outcome'))[:200])
for x in data:
    if x.get('tool')=='list_tools':
        print('TOOLS', (x.get('outcome') or {}).get('count'))
    if x.get('tool')=='execute_pipeline' and isinstance(x.get('outcome'), dict):
        print('RUN', x['outcome'].get('run_id'), x['outcome'].get('status'))
    if x.get('tool')=='install_plugin':
        print('PLUGIN_INSTALL', x.get('ok'), str(x.get('outcome'))[:300])
PY
head -120 docs/_gen/MCP_AGENTIC_SELFTEST.md
du -sh .graphyn-mcp-lean
df -h / | tail -1
