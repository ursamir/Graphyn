# app/mcp/handlers/data_ops.py
"""MCP tools for dataset versions (Wave B leftover from Wave A §21.3).

upload_dataset_file shares app.core.mlops.dataset_inputs with the REST upload
(allowlist, sha256, archive caps) and records a ``dataset.upload`` audit event.

project / version arguments are validated (project-name regex, ``v<N>``
version regex, resolved-under-datasets/output) before any filesystem access.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _err(error_type: str, message: str) -> dict[str, Any]:
    return {"error": True, "error_type": error_type, "message": message}


_SAFE_PROJECT_RE = re.compile(r"^[\w\-]{1,128}$")
_SAFE_VERSION_RE = re.compile(r"^v\d+(\.\d+)*$")


def _safe_dataset_path(project: str, version: str | None = None) -> Path:
    """Resolve datasets_output_dir()/project[/version] or raise ValueError.

    Mirrors ProjectManager._validate_name and the dataset version regex, then
    checks the resolved path stays under the datasets/output root (no ``../``).
    """
    from app.core.config import datasets_output_dir

    if not _SAFE_PROJECT_RE.fullmatch(project or ""):
        raise ValueError(f"Invalid project name {project!r}")
    if version is not None and not _SAFE_VERSION_RE.fullmatch(version or ""):
        raise ValueError(f"Invalid version {version!r} (expected v<N>[.<N>...])")
    base = datasets_output_dir()
    path = base / project / version if version is not None else base / project
    root = base.resolve()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("Dataset path escapes the datasets/output root")
    return path


def _meta_props() -> dict[str, Any]:
    return {
        "_meta": {
            "type": "object",
            "properties": {"auth_token": {"type": "string"}},
        }
    }


LIST_DATASET_VERSIONS_DESCRIPTION = (
    "List dataset versions for a project under datasets/output."
)
LIST_DATASET_VERSIONS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        **_meta_props(),
    },
    "required": ["project"],
    "additionalProperties": False,
}


def list_dataset_versions_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.core.mlops.dataset_versions import read_manifest

    args = arguments or {}
    project = str(args.get("project") or "").strip()
    if not project:
        return _err("validation_failed", "project is required")
    try:
        root = _safe_dataset_path(project)
    except ValueError as exc:
        return _err("validation_failed", str(exc))
    if not root.is_dir():
        return {"project": project, "versions": []}
    version_re = _SAFE_VERSION_RE
    versions = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or not version_re.match(child.name):
            continue
        try:
            man = read_manifest(child, ensure=False, enforce_sha256=False)
            content_hash = man.get("content_hash") or man.get("sha256")
        except Exception:
            content_hash = None
        versions.append({"version": child.name, "content_hash": content_hash})
    return {"project": project, "versions": versions}


GET_DATASET_VERSION_DESCRIPTION = (
    "Get a dataset version detail including files and content_hash."
)
GET_DATASET_VERSION_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project": {"type": "string"},
        "version": {"type": "string"},
        **_meta_props(),
    },
    "required": ["project", "version"],
    "additionalProperties": False,
}


def get_dataset_version_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from datetime import datetime, timezone
    from app.core.mlops.dataset_versions import read_manifest

    args = arguments or {}
    project = str(args.get("project") or "").strip()
    version = str(args.get("version") or "").strip()
    if not project or not version:
        return _err("validation_failed", "project and version are required")
    try:
        path = _safe_dataset_path(project, version)
    except ValueError as exc:
        return _err("validation_failed", str(exc))
    if not path.is_dir():
        return _err("not_found", f"Dataset version {project}/{version} not found")
    man = read_manifest(path, ensure=True, enforce_sha256=True)
    created_at = None
    try:
        created_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        pass
    return {
        "project": project,
        "version": version,
        "files": man.get("files") or [],
        "content_hash": man.get("content_hash") or man.get("sha256"),
        "created_at": created_at,
    }


UPLOAD_DATASET_FILE_DESCRIPTION = (
    "Upload a file (audio, csv, json, txt, md, pdf, png/jpg, parquet; zip/tar unpacked) "
    "into datasets/input/{label}/ — sha256 recorded, audited as dataset.upload."
)
UPLOAD_DATASET_FILE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "Input label directory name."},
        "filename": {"type": "string"},
        "content_base64": {
            "type": "string",
            "description": "File bytes as base64 (small files only).",
        },
        **_meta_props(),
    },
    "required": ["label", "filename", "content_base64"],
    "additionalProperties": False,
}


def upload_dataset_file_handler(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Store one base64 payload under datasets/input/{label}/ (audited).

    Same allowlist / sha256 / duplicate handling as POST /data/inputs/upload
    (app.core.mlops.dataset_inputs.UploadSession); zip/tar payloads are
    unpacked with the same caps.
    """
    import base64
    import io

    from app.core.config import datasets_input_dir
    from app.core.mlops.dataset_inputs import UploadError, UploadSession, audit_file_meta, is_valid_label

    args = arguments or {}
    label = str(args.get("label") or "").strip()
    filename = str(args.get("filename") or "").strip()
    b64 = str(args.get("content_base64") or "")
    if not label or not filename or not b64:
        return _err("validation_failed", "label, filename, content_base64 required")
    if not is_valid_label(label):
        return _err("validation_failed", "invalid label")
    safe = Path(filename.replace("\\", "/")).name
    if not safe:
        return _err("validation_failed", "invalid filename")
    try:
        data = base64.b64decode(b64, validate=True)
    except Exception:
        return _err("validation_failed", "content_base64 is not valid base64")
    if len(data) > 25 * 1024 * 1024:
        return _err("validation_failed", "file too large for MCP upload (25MB max)")
    root = datasets_input_dir()
    root.mkdir(parents=True, exist_ok=True)
    session = UploadSession(input_root=root, target_label=label)
    try:
        session.add_files([(safe, io.BytesIO(data))])
    except UploadError as exc:
        session.rollback()
        return _err("validation_failed", exc.message)
    summary = session.summary()
    if not summary["files"]:
        reason = summary["skipped"][0]["reason"] if summary["skipped"] else "nothing stored"
        if summary["skipped"] and reason.startswith("identical"):
            return {"ok": True, "label": label, "filename": safe, "duplicate": True, "size": len(data)}
        return _err("validation_failed", reason)
    try:
        from app.core.trust.audit import record_audit

        record_audit(
            actor=str(args.get("actor") or "mcp"),
            action="dataset.upload",
            resource_type="dataset_input",
            resource_id=",".join(summary["labels"]) or label,
            meta={
                "label": label,
                "labels": summary["labels"],
                "count": summary["count"],
                "total_bytes": summary["total_bytes"],
                "content_hash": summary["content_hash"],
                "via": "mcp",
                **audit_file_meta(summary["files"]),
            },
        )
    except Exception:
        pass
    first = summary["files"][0]
    return {
        "ok": True,
        "label": first["label"],
        "filename": first["path"].rsplit("/", 1)[-1],
        "path": str(root / first["path"]),
        "size": first["size"],
        "sha256": first["sha256"],
        "files": summary["files"],
    }
