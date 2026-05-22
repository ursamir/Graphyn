"""
FastAPI router for audio ingestion endpoints.

Supports URL-based and HuggingFace dataset ingestion with SSE progress streaming.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.domain.ingestion import IngestionService
import json

router = APIRouter(prefix="/ingest", tags=["ingest"])

_svc = IngestionService()


# ------------------------------------------------------------------ #
# Request models                                                       #
# ------------------------------------------------------------------ #

class UrlIngestBody(BaseModel):
    urls: list[str]
    label: str


class HFIngestBody(BaseModel):
    repo_id: str
    split: Optional[str] = "train"
    audio_col: Optional[str] = "audio"
    label_col: Optional[str] = None
    label_override: Optional[str] = None


# ------------------------------------------------------------------ #
# URL ingestion                                                        #
# ------------------------------------------------------------------ #

@router.post("/url")
def start_url_job(body: UrlIngestBody):
    """POST /ingest/url — start a URL download job.

    Returns ``{"job_id": "<id>"}`` immediately.
    """
    if not body.urls:
        raise HTTPException(status_code=422, detail="urls must not be empty")
    if not body.label:
        raise HTTPException(status_code=422, detail="label must not be empty")

    job_id = _svc.start_url_job(body.urls, body.label)
    return {"job_id": job_id}


@router.get("/url/{job_id}/stream")
def stream_url_job(job_id: str):
    """GET /ingest/url/{job_id}/stream — SSE progress stream for a URL job."""
    try:
        _svc.get_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    def event_stream():
        for event in _svc.stream_job(job_id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ------------------------------------------------------------------ #
# HuggingFace ingestion                                                #
# ------------------------------------------------------------------ #

@router.post("/huggingface")
def start_hf_job(body: HFIngestBody):
    """POST /ingest/huggingface — start a HuggingFace dataset ingestion job.

    Returns ``{"job_id": "<id>"}`` immediately.
    """
    if not body.repo_id:
        raise HTTPException(status_code=422, detail="repo_id must not be empty")

    job_id = _svc.start_hf_job(
        repo_id=body.repo_id,
        split=body.split or "train",
        audio_col=body.audio_col or "audio",
        label_col=body.label_col,
        label_override=body.label_override,
    )
    return {"job_id": job_id}


@router.get("/huggingface/{job_id}/stream")
def stream_hf_job(job_id: str):
    """GET /ingest/huggingface/{job_id}/stream — SSE progress stream for a HF job."""
    try:
        _svc.get_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    def event_stream():
        for event in _svc.stream_job(job_id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
