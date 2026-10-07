# Deployment Guide

Baseline **Docker Compose** deploy for Graphyn API + UI. This repo does **not** ship a Helm chart.

## Auth (fail-closed)

Compose sets `GRAPHYN_ENV=production` and `GRAPHYN_AUTH_REQUIRED=1`. An empty `GRAPHYN_API_TOKEN` is **forbidden**: API and MCP reject every call with 401 / `unauthorized`.

Local CLI/SDK default remains `GRAPHYN_ENV=development` (auth optional).

```bash
export GRAPHYN_API_TOKEN=change-me
```

Put the same token in the UI **Settings** dialog (Bearer) after `docker compose up`.

### Named tokens & audit identity

To make the audit trail attributable, give each person / agent their own token and map it to a name. The single `GRAPHYN_API_TOKEN` keeps working (its callers are recorded as their `X-Actor` header, unverified).

| Variable | Format | Purpose |
|---|---|---|
| `GRAPHYN_API_TOKENS` | JSON object `{"<token>": "<name>", …}` **or** `name:token,name:token` (commas or newlines) | Extra accepted bearer tokens, each bound to an identity name |
| `GRAPHYN_API_TOKENS_FILE` | path to a file in either format (`#` comment lines allowed) | Same, from a file (re-read when its mtime changes — rotate without restart). Env entries win on conflicts |

```bash
export GRAPHYN_API_TOKENS='alice:3f9c…,ci-bot:91ab…'
# or: echo '{"3f9c…": "alice", "91ab…": "ci-bot"}' > /run/secrets/graphyn-tokens.json
#     export GRAPHYN_API_TOKENS_FILE=/run/secrets/graphyn-tokens.json
```

A request with a mapped token is recorded as that name with `actor_verified: true` on every audit event, in run `meta` and in the sealed run record (`prove.json`); an `X-Actor` that differs is stored only as `claimed_actor`. Unmapped token → `X-Actor` or `"unidentified"`, `actor_verified: false`. `"system"` only appears for internal background jobs. `GET /api/v1/me` returns `{actor, actor_verified, token_mapped, claimed_actor, auth_configured, token_map_configured}`; `/system/auth-status` adds `token_map_configured`. Configuring only the map (no `GRAPHYN_API_TOKEN`) also turns auth on and satisfies fail-closed mode. MCP accepts mapped tokens in `_meta.auth_token` too (MCP actor attribution is unchanged).

Unauthenticated dev (token unset): requests whose `Host` is not `localhost` / `*.localhost` / an IP literal / `graphyn-api` get **403** (DNS-rebinding guard). Reaching a tokenless API by LAN hostname needs `GRAPHYN_ALLOWED_HOSTS=gpu-box,…` (or set a token).

Public honesty (no Bearer required): `GET /api/v1/system/auth-status`, `/system/health`, `/system/readiness` — so the console can show **Auth on** / Mode before you paste a token.

## Inbound webhooks (external triggers)

1. Add a `webhook_trigger` node to the pipeline (its `body` / `headers` / `query` outputs feed the rest of the graph), save it and publish the env the hook will run (`prod` by default; `draft` runs the saved head).
2. Enable the hook and create the signing secret (bearer-authenticated):

```bash
API=http://127.0.0.1:8001/api/v1; AUTH="Authorization: Bearer $GRAPHYN_API_TOKEN"
curl -sX PUT  "$API/projects/acme/pipelines/onpush/hook" -H "$AUTH" -H 'Content-Type: application/json' \
     -d '{"enabled": true, "env": "prod", "allowed_envs": ["prod"]}'
SECRET=$(curl -sX POST "$API/projects/acme/pipelines/onpush/hook/rotate" -H "$AUTH" | jq -r .secret)   # shown ONCE
```

3. The sender signs `"<unix timestamp>." + raw body` with HMAC-SHA256:

```bash
BODY='{"event":"push","ref":"main"}'
TS=$(date +%s)
SIG=$(printf '%s.%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -hex | sed 's/^.* //')
curl -sX POST "$API/hooks/acme/onpush" \
     -H 'Content-Type: application/json' \
     -H "X-Graphyn-Timestamp: $TS" \
     -H "X-Graphyn-Signature: sha256=$SIG" \
     -H 'Idempotency-Key: delivery-123' \
     --data-binary "$BODY"
# → 202 {"run_id": "…", "status": "pending", "hook_id": "…", "env": "prod", "idempotent_replay": false}
```

