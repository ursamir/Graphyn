FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt setup.py README.md /app/
COPY app /app/app
COPY PluginPackage /app/PluginPackage
COPY examples /app/examples
COPY docs /app/docs
COPY unit_test /app/unit_test
COPY pytest.ini /app/pytest.ini
COPY scripts /app/scripts

# Single install path: pinned runtime from requirements.txt, then editable
# package metadata with --no-deps so pins win (setup.py is source of truth
# for *which* packages; requirements.txt for deploy versions).
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -e . --no-deps

# Build provenance for sealed run records (environment.git_commit / image).
# The image has no .git, so pass the commit at build time:
#   GRAPHYN_GIT_SHA=$(git rev-parse HEAD) docker compose build graphyn-api
# Declared after the dependency layers so changing them does not bust the pip cache.
ARG GRAPHYN_GIT_SHA=""
ARG GRAPHYN_IMAGE="graphyn-api:local"
ARG GRAPHYN_BUILD_DATE=""
ENV GRAPHYN_GIT_SHA=${GRAPHYN_GIT_SHA} \
    GRAPHYN_IMAGE=${GRAPHYN_IMAGE}
RUN python -c "import json,os,datetime; json.dump({'git_sha': os.environ.get('GRAPHYN_GIT_SHA') or None, 'image': os.environ.get('GRAPHYN_IMAGE') or None, 'build_date': '${GRAPHYN_BUILD_DATE}' or datetime.datetime.now(datetime.timezone.utc).isoformat()}, open('/app/BUILD_INFO.json','w'), indent=2)"

EXPOSE 8001

# CPU-safe default; operators can override in compose/k8s.
ENV CUDA_VISIBLE_DEVICES=""

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8001"]
