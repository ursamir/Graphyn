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

from fastapi import APIRouter, File, HTTPException, UploadFile
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
    for part in parts:
        if part in {"", ".", ".."} or "/" in part or "\\" in part:
            raise HTTPException(status_code=400, detail="Path is outside workspace")
    resolved_root = root.resolve()
    path = resolved_root.joinpath(*parts).resolve()
    if not path.is_relative_to(resolved_root):
        raise HTTPException(status_code=400, detail="Path is outside workspace")
    return path


# ── Input datasets ────────────────────────────────────────────────────────────

@router.get("/inputs", summary="List input dataset labels")
def list_input_datasets():
    """Return a list of input dataset labels with file counts."""
    input_root = _input_root()
    if not input_root.exists():
        return []
    labels = []
    for label in sorted(os.listdir(input_root)):
        label_path = input_root / label
        if not label_path.is_dir():
            continue
        count = sum(
            1 for _, _, files in os.walk(label_path)
            for f in files if f.lower().endswith(SUPPORTED_AUDIO_EXTENSIONS)
        )
        labels.append({"label": label, "file_count": count})
    return labels


@router.get("/inputs/{label}", summary="List files in an input dataset label")
def get_input_dataset(label: str):
    """Return a list of audio files for a specific input label."""
    input_root = _input_root()
    label_path = _safe_child(input_root, label)
    if not label_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Label '{label}' not found")

    files = []
    for root, _, filenames in os.walk(label_path):
        for f in filenames:
            if f.lower().endswith(SUPPORTED_AUDIO_EXTENSIONS):
                abs_path = os.path.join(root, f)
                rel_path = os.path.relpath(abs_path, input_root).replace("\\", "/")
                files.append({"path": rel_path, "label": label})
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


@router.post("/inputs/upload", summary="Upload an audio file")
async def upload_file(file: UploadFile = File(...)):
    """Upload an audio file to the uploads input directory."""
    ext = os.path.splitext(file.filename or "recording.wav")[1].lower() or ".wav"
    if ext not in SUPPORTED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported audio extension")

    target_dir = _input_root() / "uploads"
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = datetime.now(timezone.utc).strftime("upload_%Y%m%d_%H%M%S_%f") + ext
    out_path = target_dir / safe_name

    content = await file.read()
    out_path.write_bytes(content)

    return {"file_path": str(out_path), "filename": safe_name}


# ── Output datasets ───────────────────────────────────────────────────────────

@router.get("/outputs", summary="List output dataset projects")
def list_output_datasets():
    """Return a list of output dataset projects and their versions.

    Version dirs must match ProjectManager ``_VERSION_RE`` (e.g. v1, v1.0.0).
    ``snapshots/`` and other non-version directories are excluded.
    """
    output_root = _output_root()
    if not output_root.exists():
        return []
    result = []
    for project in sorted(os.listdir(output_root)):
        project_path = output_root / project
        if not project_path.is_dir():
            continue
        versions = sorted(
            v for v in os.listdir(project_path)
            if (project_path / v).is_dir() and bool(_VERSION_RE.match(v))
        )
        result.append({"project": project, "versions": versions})
    return result


@router.get("/outputs/{project}/{version}", summary="Get an output dataset")
def get_output_dataset(project: str, version: str):
    """Return the sample list for a specific project/version dataset."""
    output_root = _output_root()
    dataset_path = _safe_child(output_root, project, version)
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail="Dataset not found")

    labels_file = dataset_path / "labels.csv"
    if labels_file.exists():
        rows = []
        with open(labels_file, newline="") as f:
            for row in csv.DictReader(f):
                rel_path = row.get("path")
                split = row.get("split")
                label = row.get("label")
                if not rel_path or not split or not label:
                    continue
                rows.append({
                    "path": f"{project}/{version}/{rel_path}".replace("\\", "/"),
                    "split": split,
                    "label": label,
                })
        return rows

    # Fallback: walk split/label/file structure
    data = []
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
                    data.append({
                        "path": f"{project}/{version}/{split}/{label}/{f}",
                        "split": split,
                        "label": label,
                    })
    return data


@router.delete("/outputs/{project}/{version}", summary="Delete an output dataset version")
def delete_output_dataset(project: str, version: str):
    """Delete a version dir under datasets/output; remove the project if empty."""
    import shutil

    output_root = _output_root()
    dataset_path = _safe_child(output_root, project, version)
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail="Dataset not found")
    shutil.rmtree(dataset_path)
    project_path = _safe_child(output_root, project)
    try:
        leftover = list(project_path.iterdir()) if project_path.is_dir() else []
        if project_path.is_dir() and not leftover:
            project_path.rmdir()
    except OSError:
        pass
    return {"deleted": f"{project}/{version}"}


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
    # Ensure project workspace exists for Projects sidebar discovery.
    project_root = output_root / body.target_project
    if not (project_root / "project.json").exists():
        try:
            if project_root.exists():
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
            else:
                pm.create(body.target_project)
        except ValueError:
            # Name validation failure — fall through; copy may still succeed.
            project_root.mkdir(parents=True, exist_ok=True)

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

    return {
        "target": f"{body.target_project}/{body.target_version}",
        "files_copied": files_copied,
        "errors": errors,
        "labels_written": len(label_rows),
    }
