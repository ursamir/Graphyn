#!/usr/bin/env bash
# Mode B one-shot health: control health + workers list.
# LOCAL only. Does not start workers or tunnels.
set -euo pipefail
CONTROL_URL="${GRAPHYN_CONTROL_URL:-http://127.0.0.1:18001/api/v1}"
TOKEN="${GRAPHYN_API_TOKEN:-}"
AUTH=()
if [[ -n "$TOKEN" ]]; then
  AUTH=(-H "Authorization: Bearer ${TOKEN}")
fi

echo "== Mode B health =="
echo "control: $CONTROL_URL"
echo

code_health=$(curl -sS -o /tmp/graphyn_modeb_health.json -w "%{http_code}" \
  "${AUTH[@]}" "${CONTROL_URL}/system/health" || true)
echo "GET /system/health -> HTTP ${code_health}"
python3 - <<'PY' || true
import json
try:
    d=json.load(open("/tmp/graphyn_modeb_health.json"))
    print("  status:", d.get("status") or d)
except Exception as e:
    print("  (unreadable body)", e)
PY

code_ready=$(curl -sS -o /tmp/graphyn_modeb_ready.json -w "%{http_code}" \
  "${AUTH[@]}" "${CONTROL_URL}/system/readiness" || true)
echo "GET /system/readiness -> HTTP ${code_ready}"
python3 - <<'PY' || true
import json
try:
    d=json.load(open("/tmp/graphyn_modeb_ready.json"))
    print("  ready:", d.get("ready"))
    for k in ("store_corrupt", "disk_full", "draining"):
        if k in d:
            print(f"  {k}:", d.get(k))
except Exception as e:
    print("  (unreadable body)", e)
PY

code_w=$(curl -sS -o /tmp/graphyn_modeb_workers.json -w "%{http_code}" \
  "${AUTH[@]}" "${CONTROL_URL}/workers" || true)
echo "GET /workers -> HTTP ${code_w}"
python3 - <<'PY' || true
import json
try:
    d=json.load(open("/tmp/graphyn_modeb_workers.json"))
    items = d.get("items") if isinstance(d, dict) else d
    if isinstance(d, dict) and "items" not in d and isinstance(d.get("workers"), list):
        items = d["workers"]
    if not isinstance(items, list):
        items = []
    print(f"  workers: {len(items)}")
    for w in items[:12]:
        if isinstance(w, dict):
            wid = w.get("worker_id") or w.get("id")
            print(f"   - {wid} labels={w.get('labels')} pool={w.get('pool')} status={w.get('status')}")
        else:
            print("   -", w)
    if not items:
        print("  (none registered — start a lean worker; see docs/_gen/MODE_B_OPERATE.md)")
except Exception as e:
    print("  (unreadable body)", e)
PY

ok=1
[[ "$code_health" == "200" ]] || ok=0
[[ "$code_ready" == "200" ]] || ok=0
if [[ "$ok" -eq 1 ]]; then
  echo
  echo "Mode B control plane: OK (workers may still be empty)"
  exit 0
fi
echo
echo "Mode B control plane: DEGRADED"
exit 1
