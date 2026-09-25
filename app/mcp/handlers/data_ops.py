# app/mcp/handlers/data_ops.py
"""MCP tools for dataset versions (Wave B leftover from Wave A §21.3)."""
from __future__ import annotations

from typing import Any


def _err(error_type: str, message: str) -> dict[str, Any]:
    return {"error": True, "error_type": error_type, "message": message}


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
    from app.core.config import datasets_output_dir
    from app.core.dataset_versions import read_manifest
    import re

    args = arguments or {}
    project = str(args.get("project") or "").strip()
    if not project:
        return _err("validation_failed", "project is required")
    root = datasets_output_dir() / project
    if not root.is_dir():
        return {"project": project, "versions": []}
    version_re = re.compile(r"^v\d+(\.\d+)*$")
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
    from app.core.config import datasets_output_dir
    from app.core.dataset_versions import read_manifest

    args = arguments or {}
    project = str(args.get("project") or "").strip()
    version = str(args.get("version") or "").strip()
    if not project or not version:
        return _err("validation_failed", "project and version are required")
    path = datasets_output_dir() / project / version
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
    "Upload a text/binary payload into datasets/input/{label}/ (sanitized name)."
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
    import base64
    import re
    from datetime import datetime, timezone
    from pathlib import Path

    from app.core.config import datasets_input_dir

    args = arguments or {}
    label = str(args.get("label") or "").strip()
    filename = str(args.get("filename") or "").strip()
    b64 = str(args.get("content_base64") or "")
    if not label or not filename or not b64:
        return _err("validation_failed", "label, filename, content_base64 required")
    if not re.match(r"^[A-Za-z0-9_-]+$", label):
        return _err("validation_failed", "invalid label")
    # Sanitize filename
    safe = Path(filename).name
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", safe)
    if not safe:
        return _err("validation_failed", "invalid filename")
    try:
        data = base64.b64decode(b64, validate=True)
    except Exception:
        return _err("validation_failed", "content_base64 is not valid base64")
    if len(data) > 25 * 1024 * 1024:
        return _err("validation_failed", "file too large for MCP upload (25MB max)")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_name = f"{stamp}_{safe}"
    dest_dir = datasets_input_dir() / label
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / out_name
    dest.write_bytes(data)
    return {
        "ok": True,
        "label": label,
        "filename": out_name,
        "path": str(dest),
        "size": len(data),
    }
