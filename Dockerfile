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

RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -e .

EXPOSE 8001

# CPU-safe default; operators can override in compose/k8s.
ENV CUDA_VISIBLE_DEVICES=""

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8001"]
