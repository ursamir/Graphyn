# Server-99 ? run all templates (Docker)

Path: `~/Desktop/newAudio3` on `meritech@Server-99`.

## One-time / after pull

```bash
cd ~/Desktop/newAudio3
git pull --ff-only origin cursor/usecase-plugins-workflows
python3 scripts/heal_e2e_local_data.py
# reclaim root-owned workspace files if needed:
docker exec -u 0 graphyn-api chown -R $(id -u):$(id -g) /app/workspace
docker compose build graphyn-api graphyn-ui
docker compose up -d graphyn-api graphyn-ui
# First API boot can take minutes (plugin venv installs). Wait until:
curl -sS http://127.0.0.1:8001/health   # expect {"status":"ok"}
```

## Edge model (for edge-deploy)

```bash
cp scripts/train_tny_edge_model.py workspace/train_tny_edge_model.py
docker exec graphyn-api /data/graphyn-home/plugins/venvs/trainer/bin/python /app/workspace/train_tny_edge_model.py
```

## Run matrix

```bash
export GRAPHYN_API_TOKEN=$(grep ^GRAPHYN_API_TOKEN= .env | cut -d= -f2-)
export GRAPHYN_API=http://127.0.0.1:8001
python3 scripts/e2e_all_templates_runner.py
```

Skips: `ex-26` (Slack), `ex-27` (GitHub) without tokens.

Do **not** kill FaceRecognition.
