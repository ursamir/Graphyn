#!/usr/bin/env bash
# Generate Mode B lab mTLS material: CA, control server cert, worker client certs.
#
# Usage:
#   ./scripts/gen_modeb_mtls_certs.sh [outdir] [worker_id ...]
#
# Defaults: outdir=./certs/modeb  worker_ids=s99-ml
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/certs/modeb}"
if [[ $# -gt 0 ]]; then shift; fi
WORKERS=("$@")
if [[ ${#WORKERS[@]} -eq 0 ]]; then
  WORKERS=(s99-ml)
fi
cd "$ROOT"
export GRAPHYN_MTLS_GEN_OUT="$OUT"
export GRAPHYN_MTLS_GEN_WORKERS="$(IFS=,; echo "${WORKERS[*]}")"
python3 - <<'PY'
import os
from app.core.distributed.mtls import generate_modeb_mtls_certs
out = os.environ["GRAPHYN_MTLS_GEN_OUT"]
workers = [w for w in os.environ.get("GRAPHYN_MTLS_GEN_WORKERS", "s99-ml").split(",") if w.strip()]
paths = generate_modeb_mtls_certs(out, worker_ids=workers)
print("Wrote:")
for k, v in sorted(paths.items()):
    print(f"  {k}: {v}")
print()
print("Enable:")
print(f"  export GRAPHYN_MTLS_ENABLED=1")
print(f"  export GRAPHYN_MTLS_CA_CERT={paths['ca_cert']}")
print(f"  export GRAPHYN_MTLS_CERT={paths['control_cert']}")
print(f"  export GRAPHYN_MTLS_KEY={paths['control_key']}")
wid = workers[0]
print(f"  export GRAPHYN_MTLS_CLIENT_CERT={paths[f'worker:{wid}:cert']}")
print(f"  export GRAPHYN_MTLS_CLIENT_KEY={paths[f'worker:{wid}:key']}")
print(f"  export GRAPHYN_CONTROL_URL=https://graphyn-api:8001/api/v1")
print("API: python -m app.api.mtls_serve")
PY
