# app/models/model_artifact_serializer.py
"""
Bounded Context:  BC6 — Artifacts
Responsibility:   ArtifactSerializerRegistry handler for ModelArtifact that
                  persists metadata + an ArtifactRef role manifest. File bytes
                  are copied beside the manifest for on-disk run artifacts and
                  every path field round-trips via ``path_map``;
                  Mode B distributed transfer uses the same pack helpers via
                  ``app.core.distributed.transfer`` (pickle metadata + blobs).
Owns:             ModelArtifactHandler, register_model_artifact_serializer().
Public Surface:   register_model_artifact_serializer()
Must NOT:         Perform HTTP / distributed blob I/O.
Dependencies:     artifact_serializer, artifact_pack, model_artifact, artifact_ref.
Reason To Change: On-disk layout or manifest schema evolves.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.artifacts.artifact_serializer import FileListing, FileListingEntry

logger = logging.getLogger(__name__)

ARTIFACT_TYPE = "model_artifact"
MANIFEST_NAME = "model_artifact_manifest.json"


def _legacy_role_paths(refs: list[Any], files_dir: Path, metrics: dict[str, Any]) -> str:
    """model_artifact/v1 manifests (no ``path_map``): rebuild paths from roles."""
    model_path = ""
    by_role: dict[str, str] = {}
    for ref in refs:
        local = files_dir / (ref.relative_path or ref.filename or ref.role)
        if local.exists():
            by_role.setdefault(str(ref.role), str(local))
    if "keras_model" in by_role:
        metrics["keras_model_path"] = by_role["keras_model"]
    if "saved_model" in by_role:
        metrics["saved_model_path"] = by_role["saved_model"]
    if "labels" in by_role:
        metrics["labels_path"] = by_role["labels"]
    for role in ("saved_model", "keras_model", "pytorch_model", "other"):
        if role in by_role:
            model_path = by_role[role]
            break
    return model_path


class ModelArtifactHandler:
    """Serialize ModelArtifact metadata + role files for run-artifact storage."""

    def serialize(self, data: Any, dest_dir: Path) -> None:
        from app.core.artifacts.artifact_pack import (
            build_path_map,
            collect_path_bearing_roles,
            copy_refs_to_dir,
            without_copied_paths,
        )
        from app.models.model_artifact import ModelArtifact

        if isinstance(data, ModelArtifact):
            art = data
        elif isinstance(data, dict):
            art = ModelArtifact.model_validate(data)
        else:
            raise TypeError(f"ModelArtifactHandler expected ModelArtifact, got {type(data)!r}")

        dest_dir.mkdir(parents=True, exist_ok=True)
        wire_refs, src_to_rel = copy_refs_to_dir(collect_path_bearing_roles(art), dest_dir / "files")
        path_map = build_path_map(art, src_to_rel)
        meta = {
            "format": "model_artifact/v2",
            # Paths whose files were copied restore from ``path_map``; anything
            # else (e.g. a missing producer path) round-trips verbatim.
            "model_path": "" if "model_path" in path_map else str(art.model_path or ""),
            "labels": list(art.labels or []),
            "history": dict(art.history or {}),
            "metrics": without_copied_paths(dict(art.metrics or {}), "metrics", path_map),
            "path_map": path_map,
            "refs": wire_refs,
        }
        (dest_dir / MANIFEST_NAME).write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

    def deserialize(self, src_dir: Path) -> Any | None:
        from app.core.artifacts.artifact_pack import restore_path_map
        from app.models.artifact_ref import ArtifactRef
        from app.models.model_artifact import ModelArtifact

        path = src_dir / MANIFEST_NAME
        if not path.is_file():
            return None
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("model_artifact: corrupt manifest at %s (%s)", path, exc)
            return None
        files_dir = src_dir / "files"
        refs: list[ArtifactRef] = []
        for raw in meta.get("refs") or []:
            try:
                refs.append(ArtifactRef.model_validate(raw).model_copy(update={"source_path": ""}))
            except Exception:
                continue
        metrics = dict(meta.get("metrics") or {})
        model_path = str(meta.get("model_path") or "")
        if "path_map" in meta:
            for field, local in restore_path_map(meta.get("path_map") or {}, files_dir).items():
                if field == "model_path":
                    model_path = local
                elif field.startswith("metrics."):
                    metrics[field[len("metrics."):]] = local
        else:
            model_path = _legacy_role_paths(refs, files_dir, metrics) or model_path
        return ModelArtifact(
            model_path=model_path,
            labels=list(meta.get("labels") or []),
            history=dict(meta.get("history") or {}),
            metrics=metrics,
            refs=refs,
        )

    def compute_content_hash_input(self, data: Any) -> str:
        from app.core.artifacts.artifact_pack import content_digests, path_field_items

        if isinstance(data, dict):
            from app.models.model_artifact import ModelArtifact

            data = ModelArtifact.model_validate(data)
        path_keys = set(path_field_items(data))
        metrics = {
            k: v for k, v in dict(getattr(data, "metrics", None) or {}).items()
            if f"metrics.{k}" not in path_keys
        }
        payload = {
            "labels": list(getattr(data, "labels", None) or []),
            "metrics": metrics,
            "history": dict(getattr(data, "history", None) or {}),
            "content": content_digests(data),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    def infer_type(self, value: Any) -> str | None:
        name = type(value).__name__
        if name == "ModelArtifact":
            return ARTIFACT_TYPE
        if hasattr(value, "model_path") and hasattr(value, "labels") and hasattr(value, "metrics"):
            return ARTIFACT_TYPE
        return None

    def list_files(self, src_dir: Path) -> FileListing | None:
        files_dir = src_dir / "files"
        if not files_dir.is_dir():
            return None
        entries: list[FileListingEntry] = []
        for path in sorted(files_dir.rglob("*")):
            if path.is_file():
                try:
                    size = path.stat().st_size
                except OSError:
                    size = None
                entries.append(FileListingEntry(path=path, size=size, name=path.name))
        return FileListing(total=len(entries), entries=entries)


def register_model_artifact_serializer() -> None:
    """Register the ModelArtifact handler (idempotent)."""
    from app.core.artifacts.artifact_serializer import get_serializer_registry

    registry = get_serializer_registry()
    registry.register(ARTIFACT_TYPE, ModelArtifactHandler())
    logger.debug("ModelArtifactHandler registered for artifact_type=%r", ARTIFACT_TYPE)
