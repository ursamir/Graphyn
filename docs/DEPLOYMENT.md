# Deployment Guide

Baseline **Docker Compose** deploy for Graphyn API + UI. This repo does **not** ship a Helm chart.

## Auth (fail-closed)

Compose sets `GRAPHYN_ENV=production` and `GRAPHYN_AUTH_REQUIRED=1`. An empty `GRAPHYN_API_TOKEN` is **forbidden**: API and MCP reject every call with 401 / `unauthorized`.

Local CLI/SDK default remains `GRAPHYN_ENV=development` (auth optional).

```bash
export GRAPHYN_API_TOKEN=change-me
```

Put the same token in the UI **Settings** dialog (Bearer) after `docker compose up`.

## Docker Compose (API :8001 + UI :5173)

```bash
export GRAPHYN_API_TOKEN=change-me
docker compose up --build
```

- UI: `http://localhost:5173` (nginx; `/api`, `/files`, `/input-files`, `/run-files` proxy to the API)
- API: `http://localhost:8001/api/v1/`
- Named volume `graphyn-home` persists `GRAPHYN_HOME` (plugins + `secrets/` files, mode 0600)
- `./workspace` is the project dir (`GRAPHYN_PROJECT_DIR`)
- Pipeline outputs belong in `workspace/artifacts/<name>/runs/<run_id>/` on that bind-mount (not `examples/` inside the image). Successful runs also publish `workspace/artifacts/<name>/latest/` (symlink, or a `latest.json` pointer if the host cannot symlink) so later graphs can consume the production alias.


Stop:

```bash
docker compose down
```

## Secrets for live providers

Do **not** put API keys in Graph IR. Store names only in graphs (`auth_env`, provider defaults).

```bash
# on the host, with GRAPHYN_HOME matching the volume if you exec into the API container
echo "$OPENAI_API_KEY" | python -m app.cli.main secrets set OPENAI_API_KEY
echo "$DEEPGRAM_API_KEY" | python -m app.cli.main secrets set DEEPGRAM_API_KEY
python -m app.cli.main secrets list   # names only
```

REST: `GET/POST /api/v1/secrets` (Bearer required in this compose profile). List returns names only.

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

The default **spectral** backend for podcast-leveling uses `scipy` and `noisereduce` (3.x). Those packages are in `requirements.txt` / `setup.py` `install_requires`, so the Compose image already installs them via `pip install -r requirements.txt`. **Do not** add `torch` or `deepfilternet` to the base image; they remain optional for the DeepFilterNet backend.

## Isolated plugin venvs (trainer / edge-optimizer)

TensorFlow and Keras are **not** in the API image. Isolated plugins install them into per-plugin venvs under `GRAPHYN_HOME` (`/data/graphyn-home/plugins/venvs/<name>/`). Existing volumes that predate this need a one-liner:

```bash
docker exec graphyn-api /data/graphyn-home/plugins/venvs/trainer/bin/pip install 'tensorflow>=2.13' 'keras>=3.0'
```

(Optionally the same for `edge-optimizer` if TFLite conversion fails with `ModuleNotFoundError`.)

