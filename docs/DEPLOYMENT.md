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

- Compose leaves `CUDA_VISIBLE_DEVICES` empty by default.
- If GPU is shared, set a specific device: `CUDA_VISIBLE_DEVICES=1 docker compose up --build`

## Runtime extras (speech_enhancer)

The default **spectral** backend for podcast-leveling uses `scipy` and `noisereduce` (3.x). Those packages are in `requirements.txt` / `setup.py` `install_requires`, so the Compose image already installs them via `pip install -r requirements.txt`. **Do not** add `torch` or `deepfilternet` to the base image; they remain optional for the DeepFilterNet backend.

## Isolated plugin venvs (trainer / edge-optimizer)

TensorFlow and Keras are **not** in the API image. Isolated plugins install them into per-plugin venvs under `GRAPHYN_HOME` (`/data/graphyn-home/plugins/venvs/<name>/`). Existing volumes that predate this need a one-liner:

```bash
docker exec graphyn-api /data/graphyn-home/plugins/venvs/trainer/bin/pip install 'tensorflow>=2.13' 'keras>=3.0'
```

(Optionally the same for `edge-optimizer` if TFLite conversion fails with `ModuleNotFoundError`.)

