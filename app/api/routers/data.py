# app/api/routers/data.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for input/output dataset management: generic
                  file listings, uploads (multi-file / folder / archive),
                  stats, snapshots (freeze an input label as a version),
                  streamed zip downloads, merge — every mutation audited.
Owns:             Route definitions for GET /data/capabilities,
                  GET/POST /data/inputs, GET /data/inputs/file,
                  GET/DELETE /data/inputs/{label},
                  GET /data/inputs/{label}/stats, GET /data/inputs/{label}/zip,
                  POST /data/inputs/{label}/snapshot, POST /data/inputs/upload,
                  GET /data/outputs, GET/DELETE /data/outputs/{project}/{version},
                  GET /data/outputs/{project}/{version}/stats|zip,
                  POST /data/outputs/publish-artifact, POST /data/merge.
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain dataset storage logic — delegate to
                  app.core.mlops.dataset_inputs / dataset_versions and config
                  path functions.
Dependencies:     fastapi, app.core.config, app.core.mlops.dataset_inputs,
                  app.core.mlops.dataset_versions, app.core.trust.audit,
                  app.api.actor, stdlib (csv, os, shutil, datetime, pathlib).
Reason To Change: New data endpoint added, or upload/merge/download behaviour changes.
"""
from __future__ import annotations

import csv
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.core.config import artifacts_dir as _artifacts_dir
from app.core.config import datasets_input_dir as _datasets_input_dir
from app.core.config import datasets_output_dir as _datasets_output_dir
from app.core.mlops.dataset_inputs import (
    AUDIO_EXTENSIONS,
    INPUT_SNAPSHOT_PROJECT,
    UploadError,
    UploadLimits,
    UploadSession,
    audit_file_meta,
    file_kind,
    is_valid_label,
    iter_files,
    iter_zip_stream,
    label_counts,
    label_file_rows,
    label_stats,
    list_artifact_datasets,
    list_input_snapshots,
    publish_artifact_dataset,
    snapshot_input_label,
)

router = APIRouter(prefix="/data", tags=["data"])

# Align with ProjectManager._VERSION_RE — exclude snapshots/ and junk dirs.
_VERSION_RE = re.compile(r"^v\d+(\.\d+)*$")

# Kept for importers: the audio subset. Listings now include every file type.
SUPPORTED_AUDIO_EXTENSIONS = AUDIO_EXTENSIONS


def _input_root() -> Path:
    """Return the input datasets directory, resolved from GRAPHYN_PROJECT_DIR."""
    return _datasets_input_dir()


def _output_root() -> Path:
    """Return the output datasets directory, resolved from GRAPHYN_PROJECT_DIR."""
    return _datasets_output_dir()


def _allow_external() -> bool:
    return os.environ.get("GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS", "").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _safe_child(root: Path, *parts: str) -> Path:
    """Join *parts under root and reject symlink escapes by default.

    Segments are validated lexically. The joined path is then resolved so a
    symlink whose target lies outside *root* cannot be served (e.g. ``passwd``).

    Set ``GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS=1`` to restore lexical-only
    checks for Docker layouts that intentionally symlink dataset dirs onto
    host paths outside ``GRAPHYN_PROJECT_DIR``.
    """
    for part in parts:
        if part in {"", ".", ".."} or "/" in part or "\\" in part:
            raise HTTPException(status_code=400, detail="Invalid path segment")
    resolved_root = root.resolve()
    path = resolved_root.joinpath(*parts)
    if not path.is_relative_to(resolved_root):
        raise HTTPException(status_code=400, detail="Path is outside workspace")
    if _allow_external():
        return path
    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid path: {exc}") from exc
    if not resolved.is_relative_to(resolved_root):
        raise HTTPException(status_code=400, detail="Path is outside workspace")
    return resolved


def _project_parts(project: str) -> list[str]:
    """Output project id → path segments.

    Plain workspaces are one segment; frozen input snapshots are addressed as
    ``_inputs/<label>`` (two segments). Anything else is rejected.
    """
    parts = (project or "").split("/")
    if len(parts) == 1:
        return parts
    if len(parts) == 2 and parts[0] == INPUT_SNAPSHOT_PROJECT and parts[1]:
        return parts
    raise HTTPException(status_code=400, detail="Invalid path segment")


def _audit(
    request: Request | None,
    action: str,
    resource_type: str,
    resource_id: str,
    meta: dict[str, Any] | None = None,
    *,
    result: str = "success",
) -> None:
    """Record one ``dataset.*`` audit event (best effort, never raises)."""
    try:
        from app.api.actor import resolve_actor
        from app.core.trust.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            meta=meta or {},
            result=result,
            request_id=getattr(getattr(request, "state", None), "request_id", None),
        )
    except Exception:
        pass


def _hf_available() -> tuple[bool, str | None]:
    import importlib.util

    try:
        if importlib.util.find_spec("datasets") is not None:
            return True, None
    except (ImportError, ValueError):
        pass
    return False, "The 'datasets' package is not installed on the API host (pip install -e '.[hf]')."


@router.get("/capabilities", summary="Upload limits and import sources")
def data_capabilities():
    """Upload caps / allowlist plus which import sources this API can run."""
    hf_ok, hf_reason = _hf_available()
    return {
        "upload": UploadLimits.from_env().as_dict(),
        "ingest": {
            "url": True,
            "huggingface": hf_ok,
            "huggingface_reason": hf_reason,
            "huggingface_default_max_rows": 10000,
        },
    }


# ── Input datasets ────────────────────────────────────────────────────────────

@router.get("/inputs", summary="List input dataset labels")
def list_input_datasets():
    """Return input dataset labels with file counts (all file types).

    ``file_count`` counts every (non-hidden) file; ``audio_count`` the audio
    subset. Labels that resolve outside the input root (external symlinks) are
    still listed with ``accessible: false`` so the UI does not pretend they are
    browseable unless ``GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS`` is enabled.
    """
    input_root = _input_root()
    if not input_root.exists():
        return []
    labels = []
    for label in sorted(os.listdir(input_root)):
        if label.startswith("."):
            continue
        label_path = input_root / label
        if not label_path.is_dir():
            continue
        accessible = True
        try:
            _safe_child(input_root, label)
        except HTTPException:
            accessible = False
        counts = label_counts(label_path)
        labels.append({"label": label, **counts, "accessible": accessible})
    return labels


_INPUT_MEDIA_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


@router.get("/inputs/file", summary="Download an input dataset file")
def download_input_file(
    request: Request,
    path: str = Query(..., description="Path relative to datasets/input (may be nested)"),
    download: bool = Query(
        False,
        description="Explicit user download: attachment disposition + audit event "
        "(previews omit it and are not audited)",
    ),
):
    """Serve an input file via path-jailed ``_safe_child``.

    Nested labels may use intermediate directory symlinks **within** the input
    root (resolved target must stay under the root unless
    ``GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS=1``). Static ``/input-files`` does
    not follow symlinks; prefer this API for nested trees. Pass ``download=1``
    for an audited attachment download (same contract as ``GET /outputs/file``).
    """
    rel = (path or "").replace("\\", "/").lstrip("/")
    parts = [p for p in rel.split("/") if p]
    if not parts or any(p in {"", ".", ".."} for p in parts):
        raise HTTPException(status_code=400, detail="Invalid path")
    file_path = _safe_child(_input_root(), *parts)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    media = _INPUT_MEDIA_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
    disposition = "inline"
    if download:
        from app.api.download_audit import audit_file_download

        disposition = "attachment"
        audit_file_download(request, file_path, requested=rel)
    return FileResponse(
        path=str(file_path),
        media_type=media,
        filename=file_path.name,
        content_disposition_type=disposition,
    )


def _label_dir(label: str) -> Path:
    input_root = _input_root()
    try:
        label_path = _safe_child(input_root, label)
    except HTTPException as exc:
        if exc.status_code == 400 and "outside workspace" in str(exc.detail).lower():
            raise HTTPException(
                status_code=400,
                detail=(
                    "Path is outside workspace. This label is an external symlink; "
                    "set GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS=1 on the API to browse it, "
                    "or use a label inside the Graphyn datasets/input tree."
                ),
            ) from exc
        raise
    if not label_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Label '{label}' not found")
    return label_path


@router.get("/inputs/{label}", summary="List files in an input dataset label")
def get_input_dataset(label: str):
    """Every file in an input label: ``[{path, label, kind, ext, size_bytes, modified_at}]``.

    ``kind`` is audio | table | json | text | image | pdf | archive | other.
    """
    label_path = _label_dir(label)
    return label_file_rows(_input_root(), label_path, label)


@router.get("/inputs/{label}/stats", summary="Input label statistics")
def get_input_stats(
    label: str,
    max_audio_probe: int = Query(400, ge=0, le=5000, description="Audio headers read for the duration summary"),
):
    """File counts by kind / extension, bytes, per-class (first subfolder)
    counts and a sampled audio duration / sample-rate summary."""
    label_path = _label_dir(label)
    return label_stats(label_path, label, max_audio_probe=max_audio_probe)


@router.post("/inputs/{label}/snapshot", summary="Freeze an input label as an immutable version")
def snapshot_input(label: str, request: Request):
    """Copy the label into ``datasets/output/_inputs/<label>/vN`` with a
    sha256 manifest. Runs that read the snapshot record a dataset version."""
    _label_dir(label)
    if not is_valid_label(label):
        raise HTTPException(status_code=422, detail="Label name cannot be snapshotted (letters, digits, _ and - only)")
    try:
        snap = snapshot_input_label(
            label,
            input_root=_input_root(),
            output_root=_output_root(),
            jail_external=not _allow_external(),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _audit(
        request,
        "dataset.snapshot",
        "dataset_version",
        f"{snap['project']}/{snap['version']}",
        {
            "label": label,
            "file_count": snap["file_count"],
            "total_bytes": snap["total_bytes"],
            "content_hash": snap["content_hash"],
        },
    )
    return snap


def _zip_response(gen, filename: str) -> StreamingResponse:
    return StreamingResponse(
        gen,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/inputs/{label}/zip", summary="Download an input label as a zip")
def download_input_zip(label: str, request: Request):
    """Streamed zip of every file in the label plus a ``manifest.json``
    (per-file sha256 + content_hash, computed while streaming)."""
    label_path = _label_dir(label)
    jail = None if _allow_external() else _input_root()
    files = list(iter_files(label_path, jail=jail))
    _audit(
        request,
        "dataset.download",
        "dataset_input",
        label,
        {"file_count": len(files), "format": "zip"},
    )
    gen = iter_zip_stream(
        files,
        prefix=f"{label}/",
        manifest_name="manifest.json",
        manifest_extra={"source": {"kind": "input_label", "label": label}},
    )
    return _zip_response(gen, f"{label}.zip")


@router.delete("/inputs/{label}", summary="Delete an input dataset label")
def delete_input_dataset(label: str, request: Request):
    """Delete the input label directory (jailed); audited with the file count
    and content hash it had before the delete."""
    from app.core.mlops.dataset_versions import compute_manifest

    input_root = _input_root()
    label_path = _safe_child(input_root, label)
    if not label_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Label '{label}' not found")
    before: dict[str, Any] = {}
    try:
        man = compute_manifest(label_path)
        before = {
            "file_count": man.get("file_count"),
            "content_hash": man.get("content_hash"),
            "total_bytes": sum(int(f.get("size") or 0) for f in man.get("files") or []),
        }
    except Exception:
        pass
    shutil.rmtree(label_path)
    from app.core.mlops.dataset_inputs import invalidate_label_inventory

    invalidate_label_inventory(label_path)
    _audit(request, "dataset.label_delete", "dataset_input", label, before)
    return {"deleted": label, **before}


def _truthy(raw: Optional[str]) -> Optional[bool]:
    if raw is None or str(raw).strip() == "":
        return None
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


@router.post("/inputs/upload", summary="Upload files, folders or archives into input labels")
def upload_file(
    request: Request,
    file: Optional[UploadFile] = File(None, description="Single file (legacy field)"),
    files: Optional[list[UploadFile]] = File(None, description="One or more files; a filename may carry a relative folder path"),
    label: str = Form("uploads", description="Target label (existing or new)"),
    folders_as_labels: Optional[str] = Form(
        None,
        description="true: split — the first folder of each path becomes its own input dataset; "
        "false / empty (default): keep sub-folders (e.g. class folders) under `label`",
    ),
    strip_root: Optional[str] = Form(
        None,
        description="false: keep plain-file paths exactly as sent (default true: drop one shared top folder)",
    ),
):
    """Store uploaded files under ``datasets/input/<label>/``.

    * Multiple files (``files``) and folder uploads (filenames with relative
      paths, e.g. from ``webkitdirectory``) are accepted.
    * ``.zip`` / ``.tar`` / ``.tar.gz`` / ``.tgz`` are unpacked server-side with
      caps (``GRAPHYN_UPLOAD_MAX_ARCHIVE_FILES``, ``GRAPHYN_UPLOAD_MAX_EXTRACT_BYTES``);
      symlinks, devices, absolute / ``..`` / hidden members are skipped.
    * Only allowlisted types are stored (audio, csv/tsv, json/jsonl, txt, md,
      pdf, png/jpg, parquet); others are reported under ``skipped``.
    * The request is capped at ``GRAPHYN_UPLOAD_MAX_BYTES`` (default 100 MB).
    * Each stored file's sha256 is computed server-side; the whole request is
      audited (``dataset.upload``) and rolled back on any cap violation.
    """
    limits = UploadLimits.from_env()
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > limits.max_request_bytes + 1024 * 1024:
                raise HTTPException(status_code=413, detail="Upload too large")
        except ValueError:
            pass
    uploads = [u for u in ([file] if file is not None else []) + list(files or []) if u is not None]
    if not uploads:
        raise HTTPException(status_code=422, detail="No files in the upload (use field 'files' or 'file')")
    target = (label or "uploads").strip() or "uploads"
    if not is_valid_label(target):
        raise HTTPException(
            status_code=422, detail="Invalid label (letters, digits, _ and - only, max 64 characters)"
        )
    _input_root().mkdir(parents=True, exist_ok=True)
    session = UploadSession(
        input_root=_input_root(),
        target_label=target,
        folders_as_labels=_truthy(folders_as_labels),
        strip_root=_truthy(strip_root) is not False,
        limits=limits,
    )
    try:
        session.add_files([((u.filename or "upload.bin"), u.file) for u in uploads])
    except UploadError as exc:
        session.rollback()
        _audit(
            request,
            "dataset.upload",
            "dataset_input",
            target,
            {"error": exc.message, "files_received": len(uploads)},
            result="failure",
        )
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    except Exception:
        session.rollback()
        raise
    summary = session.summary()
    if summary["count"] == 0 and summary["skipped"] and not any(
        s.get("reason", "").startswith("identical") for s in summary["skipped"]
    ):
        reasons = "; ".join(f"{s['name']}: {s['reason']}" for s in summary["skipped"][:5])
        raise HTTPException(status_code=400, detail=f"No files stored — {reasons}")
    _audit(
        request,
        "dataset.upload",
        "dataset_input",
        ",".join(summary["labels"]) or target,
        {
            "label": target,
            "labels": summary["labels"],
            "count": summary["count"],
            "total_bytes": summary["total_bytes"],
            "content_hash": summary["content_hash"],
            "archives": summary["archives"],
            "skipped": len(summary["skipped"]),
            **audit_file_meta(summary["files"]),
        },
    )
    first = summary["files"][0] if summary["files"] else None
    if first:
        summary["file_path"] = str(_input_root() / first["path"])
        summary["filename"] = first["path"].rsplit("/", 1)[-1]
    return summary


# ── Output datasets ───────────────────────────────────────────────────────────

@router.get("/outputs", summary="List output dataset projects")
def list_output_datasets(
    envelope: str | None = Query(None, description="List envelope (default on). Pass 0/false/no/off for bare array."),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Return a list of output dataset projects and their versions.

    Version dirs must match ProjectManager ``_VERSION_RE`` (e.g. v1, v1.0.0).
    ``snapshots/`` and other non-version directories are excluded. Frozen
    input labels are listed as ``{project: "_inputs/<label>", kind:
    "input_snapshot"}``. Legacy ``artifacts/<slug>/dataset/<name>`` trees are
    soft-listed as ``kind: "artifact_dataset"`` (``fs_path`` for publish/pick).
    Envelope by default (API-PAGE-001 P1). Pass ``?envelope=0`` for bare array.
    """
    from app.api.pagination import maybe_envelope, parse_envelope_flag

    output_root = _output_root()
    result: list[dict[str, Any]] = []
    if output_root.exists():
        for project in sorted(os.listdir(output_root)):
            if project.startswith(".") or project == INPUT_SNAPSHOT_PROJECT:
                continue
            project_path = output_root / project
            if not project_path.is_dir():
                continue
            versions = sorted(
                v for v in os.listdir(project_path)
                if (project_path / v).is_dir() and bool(_VERSION_RE.match(v))
            )
            result.append({"project": project, "versions": versions})
        result.extend(list_input_snapshots(output_root))
    result.extend(list_artifact_datasets(_artifacts_dir()))
    total = len(result)
    page = result[offset : offset + limit]
    return maybe_envelope(
        page,
        envelope=parse_envelope_flag(envelope),
        total=total,
        limit=limit,
        offset=offset,
    )


