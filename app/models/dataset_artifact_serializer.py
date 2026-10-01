# app/models/dataset_artifact_serializer.py
"""
Bounded Context:  Domain — ML Data Models
Responsibility:   Domain-side ArtifactTypeHandler for ``dataset_artifact``.
                  Stores split arrays as ``.npy`` plus a small ``manifest.json``
                  instead of dumping tensors into ``data.json`` (which produced
                  100 MB–1 GB JSON and stalled ``GET /runs/{id}/outputs``).
Owns:             DatasetArtifactHandler, register_dataset_serializer().
Public Surface:   register_dataset_serializer() — called once at startup from
                  each entry point (API, CLI, MCP).
Must NOT:         Import from app.core.execution.orchestrator or other
                  execution-layer modules. Must not register at import time.
Dependencies:     app.core.artifacts.artifact_serializer (interface only),
                  app.models.dataset_artifact, numpy, json, hashlib, pathlib.
Reason To Change: DatasetArtifact schema changes, or a new on-disk layout
                  (e.g. memory-mapped / zarr) is adopted.

## Layout (artifacts/{id}/data/)

    manifest.json
    {
      "format": "dataset_artifact/v1",
      "labels": ["yes", "no", ...],
      "input_shape": [101, 40, 1],
      "n_classes": 6,
      "version": "",
      "content_hash": "",
      "manifest_path": "",
      "metadata": {},
      "arrays": {
        "X_train": {"file": "X_train.npy", "shape": [N, ...], "dtype": "float32"},
        ...
      }
    }
    X_train.npy  X_val.npy  X_test.npy  y_train.npy  y_val.npy  y_test.npy
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ARRAY_FIELDS = ("X_train", "X_val", "X_test", "y_train", "y_val", "y_test")
_FORMAT = "dataset_artifact/v1"


class DatasetArtifactHandler:
    """ArtifactTypeHandler for ``dataset_artifact`` (``.npy`` + ``manifest.json``)."""

    def serialize(self, data: Any, dest_dir: Path) -> None:
        """Write DatasetArtifact arrays as ``.npy`` and metadata as ``manifest.json``."""
        import shutil
        import tempfile

        import numpy as np

        from app.models.dataset_artifact import DatasetArtifact

        if not isinstance(data, DatasetArtifact):
            # Duck-type: anything with the split fields (plugin re-export, copy).
            if not all(hasattr(data, name) for name in ("labels", "n_classes", "X_train")):
                raise TypeError(
                    f"Expected DatasetArtifact, got {type(data).__name__}"
                )

        dest_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(dir=dest_dir.parent, prefix=".tmp_dataset_"))
        try:
            arrays_meta: dict[str, dict[str, Any]] = {}
            for name in _ARRAY_FIELDS:
                value = getattr(data, name, None)
                if value is None:
                    arr = np.zeros((0,), dtype=np.float32 if name.startswith("X_") else np.int32)
                else:
                    arr = np.asarray(value)
                filename = f"{name}.npy"
                np.save(tmp_dir / filename, arr)
                arrays_meta[name] = {
                    "file": filename,
                    "shape": list(arr.shape),
                    "dtype": str(arr.dtype),
                }

            input_shape = getattr(data, "input_shape", ()) or ()
            manifest = {
                "format": _FORMAT,
                "labels": list(getattr(data, "labels", None) or []),
                "input_shape": list(input_shape),
                "n_classes": int(getattr(data, "n_classes", 0) or 0),
                "version": str(getattr(data, "version", "") or ""),
                "content_hash": str(getattr(data, "content_hash", "") or ""),
                "manifest_path": str(getattr(data, "manifest_path", "") or ""),
                "metadata": dict(getattr(data, "metadata", None) or {}),
                "arrays": arrays_meta,
            }
            (tmp_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            tmp_dir.rename(dest_dir)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def deserialize(self, src_dir: Path) -> Any | None:
        """Read ``manifest.json`` + ``.npy`` files → DatasetArtifact."""
        import numpy as np

        from app.models.dataset_artifact import DatasetArtifact

        manifest_path = src_dir / "manifest.json"
        if not manifest_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(
                "DatasetArtifactHandler.deserialize: corrupt manifest at %s (%s)",
                src_dir,
                exc,
            )
            return None
        if not isinstance(manifest, dict):
            return None

        arrays: dict[str, Any] = {}
        array_meta = manifest.get("arrays") if isinstance(manifest.get("arrays"), dict) else {}
        for name in _ARRAY_FIELDS:
            info = array_meta.get(name) if isinstance(array_meta, dict) else None
            filename = info.get("file") if isinstance(info, dict) else f"{name}.npy"
            path = src_dir / str(filename)
            if path.is_file():
                try:
                    arrays[name] = np.load(path, allow_pickle=False)
                except Exception as exc:
                    logger.warning(
                        "DatasetArtifactHandler.deserialize: failed to load %s (%s)",
                        path,
                        exc,
                    )
                    arrays[name] = None
            else:
                arrays[name] = None

        shape_raw = manifest.get("input_shape") or ()
        try:
            input_shape = tuple(int(x) for x in shape_raw)
        except (TypeError, ValueError):
            input_shape = ()

        return DatasetArtifact(
            X_train=arrays.get("X_train"),
            X_val=arrays.get("X_val"),
            X_test=arrays.get("X_test"),
            y_train=arrays.get("y_train"),
            y_val=arrays.get("y_val"),
            y_test=arrays.get("y_test"),
            labels=list(manifest.get("labels") or []),
            input_shape=input_shape,
            n_classes=int(manifest.get("n_classes") or 0),
            version=str(manifest.get("version") or ""),
            content_hash=str(manifest.get("content_hash") or ""),
            manifest_path=str(manifest.get("manifest_path") or ""),
            metadata=dict(manifest.get("metadata") or {}),
        )

    def compute_content_hash_input(self, data: Any) -> str:
        """Stable fingerprint: labels/shape + per-array dtype/shape/prefix hash."""
        import numpy as np

        entries: dict[str, Any] = {
            "labels": list(getattr(data, "labels", None) or []),
            "input_shape": list(getattr(data, "input_shape", ()) or ()),
            "n_classes": int(getattr(data, "n_classes", 0) or 0),
            "version": str(getattr(data, "version", "") or ""),
            "arrays": {},
        }
        for name in _ARRAY_FIELDS:
            value = getattr(data, name, None)
            if value is None:
                entries["arrays"][name] = None
                continue
            arr = np.asarray(value)
            try:
                prefix = arr.reshape(-1)[:1024].tobytes()
                pcm_hash = hashlib.sha256(prefix).hexdigest()[:16]
            except Exception:
                pcm_hash = ""
            entries["arrays"][name] = {
                "shape": list(arr.shape),
                "dtype": str(arr.dtype),
                "nbytes": int(arr.nbytes),
                "prefix_hash": pcm_hash,
            }
        return json.dumps(entries, sort_keys=True)

    def infer_type(self, value: Any) -> str | None:
        """Return ``dataset_artifact`` for DatasetArtifact (or duck-typed twin)."""
        try:
            from app.models.dataset_artifact import DatasetArtifact

            if isinstance(value, DatasetArtifact):
                return "dataset_artifact"
        except ImportError:
            pass
        # Plugin re-exports / dynamic subclasses share the field set.
        if (
            hasattr(value, "X_train")
            and hasattr(value, "y_train")
            and hasattr(value, "labels")
            and hasattr(value, "n_classes")
            and hasattr(value, "input_shape")
        ):
            return "dataset_artifact"
        return None

    def list_files(self, src_dir: Path):
        """Expose ``manifest.json`` + ``.npy`` sidecars for run-output listing."""
        from app.core.artifacts.artifact_serializer import FileListing, FileListingEntry

        manifest_path = src_dir / "manifest.json"
        if not manifest_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(
                "DatasetArtifactHandler.list_files: corrupt manifest at %s (%s)",
                src_dir,
                exc,
            )
            return None
        if not isinstance(manifest, dict):
            return None
        entries: list[FileListingEntry] = [
            FileListingEntry(path=manifest_path, name="manifest.json")
        ]
        arrays = manifest.get("arrays") if isinstance(manifest.get("arrays"), dict) else {}
        for info in arrays.values():
            if isinstance(info, dict) and info.get("file"):
                name = str(info["file"])
                entries.append(FileListingEntry(path=src_dir / name, name=name))
        return FileListing(total=len(entries), entries=entries)


def register_dataset_serializer() -> None:
    """Register DatasetArtifactHandler on the process-wide serializer registry.

    Call once at startup from each entry point (alongside
    ``register_audio_serializer``). Idempotent.
    """
    from app.core.artifacts.artifact_serializer import get_serializer_registry

    registry = get_serializer_registry()
    registry.register("dataset_artifact", DatasetArtifactHandler())
    logger.debug("DatasetArtifactHandler registered for artifact_type='dataset_artifact'")
