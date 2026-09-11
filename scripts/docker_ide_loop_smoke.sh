#!/usr/bin/env bash
# Prove the Graphyn IDE loop against a running Docker (or local) API:
#   auth honesty → nodes → project → pipeline save → validate → run → Trace
#
# Usage (never prints the token):
#   export GRAPHYN_API_TOKEN=…   # same token as compose
#   ./scripts/docker_ide_loop_smoke.sh
#   GRAPHYN_BASE_URL=http://127.0.0.1:5173 ./scripts/docker_ide_loop_smoke.sh  # via UI nginx proxy
#
# Exit 0 = loop OK. Does not echo secrets.
set -euo pipefail

BASE="${GRAPHYN_BASE_URL:-http://127.0.0.1:8001}"
BASE="${BASE%/}"

# Prefer Compose .env file (ignore a mismatched shell export).
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
TOKEN="$(printf '%s' "${GRAPHYN_API_TOKEN:-}" | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
PROJECT="${GRAPHYN_SMOKE_PROJECT:-docker_smoke}"
PIPELINE="${GRAPHYN_SMOKE_PIPELINE:-hello}"

if [[ -z "${TOKEN}" ]]; then
  echo "FAIL: set GRAPHYN_API_TOKEN (same value as docker compose)." >&2
  exit 1
fi
echo "token_len=${#TOKEN}"

# Avoid bash array + curl header quirks on some hosts.
api() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  if [[ -n "${body}" ]]; then
    curl -sS -f -X "${method}" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json" \
      -H "X-Actor: docker-smoke" \
      -d "${body}" \
      "${BASE}${path}"
  else
    curl -sS -f -X "${method}" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json" \
      -H "X-Actor: docker-smoke" \
      "${BASE}${path}"
  fi
}

echo "== 1) Public auth-status (no Bearer) =="
AUTH_JSON="$(curl -sS -f "${BASE}/api/v1/system/auth-status")"
echo "${AUTH_JSON}" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert "auth_required" in d and "token_configured" in d, d; print("auth_required=", d.get("auth_required"), "token_configured=", d.get("token_configured"), "ok=", d.get("ok"))'

echo "== 2) Mode honesty (readiness, no Bearer) =="
READY="$(curl -sS -f "${BASE}/api/v1/system/readiness")"
echo "${READY}" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("backend_mode=", d.get("backend_mode"), "backend=", d.get("backend"))'

echo "== 3) Nodes catalog (Bearer) =="
NODES="$(api GET /api/v1/nodes)"
echo "${NODES}" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert isinstance(d,list) and len(d)>0, d; print("nodes=", len(d))'

echo "== 4) Project create/open =="
# create may 409 if exists — ignore
PROJ_CODE="$(curl -sS -o /tmp/graphyn_smoke_proj.json -w "%{http_code}" -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -H "X-Actor: docker-smoke" \
  -d "{\"name\":\"${PROJECT}\"}" "${BASE}/api/v1/projects" || true)"
if [[ "${PROJ_CODE}" != "200" && "${PROJ_CODE}" != "201" && "${PROJ_CODE}" != "409" && "${PROJ_CODE}" != "400" ]]; then
  echo "WARN: project create HTTP ${PROJ_CODE} (continuing if project exists)" >&2
fi
api GET "/api/v1/projects" | python3 -c "import json,sys; d=json.load(sys.stdin); names=[(p.get('name') if isinstance(p,dict) else p) for p in (d if isinstance(d,list) else d.get('projects',[]))]; assert '${PROJECT}' in names, names; print('project ok')"

GRAPH="$(python3 - <<'PY'
import json
print(json.dumps({
  "schema_version": "1.0",
  "metadata": {"name": "docker_smoke_hello", "seed": 1},
  "nodes": [{
    "id": "set_0",
    "node_type": "set_map",
    "config": {"set": {"hello": "docker", "smoke": True}},
  }],
  "edges": [],
}))
PY
)"

echo "== 5) Save project pipeline =="
api PUT "/api/v1/projects/${PROJECT}/pipelines/${PIPELINE}" "${GRAPH}" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("saved", d.get("name") or d.get("pipeline") or "ok")'

echo "== 6) Validate =="
api POST /api/v1/pipelines/validate "${GRAPH}" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("valid") is True or d.get("ok") is True or "errors" not in d or not d.get("errors"), d; print("valid ok")'

echo "== 7) Run-async =="
RUN_JSON="$(api POST /api/v1/pipelines/run-async "{\"graph\": ${GRAPH}, \"project\": \"${PROJECT}\"}")"
RUN_ID="$(echo "${RUN_JSON}" | python3 -c 'import json,sys; d=json.load(sys.stdin); rid=d.get("run_id"); assert rid, d; print(rid)')"
echo "run_id=${RUN_ID}"

echo "== 8) Poll status =="
STATUS="unknown"
for _ in $(seq 1 60); do
  ST="$(api GET "/api/v1/runs/${RUN_ID}/status" || true)"
  STATUS="$(echo "${ST}" | python3 -c 'import json,sys; 
try:
 d=json.load(sys.stdin); print(str(d.get("status") or "unknown").lower())
except Exception:
 print("unknown")' 2>/dev/null || echo unknown)"
  echo "  status=${STATUS}"
  case "${STATUS}" in
    completed|failed|cancelled|success|error) break ;;
  esac
  sleep 1
done
if [[ "${STATUS}" != "completed" && "${STATUS}" != "success" ]]; then
  echo "FAIL: run did not complete (status=${STATUS})" >&2
  api GET "/api/v1/runs/${RUN_ID}" >/tmp/graphyn_smoke_run.json || true
  python3 -c 'import json; print(json.load(open("/tmp/graphyn_smoke_run.json")) )' 2>/dev/null | head -c 2000 >&2 || true
  exit 1
fi

echo "== 9) Trace backtrack =="
api GET "/api/v1/trace?run_id=${RUN_ID}" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("run") or d.get("subject") or d.get("chain"), d; print("trace ok keys=", sorted(d.keys())[:8])'

echo "== 10) Run detail =="
api GET "/api/v1/runs/${RUN_ID}" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("run status=", (d.get("meta") or d).get("status") if isinstance(d.get("meta"), dict) else d.get("status"))'

echo "PASS: Docker/Server IDE loop (project → pipeline → run → Trace)"
