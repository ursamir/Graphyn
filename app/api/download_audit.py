# app/api/download_audit.py
"""
Bounded Context:  REST API Layer
Responsibility:   Audit explicit downloads (output files, run output zips,
                  ship packages) — who took which bytes.
Owns:             audit_file_download(), audit_bytes_download(),
                  download_kind(); the cheap-sha256 policy (known sidecar
                  checksum, else hash files up to 64 MiB).
Public Surface:   audit_file_download, audit_bytes_download, download_kind,
                  HASH_LIMIT_BYTES
Must NOT:         Raise to the caller (a failed audit never blocks a download);
                  audit previews / probes (callers only invoke it for
                  ``download=1`` or attachment endpoints).
Dependencies:     app.core.trust.audit.record_audit, app.api.actor, hashlib.
Reason To Change: Download audit fields or hashing policy change.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

HASH_LIMIT_BYTES = 64 * 1024 * 1024
_RUN_ID = re.compile(r"(?:^|/)runs/([0-9a-f]{32})(?:/|$)")
_MODEL_SUFFIXES = (
    ".tflite", ".onnx", ".keras", ".h5", ".pb", ".pt", ".pth", ".pkl", ".pickle",
    ".tar.gz", ".tgz", ".zip", ".h",
)


def download_kind(path: Path) -> str:
    """``model`` for model / package files, else ``output``."""
    name = path.name.lower()
    return "model" if name.endswith(_MODEL_SUFFIXES) else "output"


def _known_sha256(path: Path) -> str | None:
    """Checksum from a deployment_packager sidecar (``<file>.manifest.json``)."""
    side = path.with_name(path.name + ".manifest.json")
    try:
        if side.is_file():
            data = json.loads(side.read_text(encoding="utf-8"))
            sha = data.get("sha256") if isinstance(data, dict) else None
            if isinstance(sha, str) and len(sha) == 64:
                return sha
    except (OSError, ValueError):
        pass
    return None


def _file_sha256(path: Path, size: int) -> str | None:
    if size > HASH_LIMIT_BYTES:
        return None
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _record(request: Any, action: str, resource_type: str, resource_id: str, meta: dict[str, Any]) -> None:
    try:
        from app.api.actor import resolve_actor
        from app.core.trust.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            meta=meta,
        )
    except Exception:  # pragma: no cover - audit must never block a download
        log.debug("download audit failed", exc_info=True)


def audit_file_download(request: Any, path: Path, *, requested: str | None = None) -> dict[str, Any]:
    """Record ``model.download`` / ``run.output_download`` for one jailed file."""
    try:
        size = path.stat().st_size
    except OSError:
        size = None
    sha = _known_sha256(path) or (_file_sha256(path, size) if size is not None else None)
    posix = str(requested or path).replace("\\", "/")
    m = _RUN_ID.search(posix) or _RUN_ID.search(str(path).replace("\\", "/"))
    kind = download_kind(path)
    meta = {
        "path": requested or str(path),
        "file": path.name,
        "size_bytes": size,
        "sha256": sha,
        "kind": kind,
        "run_id": m.group(1) if m else None,
    }
    action = "model.download" if kind == "model" else "run.output_download"
    _record(request, action, "file", requested or str(path), meta)
    return meta


def audit_bytes_download(
    request: Any,
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    payload: bytes | None = None,
    size: int | None = None,
    sha256: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a download whose bytes are in memory (zip) or already hashed."""
    if payload is not None:
        size = len(payload)
        sha256 = sha256 or hashlib.sha256(payload).hexdigest()
    meta = {"size_bytes": size, "sha256": sha256, **(extra or {})}
    _record(request, action, resource_type, resource_id, meta)
    return meta
