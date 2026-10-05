# app/api/routers/outputs.py
"""
Bounded Context:  REST API Layer
Responsibility:   Authenticated, path-jailed download of pipeline output files.
Owns:             GET /outputs/file (``download=1`` = explicit download:
                  attachment disposition + ``model.download`` /
                  ``run.output_download`` audit event; previews/probes are
                  not audited)
Public Surface:   FastAPI router — mounted at /api/v1 in app/api.main
Must NOT:         Serve paths outside the download jail.
Dependencies:     fastapi, app.core.runs.run_outputs, app.api.download_audit.
Reason To Change: Download policy or allowed file types change.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.core.runs.run_outputs import OutputPathError, resolve_download_path

router = APIRouter(prefix="/outputs", tags=["outputs"])

_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".bmp": "image/bmp",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".zip": "application/zip",
    ".gz": "application/gzip",
    ".tgz": "application/gzip",
    ".h": "text/x-c",
    ".tflite": "application/octet-stream",
    ".keras": "application/octet-stream",
    ".h5": "application/octet-stream",
    ".pb": "application/octet-stream",
    ".onnx": "application/octet-stream",
    ".pt": "application/octet-stream",
    ".pth": "application/octet-stream",
    ".pkl": "application/octet-stream",
    ".pickle": "application/octet-stream",
    ".npy": "application/octet-stream",
    ".npz": "application/octet-stream",
    ".npzz": "application/octet-stream",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".log": "text/plain",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".html": "text/html",
    ".htm": "text/html",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".webm": "video/webm",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
}

# Prefer inline so <audio>/<video>/<img> and blob URLs get a usable MIME.
_INLINE_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".svg",
        ".bmp",
        ".wav",
        ".mp3",
        ".flac",
        ".ogg",
        ".m4a",
        ".aac",
        ".webm",
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".json",
        ".txt",
        ".md",
        ".csv",
        ".html",
        ".htm",
    }
)


@router.get("/file", summary="Download a jailed output file")
def download_output_file(
    request: Request,
    path: str = Query(..., description="Filesystem path of the output file"),
    download: bool = Query(
        False,
        description="Explicit user download: attachment disposition + audit event "
        "(previews and existence probes omit it and are not audited)",
    ),
):
    """Return the file if it sits inside the download jail (``download=1`` audits)."""
    try:
        resolved = resolve_download_path(path)
    except OutputPathError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    suffix = resolved.suffix.lower()
    media = _MEDIA_TYPES.get(suffix, "application/octet-stream")
    disposition = "inline" if suffix in _INLINE_SUFFIXES else "attachment"
    if download:
        from app.api.download_audit import audit_file_download

        disposition = "attachment"
        audit_file_download(request, resolved, requested=path)
    return FileResponse(
        path=str(resolved),
        media_type=media,
        filename=resolved.name,
        content_disposition_type=disposition,
    )