class PublishArtifactBody(BaseModel):
    """Copy a legacy artifact dataset version into Library Outputs."""

    fs_path: str
    version: str | None = None
    target_project: str
    source_version: str | None = None


@router.post("/outputs/publish-artifact", summary="Publish artifact dataset into Library Outputs")
def publish_artifact_to_outputs(body: PublishArtifactBody, request: Request):
    """Copy ``workspace/artifacts/.../dataset/.../vN`` into ``datasets/output/<ws>/vN``.

    Soft-listed artifact rows (``kind: artifact_dataset``) use this so prepared
    data becomes visible under Datasets → Outputs for the active workspace.
    """
    from app.core.mlops.dataset_versions import next_free_version, version_has_content
    from app.core.paths.workspace_paths import ARTIFACTS_PREFIX

    fs = (body.fs_path or "").strip().replace("\\", "/").rstrip("/")
    prefix = f"{ARTIFACTS_PREFIX}/"
    # Exact shape workspace/artifacts/<slug>/dataset/<name>: each segment is
    # validated and jailed by _safe_child (no "..", no absolute, no symlink escape).
    parts = fs[len(prefix) :].split("/") if fs.startswith(prefix) else []
    if len(parts) != 3 or parts[1] != "dataset":
        raise HTTPException(
            status_code=400,
            detail="fs_path must look like workspace/artifacts/<slug>/dataset/<name>",
        )
    proj = (body.target_project or "").strip()
    if not proj or proj.startswith("_") or "/" in proj or ".." in proj:
        raise HTTPException(status_code=400, detail="Invalid target_project")
    if body.version is not None and body.version.strip() and not _VERSION_RE.match(body.version.strip()):
        raise HTTPException(status_code=400, detail="Invalid version (expected vN / vN.N.N)")
    src_base = _safe_child(_artifacts_dir(), *parts)
    ver = (body.source_version or "").strip()
    if not ver:
        from app.core.execution.dataset_refs import newest_version_dir

        ver = newest_version_dir(src_base) or ""
        if not ver:
            raise HTTPException(status_code=404, detail="No version folders under artifact dataset")
    if not _VERSION_RE.match(ver):
        raise HTTPException(status_code=400, detail="Invalid source_version (expected vN / vN.N.N)")
    src = _safe_child(_artifacts_dir(), *parts, ver)
    if not src.is_dir():
        raise HTTPException(status_code=404, detail="Source version not found")
    output_root = _output_root()
    target = _safe_child(output_root, proj)
    want = (body.version or "").strip()
    if want and version_has_content(_safe_child(output_root, proj, want)):
        suggestion = next_free_version(target, want)
        raise HTTPException(
            status_code=409,
            detail={
                "error": "conflict",
                "code": "version_exists",
                "message": (
                    f"{proj}/{want} already exists and dataset versions are immutable — "
                    f"publish into {suggestion} or omit version"
                ),
                "suggested_version": suggestion,
            },
        )
    source_label = f"{fs}/{ver}"
    try:
        out = publish_artifact_dataset(
            source_dir=src,
            target_project_dir=target,
            version=want or None,
            source_label=source_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Source version not found") from exc
    except (OSError, shutil.Error) as exc:
        _audit(
            request,
            "dataset.publish_artifact",
            "dataset_version",
            f"{proj}/{want or '?'}",
            {"from": source_label, "error": type(exc).__name__},
            result="failure",
        )
        raise HTTPException(status_code=500, detail="Publish failed while copying files") from exc
    _ensure_project_json(target, proj)
    _audit(
        request,
        "dataset.publish_artifact",
        "dataset_version",
        f"{out['project']}/{out['version']}",
        {"from": source_label, "content_hash": out.get("content_hash"), "file_count": out.get("file_count")},
    )
    out["path"] = f"workspace/datasets/output/{out['project']}/{out['version']}"
    return out


def _version_dir(project: str, version: str) -> Path:
    if not _VERSION_RE.match(version or ""):
        raise HTTPException(status_code=400, detail="Invalid version (expected vN / vN.N.N)")
    return _safe_child(_output_root(), *_project_parts(project), version)


# NOTE: the ``/stats`` and ``/zip`` routes are registered before the bare
# ``/outputs/{project:path}/{version}`` route — ``project`` may contain one
# slash (``_inputs/<label>``), so the more specific routes must win.

@router.get("/outputs/{project:path}/{version}/stats", summary="Get dataset statistics")
def get_dataset_stats(project: str, version: str):
    """Return split counts and per-label distribution for a dataset.

    Prefers ``labels.csv`` (audio exporter layout). When absent, derives a
    best-effort split/label histogram from ``manifest.json`` paths
    (``train|val|test/<label>/…``) so non-wav / non-exporter versions still
    answer without scavenging the tree.
    """
    from app.core.mlops.dataset_versions import read_manifest

    dataset_path = _version_dir(project, version)
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail="Dataset not found")

    labels_file = dataset_path / "labels.csv"
    if labels_file.exists():
        splits: dict[str, dict[str, int]] = {}
        total = 0
        with open(labels_file, newline="") as f:
            for row in csv.DictReader(f):
                split = row.get("split", "unknown")
                label = row.get("label", "unknown")
                splits.setdefault(split, {})
                splits[split][label] = splits[split].get(label, 0) + 1
                total += 1
        return {
            "project": project,
            "version": version,
            "total": total,
            "splits": splits,
            "source": "labels.csv",
        }

    man = read_manifest(dataset_path, ensure=True, enforce_sha256=False)
    splits = {}
    total = 0
    for item in man.get("files") if isinstance(man.get("files"), list) else []:
        if isinstance(item, str):
            rel = item
        elif isinstance(item, dict):
            rel = str(item.get("path") or "")
        else:
            continue
        if not rel or rel.endswith("manifest.json"):
            continue
        parts = rel.replace("\\", "/").split("/")
        if len(parts) >= 3 and parts[0] in {"train", "val", "test", "dev"}:
            split, label = parts[0], parts[1]
            splits.setdefault(split, {})
            splits[split][label] = splits[split].get(label, 0) + 1
        total += 1
    if total == 0:
        fc = man.get("file_count")
        total = int(fc) if isinstance(fc, (int, float)) else 0
    return {
        "project": project,
        "version": version,
        "total": total,
        "splits": splits,
        "source": "manifest",
    }


