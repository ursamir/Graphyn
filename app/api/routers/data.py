# app/api/routers/data.py
"""
Bounded Context:  REST API Layer
Responsibility:   HTTP endpoints for input/output dataset management and
                  audio file uploads.
Owns:             Route definitions for GET/POST /data/inputs,
                  DELETE /data/inputs/{label},
                  GET /data/outputs, DELETE /data/outputs/{project}/{version},
                  POST /data/merge.
Public Surface:   FastAPI router — mounted at /api/v1 in app/api/main.py
Must NOT:         Contain dataset storage logic — delegate to filesystem
                  helpers and config path functions.
Dependencies:     fastapi, app.core.config, stdlib (csv, os, datetime,
                  pathlib).
Reason To Change: New data endpoint added, or upload/merge behaviour changes.
"""
from __future__ import annotations

import csv
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.config import datasets_input_dir as _datasets_input_dir
from app.core.config import datasets_output_dir as _datasets_output_dir

router = APIRouter(prefix="/data", tags=["data"])

# Align with ProjectManager._VERSION_RE — exclude snapshots/ and junk dirs.
_VERSION_RE = re.compile(r"^v\d+(\.\d+)*$")

SUPPORTED_AUDIO_EXTENSIONS = (".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac")


def _input_root() -> Path:
    """Return the input datasets directory, resolved from GRAPHYN_PROJECT_DIR."""
    return _datasets_input_dir()


def _output_root() -> Path:
    """Return the output datasets directory, resolved from GRAPHYN_PROJECT_DIR."""
    return _datasets_output_dir()


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
    allow_external = os.environ.get("GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS", "").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if allow_external:
        return path
    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid path: {exc}") from exc
    if not resolved.is_relative_to(resolved_root):
        raise HTTPException(status_code=400, detail="Path is outside workspace")
    return resolved


# ── Input datasets ────────────────────────────────────────────────────────────

@router.get("/inputs", summary="List input dataset labels")
def list_input_datasets():
    """Return a list of input dataset labels with file counts.

    Labels that resolve outside the input root (external symlinks) are still
    listed with ``accessible: false`` so the UI does not pretend they are
    browseable unless ``GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS`` is enabled.
    """
    input_root = _input_root()
    if not input_root.exists():
        return []
    labels = []
    for label in sorted(os.listdir(input_root)):
        label_path = input_root / label
        if not label_path.is_dir():
            continue
        accessible = True
        try:
            _safe_child(input_root, label)
        except HTTPException:
            accessible = False
        count = sum(
            1 for _, _, files in os.walk(label_path, followlinks=True)
            for f in files if f.lower().endswith(SUPPORTED_AUDIO_EXTENSIONS)
        )
        labels.append({"label": label, "file_count": count, "accessible": accessible})
    return labels


_INPUT_MEDIA_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
}


@router.get("/inputs/file", summary="Download an input dataset file")
def download_input_file(
    path: str = Query(..., description="Path relative to datasets/input (may be nested)"),
):
    """Serve an input audio file via path-jailed ``_safe_child``.

    Nested labels may use intermediate directory symlinks **within** the input
    root (resolved target must stay under the root unless
    ``GRAPHYN_DATA_ALLOW_EXTERNAL_SYMLINKS=1``). Static ``/input-files`` does
    not follow symlinks; prefer this API for nested trees.
    """
    rel = (path or "").replace("\\", "/").lstrip("/")
    parts = [p for p in rel.split("/") if p]
    if not parts or any(p in {"", ".", ".."} for p in parts):
        raise HTTPException(status_code=400, detail="Invalid path")
    file_path = _safe_child(_input_root(), *parts)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    media = _INPUT_MEDIA_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path=str(file_path),
        media_type=media,
        filename=file_path.name,
    )


@router.get("/inputs/{label}", summary="List files in an input dataset label")
def get_input_dataset(label: str):
    """Return a list of audio files for a specific input label."""
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

    files = []
    for root, _, filenames in os.walk(label_path, followlinks=True):
        for f in filenames:
            if f.lower().endswith(SUPPORTED_AUDIO_EXTENSIONS):
                abs_path = os.path.join(root, f)
                rel_path = os.path.relpath(abs_path, input_root).replace("\\", "/")
                entry = {"path": rel_path, "label": label}
                # Size and mtime come from a stat on a path os.walk has already
                # surfaced, so the browser can show what a file browser should
                # show. Previously every record carried only its path plus the
                # label the caller already asked for, leaving the UI with one
                # constant column and nothing to sort by. Never fatal: a file
                # that vanished or is unreadable mid-walk drops its metadata
                # rather than failing the whole listing.
                try:
                    st = os.stat(abs_path)
                    entry["size_bytes"] = st.st_size
                    entry["modified_at"] = datetime.fromtimestamp(
                        st.st_mtime, tz=timezone.utc
                    ).isoformat()
                except OSError:
                    pass
                files.append(entry)
    return files


