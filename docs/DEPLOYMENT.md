# Deployment Guide

This guide provides a baseline container deployment for Graphyn API.

## Docker

Build image:

```bash
docker build -t graphyn:local .
```

Run:

```bash
docker run --rm -p 8001:8001 \
  -e GRAPHYN_API_TOKEN=secret \
  -v "$(pwd)/workspace:/app/workspace" \
  -v "$(pwd)/plugins:/app/plugins" \
  graphyn:local
```

API base:

`http://localhost:8001/api/v1/`

## Docker Compose

```bash
docker compose up --build -d
docker compose logs -f graphyn-api
```

Stop:

```bash
docker compose down
```

## GPU Safety Notes

- Compose leaves `CUDA_VISIBLE_DEVICES` empty by default.
- If GPU is shared with other processes, set a specific device:

```bash
CUDA_VISIBLE_DEVICES=1 docker compose up -d
```

- For heavy training/inference workloads, schedule jobs explicitly and avoid unbounded concurrent runs.