@router.get("/outputs/{project:path}/{version}/zip", summary="Download a dataset version as a zip")
def download_output_zip(project: str, version: str, request: Request):
    """Streamed zip of the version folder, including its ``manifest.json``."""
    from app.core.mlops.dataset_versions import read_manifest

    dataset_path = _version_dir(project, version)
    if not dataset_path.is_dir():
        raise HTTPException(status_code=404, detail="Dataset not found")
    man = read_manifest(dataset_path, ensure=True, enforce_sha256=True)
    files = list(iter_files(dataset_path, jail=_output_root()))
    _audit(
        request,
        "dataset.download",
        "dataset_version",
        f"{project}/{version}",
        {"file_count": len(files), "content_hash": man.get("content_hash"), "format": "zip"},
    )
    name = f"{project.replace('/', '_')}_{version}"
    return _zip_response(iter_zip_stream(files, prefix=f"{name}/"), f"{name}.zip")


@router.get("/outputs/{project:path}/{version}", summary="Get an output dataset")
def get_output_dataset(
    project: str,
    version: str,
    limit: int = Query(200, ge=1, le=1000, description="Max file rows to return (browse default)"),
    offset: int = Query(0, ge=0, description="File-row offset for pagination"),
    include_hash: bool = Query(
        False,
        description="Include per-file sha256 (legacy/integrity). Default false for lean browse.",
    ),
    include_samples: bool = Query(
        False,
        description="Include legacy samples[] (duplicates path info). Default false.",
    ),
    split: Optional[str] = Query(
        None,
        description="Only files in this split (train/val/test…); file_count is then the split's total",
    ),
):
    """Return dataset version detail for browse or integrity tooling (DATA-VER-002).

    Default is a **lean** page: ``files`` with path/size/kind/split/label, no
    per-file sha256, empty ``samples``. Pass ``include_hash=1`` for hashes;
    ``include_samples=1`` for the legacy samples array.
    """
    from app.core.mlops.dataset_versions import read_manifest

    dataset_path = _version_dir(project, version)
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail="Dataset not found")

    man = read_manifest(dataset_path, ensure=True, enforce_sha256=False)
    all_files = _file_rows(man.get("files"), include_hash=include_hash)
    dataset_files = [r for r in all_files if r["path"] in _DATASET_META_FILES]
    data_files = [r for r in all_files if r["path"] not in _DATASET_META_FILES]
    data_files = _enrich_file_rows_split_label(data_files, dataset_path)
    if split:
        data_files = [r for r in data_files if r.get("split") == split]
    data_files.sort(key=lambda r: (_SPLIT_ORDER.get(str(r.get("split") or ""), 99), r["path"]))
    total = len(data_files)
    page = data_files[offset : offset + limit]
    truncated = offset + len(page) < total
    _stat_rows(page, dataset_path)
    _stat_rows(dataset_files, dataset_path)

    created_at = man.get("created_at") if isinstance(man.get("created_at"), str) else None
    if created_at is None:
        try:
            created_at = datetime.fromtimestamp(
                dataset_path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        except OSError:
            created_at = None

    samples: list[dict[str, Any]] = []
    if include_samples:
        samples = _build_samples(project, version, dataset_path, man)

    out: dict[str, Any] = {
        "project": project,
        "version": version,
        "files": page,
        "file_count": total,
        "dataset_files": dataset_files,
        "content_hash": man.get("content_hash") or man.get("sha256"),
        "created_at": created_at,
        "samples": samples,
        "limit": limit,
        "offset": offset,
        "truncated": truncated,
    }
    if isinstance(man.get("source"), dict):
        out["source"] = man["source"]
    return out


def _build_samples(
    project: str,
    version: str,
    dataset_path: Path,
    man: dict[str, Any],
) -> list[dict[str, Any]]:
    """Legacy samples[] (path + split + label) — opt-in only (duplicates files)."""
    samples: list[dict[str, Any]] = []
    labels_file = dataset_path / "labels.csv"
    if labels_file.exists():
        with open(labels_file, newline="") as f:
            for row in csv.DictReader(f):
                rel_path = row.get("path")
                split = row.get("split")
                label = row.get("label")
                if not rel_path or not split or not label:
                    continue
                samples.append({
                    "path": f"{project}/{version}/{rel_path}".replace("\\", "/"),
                    "split": split,
                    "label": label,
                })
        return samples

    for item in man.get("files") if isinstance(man.get("files"), list) else []:
        if isinstance(item, str):
            rel = item
        elif isinstance(item, dict):
            rel = str(item.get("path") or "")
        else:
            continue
        rel = rel.replace("\\", "/")
        if not rel or rel.endswith("manifest.json") or rel.endswith("labels.csv"):
            continue
        parts = rel.split("/")
        if len(parts) >= 3 and parts[0] in {"train", "val", "test", "dev"}:
            samples.append({
                "path": f"{project}/{version}/{rel}",
                "split": parts[0],
                "label": parts[1],
            })
        if len(samples) >= 5000:
            break
    return samples


#: Version-root bookkeeping written by exporters / the manifest writer — not samples.
_DATASET_META_FILES = frozenset({"labels.csv", "lineage.json", "manifest.json", "metadata.json"})
#: Browse page order: unsplit files, then train → val → dev → test, then other splits.
_SPLIT_ORDER = {"": 0, "train": 1, "val": 2, "dev": 3, "test": 4}


def _stat_rows(rows: list[dict], dataset_path: Path) -> None:
    """Fill ``modified_at`` (and a missing ``size``) from the filesystem — one page only."""
    for r in rows:
        rel = str(r["path"]).replace("\\", "/")
        if rel.startswith("/") or ".." in rel.split("/"):
            continue
        try:
            st = (dataset_path / rel).stat()
        except OSError:
            continue
        r["modified_at"] = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
        if r.get("size") is None:
            r["size"] = st.st_size


def _enrich_file_rows_split_label(rows: list[dict], dataset_path: Path) -> list[dict]:
    """Attach split/label from labels.csv or path shape (train|val|test/<label>/…)."""
    by_rel: dict[str, tuple[str, str]] = {}
    labels_file = dataset_path / "labels.csv"
    if labels_file.exists():
        try:
            with open(labels_file, newline="") as f:
                for row in csv.DictReader(f):
                    rel = str(row.get("path") or "").replace("\\", "/")
                    split = row.get("split")
                    label = row.get("label")
                    if rel and split and label:
                        by_rel[rel] = (str(split), str(label))
        except OSError:
            pass
    out: list[dict] = []
    for row in rows:
        r = dict(row)
        path = str(r.get("path") or "").replace("\\", "/")
        if path in by_rel:
            r["split"], r["label"] = by_rel[path]
        else:
            parts = path.split("/")
            if len(parts) >= 3 and parts[0] in {"train", "val", "test", "dev"}:
                r["split"], r["label"] = parts[0], parts[1]
        out.append(r)
    return out


def _file_rows(raw, *, include_hash: bool = True) -> list[dict]:
    """Normalize manifest ``files`` to browse/integrity rows.

    Always a list (never a dict/None) so clients can iterate safely.
    When ``include_hash`` is false, ``sha256`` is stripped from each row.
    """
    rows: list[dict] = []
    if isinstance(raw, dict):
        raw = [{"path": k, **(v if isinstance(v, dict) else {"sha256": v})} for k, v in raw.items()]
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            item = {"path": item}
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or item.get("name") or "")
        if not path:
            continue
        row = dict(item)
        row["path"] = path
        row["name"] = str(item.get("name") or path.rsplit("/", 1)[-1])
        size = item.get("size")
        row["size"] = int(size) if isinstance(size, (int, float)) else None
        row.setdefault("kind", file_kind(path))
        if not include_hash:
            row.pop("sha256", None)
        rows.append(row)
    return rows