Sign the exact bytes you send (`--data-binary`, no re-serialisation). Systems that cannot sign can send `Authorization: Bearer <token>` instead (prefer a named `GRAPHYN_API_TOKENS` entry such as `github-ci:<token>` so runs are attributed). Rotate with `…/hook/rotate` (old secret stops working immediately); `DELETE …/hook` removes the hook and its secret.

| Env | Default | Meaning |
|---|---|---|
| `GRAPHYN_WEBHOOK_MAX_BYTES` | `1048576` | Max request body (413 above) |
| `GRAPHYN_WEBHOOK_TOLERANCE_S` | `300` | ± timestamp window / replay-cache window |
| `GRAPHYN_WEBHOOK_RATE_BURST` | `10` | Token-bucket capacity per hook |
| `GRAPHYN_WEBHOOK_RATE_PER_MIN` | `60` | Refill rate per hook (429 + `Retry-After` when empty) |
| `GRAPHYN_RUN_INPUTS_MAX_BYTES` | `1048576` | Max `inputs` JSON on `/pipelines/run*` (413 above) |

With no `GRAPHYN_API_TOKEN` set, the DNS-rebinding host guard (TRUST_MODEL §1) answers 403 to senders that use a DNS name — set a token or `GRAPHYN_ALLOWED_HOSTS`. Behind a reverse proxy, forward the raw body unchanged and the client IP (the run meta records `request.client.host`). Rate limit, replay cache and idempotency lock are per API process. The `webhook_trigger` node comes from plugin `webhook-trigger` (`PluginPackage/Common/webhook_trigger`); when `GRAPHYN_BUNDLED_PLUGIN_ALLOWLIST` is set it must list `webhook-trigger` (and `hitl-approve` for approval gates).

## Docker Compose (API :8001 + UI :5173)

```bash
cp .env.example .env    # set GRAPHYN_API_TOKEN
docker compose up --build -d graphyn-api graphyn-ui
```

- UI: `http://localhost:5173` (nginx; `/api`, `/files`, `/input-files`, `/run-files` proxy to the API)
- API: `http://localhost:8001/api/v1/`
- Named volume `graphyn-home` persists `GRAPHYN_HOME` (plugins + `secrets/` files, mode 0600)
- `./workspace` is the project dir (`GRAPHYN_PROJECT_DIR`)
- Pipeline outputs belong in `workspace/artifacts/<name>/runs/<run_id>/` on that bind-mount (not `examples/` inside the image). Successful runs that wrote at least one file into their `runs/<run_id>/` dir also publish `workspace/artifacts/<name>/latest/` (symlink, or a `latest.json` pointer if the host cannot symlink) so later graphs can consume the production alias. A run that produced nothing there (e.g. a preprocess graph exporting into the stable `<name>/dataset/` tree) leaves `latest` unchanged, and its empty run dir is removed (run dirs are no longer pre-created).

**UI-only rebuild (do not touch the API):** recreating `graphyn-api` re-runs plugin install/venv boot and routinely takes **15+ minutes**. For `graphyn-ui` changes only:

```bash
docker compose build graphyn-ui && docker compose up -d --no-deps graphyn-ui
```

### Prove the IDE loop (Server-99 / Docker)

After the stack is healthy, run the smoke script (token is never printed):

```bash
export GRAPHYN_API_TOKEN="$(grep -E '^GRAPHYN_API_TOKEN=' .env | cut -d= -f2-)"
chmod +x scripts/docker_ide_loop_smoke.sh
./scripts/docker_ide_loop_smoke.sh
# or via UI proxy:
# GRAPHYN_BASE_URL=http://127.0.0.1:5173 ./scripts/docker_ide_loop_smoke.sh
```

Covers: public auth/mode → nodes (paginated `{items,total}`) → project
(paginated `items`; create may return 422 if the project already exists) →
pipeline PUT → validate → run-async → poll until `succeeded`/`completed` → Trace.

Stop:

```bash
docker compose down
```

