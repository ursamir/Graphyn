# app/core/artifact_store.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Content-addressed, typed artifact registry. Stores artifact
                  metadata envelopes and serialized data with deduplication.
Owns:             ArtifactRecord (immutable metadata model), ArtifactStore
                  (registry with content-hash deduplication and secondary indexes).
Public Surface:   ArtifactStore.register(), .get(), .list(), .get_versions(),
                  .cleanup(); ArtifactRecord; ArtifactNotFoundError;
                  ArtifactSerializationError; _get_supported_artifact_types();
                  _infer_artifact_type() (delegates to ArtifactSerializerRegistry).
Must NOT:         Import from app.domain, app.api, or app.core.orchestrator.
                  Must not contain domain-specific serialization logic or
                  domain type heuristics (duck-typing, hardcoded type strings,
                  domain model imports). All type inference lives in domain
                  handlers registered via ArtifactSerializerRegistry at startup.
Dependencies:     stdlib, pydantic, app.core.config (path resolution),
                  app.core.artifact_serializer (registry interface — no domain
                  knowledge flows through it).
Reason To Change: New artifact types, storage format changes, index strategy
                  changes, or deduplication policy evolves.
"""
from __future__ import annotations

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

def _get_supported_artifact_types() -> frozenset[str]:
    """Return the set of artifact_type strings currently supported.

    Derived dynamically from the ArtifactSerializerRegistry plus the
    built-in "generic" fallback. This replaces the old hardcoded
    SUPPORTED_ARTIFACT_TYPES constant so that new domain types registered
    at startup are automatically accepted without editing platform code.
    """
    from app.core.artifact_serializer import get_serializer_registry  # noqa: PLC0415
    registered = get_serializer_registry().registered_types()
    return frozenset(registered) | {"generic"}


def _infer_artifact_type(value: Any) -> str:
    """Infer the ArtifactStore artifact_type string from a node output value.

    Delegates entirely to the ArtifactSerializerRegistry. Domain handlers
    (e.g. AudioSampleHandler, FeatureArrayHandler) are registered at startup
    and implement infer_type() to identify their own values.

    Falls back to "generic" for any value no handler recognises.
    Platform code contains zero domain-specific heuristics.
    """
    from app.core.artifact_serializer import get_serializer_registry  # noqa: PLC0415
    inferred = get_serializer_registry().infer_type(value)
    return inferred if inferred is not None else "generic"


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
    """Artifact type string, as returned by _infer_artifact_type()."""

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
        # Use a SHA-256 prefix of the original name as the filename to avoid
        # sanitization collisions (e.g. "my model" and "my_model" mapping to
        # the same file). The original name is stored inside the index file
        # for exact-match filtering in _load_by_name.
        # SA-AS9 fix: hash-based filename replaces character-substitution
        # sanitization which caused silent cross-name collisions.
        import hashlib as _hashlib
        name_hash = _hashlib.sha256(name.encode("utf-8")).hexdigest()[:32]
        return self.base / "by_name" / f"{name_hash}.json"

    def _load_by_name(self, name: str) -> list[str]:
        """Return list of artifact_ids whose stored name exactly matches `name`.

        Index format: list of {"id": str, "name": str} dicts.
        Legacy format (plain list of str) is also handled for backward compat.
        Returns [] on missing/corrupt.
        """
        path = self._by_name_path(name)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            result: list[str] = []
            for entry in data:
                if isinstance(entry, dict):
                    # New format: {"id": ..., "name": ...}
                    if entry.get("name") == name:
                        result.append(entry["id"])
                elif isinstance(entry, str):
                    # Legacy format: plain artifact_id (no name stored — include all)
                    result.append(entry)
            return result
        except FileNotFoundError:
            return []
        except Exception as exc:
            logger.warning("ArtifactStore: by_name index for %r corrupt (%s) — treating as empty", name, exc)
            return []

    def _append_by_name(self, name: str, artifact_id: str) -> None:
        """Append artifact_id to the by_name index (caller must hold self._lock).

        Stores {"id": artifact_id, "name": name} so that _load_by_name can
        filter by exact name match even when two names hash to the same file
        (extremely unlikely with SHA-256/32 but handled defensively).
        """
        (self.base / "by_name").mkdir(exist_ok=True)
        path = self._by_name_path(name)
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except FileNotFoundError:
            existing = []
        except Exception:
            existing = []
        # Avoid duplicates
        if not any(
            (isinstance(e, dict) and e.get("id") == artifact_id)
            or (isinstance(e, str) and e == artifact_id)
            for e in existing
        ):
            existing.append({"id": artifact_id, "name": name})
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        tmp.replace(path)

    # ------------------------------------------------------------------
    # Content hashing
    # ------------------------------------------------------------------

    def _compute_content_hash(self, artifact_type: str, data: Any) -> str:
        """Compute SHA-256 content hash for the given artifact data.

        For registered artifact types: delegates to the handler's
        ``compute_content_hash_input()`` method.

        For all others: hash ``json.dumps(data, sort_keys=True, default=str)``.

        ARCH-2 fix: audio-specific hashing logic removed from platform
        infrastructure. AudioSampleHandler.compute_content_hash_input()
        in app/models/audio_artifact_serializer.py owns that logic.
        """
        from app.core.artifact_serializer import get_serializer_registry  # noqa: PLC0415
        handler = get_serializer_registry().get(artifact_type)
        if handler is not None:
            raw = handler.compute_content_hash_input(data)
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

        Delegates to the ArtifactSerializerRegistry for registered types.
        Falls back to JSON serialization for unregistered types.

        ARCH-2 fix: _serialize_audio_samples() removed. WAV I/O is now
        handled by AudioSampleHandler in app/models/audio_artifact_serializer.py,
        registered at startup via register_audio_serializer().

        Raises ArtifactSerializationError on failure.
        """
        from app.core.artifact_serializer import get_serializer_registry  # noqa: PLC0415
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            handler = get_serializer_registry().get(artifact_type)
            if handler is not None:
                handler.serialize(data, data_dir)
            else:
                self._serialize_json(data, data_dir)
        except ArtifactSerializationError:
            raise
        except Exception as exc:
            raise ArtifactSerializationError(artifact_type, exc) from exc

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

        Deduplication contract: when an existing record is returned, the
        ``artifact_id`` and ``data_path`` fields refer to the ORIGINAL artifact.
        The returned record's ``run_id`` and ``node_id`` reflect the CURRENT
        call's context (so the caller can use them for logging/display), but
        ``get(artifact_id)`` will return the canonical record with the original
        ``run_id``. The current run is still registered in the ``by_run`` index.
        Callers that need the canonical record should call ``get(record.artifact_id)``.

        Raises:
            ValueError: if artifact_type is not supported by the registry
            ArtifactSerializationError: if serialization fails
        """
        supported = _get_supported_artifact_types()
        if artifact_type not in supported:
            raise ValueError(
                f"Unsupported artifact_type {artifact_type!r}. "
                f"Supported types: {sorted(supported)}"
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
            # SA-AS7 fix: clean up the temp directory before re-raising so that
            # failed serializations do not accumulate _tmp_*/ directories on disk.
            import shutil as _shutil
            _shutil.rmtree(str(tmp_artifact_dir), ignore_errors=True)
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
                # SA-AS8 fix: rmtree and accounting are INSIDE the try block so
                # that entries with corrupt record.json are skipped (the except
                # block continues) rather than silently deleted with stale index
                # entries left behind.
                for f in entry.rglob("*"):
                    if f.is_file():
                        bytes_freed += f.stat().st_size
                shutil.rmtree(str(entry), ignore_errors=True)
                entries_deleted += 1
            except Exception:
                # Skip entries whose record.json cannot be parsed — do NOT delete
                # them, as their content-hash index entry would become stale.
                continue

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
                            # Handle both new format (list of dicts) and legacy (list of str)
                            cleaned = [
                                e for e in ids
                                if (isinstance(e, dict) and e.get("id") not in deleted_set)
                                or (isinstance(e, str) and e not in deleted_set)
                            ]
                            if len(cleaned) != len(ids):
                                tmp = name_index_file.with_suffix(".json.tmp")
                                tmp.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
                                tmp.replace(name_index_file)
                        except Exception as exc:
                            logger.warning("cleanup: failed to update by_name index %s: %s", name_index_file, exc)

        return {"entries_deleted": entries_deleted, "bytes_freed": bytes_freed}
