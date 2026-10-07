# app/models/deployment_artifact_serializer.py
"""
Bounded Context:  BC6 — Artifacts
Responsibility:   ArtifactSerializerRegistry handlers for DeploymentArtifact
                  and TFLiteArtifact (ArtifactRef role manifests).
Owns:             DeploymentArtifactHandler, TFLiteArtifactHandler,
                  register_deployment_artifact_serializer().
Public Surface:   register_deployment_artifact_serializer()
Must NOT:         Perform HTTP / distributed blob I/O.
Dependencies:     artifact_serializer, artifact_pack, deployment/tflite models.
Reason To Change: On-disk layout or manifest schema evolves.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.artifacts.artifact_serializer import FileListing, FileListingEntry

logger = logging.getLogger(__name__)

DEPLOYMENT_TYPE = "deployment_artifact"
TFLITE_TYPE = "tflite_artifact"
DEPLOYMENT_MANIFEST = "deployment_artifact_manifest.json"
TFLITE_MANIFEST = "tflite_artifact_manifest.json"


def _copy_roles(art: Any, files_dir: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Copy role files; return ``(wire_refs, path_map)``."""
    from app.core.artifacts.artifact_pack import build_path_map, collect_path_bearing_roles, copy_refs_to_dir

    wire_refs, src_to_rel = copy_refs_to_dir(collect_path_bearing_roles(art), files_dir)
    return wire_refs, build_path_map(art, src_to_rel)


def _load_refs(meta: dict[str, Any]) -> list[Any]:
    from app.models.artifact_ref import ArtifactRef

    refs = []
    for raw in meta.get("refs") or []:
        try:
            refs.append(ArtifactRef.model_validate(raw).model_copy(update={"source_path": ""}))
        except Exception:
            continue
    return refs


def _hash_input(data: Any, scalar_fields: tuple[str, ...]) -> str:
    from app.core.artifacts.artifact_pack import content_digests, path_field_items

    path_keys = set(path_field_items(data))
    payload: dict[str, Any] = {f: getattr(data, f, None) for f in scalar_fields}
    for dict_field in ("metrics", "metadata"):
        d = getattr(data, dict_field, None)
        if isinstance(d, dict):
            payload[dict_field] = {k: v for k, v in d.items() if f"{dict_field}.{k}" not in path_keys}
    payload["content"] = content_digests(data)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _list_files(src_dir: Path) -> FileListing | None:
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


class DeploymentArtifactHandler:
    """Serialize DeploymentArtifact metadata + role files for run-artifact storage."""

    def serialize(self, data: Any, dest_dir: Path) -> None:
        from app.models.deployment_artifact import DeploymentArtifact

        if isinstance(data, DeploymentArtifact):
            art = data
        elif isinstance(data, dict):
            art = DeploymentArtifact.model_validate(data)
        else:
            raise TypeError(f"DeploymentArtifactHandler expected DeploymentArtifact, got {type(data)!r}")

        from app.core.artifacts.artifact_pack import without_copied_paths

        dest_dir.mkdir(parents=True, exist_ok=True)
        wire_refs, path_map = _copy_roles(art, dest_dir / "files")
        meta = {
            "format": "deployment_artifact/v2",
            "artifact_path": "" if "artifact_path" in path_map else str(art.artifact_path or ""),
            "model_format": art.model_format,
            "target_hardware": art.target_hardware,
            "quantization": art.quantization,
            "labels": list(art.labels or []),
            "input_shape": list(art.input_shape or []),
            "output_shape": list(art.output_shape or []),
            "file_size_bytes": int(art.file_size_bytes or 0),
            "benchmark": art.benchmark,
            "metadata": without_copied_paths(dict(art.metadata or {}), "metadata", path_map),
            "path_map": path_map,
            "refs": wire_refs,
        }
        (dest_dir / DEPLOYMENT_MANIFEST).write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

    def deserialize(self, src_dir: Path) -> Any | None:
        from app.models.deployment_artifact import DeploymentArtifact

        path = src_dir / DEPLOYMENT_MANIFEST
        if not path.is_file():
            return None
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("deployment_artifact: corrupt manifest at %s (%s)", path, exc)
            return None
        from app.core.artifacts.artifact_pack import restore_path_map

        files_dir = src_dir / "files"
        refs = _load_refs(meta)
        artifact_path = str(meta.get("artifact_path") or "")
        metadata = dict(meta.get("metadata") or {})
        if "path_map" in meta:
            for field, local in restore_path_map(meta.get("path_map") or {}, files_dir).items():
                if field == "artifact_path":
                    artifact_path = local
                elif field.startswith("metadata."):
                    metadata[field[len("metadata."):]] = local
        else:
            for ref in refs:
                local = files_dir / (ref.relative_path or ref.filename or ref.role)
                if not local.exists():
                    continue
                if ref.role in {"deployment_bundle", "tflite"} and not artifact_path:
                    artifact_path = str(local)
                elif ref.role == "labels":
                    metadata["labels_path"] = str(local)
        return DeploymentArtifact(
            artifact_path=artifact_path,
            model_format=str(meta.get("model_format") or ""),
            target_hardware=str(meta.get("target_hardware") or "cpu"),
            quantization=str(meta.get("quantization") or "none"),
            labels=list(meta.get("labels") or []),
            input_shape=list(meta.get("input_shape") or []),
            output_shape=list(meta.get("output_shape") or []),
            file_size_bytes=int(meta.get("file_size_bytes") or 0),
            benchmark=meta.get("benchmark"),
            metadata=metadata,
            refs=refs,
        )

    def compute_content_hash_input(self, data: Any) -> str:
        from app.models.deployment_artifact import DeploymentArtifact

        if isinstance(data, dict):
            data = DeploymentArtifact.model_validate(data)
        return _hash_input(
            data,
            ("labels", "model_format", "target_hardware", "quantization", "input_shape",
             "output_shape", "benchmark"),
        )

    def infer_type(self, value: Any) -> str | None:
        name = type(value).__name__
        if name == "DeploymentArtifact":
            return DEPLOYMENT_TYPE
        if hasattr(value, "artifact_path") and hasattr(value, "model_format"):
            return DEPLOYMENT_TYPE
        return None

    def list_files(self, src_dir: Path) -> FileListing | None:
        return _list_files(src_dir)