## Python dependency install (image)

The API image installs via **one path** (see `Dockerfile`):

1. `pip install -r requirements.txt` — deploy pins for the default runtime set
2. `pip install -e . --no-deps` — package metadata; deps already satisfied by step 1

**Source of truth for package *names*:** `setup.py` `install_requires`. Optional Redis / MCP / TF / HF / webrtcvad are extras (`pip install -e ".[redis,mcp,...]"`) and are **not** baked into the default image. Validate sync with `python scripts/check_deps.py`.

## Build provenance in run records (git commit / image)

The image has no `.git`, so sealed run records (`prove.json` → `environment`) take the commit and image from build args baked into `/app/BUILD_INFO.json` and the `GRAPHYN_GIT_SHA` / `GRAPHYN_IMAGE` env:

```bash
GRAPHYN_GIT_SHA=$(git rev-parse HEAD) GRAPHYN_IMAGE=graphyn-api:$(git rev-parse --short HEAD) \
  docker compose build graphyn-api
# optional, at run time (e.g. from `docker inspect --format '{{.Id}}' <image>`):
GRAPHYN_IMAGE_DIGEST=sha256:… docker compose up -d graphyn-api
```

Defaults: `GRAPHYN_IMAGE=graphyn-api:local`, empty commit (record shows no git). Lookup order for the commit: env `GRAPHYN_GIT_SHA` → `BUILD_INFO.json` (`/app`, repo root, or `GRAPHYN_BUILD_INFO`) → `.git`. Container detection (`/.dockerenv`, cgroup, mountinfo) works without any env; without an image name the record shows `docker container <id> (image not recorded)`.

## Credentials & env bootstrap for live providers

Do **not** put API keys in Graph IR. Prefer **Admin → Credentials** (connection ids on nodes).
Env / named-file bootstrap remains for ops (no second console page) — see `docs/ops/CREDENTIAL_STORE.md`.

```bash
# preferred: create a connection via console or POST /api/v1/credentials
# ops bootstrap (GRAPHYN_HOME matching the API volume):
export OPENAI_API_KEY=sk-...
echo "$OPENAI_API_KEY" | python -m app.cli.main secrets set OPENAI_API_KEY   # optional durable file
python -m app.cli.main secrets list   # names only — never values
```

REST product surface: `/api/v1/credentials` (Bearer). Legacy `/api/v1/secrets` is removed.

## GPU Safety Notes

Default `docker-compose.yml` is **CPU-safe**: it does not request NVIDIA devices, so Graphyn cannot steal VRAM from other host apps (e.g. FaceRecognition on an RTX 3070 Ti). Isolated trainer workers will use CPU in that setup.

To let `graphyn-api` *see* the GPU **without** killing or resetting other CUDA processes:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d graphyn-api
```

That overlay sets `gpus: all` and `NVIDIA_VISIBLE_DEVICES=all` on **graphyn-api only**. It does not bake TensorFlow/CUDA into the API image (TF stays in isolated plugin venvs).

Sharing policy (so Graphyn does not grab 100% of the card):

- `GRAPHYN_TF_DEVICE=auto|cpu|gpu` (default `auto`)
- `GRAPHYN_TF_GPU_MIN_FREE_MIB=4096` — if `nvidia-smi` reports less free VRAM than this, Keras stays on `/CPU:0`
- TF memory growth is on (`TF_FORCE_GPU_ALLOW_GROWTH`); Graphyn must not full-preallocate VRAM
- `GRAPHYN_TF_FORCE_GPU=1` only overrides the compute-capability ≥12 CPU fallback; it does **not** bypass the free-VRAM gate
- `CUDA_VISIBLE_DEVICES=-1` is set only when `GRAPHYN_TF_DEVICE=cpu`

Trainer/evaluator still retry on GPU OOM by rebuilding on CPU. Do not run `nvidia-smi -r` or kill FaceRecognition.

## Runtime extras (speech_enhancer)

The default **spectral** backend for podcast-leveling uses `scipy` and `noisereduce` (3.x). Those packages are in `setup.py` `install_requires` and mirrored in `requirements.txt`, so the Compose image installs them via the Dockerfile install path above. **Do not** add `torch` or `deepfilternet` to the base image; they remain optional for the DeepFilterNet backend.

## Isolated plugin venvs (trainer / edge-optimizer)

TensorFlow and Keras are **not** in the API image. Isolated plugins install them into per-plugin venvs under `GRAPHYN_HOME` (`/data/graphyn-home/plugins/venvs/<name>/`). Existing volumes that predate this need a one-liner:

```bash
docker exec graphyn-api /data/graphyn-home/plugins/venvs/trainer/bin/pip install 'tensorflow>=2.13' 'keras>=3.0'
```

(Optionally the same for `edge-optimizer` if TFLite conversion fails with `ModuleNotFoundError`.)

## Distributed workers (second host)

First-run Mode A vs Mode B: [GETTING_STARTED.md](./GETTING_STARTED.md). This section is Compose/host deploy notes only.

Default Compose is single-machine `LocalPythonBackend`. For multi-machine placement:

1. On the control / API host: `GRAPHYN_BACKEND=distributed` (and the usual auth vars).
2. On a GPU / edge worker host: same Graphyn version + plugins, then:

```bash
export GRAPHYN_CONTROL_URL=http://<control-host>:8001/api/v1
export GRAPHYN_WORKER_TOKEN=change-me   # worker-scoped token bound to this worker id
venv/bin/python -m app.cli.main worker start \
  --control-url "$GRAPHYN_CONTROL_URL" \
  --worker-id server99-gpu --labels gpu --pool gpu-lab