@router.delete("/inputs/{label}", summary="Delete an input dataset label")
def delete_input_dataset(label: str):
    """Delete the input label directory, jailed under datasets/input."""
    import shutil

    input_root = _input_root()
    label_path = _safe_child(input_root, label)
    if not label_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Label '{label}' not found")
    shutil.rmtree(label_path)
    return {"deleted": label}


_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
_UPLOAD_CHUNK_BYTES = 1024 * 1024


@router.post("/inputs/upload", summary="Upload an audio file")
def upload_file(request: Request, file: UploadFile = File(...)):
    """Upload an audio file to the uploads input directory."""
    ext = os.path.splitext(file.filename or "recording.wav")[1].lower() or ".wav"
    if ext not in SUPPORTED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported audio extension")

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Upload too large")
        except ValueError:
            pass

    target_dir = _input_root() / "uploads"
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = datetime.now(timezone.utc).strftime("upload_%Y%m%d_%H%M%S_%f") + ext
    out_path = target_dir / safe_name

    total = 0
    with out_path.open("wb") as out_f:
        while True:
            chunk = file.file.read(_UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_UPLOAD_BYTES:
                out_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Upload too large")
            out_f.write(chunk)

    return {"file_path": str(out_path), "filename": safe_name}


# ── Output datasets ───────────────────────────────────────────────────────────

@router.get("/outputs", summary="List output dataset projects")
def list_output_datasets(
    envelope: str | None = Query(None, description="Set to 1 for list envelope"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Return a list of output dataset projects and their versions.

    Version dirs must match ProjectManager ``_VERSION_RE`` (e.g. v1, v1.0.0).
    ``snapshots/`` and other non-version directories are excluded.
    Pass ``?envelope=1`` for API-PAGE-001 list envelope (additive).
    """
    from app.api.pagination import maybe_envelope, parse_envelope_flag

    output_root = _output_root()
    result = []
    if output_root.exists():
        for project in sorted(os.listdir(output_root)):
            project_path = output_root / project
            if not project_path.is_dir():
                continue
            versions = sorted(
                v for v in os.listdir(project_path)
                if (project_path / v).is_dir() and bool(_VERSION_RE.match(v))
            )
            result.append({"project": project, "versions": versions})
    total = len(result)
    page = result[offset : offset + limit]
    return maybe_envelope(
        page,
        envelope=parse_envelope_flag(envelope),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/outputs/{project}/{version}", summary="Get an output dataset")
def get_output_dataset(project: str, version: str):
    """Return dataset version detail with files + content_hash (DATA-VER-002)."""
    from app.core.dataset_versions import read_manifest

    output_root = _output_root()
    dataset_path = _safe_child(output_root, project, version)
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail="Dataset not found")

    man = read_manifest(dataset_path, ensure=True, enforce_sha256=True)
    files = list(man.get("files") or [])
    created_at = None
    try:
        created_at = datetime.fromtimestamp(
            dataset_path.stat().st_mtime, tz=timezone.utc
        ).isoformat()
    except OSError:
        created_at = None

    samples = []
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
    else:
        for split in ["train", "val", "test"]:
            split_path = dataset_path / split
            if not split_path.exists():
                continue
            for label in os.listdir(split_path):
                label_path = split_path / label
                if not label_path.is_dir():
                    continue
                for f in os.listdir(label_path):
                    if f.lower().endswith(".wav"):
                        samples.append({
                            "path": f"{project}/{version}/{split}/{label}/{f}",
                            "split": split,
                            "label": label,
                        })

    return {
        "project": project,
        "version": version,
        "files": files,
        "content_hash": man.get("content_hash") or man.get("sha256"),
        "created_at": created_at,
        "samples": samples,
    }


@router.delete("/outputs/{project}/{version}", summary="Delete an output dataset version")
def delete_output_dataset(
    project: str,
    version: str,
    request: Request,
    force: bool = Query(False, description="Admin force-delete when referenced (audited)"),
):
    """Delete a version dir under datasets/output; remove the project if empty.

    DATA-VER-006: referenced versions return 409 unless ``force=true``.
    """
    import shutil
    from app.api.actor import resolve_actor
    from app.core.dataset_versions import find_references

    output_root = _output_root()
    dataset_path = _safe_child(output_root, project, version)
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
    project_path = _safe_child(output_root, project)
    try:
        leftover = list(project_path.iterdir()) if project_path.is_dir() else []
        if project_path.is_dir() and not leftover:
            project_path.rmdir()
    except OSError:
        pass
    try:
        from app.core.audit import record_audit

        record_audit(
            actor=resolve_actor(request),
            action="dataset.version_delete",
            resource_type="dataset_version",
            resource_id=f"{project}/{version}",
            meta={"force": bool(force), "references": refs},
            request_id=getattr(request.state, "request_id", None),
        )
    except Exception:
        pass
    return {"deleted": f"{project}/{version}", "forced": bool(force)}


@router.get("/outputs/{project}/{version}/stats", summary="Get dataset statistics")
def get_dataset_stats(project: str, version: str):
    """Return split counts and per-label distribution for a dataset."""
    output_root = _output_root()
    dataset_path = _safe_child(output_root, project, version)
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail="Dataset not found")

    labels_file = dataset_path / "labels.csv"
    if not labels_file.exists():
        raise HTTPException(status_code=404, detail="labels.csv not found")

    splits: dict[str, dict[str, int]] = {}
    total = 0
    with open(labels_file, newline="") as f:
        for row in csv.DictReader(f):
            split = row.get("split", "unknown")
            label = row.get("label", "unknown")
            splits.setdefault(split, {})
            splits[split][label] = splits[split].get(label, 0) + 1
            total += 1

    return {"project": project, "version": version, "total": total, "splits": splits}


# ── Merge ─────────────────────────────────────────────────────────────────────

class MergeRequest(BaseModel):
    sources: list[dict]       # [{project: str, version: str}]
    target_project: str
    target_version: str


@router.post("/merge", summary="Merge datasets")
def merge_datasets(body: MergeRequest):
    """Copy audio files from multiple source versions into a target version.

    Ensures ``project.json`` exists on the target project (so Projects sidebar
    sees it) and writes/refreshes ``labels.csv`` under the target version.
    """
    import shutil

    from app.domain.project_manager import ProjectManager

    if not body.sources:
        raise HTTPException(status_code=422, detail="sources must not be empty")
    if not _VERSION_RE.match(body.target_version):
        raise HTTPException(
            status_code=422,
            detail="target_version must match vN / vN.N.N (e.g. v1, v1.0.0)",
        )

    output_root = _output_root()
    pm = ProjectManager()
    # Jail the target project BEFORE any mkdir/write (P1-25).
    try:
        project_root = _safe_child(output_root, body.target_project)
    except HTTPException:
        raise
    # Ensure project workspace exists for Projects sidebar discovery.
    # Prefer writing project.json under the (possibly patched) output root so
    # tests and alternate roots do not depend on ProjectManager's global path.
    if not (project_root / "project.json").exists():
        try:
            project_root.mkdir(parents=True, exist_ok=True)
            now = datetime.now(timezone.utc).isoformat()
            (project_root / "project.json").write_text(
                __import__("json").dumps(
                    {
                        "name": body.target_project,
                        "status": "draft",
                        "created_at": now,
                        "updated_at": now,
                        "versions": [],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    target_dir = _safe_child(output_root, body.target_project, body.target_version)
    target_dir.mkdir(parents=True, exist_ok=True)

    files_copied = 0
    errors = []
    label_rows: list[dict] = []

    for source in body.sources:
        src_project = source.get("project")
        src_version = source.get("version")
        if not src_project or not src_version:
            errors.append(f"Invalid source entry: {source}")
            continue
        try:
            src_dir = _safe_child(output_root, src_project, src_version)
        except HTTPException:
            errors.append(f"Invalid source path: {src_project}/{src_version}")
            continue
        if not src_dir.exists():
            errors.append(f"Source not found: {src_project}/{src_version}")
            continue
        src_labels = src_dir / "labels.csv"
        src_label_map: dict[str, dict] = {}
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
        for wav_file in src_dir.rglob("*.wav"):
            rel = wav_file.relative_to(src_dir)
            dst = target_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(wav_file), str(dst))
            files_copied += 1
            rel_s = str(rel).replace("\\", "/")
            row = src_label_map.get(rel_s)
            if row:
                label_rows.append(
                    {
                        "id": len(label_rows),
                        "path": rel_s,
                        "label": row.get("label") or "unknown",
                        "split": row.get("split") or "train",
                    }
                )
            else:
                parts = Path(rel_s).parts
                split = parts[0] if len(parts) > 0 else "train"
                label = parts[1] if len(parts) > 1 else "unknown"
                label_rows.append(
                    {
                        "id": len(label_rows),
                        "path": rel_s,
                        "label": label,
                        "split": split,
                    }
                )

    labels_csv = target_dir / "labels.csv"
    with open(labels_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "path", "label", "split"])
        writer.writeheader()
        writer.writerows(label_rows)

    from app.core.dataset_versions import write_manifest

    man = write_manifest(target_dir)
    return {
        "project": body.target_project,
        "version": body.target_version,
        "target": f"{body.target_project}/{body.target_version}",
        "files_copied": files_copied,
        "errors": errors,
        "labels_written": len(label_rows),
        "content_hash": man.get("content_hash"),
    }