class TFLiteArtifactHandler:
    """Serialize TFLiteArtifact metadata + role files for run-artifact storage."""

    def serialize(self, data: Any, dest_dir: Path) -> None:
        from app.models.tflite_artifact import TFLiteArtifact

        if isinstance(data, TFLiteArtifact):
            art = data
        elif isinstance(data, dict):
            art = TFLiteArtifact.model_validate(data)
        else:
            raise TypeError(f"TFLiteArtifactHandler expected TFLiteArtifact, got {type(data)!r}")

        dest_dir.mkdir(parents=True, exist_ok=True)
        wire_refs, path_map = _copy_roles(art, dest_dir / "files")
        meta = {
            "format": "tflite_artifact/v2",
            "tflite_path": "" if "tflite_path" in path_map else str(art.tflite_path or ""),
            "labels": list(art.labels or []),
            "quantisation": art.quantisation,
            "file_size_bytes": int(art.file_size_bytes or 0),
            "path_map": path_map,
            "refs": wire_refs,
        }
        (dest_dir / TFLITE_MANIFEST).write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def deserialize(self, src_dir: Path) -> Any | None:
        from app.models.tflite_artifact import TFLiteArtifact

        path = src_dir / TFLITE_MANIFEST
        if not path.is_file():
            return None
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("tflite_artifact: corrupt manifest at %s (%s)", path, exc)
            return None
        from app.core.artifacts.artifact_pack import restore_path_map

        files_dir = src_dir / "files"
        refs = _load_refs(meta)
        tflite_path = str(meta.get("tflite_path") or "")
        if "path_map" in meta:
            tflite_path = restore_path_map(meta.get("path_map") or {}, files_dir).get(
                "tflite_path", tflite_path
            )
        else:
            for ref in refs:
                local = files_dir / (ref.relative_path or ref.filename or ref.role)
                if ref.role == "tflite" and local.exists():
                    tflite_path = str(local)
        return TFLiteArtifact(
            tflite_path=tflite_path,
            labels=list(meta.get("labels") or []),
            quantisation=str(meta.get("quantisation") or "float32"),
            file_size_bytes=int(meta.get("file_size_bytes") or 0),
            refs=refs,
        )

    def compute_content_hash_input(self, data: Any) -> str:
        from app.models.tflite_artifact import TFLiteArtifact

        if isinstance(data, dict):
            data = TFLiteArtifact.model_validate(data)
        return _hash_input(data, ("labels", "quantisation"))

    def infer_type(self, value: Any) -> str | None:
        name = type(value).__name__
        if name == "TFLiteArtifact":
            return TFLITE_TYPE
        if hasattr(value, "tflite_path") and hasattr(value, "quantisation"):
            return TFLITE_TYPE
        return None

    def list_files(self, src_dir: Path) -> FileListing | None:
        return _list_files(src_dir)


def register_deployment_artifact_serializer() -> None:
    """Register DeploymentArtifact + TFLiteArtifact handlers (idempotent)."""
    from app.core.artifacts.artifact_serializer import get_serializer_registry

    registry = get_serializer_registry()
    registry.register(DEPLOYMENT_TYPE, DeploymentArtifactHandler())
    registry.register(TFLITE_TYPE, TFLiteArtifactHandler())
    logger.debug(
        "Deployment/TFLite handlers registered for %r / %r",
        DEPLOYMENT_TYPE,
        TFLITE_TYPE,
    )