@router.delete("/outputs/{project:path}/{version}", summary="Delete an output dataset version")
def delete_output_dataset(
    project: str,
    version: str,
    request: Request,
    force: bool = Query(False, description="Admin force-delete when referenced (audited)"),
):
    """Delete a version dir under datasets/output; remove the project if empty.

    DATA-VER-006: referenced versions return 409 unless ``force=true``.
    """
    from app.core.mlops.dataset_versions import find_references

    output_root = _output_root()
    dataset_path = _version_dir(project, version)
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail="Dataset not found")

    refs = find_references(project, version)
    if refs and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "conflict",
                "code": "conflict",
                "message": f"Dataset version {project}/{version} is referenced",
                "references": refs,
            },
        )

    shutil.rmtree(dataset_path)
    parts = _project_parts(project)
    # Remove now-empty parents (project dir; for snapshots also _inputs/).
    for depth in range(len(parts), 0, -1):
        try:
            parent = _safe_child(output_root, *parts[:depth])
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        except (OSError, HTTPException):
            break
    _audit(
        request,
        "dataset.version_delete",
        "dataset_version",
        f"{project}/{version}",
        {"force": bool(force), "references": refs},
    )
    return {"deleted": f"{project}/{version}", "forced": bool(force)}


# ── Merge ─────────────────────────────────────────────────────────────────────

