# app/core/artifacts/file_tree.py
"""
Bounded Context:  BC6 — Artifacts
Responsibility:   Platform-generic ``file_tree`` artifact type for path
                  side-effects announced via ``Node.publish_files``.
Owns:             FileTreeHandler, register_file_tree_serializer,
                  file_tree_payload, inventory schema ``file_tree/v1``.
Public Surface:   FileTreeHandler, register_file_tree_serializer,
                  file_tree_payload, FILE_TREE_FORMAT.
Must NOT:         Know about labels.csv, WAV, video codecs, or any domain
                  layout. Must not import app.domain or app.models.
Dependencies:     app.core.artifacts.artifact_serializer, stdlib.
Reason To Change: inventory.json schema evolves, or listing needs richer
                  metadata fields on entries.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.artifacts.artifact_serializer import FileListing, FileListingEntry

logger = logging.getLogger(__name__)

FILE_TREE_FORMAT = "file_tree/v1"
ARTIFACT_TYPE = "file_tree"


def file_tree_payload(published: dict[str, Any]) -> dict[str, Any]:
    """Normalise a ``Node.publish_files`` queue entry into a registerable value."""
    root = str(published.get("root") or "").replace("\\", "/").strip()
    if not root:
        raise ValueError("file_tree payload requires a non-empty root")
    raw_files = published.get("files") or []
    files: list[dict[str, Any]] = []
    if isinstance(raw_files, list):
        for item in raw_files:
            if isinstance(item, str) and item.strip():
                files.append({"path": item.replace("\\", "/").lstrip("./")})
            elif isinstance(item, dict):
                path = item.get("path")
                if isinstance(path, str) and path.strip():
                    entry: dict[str, Any] = {
                        "path": path.replace("\\", "/").lstrip("./")
                    }
                    size = item.get("size")
                    if isinstance(size, (int, float)) and size >= 0:
                        entry["size"] = int(size)
                    name = item.get("name")
                    if isinstance(name, str) and name.strip():
                        entry["name"] = name
                    files.append(entry)
    total = published.get("total")
    if not isinstance(total, int) or total < 0:
        total = len(files)
    return {
        "format": FILE_TREE_FORMAT,
        "root": root,
        "total": int(total),
        "files": files,
    }


class FileTreeHandler:
    """Serialize / list a published file tree (external jailed root + inventory)."""

    def serialize(self, data: Any, dest_dir: Path) -> None:
        payload = file_tree_payload(data if isinstance(data, dict) else {})
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / "inventory.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def deserialize(self, src_dir: Path) -> Any | None:
        path = src_dir / "inventory.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("file_tree: corrupt inventory at %s (%s)", path, exc)
            return None
        return data if isinstance(data, dict) else None

    def compute_content_hash_input(self, data: Any) -> str:
        payload = file_tree_payload(data if isinstance(data, dict) else {})
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def infer_type(self, value: Any) -> str | None:
        if not isinstance(value, dict):
            return None
        fmt = value.get("format")
        if fmt == FILE_TREE_FORMAT:
            return ARTIFACT_TYPE
        # Accept publish_files-shaped dicts without format yet.
        if "root" in value and "files" in value and "format" not in value:
            return ARTIFACT_TYPE
        return None

    def list_files(self, src_dir: Path) -> FileListing | None:
        inventory = self.deserialize(src_dir)
        if not isinstance(inventory, dict):
            return None
        root_raw = str(inventory.get("root") or "").strip()
        if not root_raw:
            return None
        try:
            from app.core.config import project_dir

            root = Path(root_raw)
            if not root.is_absolute():
                text = root_raw.replace("\\", "/").lstrip("./")
                if text.startswith("workspace/"):
                    text = text[len("workspace/") :]
                root = (project_dir() / text).resolve()
            else:
                root = root.resolve()
        except OSError:
            return None

        raw_files = inventory.get("files") if isinstance(inventory.get("files"), list) else []
        total = inventory.get("total")
        if not isinstance(total, int) or total < 0:
            total = len(raw_files)

        entries: list[FileListingEntry] = []
        for item in raw_files:
            if not isinstance(item, dict):
                continue
            rel = item.get("path")
            if not isinstance(rel, str) or not rel.strip():
                continue
            abs_path = root / rel.replace("\\", "/").lstrip("./")
            size = item.get("size") if isinstance(item.get("size"), int) else None
            name = item.get("name") if isinstance(item.get("name"), str) else abs_path.name
            entries.append(FileListingEntry(path=abs_path, size=size, name=name))

        return FileListing(total=max(total, len(raw_files)), entries=entries)


def register_file_tree_serializer() -> None:
    """Register the platform ``file_tree`` handler (idempotent)."""
    from app.core.artifacts.artifact_serializer import get_serializer_registry

    registry = get_serializer_registry()
    registry.register(ARTIFACT_TYPE, FileTreeHandler())
    logger.debug("FileTreeHandler registered for artifact_type=%r", ARTIFACT_TYPE)
