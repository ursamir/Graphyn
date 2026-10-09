#!/usr/bin/env bash
# Build + (re)create the Graphyn api / ui / worker containers WITH build
# provenance (F19 / F-16). Every image records the exact git commit in
# /app/BUILD_INFO.json and GRAPHYN_GIT_SHA, which sealed run records copy into
# meta.environment.git_commit. Refuses to build when the commit is unknown.
#
#   scripts/build_stack.sh            # api + ui + worker (Mode B overlay)
#   GRAPHYN_MODEB=0 scripts/build_stack.sh   # api + ui only (Mode A)
#
# Only touches the graphyn-api, graphyn-ui and graphyn-worker services.
set -euo pipefail
cd "$(dirname "$0")/.."

sha="$(git rev-parse HEAD 2>/dev/null || true)"
if [[ -z "${sha}" ]]; then
  echo "build_stack: cannot resolve git HEAD — refusing to build an image without provenance" >&2
  exit 2
fi
if ! git diff --quiet HEAD -- app PluginPackage Dockerfile setup.py requirements.txt 2>/dev/null; then
  sha="${sha}-dirty"
  echo "build_stack: WARNING tracked sources differ from HEAD; recording ${sha}" >&2
fi
export GRAPHYN_GIT_SHA="${sha}"
export GRAPHYN_BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export GRAPHYN_IMAGE="${GRAPHYN_IMAGE:-newaudio3-graphyn-api:${sha:0:12}}"

files=(-f docker-compose.yml)
services=(graphyn-api graphyn-ui)
if [[ "${GRAPHYN_MODEB:-1}" == "1" ]]; then
  files+=(-f docker-compose.modeb.yml)
  services+=(graphyn-worker)
fi

echo "build_stack: GRAPHYN_GIT_SHA=${GRAPHYN_GIT_SHA} image=${GRAPHYN_IMAGE}"
docker compose "${files[@]}" build graphyn-api graphyn-ui
docker compose "${files[@]}" up -d --no-deps "${services[@]}"
docker exec graphyn-api cat /app/BUILD_INFO.json
