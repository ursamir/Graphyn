# app/models/model_artifact_serializer.py
"""
Bounded Context:  BC6 — Artifacts
Responsibility:   ArtifactSerializerRegistry handler for ModelArtifact that
                  persists metadata + an ArtifactRef role manifest. File bytes
                  are copied beside the manifest for on-disk run artifacts;
                  Mode B distributed transfer uses the same pack helpers via
                  ``app.core.distributed.transfer`` (pickle metadata + blobs).
Owns:             ModelArtifactHandler, register_model_artifact_serializer().
Public Surface:   register_model_artifact_serializer()
Must NOT:         Perform HTTP / distributed blob I/O.
Dependencies:     artifact_serializer, artifact_pack, model_artifact, artifact_ref.
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

ARTIFACT_TYPE = "model_artifact"
MANIFEST_NAME = "model_artifact_manifest.json"
_PATH_METRIC_KEYS = frozenset(
    {
        "keras_model_path",
        "saved_model_path",
        "labels_path",
        "model_path",
    }
)


def _is_abs_path_str(value: str) -> bool:
    if value.startswith("/") or value.startswith("\\"):
        return True
    return len(value) > 2 and value[1] == ":"


class ModelArtifactHandler:
    """Serialize ModelArtifact metadata + role files for run-artifact storage."""

    def serialize(self, data: Any, dest_dir: Path) -> None:
        from app.core.artifacts.artifact_pack import collect_path_bearing_roles, pack_path_bytes
        from app.models.artifact_ref import ArtifactRef
        from app.models.model_artifact import ModelArtifact

        if isinstance(data, ModelArtifact):
            art = data
        elif isinstance(data, dict):
            art = ModelArtifact.model_validate(data)
        else:
            raise TypeError(f"ModelArtifactHandler expected ModelArtifact, got {type(data)!r}")

        dest_dir.mkdir(parents=True, exist_ok=True)
        refs = collect_path_bearing_roles(art)
        files_dir = dest_dir / "files"
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

        cleaned_metrics: dict[str, Any] = {}
        for key, val in dict(art.metrics or {}).items():
            if key in _PATH_METRIC_KEYS:
                continue
            if isinstance(val, str) and _is_abs_path_str(val):
                continue
            cleaned_metrics[key] = val

        meta = {
            "format": "model_artifact/v1",
            "model_path": "",
            "labels": list(art.labels or []),
            "history": dict(art.history or {}),
            "metrics": cleaned_metrics,
            "refs": wire_refs,
        }
        (dest_dir / MANIFEST_NAME).write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def deserialize(self, src_dir: Path) -> Any | None:
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
        metrics = dict(meta.get("metrics") or {})
        model_path = ""
        for raw in meta.get("refs") or []:
            try:
                ref = ArtifactRef.model_validate(raw)
            except Exception:
                continue
            local = files_dir / (ref.relative_path or ref.filename or ref.role)
            if local.exists():
                ref = ref.model_copy(update={"source_path": ""})
                if ref.role == "keras_model":
                    metrics["keras_model_path"] = str(local)
                    if not model_path:
                        model_path = str(local)
                elif ref.role == "saved_model":
                    metrics["saved_model_path"] = str(local)
                    model_path = str(local)
                elif ref.role == "labels":
                    metrics["labels_path"] = str(local)
                elif ref.role == "pytorch_model":
                    model_path = str(local)
            refs.append(ref)
        if not model_path:
            for role in ("saved_model", "keras_model", "pytorch_model"):
                for ref in refs:
                    local = files_dir / (ref.relative_path or ref.filename or ref.role)
                    if ref.role == role and local.exists():
                        model_path = str(local)
                        break
                if model_path:
                    break
        return ModelArtifact(
            model_path=model_path,
            labels=list(meta.get("labels") or []),
            history=dict(meta.get("history") or {}),
            metrics=metrics,
            refs=refs,
        )

    def compute_content_hash_input(self, data: Any) -> str:
        from app.core.artifacts.artifact_pack import collect_path_bearing_roles

        if hasattr(data, "model_dump"):
            payload = data.model_dump()
        elif isinstance(data, dict):
            payload = dict(data)
        else:
            payload = {"repr": repr(data)}
        refs = (
            collect_path_bearing_roles(data)
            if not isinstance(data, dict)
            else data.get("refs") or []
        )
        digests = []
        for ref in refs:
            digest = getattr(ref, "sha256", None) if not isinstance(ref, dict) else ref.get("sha256")
            role = getattr(ref, "role", None) if not isinstance(ref, dict) else ref.get("role")
            if digest:
                digests.append(f"{role}:{digest}")
        payload = {
            "labels": payload.get("labels"),
            "metrics_keys": sorted((payload.get("metrics") or {}).keys())
            if isinstance(payload.get("metrics"), dict)
            else [],
            "ref_digests": digests,
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
