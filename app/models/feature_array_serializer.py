# app/models/feature_array_serializer.py
"""
Bounded Context:  Domain — ML Data Models
Responsibility:   Domain-side ArtifactTypeHandler for ``feature_arrays``
                  (``list[FeatureArray]``). Stores every clip's matrix in one
                  ``features.npz`` plus a ``manifest.json`` with per-item
                  label / sample_rate / source_path / feature_type / metadata,
                  so pipeline-cache hits restore real FeatureArray objects.
Owns:             FeatureArrayHandler, register_feature_array_serializer().
Public Surface:   register_feature_array_serializer() — called once at startup
                  from each entry point (API, CLI, MCP).
Must NOT:         Import from app.core.execution.orchestrator or other
                  execution-layer modules. Must not register at import time.
Dependencies:     app.core.artifacts.artifact_serializer (interface only),
                  app.models.feature_array, numpy, json, hashlib, pathlib.
Reason To Change: FeatureArray schema changes, or a new on-disk layout is
                  adopted.

## Layout (artifacts/{id}/data/)

    manifest.json   {"format": "feature_arrays/v1", "items": [{key, label,
                     sample_rate, source_path, feature_type, metadata,
                     shape, dtype}, ...]}
    features.npz    f0, f1, ... (one array per item; shapes may differ)

Before this handler existed, AudioSampleHandler's duck-typed fallback claimed
FeatureArray lists (both have ``.data`` + ``.sample_rate``), so features were
written as WAV files and cache hits returned AudioSample objects.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FORMAT = "feature_arrays/v1"
_NPZ = "features.npz"


def _looks_like_feature_array(obj: Any) -> bool:
    return all(hasattr(obj, attr) for attr in ("data", "feature_type", "source_path"))


def _json_safe(meta: Any) -> dict[str, Any]:
    if not isinstance(meta, dict):
        return {}
    try:
        json.dumps(meta)
        return dict(meta)
    except (TypeError, ValueError):
        return {k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool)) or v is None}


class FeatureArrayHandler:
    """ArtifactTypeHandler for ``feature_arrays`` (``.npz`` + ``manifest.json``)."""

    def serialize(self, data: Any, dest_dir: Path) -> None:
        """Write list[FeatureArray] as one ``features.npz`` + ``manifest.json``."""
        import shutil
        import tempfile

        import numpy as np

        if not isinstance(data, list) or not all(_looks_like_feature_array(v) for v in data):
            raise TypeError(f"Expected list[FeatureArray], got {type(data).__name__}")

        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(dir=dest_dir.parent, prefix=".tmp_features_"))
        try:
            arrays: dict[str, Any] = {}
            items: list[dict[str, Any]] = []
            for i, fa in enumerate(data):
                key = f"f{i}"
                arr = np.asarray(fa.data if fa.data is not None else np.zeros((0, 0)), dtype=np.float32)
                arrays[key] = arr
                items.append({
                    "key": key,
                    "label": str(getattr(fa, "label", "") or ""),
                    "sample_rate": int(getattr(fa, "sample_rate", 16000) or 16000),
                    "source_path": str(getattr(fa, "source_path", "") or ""),
                    "feature_type": str(getattr(fa, "feature_type", "") or ""),
                    "metadata": _json_safe(getattr(fa, "metadata", None)),
                    "shape": list(arr.shape),
                    "dtype": str(arr.dtype),
                })
            np.savez(tmp_dir / _NPZ, **arrays)
            (tmp_dir / "manifest.json").write_text(
                json.dumps({"format": _FORMAT, "count": len(items), "items": items}, indent=1),
                encoding="utf-8",
            )
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            tmp_dir.rename(dest_dir)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def deserialize(self, src_dir: Path) -> Any | None:
        """Read ``manifest.json`` + ``features.npz`` → list[FeatureArray]; None on miss."""
        import numpy as np

        from app.models.feature_array import FeatureArray

        manifest_path = src_dir / "manifest.json"
        npz_path = src_dir / _NPZ
        if not manifest_path.is_file() or not npz_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("FeatureArrayHandler.deserialize: corrupt manifest at %s (%s)", src_dir, exc)
            return None
        if not isinstance(manifest, dict) or manifest.get("format") != _FORMAT:
            return None
        items = manifest.get("items")
        if not isinstance(items, list):
            return None
        out: list[Any] = []
        try:
            with np.load(npz_path, allow_pickle=False) as npz:
                for entry in items:
                    out.append(FeatureArray(
                        data=npz[entry["key"]],
                        label=entry.get("label", ""),
                        sample_rate=int(entry.get("sample_rate") or 16000),
                        source_path=entry.get("source_path", ""),
                        feature_type=entry.get("feature_type", ""),
                        metadata=dict(entry.get("metadata") or {}),
                    ))
        except Exception as exc:
            # A partial list would silently shrink the dataset — treat as a miss.
            logger.warning("FeatureArrayHandler.deserialize: failed to load %s (%s)", npz_path, exc)
            return None
        return out

    def compute_content_hash_input(self, data: Any) -> str:
        """Stable fingerprint: per-item label/path/shape + data prefix hash."""
        import numpy as np

        entries = []
        for fa in data:
            arr = np.asarray(getattr(fa, "data", None) if getattr(fa, "data", None) is not None else [])
            try:
                prefix_hash = hashlib.sha256(arr.reshape(-1)[:1024].tobytes()).hexdigest()[:16]
            except Exception:
                prefix_hash = ""
            entries.append({
                "label": str(getattr(fa, "label", "") or ""),
                "source_path": str(getattr(fa, "source_path", "") or ""),
                "feature_type": str(getattr(fa, "feature_type", "") or ""),
                "shape": list(arr.shape),
                "prefix_hash": prefix_hash,
            })
        return json.dumps(entries, sort_keys=True)

    def infer_type(self, value: Any) -> str | None:
        """Return ``feature_arrays`` for a non-empty list of FeatureArray(-like) objects."""
        if isinstance(value, list) and value and all(_looks_like_feature_array(v) for v in value):
            return "feature_arrays"
        return None

    def list_files(self, src_dir: Path):
        """Expose ``manifest.json`` + ``features.npz`` for run-output listing."""
        from app.core.artifacts.artifact_serializer import FileListing, FileListingEntry

        manifest_path = src_dir / "manifest.json"
        if not manifest_path.is_file():
            return None
        entries = [FileListingEntry(path=manifest_path, name="manifest.json")]
        if (src_dir / _NPZ).is_file():
            entries.append(FileListingEntry(path=src_dir / _NPZ, name=_NPZ))
        return FileListing(total=len(entries), entries=entries)


def register_feature_array_serializer() -> None:
    """Register FeatureArrayHandler on the process-wide serializer registry. Idempotent."""
    from app.core.artifacts.artifact_serializer import get_serializer_registry

    get_serializer_registry().register("feature_arrays", FeatureArrayHandler())
