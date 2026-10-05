#!/usr/bin/env python3
"""Optional tiny HTTP endpoint around run_inference.py.

    pip install -r requirements.txt -r requirements-serve.txt
    uvicorn serve:app --host 0.0.0.0 --port 8080
    curl -X POST --data-binary @clip.wav -H 'Content-Type: audio/wav' \
        'http://localhost:8080/predict?top_k=3'

The request body is the raw audio file. Preprocessing is identical to
``python run_inference.py clip.wav`` (same functions, same preprocessing.json).
"""
from __future__ import annotations

import io

from fastapi import FastAPI, HTTPException, Query, Request

import run_inference as ri

app = FastAPI(title="Graphyn packaged model")
_CFG = ri.load_preprocessing()
_LABELS = ri.load_labels(_CFG)
_INTERP, _RUNTIME = ri.make_interpreter(ri.HERE / "model.tflite")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "runtime": _RUNTIME, "labels": _LABELS}


@app.post("/predict")
async def predict(request: Request, top_k: int = Query(3, ge=1, le=100)) -> dict:
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="send the audio file as the request body")
    try:
        import librosa

        y, sr = librosa.load(io.BytesIO(body), sr=None, mono=True)
        feats = ri.extract_features(y, int(sr), _CFG)
        probs = ri.predict(_INTERP, feats)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"{type(exc).__name__}: {exc}") from exc
    return {"top": ri.top_k(probs, _LABELS, top_k), "probabilities": [float(p) for p in probs]}