class MergeRequest(BaseModel):
    sources: list[dict]       # [{project: str, version: str}]
    target_project: str
    target_version: str
    overwrite: bool = False   # replace an existing, unreferenced target version


# Per-version metadata regenerated by merge — never copied from sources.
_MERGE_REGENERATED = frozenset({"manifest.json", "labels.csv", "lineage.json"})


def _ensure_project_json(project_root: Path, name: str) -> None:
    """Create project.json so the Projects sidebar discovers the target."""
    import json

    if (project_root / "project.json").exists():
        return
    try:
        project_root.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        (project_root / "project.json").write_text(
            json.dumps(
                {"name": name, "status": "draft", "created_at": now, "updated_at": now, "versions": []},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/merge", summary="Merge datasets")
def merge_datasets(body: MergeRequest, request: Request):
    """Copy every file of several source versions into a NEW target version.

    * Existing target versions are immutable: 409 unless ``overwrite=true``,
      and even then 409 when the target is referenced by runs / packages.
    * All files are copied (not only audio) with relative paths preserved; a
      path already taken by an earlier source with different bytes is stored
      as ``<stem>__<project>_<version><ext>`` and reported under ``renamed``.
    * ``labels.csv`` is rebuilt for audio files, ``lineage.json`` records the
      sources and ``manifest.json`` (sha256 per file) is recomputed.
    """
    import json

    from app.core.mlops.dataset_versions import (
        find_references,
        next_free_version,
        read_manifest,
        version_has_content,
        write_manifest,
    )

    if not body.sources:
        raise HTTPException(status_code=422, detail="sources must not be empty")
    if not _VERSION_RE.match(body.target_version):
        raise HTTPException(
            status_code=422,
            detail="target_version must match vN / vN.N.N (e.g. v1, v1.0.0)",
        )
    if "/" in body.target_project or body.target_project == INPUT_SNAPSHOT_PROJECT:
        raise HTTPException(status_code=422, detail="Invalid target_project")

    output_root = _output_root()
    # Jail the target project BEFORE any mkdir/write (P1-25).
    project_root = _safe_child(output_root, body.target_project)
    target_dir = _safe_child(output_root, body.target_project, body.target_version)

    if version_has_content(target_dir):
        if not body.overwrite:
            suggestion = next_free_version(project_root, body.target_version)
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "conflict",
                    "code": "version_exists",
                    "message": (
                        f"{body.target_project}/{body.target_version} already exists and dataset "
                        f"versions are immutable — merge into {suggestion} or pass overwrite=true"
                    ),
                    "suggested_version": suggestion,
                },
            )
        refs = find_references(body.target_project, body.target_version)
        if refs:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "conflict",
                    "code": "conflict",
                    "message": (
                        f"{body.target_project}/{body.target_version} is referenced by runs or "
                        "packages and cannot be overwritten — pick a new target_version"
                    ),
                    "references": refs,
                },
            )

    # Resolve sources up front so a bad request never touches the target.
    errors: list[str] = []
    resolved: list[tuple[str, str, Path]] = []
    for source in body.sources:
        src_project = str(source.get("project") or "")
        src_version = str(source.get("version") or "")
        if not src_project or not src_version:
            errors.append(f"Invalid source entry: {source}")
            continue
        try:
            src_dir = _version_dir(src_project, src_version)
        except HTTPException:
            errors.append(f"Invalid source path: {src_project}/{src_version}")
            continue
        if not src_dir.exists():
            errors.append(f"Source not found: {src_project}/{src_version}")
            continue
        if src_dir.resolve() == target_dir.resolve():
            errors.append(f"Source equals target: {src_project}/{src_version}")
            continue
        resolved.append((src_project, src_version, src_dir))

    _ensure_project_json(project_root, body.target_project)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    files_copied = 0
    renamed: list[dict[str, str]] = []
    label_rows: list[dict] = []
    lineage_sources: list[dict[str, Any]] = []
    from app.core.mlops.dataset_inputs import sha256_file

    for src_project, src_version, src_dir in resolved:
        try:
            src_hash = read_manifest(src_dir, ensure=True, enforce_sha256=True).get("content_hash")
        except Exception:
            src_hash = None
        lineage_sources.append({"project": src_project, "version": src_version, "content_hash": src_hash})
        src_label_map: dict[str, dict] = {}
        src_labels = src_dir / "labels.csv"
        if src_labels.exists():
            with open(src_labels, newline="") as f:
                for row in csv.DictReader(f):
                    rel_path = (row.get("path") or "").replace("\\", "/")
                    # Normalize version-prefixed paths from older exporters.
                    prefix = f"{src_version}/"
                    if rel_path.startswith(prefix):
                        rel_path = rel_path[len(prefix):]
                    if rel_path:
                        src_label_map[rel_path] = row
        for src_file, rel_s in iter_files(src_dir, jail=output_root):
            if "/" not in rel_s and rel_s in _MERGE_REGENERATED:
                continue
            dst = target_dir / rel_s
            if dst.exists():
                if dst.stat().st_size == src_file.stat().st_size and sha256_file(dst) == sha256_file(src_file):
                    continue
                stem, ext = os.path.splitext(dst.name)
                tag = re.sub(r"[^\w\-]", "_", f"{src_project}_{src_version}")
                dst = dst.with_name(f"{stem}__{tag}{ext}")
                renamed.append({"from": f"{src_project}/{src_version}/{rel_s}", "to": dst.relative_to(target_dir).as_posix()})
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_file), str(dst))
            files_copied += 1
            out_rel = dst.relative_to(target_dir).as_posix()
            row = src_label_map.get(rel_s)
            if row:
                label_rows.append(
                    {
                        "id": len(label_rows),
                        "path": out_rel,
                        "label": row.get("label") or "unknown",
                        "split": row.get("split") or "train",
                    }
                )
            elif file_kind(out_rel) == "audio":
                parts = Path(out_rel).parts
                split = parts[0] if len(parts) > 2 else "train"
                label = parts[1] if len(parts) > 2 else (parts[0] if len(parts) > 1 else "unknown")
                label_rows.append({"id": len(label_rows), "path": out_rel, "label": label, "split": split})

    labels_csv = target_dir / "labels.csv"
    with open(labels_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "path", "label", "split"])
        writer.writeheader()
        writer.writerows(label_rows)
    now = datetime.now(timezone.utc).isoformat()
    (target_dir / "lineage.json").write_text(
        json.dumps(
            {"version": body.target_version, "merged_from": lineage_sources, "timestamp": now, "node_type": "merge"},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    from app.core.mlops.dataset_versions import compute_manifest

    man = compute_manifest(target_dir)
    man["source"] = {"kind": "merge", "sources": lineage_sources}
    man["created_at"] = now
    write_manifest(target_dir, man)
    _audit(
        request,
        "dataset.merge",
        "dataset_version",
        f"{body.target_project}/{body.target_version}",
        {
            "sources": lineage_sources,
            "files_copied": files_copied,
            "renamed": len(renamed),
            "content_hash": man.get("content_hash"),
            "overwrite": bool(body.overwrite),
            "errors": errors,
        },
    )
    return {
        "project": body.target_project,
        "version": body.target_version,
        "target": f"{body.target_project}/{body.target_version}",
        "files_copied": files_copied,
        "renamed": renamed,
        "errors": errors,
        "labels_written": len(label_rows),
        "content_hash": man.get("content_hash"),
    }
