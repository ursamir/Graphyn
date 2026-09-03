# app/api/routers/outputs.py
"""
Bounded Context:  REST API Layer
Responsibility:   Authenticated, path-jailed download of pipeline output files.
Owns:             GET /outputs/file
Public Surface:   FastAPI router — mounted at /api/v1 in app/api.main
Must NOT:         Serve paths outside the download jail.
Dependencies:     fastapi, app.core.run_outputs.
Reason To Change: Download policy or allowed file types change.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.run_outputs import OutputPathError, resolve_download_path

router = APIRouter(prefix="/outputs", tags=["outputs"])

_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".zip": "application/zip",
    ".tflite": "application/octet-stream",
    ".keras": "application/octet-stream",
    ".h5": "application/octet-stream",
    ".pb": "application/octet-stream",
    ".txt": "text/plain",
    ".npy": "application/octet-stream",
    ".npz": "application/octet-stream",
    ".onnx": "application/octet-stream",
}


@router.get("/file", summary="Download a jailed output file")
def download_output_file(path: str = Query(..., description="Filesystem path of the output file")):
    """Return the file as an attachment if it sits inside the download jail."""
    try:
        resolved = resolve_download_path(path)
    except OutputPathError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    media = _MEDIA_TYPES.get(resolved.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path=str(resolved),
        media_type=media,
        filename=resolved.name,
        content_disposition_type="attachment",
    )
