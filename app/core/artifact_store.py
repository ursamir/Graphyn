from __future__ import annotations

"""ArtifactStore — content-addressed, typed artifact registry (Phase 4).

This module defines:
- ArtifactRecord: immutable Pydantic model for artifact metadata
- ArtifactNotFoundError: raised when an artifact ID is not found
- ArtifactSerializationError: raised when artifact serialization fails
- SUPPORTED_ARTIFACT_TYPES: frozenset of valid artifact type strings
- ArtifactStore: content-addressed artifact registry (see req-01)
"""

import hashlib
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported artifact types
# ---------------------------------------------------------------------------

SUPPORTED_ARTIFACT_TYPES: frozenset[str] = frozenset(
    {
        "audio_samples",
        "model_artifact",
        "tflite_artifact",
        "prediction_result",
        "feature_array",
        "generic",
    }
)


def _infer_artifact_type(value: Any) -> str:
    """Infer the ArtifactStore artifact_type string from a node output value."""
    try:
        from app.models.dataset_artifact import DatasetArtifact  # noqa: PLC0415
        if isinstance(value, DatasetArtifact):
            return "generic"
    except ImportError:
        pass

    if isinstance(value, list) and value:
        first = value[0]
        if hasattr(first, "data") and hasattr(first, "sample_rate"):
            return "audio_samples"
        if hasattr(first, "model_dump"):
            return "generic"

    if isinstance(value, dict):
        if any(k in value for k in ("train", "val", "test")):
            return "generic"
        if any(k in value for k in ("features", "feature_array")):
            return "feature_array"

    try:
        import numpy as np
        if isinstance(value, np.ndarray):
            return "feature_array"
    except ImportError:
        pass

    return "generic"


# ---------------------------------------------------------------------------
# Error classes
# ---------------------------------------------------------------------------


class ArtifactNotFoundError(KeyError):
    """Raised when an artifact_id is not found in the ArtifactStore.

    Subclasses KeyError so callers can catch it with ``except KeyError``.
    """

    def __init__(self, artifact_id: str) -> None:
        super().__init__(artifact_id)
        self.artifact_id = artifact_id

    def __str__(self) -> str:
        return f"Artifact not found: {self.artifact_id!r}"


class ArtifactSerializationError(RuntimeError):
    """Raised when artifact serialization fails during register().

    Subclasses RuntimeError.
    """

    def __init__(self, artifact_type: str, cause: Exception) -> None:
        super().__init__(f"Failed to serialize artifact of type {artifact_type!r}: {cause}")
        self.artifact_type = artifact_type
        self.cause = cause


# ---------------------------------------------------------------------------
# ArtifactRecord data model
# ---------------------------------------------------------------------------


class ArtifactRecord(BaseModel):
    """Immutable metadata envelope for a registered artifact.

    All fields are JSON-serializable via ``model_dump(mode="json")``.

    Requirements: req-01 §1, §2, §4
    """

    model_config = ConfigDict(frozen=True)

    artifact_id: str
    """Globally unique identifier (UUID4, 8-char prefix)."""

    content_hash: str
    """SHA-256 hex digest of the canonical serialized artifact data."""

    artifact_type: str
    """One of SUPPORTED_ARTIFACT_TYPES."""

    node_id: str
    """The IR node ID that produced this artifact."""

    node_type: str
    """The node type string (e.g. ``"clean"``, ``"train"``)."""

    run_id: str
    """The run that produced this artifact."""

    name: str | None = None
    """Optional human-readable name."""

    metadata: dict[str, Any] = {}
    """Arbitrary key-value metadata."""

    created_at: str
    """ISO 8601 UTC timestamp."""

    schema_version: str = "1.0"
    """Schema version for forward compatibility."""

    data_path: str | None = None
    """Relative path from workspace root to the serialized data directory."""


# ---------------------------------------------------------------------------
# ArtifactStore
# ---------------------------------------------------------------------------


