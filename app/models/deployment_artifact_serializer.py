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

import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from app.core.artifacts.artifact_serializer import FileListing, FileListingEntry

logger = logging.getLogger(__name__)

DEPLOYMENT_TYPE = "deployment_artifact"
TFLITE_TYPE = "tflite_artifact"
DEPLOYMENT_MANIFEST = "deployment_artifact_manifest.json"
TFLITE_MANIFEST = "tflite_artifact_manifest.json"


def _copy_refs_to_files(refs: list[Any], files_dir: Path) -> list[dict[str, Any]]:
    from app.core.artifacts.artifact_pack import pack_path_bytes
    from app.models.artifact_ref import ArtifactRef

    files_dir.mkdir(parents=True, exist_ok=True)
    wire_refs: list[dict[str, Any]] = []
    for ref in refs:
        src = str(getattr(ref, "source_path", "") or "")
        if not src or not Path(src).exists():
            wire_refs.append(ref.model_dump() if hasattr(ref, "model_dump") else dict(ref))
            continue
        rel = (ref.relative_path or ref.filename or ref.role or "artifact").replace("\\", "/")
        dest = files_dir / rel
        if Path(src).is_dir():
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(src, dest)
            kind = "dir"
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            kind = "file"
        blob, _ = pack_path_bytes(Path(src))
        digest = hashlib.sha256(blob).hexdigest()
        wire_refs.append(
            ArtifactRef(
                logical_id=digest,
                role=ref.role,
                sha256=digest,
                uri="",
                media_type=ref.media_type,
                filename=ref.filename or Path(src).name,
                kind=kind,  # type: ignore[arg-type]
                relative_path=rel,
                source_path="",
            ).model_dump()
        )
    return wire_refs


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
        from app.core.artifacts.artifact_pack import collect_path_bearing_roles
        from app.models.deployment_artifact import DeploymentArtifact

        if isinstance(data, DeploymentArtifact):
            art = data
        elif isinstance(data, dict):
            art = DeploymentArtifact.model_validate(data)
        else:
            raise TypeError(f"DeploymentArtifactHandler expected DeploymentArtifact, got {type(data)!r}")

        dest_dir.mkdir(parents=True, exist_ok=True)
        refs = collect_path_bearing_roles(art)
        wire_refs = _copy_refs_to_files(refs, dest_dir / "files")
        meta = {
            "format": "deployment_artifact/v1",
            "artifact_path": "",
            "model_format": art.model_format,
            "target_hardware": art.target_hardware,
            "quantization": art.quantization,
            "labels": list(art.labels or []),
            "input_shape": list(art.input_shape or []),
            "output_shape": list(art.output_shape or []),
            "file_size_bytes": int(art.file_size_bytes or 0),
            "benchmark": art.benchmark,
            "metadata": {
                k: v
                for k, v in dict(art.metadata or {}).items()
                if not (
                    isinstance(v, str)
                    and (
                        k.endswith("_path")
                        or k in {"source", "source_model_path", "package_path"}
                    )
                )
            },
            "refs": wire_refs,
        }
        (dest_dir / DEPLOYMENT_MANIFEST).write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def deserialize(self, src_dir: Path) -> Any | None:
        from app.models.artifact_ref import ArtifactRef
        from app.models.deployment_artifact import DeploymentArtifact

        path = src_dir / DEPLOYMENT_MANIFEST
        if not path.is_file():
            return None
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("deployment_artifact: corrupt manifest at %s (%s)", path, exc)
            return None
        files_dir = src_dir / "files"
        refs: list[ArtifactRef] = []
        artifact_path = ""
        metadata = dict(meta.get("metadata") or {})
        for raw in meta.get("refs") or []:
            try:
                ref = ArtifactRef.model_validate(raw)
            except Exception:
                continue
            local = files_dir / (ref.relative_path or ref.filename or ref.role)
            if local.exists():
                ref = ref.model_copy(update={"source_path": ""})
                if ref.role in {"deployment_bundle", "tflite"} and not artifact_path:
                    artifact_path = str(local)
                elif ref.role == "labels":
                    metadata["labels_path"] = str(local)
            refs.append(ref)
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
        from app.core.artifacts.artifact_pack import collect_path_bearing_roles

        payload = data.model_dump() if hasattr(data, "model_dump") else (dict(data) if isinstance(data, dict) else {})
        refs = collect_path_bearing_roles(data) if not isinstance(data, dict) else data.get("refs") or []
        digests = []
        for ref in refs:
            digest = getattr(ref, "sha256", None) if not isinstance(ref, dict) else ref.get("sha256")
            role = getattr(ref, "role", None) if not isinstance(ref, dict) else ref.get("role")
            if digest:
                digests.append(f"{role}:{digest}")
        return json.dumps(
            {
                "labels": payload.get("labels"),
                "model_format": payload.get("model_format"),
                "ref_digests": digests,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
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
        from app.core.artifacts.artifact_pack import collect_path_bearing_roles
        from app.models.tflite_artifact import TFLiteArtifact

        if isinstance(data, TFLiteArtifact):
            art = data
        elif isinstance(data, dict):
            art = TFLiteArtifact.model_validate(data)
        else:
            raise TypeError(f"TFLiteArtifactHandler expected TFLiteArtifact, got {type(data)!r}")

        dest_dir.mkdir(parents=True, exist_ok=True)
        refs = collect_path_bearing_roles(art)
        wire_refs = _copy_refs_to_files(refs, dest_dir / "files")
        meta = {
            "format": "tflite_artifact/v1",
            "tflite_path": "",
            "labels": list(art.labels or []),
            "quantisation": art.quantisation,
            "file_size_bytes": int(art.file_size_bytes or 0),
            "refs": wire_refs,
        }
        (dest_dir / TFLITE_MANIFEST).write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def deserialize(self, src_dir: Path) -> Any | None:
        from app.models.artifact_ref import ArtifactRef
        from app.models.tflite_artifact import TFLiteArtifact

        path = src_dir / TFLITE_MANIFEST
        if not path.is_file():
            return None
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("tflite_artifact: corrupt manifest at %s (%s)", path, exc)
            return None
        files_dir = src_dir / "files"
        refs: list[ArtifactRef] = []
        tflite_path = ""
        for raw in meta.get("refs") or []:
            try:
                ref = ArtifactRef.model_validate(raw)
            except Exception:
                continue
            local = files_dir / (ref.relative_path or ref.filename or ref.role)
            if local.exists():
                ref = ref.model_copy(update={"source_path": ""})
                if ref.role == "tflite":
                    tflite_path = str(local)
            refs.append(ref)
        return TFLiteArtifact(
            tflite_path=tflite_path,
            labels=list(meta.get("labels") or []),
            quantisation=str(meta.get("quantisation") or "float32"),
            file_size_bytes=int(meta.get("file_size_bytes") or 0),
            refs=refs,
        )

    def compute_content_hash_input(self, data: Any) -> str:
        from app.core.artifacts.artifact_pack import collect_path_bearing_roles

        payload = data.model_dump() if hasattr(data, "model_dump") else (dict(data) if isinstance(data, dict) else {})
        refs = collect_path_bearing_roles(data) if not isinstance(data, dict) else data.get("refs") or []
        digests = []
        for ref in refs:
            digest = getattr(ref, "sha256", None) if not isinstance(ref, dict) else ref.get("sha256")
            role = getattr(ref, "role", None) if not isinstance(ref, dict) else ref.get("role")
            if digest:
                digests.append(f"{role}:{digest}")
        return json.dumps(
            {
                "labels": payload.get("labels"),
                "quantisation": payload.get("quantisation"),
                "ref_digests": digests,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

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
