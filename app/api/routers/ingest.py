# app/api/routers/ingest.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for audio ingestion — URL-based and
                  HuggingFace dataset ingestion with SSE progress streaming.
Owns:             Route definitions for POST /ingest/url,
                  GET /ingest/url/{job_id}/stream,
                  POST /ingest/huggingface,
                  GET /ingest/huggingface/{job_id}/stream.
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
                  Job starts are audited (``dataset.ingest_start``); the
                  service audits the finish with provenance.
Must NOT:         Contain ingestion logic — delegate to IngestionService.
Dependencies:     fastapi, app.domain.ingestion.IngestionService,
                  app.api.actor, app.core.trust.audit.
Reason To Change: New ingestion source type added, or SSE protocol changes.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.domain.ingestion import DEFAULT_HF_MAX_ROWS, IngestionService
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
    max_rows: int = Field(DEFAULT_HF_MAX_ROWS, ge=1, le=1_000_000)
    revision: Optional[str] = None


def _actor(request: Request) -> str:
    try:
        from app.api.actor import resolve_actor

        return resolve_actor(request)
    except Exception:
        return "unknown"


def _audit_start(request: Request, job_id: str, resource_id: str, meta: dict) -> None:
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=_actor(request),
            action="dataset.ingest_start",
            resource_type="dataset_input",
            resource_id=resource_id,
            meta={"job_id": job_id, **meta},
            request_id=getattr(getattr(request, "state", None), "request_id", None),
        )
    except Exception:
        pass


# ------------------------------------------------------------------ #
# URL ingestion                                                        #
# ------------------------------------------------------------------ #

@router.post("/url")
def start_url_job(body: UrlIngestBody, request: Request):
    """POST /ingest/url — start a URL download job.

    Returns ``{"job_id": "<id>"}`` immediately.
    """
    if not body.urls:
        raise HTTPException(status_code=422, detail="urls must not be empty")
    if not body.label:
        raise HTTPException(status_code=422, detail="label must not be empty")

    from app.core.trust.egress import HttpEgressError, validate_http_egress_url

    for url in body.urls:
        try:
            validate_http_egress_url(url)
        except HttpEgressError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    job_id = _svc.start_url_job(body.urls, body.label, actor=_actor(request))
    _audit_start(request, job_id, body.label, {"source": {"kind": "url", "urls": list(body.urls)}})
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
def start_hf_job(body: HFIngestBody, request: Request):
    """POST /ingest/huggingface — start a HuggingFace dataset ingestion job.

    Labels come from ``label_col`` (ClassLabel ints are mapped to names)
    unless ``label_override`` is set; at most ``max_rows`` rows (default
    10 000) are read. ``revision`` pins a branch / tag / commit; the resolved
    commit sha is recorded in the job provenance and audit event.
    Returns ``{"job_id": "<id>"}`` immediately; 503 when the ``datasets``
    package is not installed on the API host (see GET /data/capabilities).
    """
    import importlib.util

    if not body.repo_id or not body.repo_id.strip():
        raise HTTPException(status_code=422, detail="repo_id must not be empty")
    if importlib.util.find_spec("datasets") is None:
        raise HTTPException(
            status_code=503,
            detail="HuggingFace import is unavailable: the 'datasets' package is not installed "
            "on the API host (pip install -e '.[hf]').",
        )
    repo_id = body.repo_id.strip()
    split = (body.split or "train").strip() or "train"
    job_id = _svc.start_hf_job(
        repo_id=repo_id,
        split=split,
        audio_col=(body.audio_col or "audio").strip() or "audio",
        label_col=(body.label_col or "").strip() or None,
        label_override=(body.label_override or "").strip() or None,
        max_rows=body.max_rows,
        revision=(body.revision or "").strip() or None,
        actor=_actor(request),
    )
    _audit_start(
        request,
        job_id,
        (body.label_override or "").strip() or repo_id,
        {
            "source": {
                "kind": "huggingface",
                "repo_id": repo_id,
                "split": split,
                "revision": (body.revision or "").strip() or None,
                "label_col": body.label_col,
                "label_override": body.label_override,
                "max_rows": body.max_rows,
            }
        },
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