class ArtifactStore:
    """Content-addressed, typed artifact registry.

    Stores typed metadata envelopes (ArtifactRecord) alongside serialized
    data. Supports deduplication via SHA-256 content addressing.

    Requirements: req-01 §2, §3, §4, §5, §6
    """

    def __init__(self, base_dir: str | None = None) -> None:
        from app.core.config import artifacts_dir as _artifacts_dir
        workspace = Path(base_dir) if base_dir else _artifacts_dir().parent
        self.base: Path = workspace / "artifacts"
        self._lock = threading.Lock()
        self._init_workspace()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _init_workspace(self) -> None:
        """Create artifacts/ directory, index.json, and by_run/ + by_name/ sub-dirs if they don't exist."""
        self.base.mkdir(parents=True, exist_ok=True)
        index_path = self.base / "index.json"
        if not index_path.exists():
            index_path.write_text("{}", encoding="utf-8")
        (self.base / "by_run").mkdir(exist_ok=True)
        (self.base / "by_name").mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def _load_index(self) -> dict[str, str]:
        """Read index.json → {content_hash: artifact_id}.

        Returns {} on missing or corrupt file (fail-open, logs warning).
        """
        index_path = self.base / "index.json"
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("index.json is not a JSON object")
            return data
        except FileNotFoundError:
            return {}
        except Exception as exc:
            logger.warning(
                "ArtifactStore: index.json is corrupt or unreadable (%s: %s) — treating as empty",
                type(exc).__name__,
                exc,
            )
            return {}

    def _save_index(self, index: dict[str, str]) -> None:
        """Write index.json atomically (caller must hold self._lock)."""
        index_path = self.base / "index.json"
        tmp_path = index_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
        tmp_path.replace(index_path)

    # ------------------------------------------------------------------
    # Secondary index: by_run/{run_id}.json → [artifact_id, ...]
    # ------------------------------------------------------------------

    def _by_run_path(self, run_id: str) -> Path:
        return self.base / "by_run" / f"{run_id}.json"

    def _load_by_run(self, run_id: str) -> list[str]:
        """Return list of artifact_ids for run_id. Returns [] on missing/corrupt."""
        path = self._by_run_path(run_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except FileNotFoundError:
            return []
        except Exception as exc:
            logger.warning("ArtifactStore: by_run/%s.json corrupt (%s) — treating as empty", run_id, exc)
            return []

    def _append_by_run(self, run_id: str, artifact_id: str) -> None:
        """Append artifact_id to the by_run index for run_id (caller must hold self._lock)."""
        (self.base / "by_run").mkdir(exist_ok=True)
        ids = self._load_by_run(run_id)
        if artifact_id not in ids:
            ids.append(artifact_id)
        path = self._by_run_path(run_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(ids, indent=2), encoding="utf-8")
        tmp.replace(path)

    # ------------------------------------------------------------------
    # Secondary index: by_name/{name}.json → [artifact_id, ...]
    # ------------------------------------------------------------------

    def _by_name_path(self, name: str) -> Path:
        # Sanitize name for use as a filename
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)[:128]
        # SA-AS5 fix: prevent "." and ".." from being used as filenames, which
        # would produce directory references instead of index files.
        safe = safe.lstrip(".") or "_unnamed"
        if safe in (".", "..") or not safe:
            safe = "_unnamed"
        return self.base / "by_name" / f"{safe}.json"

    def _load_by_name(self, name: str) -> list[str]:
        """Return list of artifact_ids for the given name. Returns [] on missing/corrupt."""
        path = self._by_name_path(name)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except FileNotFoundError:
            return []
        except Exception as exc:
            logger.warning("ArtifactStore: by_name/%s corrupt (%s) — treating as empty", name, exc)
            return []

    def _append_by_name(self, name: str, artifact_id: str) -> None:
        """Append artifact_id to the by_name index (caller must hold self._lock)."""
        (self.base / "by_name").mkdir(exist_ok=True)
        ids = self._load_by_name(name)
        if artifact_id not in ids:
            ids.append(artifact_id)
        path = self._by_name_path(name)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(ids, indent=2), encoding="utf-8")
        tmp.replace(path)

    # ------------------------------------------------------------------
    # Content hashing
    # ------------------------------------------------------------------

    def _compute_content_hash(self, artifact_type: str, data: Any) -> str:
        """Compute SHA-256 content hash for the given artifact data.

        For ``audio_samples``: hash path + sample_rate + shape + label + a
        truncated digest of the raw PCM bytes for each sample, so that two
        files with identical metadata but different audio content produce
        different hashes (prevents false deduplication).

        For all others: hash ``json.dumps(data, sort_keys=True, default=str)``.
        """
        if artifact_type == "audio_samples":
            manifest_entries = []
            for sample in data:
                path = getattr(sample, "path", None) or getattr(sample, "source_path", str(id(sample)))
                sr = getattr(sample, "sample_rate", 0)
                raw_data = getattr(sample, "data", None)
                shape = tuple(raw_data.shape) if raw_data is not None else ()
                label = getattr(sample, "label", None)
                # Include a hash of the actual PCM bytes to distinguish files
                # that share the same path/shape/sr but have different content.
                if raw_data is not None and hasattr(raw_data, "tobytes"):
                    try:
                        pcm_hash = hashlib.sha256(raw_data.tobytes()).hexdigest()[:16]
                    except Exception:
                        pcm_hash = ""
                else:
                    pcm_hash = ""
                manifest_entries.append({
                    "path": path,
                    "sample_rate": sr,
                    "shape": list(shape),
                    "label": label,
                    "pcm_hash": pcm_hash,
                })
            raw = json.dumps(manifest_entries, sort_keys=True)
        else:
            try:
                def _numpy_default(obj: Any) -> Any:
                    try:
                        import numpy as np  # noqa: PLC0415
                        if isinstance(obj, np.ndarray):
                            return obj.tolist()
                        if isinstance(obj, np.integer):
                            return int(obj)
                        if isinstance(obj, np.floating):
                            return float(obj)
                    except ImportError:
                        pass
                    return str(obj)

                if hasattr(data, "model_dump"):
                    serializable = data.model_dump()
                elif isinstance(data, list) and data and hasattr(data[0], "model_dump"):
                    serializable = [item.model_dump() for item in data]
                else:
                    serializable = data
                raw = json.dumps(serializable, sort_keys=True, default=_numpy_default)
            except Exception:
                raw = json.dumps(str(data), sort_keys=True)

        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def _serialize_data(self, artifact_type: str, data: Any, data_dir: Path) -> None:
        """Write artifact data to data_dir.

        Raises ArtifactSerializationError on failure.
        """
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            if artifact_type == "audio_samples":
                self._serialize_audio_samples(data, data_dir)
            else:
                self._serialize_json(data, data_dir)
        except ArtifactSerializationError:
            raise
        except Exception as exc:
            raise ArtifactSerializationError(artifact_type, exc) from exc

    def _serialize_audio_samples(self, samples: list, data_dir: Path) -> None:
        """Write WAV files + manifest.json (same format as PipelineCache)."""
        import numpy as np
        import soundfile as sf

        manifest_entries = []
        for i, sample in enumerate(samples):
            filename = f"{i}.wav"
            wav_path = data_dir / filename
            sample_data = getattr(sample, "data", None)
            sample_rate = getattr(sample, "sample_rate", 22050)
            if sample_data is not None and len(sample_data) > 0:
                sf.write(str(wav_path), sample_data, sample_rate)
            else:
                sf.write(str(wav_path), np.array([], dtype=np.float32), sample_rate)
            manifest_entries.append(
                {
                    "filename": filename,
                    "label": getattr(sample, "label", None),
                    "path": getattr(sample, "path", None) or getattr(sample, "source_path", ""),
                    "sample_rate": sample_rate,
                    "metadata": getattr(sample, "metadata", {}),
                }
            )
        manifest = {"samples": manifest_entries}
        (data_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def _serialize_json(self, data: Any, data_dir: Path) -> None:
        """Write data.json using model_dump or json.dumps.

        Handles numpy arrays by converting them to lists via a custom default.
        Numpy is imported conditionally so this method works on systems
        without numpy installed.
        """
        try:
            import numpy as np  # noqa: PLC0415
            _has_numpy = True
        except ImportError:
            _has_numpy = False

        def _numpy_default(obj: Any) -> Any:
            if _has_numpy:
                if isinstance(obj, np.ndarray):
                    return obj.tolist()
                if isinstance(obj, np.integer):
                    return int(obj)
                if isinstance(obj, np.floating):
                    return float(obj)
            return str(obj)

        if hasattr(data, "model_dump"):
            try:
                serializable = data.model_dump()
            except Exception:
                serializable = {"repr": str(data)}
        elif isinstance(data, list) and data and hasattr(data[0], "model_dump"):
            try:
                serializable = [item.model_dump() for item in data]
            except Exception:
                serializable = [str(item) for item in data]
        else:
            serializable = data
        (data_dir / "data.json").write_text(
            json.dumps(serializable, indent=2, default=_numpy_default), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(
        self,
        run_id: str,
        node_id: str,
        node_type: str,
        artifact_type: str,
        data: Any,
        metadata: dict[str, Any] | None = None,
        name: str | None = None,
    ) -> ArtifactRecord:
        """Register a node output as an artifact.

        Returns an existing ArtifactRecord if content_hash already exists
        (content-addressed deduplication). Otherwise creates a new record.

        Raises:
            ValueError: if artifact_type is not in SUPPORTED_ARTIFACT_TYPES
            ArtifactSerializationError: if serialization fails
        """
        if artifact_type not in SUPPORTED_ARTIFACT_TYPES:
            raise ValueError(
                f"Unsupported artifact_type {artifact_type!r}. "
                f"Supported types: {sorted(SUPPORTED_ARTIFACT_TYPES)}"
            )

        content_hash = self._compute_content_hash(artifact_type, data)

        # Serialize data BEFORE acquiring the lock so the lock is held only for
        # the index read-modify-write, not for the (potentially slow) disk write
        # (ARCH-6 fix — prevents parallel execution bottleneck).
        # We use a temporary artifact_id for the directory; if deduplication
        # finds an existing record we discard the temp directory.
        import tempfile as _tempfile
        # SA-AS1 fix: use the full UUID4 hex string (32 chars, 128 bits of entropy)
        # instead of truncating to 16 chars (64 bits), which risks collisions at
        # very high artifact throughput.
        tmp_artifact_id = str(uuid.uuid4()).replace("-", "")
        tmp_artifact_dir = self.base / f"_tmp_{tmp_artifact_id}"
        tmp_data_dir = tmp_artifact_dir / "data"
        try:
            self._serialize_data(artifact_type, data, tmp_data_dir)
        except ArtifactSerializationError:
            raise

        with self._lock:
            index = self._load_index()

            # Deduplication: return existing record if content_hash known.
            if content_hash in index:
                existing_id = index[content_hash]
                record_path = self.base / existing_id / "record.json"
                if record_path.exists():
                    try:
                        record_data = json.loads(record_path.read_text(encoding="utf-8"))
                        existing = ArtifactRecord.model_validate(record_data)
                        # Discard the temp directory — we don't need it.
                        import shutil as _shutil
                        _shutil.rmtree(str(tmp_artifact_dir), ignore_errors=True)
                        # G3-09 fix: add deduplicated artifact to the by_run index for this run
                        self._append_by_run(run_id, existing.artifact_id)
                        return ArtifactRecord(
                            artifact_id=existing.artifact_id,
                            content_hash=existing.content_hash,
                            artifact_type=existing.artifact_type,
                            node_id=node_id,
                            node_type=node_type,
                            run_id=run_id,
                            name=name if name is not None else existing.name,
                            metadata=metadata if metadata is not None else existing.metadata,
                            created_at=existing.created_at,
                            schema_version=existing.schema_version,
                            data_path=existing.data_path,
                        )
                    except Exception as exc:
                        logger.warning(
                            "ArtifactStore: failed to load existing record for %s (%s) — re-registering",
                            existing_id,
                            exc,
                        )

            # New artifact — rename temp dir to final artifact_id dir.
            artifact_id = tmp_artifact_id
            artifact_dir = self.base / artifact_id
            try:
                tmp_artifact_dir.rename(artifact_dir)
            except OSError as exc:
                # SA-AS3 fix: re-check the index after acquiring the lock — a
                # concurrent register() call may have already written this hash
                # between our pre-lock serialize and the lock acquisition.
                # If so, return the existing record rather than raising a
                # confusing OSError about a file that already exists.
                index_recheck = self._load_index()
                if content_hash in index_recheck:
                    existing_id = index_recheck[content_hash]
                    record_path_recheck = self.base / existing_id / "record.json"
                    if record_path_recheck.exists():
                        try:
                            import shutil as _shutil
                            _shutil.rmtree(str(tmp_artifact_dir), ignore_errors=True)
                            record_data = json.loads(record_path_recheck.read_text(encoding="utf-8"))
                            return ArtifactRecord.model_validate(record_data)
                        except Exception:
                            pass
                import shutil as _shutil
                _shutil.rmtree(str(tmp_artifact_dir), ignore_errors=True)
                raise ArtifactSerializationError(artifact_type, exc) from exc

            created_at = datetime.now(timezone.utc).isoformat()
            data_path = str(Path("artifacts") / artifact_id / "data")

            record = ArtifactRecord(
                artifact_id=artifact_id,
                content_hash=content_hash,
                artifact_type=artifact_type,
                node_id=node_id,
                node_type=node_type,
                run_id=run_id,
                name=name,
                metadata=metadata or {},
                created_at=created_at,
                schema_version="1.0",
                data_path=data_path,
            )

            # Write record.json
            (artifact_dir / "record.json").write_text(
                json.dumps(record.model_dump(mode="json"), indent=2), encoding="utf-8"
            )

            # Update content-hash index
            index[content_hash] = artifact_id
            self._save_index(index)

            # Update secondary run_id index
            self._append_by_run(run_id, artifact_id)

            # Update secondary name index (if name is set)
            if name:
                self._append_by_name(name, artifact_id)

            return record

    def get(self, artifact_id: str) -> ArtifactRecord:
        """Return the ArtifactRecord for the given artifact_id.

        Raises:
            ArtifactNotFoundError: if artifact_id is not found
        """
        record_path = self.base / artifact_id / "record.json"
        if not record_path.exists():
            raise ArtifactNotFoundError(artifact_id)
        try:
            record_data = json.loads(record_path.read_text(encoding="utf-8"))
            return ArtifactRecord.model_validate(record_data)
        except ArtifactNotFoundError:
            raise
        except Exception as exc:
            raise ArtifactNotFoundError(artifact_id) from exc

    def list(
        self,
        run_id: str | None = None,
        node_type: str | None = None,
        artifact_type: str | None = None,
    ) -> list[ArtifactRecord]:
        """Return all registered artifacts, optionally filtered.

        Filters are ANDed. Results are sorted by created_at descending.

        When only ``run_id`` is provided the secondary ``by_run/`` index is
        used to avoid a full directory scan (O(1) index lookup + O(k) record
        reads where k = artifacts in that run).
        """
        records: list[ArtifactRecord] = []
        if not self.base.is_dir():
            return records

        # Fast path: run_id-only filter uses the secondary index
        if run_id is not None and node_type is None and artifact_type is None:
            for artifact_id in self._load_by_run(run_id):
                record_path = self.base / artifact_id / "record.json"
                if not record_path.exists():
                    continue
                try:
                    record = ArtifactRecord.model_validate(
                        json.loads(record_path.read_text(encoding="utf-8"))
                    )
                    records.append(record)
                except Exception as exc:
                    logger.warning(
                        "ArtifactStore: failed to load record %s (%s) — skipping", artifact_id, exc
                    )
            records.sort(key=lambda r: r.created_at, reverse=True)
            return records

        # Slow path: full directory scan (needed for node_type / artifact_type filters)
        for entry in self.base.iterdir():
            # SA-AS4 fix: also skip by_name/ in the slow-path scan (previously
            # only by_run/ was skipped, wasting one os.stat call per by_name entry).
            if not entry.is_dir() or entry.name in ("by_run", "by_name"):
                continue
            record_path = entry / "record.json"
            if not record_path.exists():
                continue
            try:
                record_data = json.loads(record_path.read_text(encoding="utf-8"))
                record = ArtifactRecord.model_validate(record_data)
            except Exception as exc:
                logger.warning("ArtifactStore: failed to load record at %s (%s) — skipping", record_path, exc)
                continue

            if run_id is not None and record.run_id != run_id:
                continue
            if node_type is not None and record.node_type != node_type:
                continue
            if artifact_type is not None and record.artifact_type != artifact_type:
                continue

            records.append(record)

        records.sort(key=lambda r: r.created_at, reverse=True)
        return records

    def get_versions(self, artifact_name: str) -> list[ArtifactRecord]:
        """Return all artifacts whose name equals artifact_name, sorted by created_at descending.

        Uses the ``by_name/`` secondary index for O(k) lookup where k = number
        of artifacts with that name (BUG-11 fix — previously O(N) full scan).
        Falls back to full scan if the index is missing (e.g. artifacts
        registered before the index was introduced).
        """
        ids = self._load_by_name(artifact_name)
        if ids:
            records: list[ArtifactRecord] = []
            for artifact_id in ids:
                record_path = self.base / artifact_id / "record.json"
                if not record_path.exists():
                    continue
                try:
                    records.append(
                        ArtifactRecord.model_validate(
                            json.loads(record_path.read_text(encoding="utf-8"))
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        "ArtifactStore: failed to load record %s (%s) — skipping",
                        artifact_id, exc,
                    )
            records.sort(key=lambda r: r.created_at, reverse=True)
            return records
        # Fallback: full scan for artifacts registered before by_name index existed
        return [r for r in self.list() if r.name == artifact_name]

    def cleanup(self, older_than_days: int = 30) -> dict:
        """Delete artifact directories older than older_than_days.

        Removes the artifact directory, its record.json, and updates the
        content-hash index and all secondary indexes (by_run/, by_name/).
        Returns a summary dict.

        Args:
            older_than_days: Artifacts created more than this many days ago
                             are deleted. Default: 30 days.
        """
        from datetime import timedelta
        import shutil

        if not self.base.is_dir():
            return {"entries_deleted": 0, "bytes_freed": 0}

        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        entries_deleted = 0
        bytes_freed = 0
        hashes_to_remove: list[str] = []
        deleted_ids: list[str] = []

        for entry in list(self.base.iterdir()):
            if not entry.is_dir() or entry.name in ("by_run", "by_name"):
                continue
            record_path = entry / "record.json"
            if not record_path.exists():
                continue
            try:
                record_data = json.loads(record_path.read_text(encoding="utf-8"))
                record = ArtifactRecord.model_validate(record_data)
                from datetime import datetime as _dt
                created = _dt.fromisoformat(record.created_at)
                if created.tzinfo is None:
                    from datetime import timezone as _tz
                    created = created.replace(tzinfo=_tz.utc)
                if created >= cutoff:
                    continue
                hashes_to_remove.append(record.content_hash)
                deleted_ids.append(record.artifact_id)
            except Exception:
                pass

            for f in entry.rglob("*"):
                if f.is_file():
                    bytes_freed += f.stat().st_size
            shutil.rmtree(str(entry), ignore_errors=True)
            entries_deleted += 1

        if hashes_to_remove or deleted_ids:
            with self._lock:
                # Update content-hash index
                index = self._load_index()
                for h in hashes_to_remove:
                    index.pop(h, None)
                self._save_index(index)

                # NEW-10 fix: remove stale entries from by_run/ and by_name/ indexes.
                # Without this, the indexes grow unboundedly on high-artifact-turnover systems.
                deleted_set = set(deleted_ids)

                by_run_dir = self.base / "by_run"
                if by_run_dir.is_dir():
                    for run_index_file in by_run_dir.iterdir():
                        if not run_index_file.is_file() or run_index_file.suffix != ".json":
                            continue
                        try:
                            ids: list[str] = json.loads(run_index_file.read_text(encoding="utf-8"))
                            cleaned = [i for i in ids if i not in deleted_set]
                            if len(cleaned) != len(ids):
                                tmp = run_index_file.with_suffix(".json.tmp")
                                tmp.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
                                tmp.replace(run_index_file)
                        except Exception as exc:
                            logger.warning("cleanup: failed to update by_run index %s: %s", run_index_file, exc)

                by_name_dir = self.base / "by_name"
                if by_name_dir.is_dir():
                    for name_index_file in by_name_dir.iterdir():
                        if not name_index_file.is_file() or name_index_file.suffix != ".json":
                            continue
                        try:
                            ids = json.loads(name_index_file.read_text(encoding="utf-8"))
                            cleaned = [i for i in ids if i not in deleted_set]
                            if len(cleaned) != len(ids):
                                tmp = name_index_file.with_suffix(".json.tmp")
                                tmp.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
                                tmp.replace(name_index_file)
                        except Exception as exc:
                            logger.warning("cleanup: failed to update by_name index %s: %s", name_index_file, exc)

        return {"entries_deleted": entries_deleted, "bytes_freed": bytes_freed}