```

Full runbook, env vars, cancel/lease, and UI (**Deploy → Workers**): [DISTRIBUTED_EXECUTION.md](./DISTRIBUTED_EXECUTION.md). Upgrade the control plane and every worker **together** — the job/worker models reject unknown fields (`extra="forbid"`).

## Environment reference — security & Mode B (2026-09 additions)

| Variable | Default | Where | Purpose |
|---|---|---|---|
| `GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS` | unset in the process; Compose `1` | `app/api/routers/data.py` | When unset, input-label symlinks that resolve outside `datasets/input` are listed as `accessible: false` and cannot be browsed. Compose defaults to `1` so the bundled `examples/` dataset links work. Set `0` to fail closed. |
| `GRAPHYN_UPLOAD_MAX_BYTES` / `GRAPHYN_UPLOAD_MAX_FILES` / `GRAPHYN_UPLOAD_MAX_EXTRACT_BYTES` / `GRAPHYN_UPLOAD_MAX_ARCHIVE_FILES` | 100 MB / 1000 / 2 GiB / 20000 | `app/core/mlops/dataset_inputs.py` | Caps for `POST /data/inputs/upload` (per request; archive members unpacked; exceeding one → 413 and the request is rolled back). Reported by `GET /data/capabilities`. The UI batches uploads under these caps. HuggingFace import additionally needs the `hf` extra (`datasets`) — not in the default image, so the console hides it. |
| `GRAPHYN_BUNDLED_PLUGIN_ALLOWLIST` | unset | `app/core/config.py` | Comma-separated plugin slugs startup may install. Branch `test/example-06-plugins` sets Example 06 plus `deployment-packager` and `python-code`, plus the restored workflow-automation plugins (see `docs/PLUGIN_GUIDE.md`), and Compose sets `GRAPHYN_AUTO_INSTALL_PLUGINS=0` so a restart does not restore removed plugins. |
| `GRAPHYN_ISOLATED_DETERMINISTIC` | on | `app/core/config.py`, `app/core/plugins/isolated_executor.py`, `worker.py` | Isolated plugin workers run with `PYTHONHASHSEED=<node seed>`, `TF_DETERMINISTIC_OPS=1`, `TF_CUDNN_DETERMINISTIC=1` and seeded `random`/`np.random`; the trainer plugin also enables TF op determinism. `0` opts out. Startup also re-copies bundled plugin code whose content hash changed at the same version (venv kept) — see `PLUGIN_GUIDE.md` → Bundled auto-install. |
| `GRAPHYN_SECRET_ENV_ALLOWLIST` | empty | `app/core/trust/secrets.py` | Comma-separated env names that node-selected secret names may read even if not secret-shaped / `GRAPHYN_*` (default: only `*_API_KEY`, `*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`, `*_DSN`, `*_URL`, `*_URI` not starting with `GRAPHYN_`) |
| `GRAPHYN_LLM_BASE_URL_ALLOWLIST` | empty | `app/core/ml/llm_client.py` | Comma-separated hosts an env/secret LLM key may be sent to when a node `base_url` differs from the provider default (connections bind to their own `base_url`) |
| `GRAPHYN_ALLOWED_HOSTS` | empty | `app/api/main.py` | Extra `Host` names accepted while no bearer token (`GRAPHYN_API_TOKEN` / `GRAPHYN_API_TOKENS[_FILE]`) is configured; `*` disables the guard |
| `GRAPHYN_API_TOKENS` | empty | `app/core/trust/identity.py` | Named bearer tokens (`{"token": "name"}` JSON or `name:token,…`); binds the audit actor — see [Named tokens](#named-tokens--audit-identity) |
| `GRAPHYN_API_TOKENS_FILE` | empty | `app/core/trust/identity.py` | File with the same formats (mtime-cached) |
| `GRAPHYN_JOB_RESULT_TTL_S` | `3600` | `distributed/queue.py` | Unread job results protected from history trim for this long |
| `GRAPHYN_JOB_EVENTS_MAX` | `500` | `distributed/queue.py` | Events kept per job (newest) |
| `GRAPHYN_WORKER_COMPLETE_RETRIES` | `6` | worker CLI | Retries (exp. backoff) for `complete` / blob upload on network errors / 5xx; 4xx is final |
| `GRAPHYN_DISTRIBUTED_BLOB_GRACE_S` | `30` | `distributed/backend.py` | Delay before run-end transfer-blob cleanup (`0` = immediately) |
| `GRAPHYN_DISTRIBUTED_KEEP_BLOBS` | unset | `distributed/backend.py` | `1` disables run-end blob cleanup (debugging) |
| `GRAPHYN_DISTRIBUTED_BLOB_TTL_S` | `86400` | `run_cleanup.py` | `cleanup_workspace` sweep age for `artifacts/distributed_blobs` |
| `GRAPHYN_WORKER_TOKEN` | unset | worker CLI (`distributed/transfer.py`) | Worker bearer token; preferred over `GRAPHYN_API_TOKEN` on worker hosts |
| `GRAPHYN_WORKER_UNBOUND_TOKENS` | unset | `trust/identity.py` | `1` allows `kind=worker` tokens without a `worker_id` binding (lab only); otherwise they fail closed unless mTLS supplies the id |
| `GRAPHYN_BLOB_SIGNING_KEY` | unset | `distributed/transfer.py` | Control-plane HMAC key for signed blob URLs; no API-token fallback |
| `GRAPHYN_BLOB_ENCRYPTION_OLD_KEYS` | unset | `distributed/blob_crypto.py` | Comma-separated retired blob encryption keys, tried on decrypt during rotation |
| `GRAPHYN_ENV` | unset | `app/api/main.py` | `production` / `prod` / `staging` disables the `X-Graphyn-Mtls-Worker-Id` test header |
| `GRAPHYN_INPUT_INVENTORY_TTL_S` | `300` | `mlops/dataset_inputs.py` | Max age of the cached input-label inventory before a re-scan |

See [TRUST_MODEL.md](./TRUST_MODEL.md) for the security rationale and [DISTRIBUTED_EXECUTION.md § Env reference](./DISTRIBUTED_EXECUTION.md) for the full Mode B list.

Helm / K8s backend remain future (P3) — not shipped.

### HuggingFace import in the API image

The API image installs the `hf` extra (`datasets`, `huggingface_hub`) in its own layer so
Datasets → Import → HuggingFace works out of the box. Build a lean image without it with
`docker compose build --build-arg GRAPHYN_INSTALL_HF=0 graphyn-api`; the console then hides
HuggingFace import (`GET /api/v1/data/capabilities` reports it unavailable).

| `GRAPHYN_RETAIN_RUN_INPUTS` | `1` | Keep run inputs / webhook payloads in `runs/<id>/inputs.json` so "Replay exactly" reproduces input-driven runs. `0` stores fingerprints only (privacy) — such runs can then not be replayed exactly. |
