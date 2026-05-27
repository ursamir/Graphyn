# app/core/pipeline_cache.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Content-keyed cache for node outputs. Avoids re-executing
                  nodes whose inputs and config have not changed.
Owns:             PipelineCache class — key derivation, load, save, clear.
Public Surface:   PipelineCache().key(), .input_hash(), .load(), .save(), .clear()
Must NOT:         Import app.models at module level or reference any artifact
                  type string by name (e.g. "audio_samples"). All type
                  inference is done via ArtifactSerializerRegistry.infer_type().
                  Must not share its base directory with ArtifactStore (SA-PC4).
Dependencies:     stdlib, pydantic (lazy), app.core.config (cache_dir),
                  app.core.artifact_serializer (registry — no domain knowledge).
Reason To Change: Cache storage format evolves, new cacheable output types
                  are added, or cache key derivation strategy changes.

## Storage formats (current — no legacy support)

``outputs.json``
    Generic JSON-serializable outputs dict. Written for ports whose type is
    not recognised by ArtifactSerializerRegistry.

``manifest.json`` + ``port_<name>/``
    Written for ports whose type IS recognised by ArtifactSerializerRegistry.
    manifest.json contains ``cached_ports`` (list) and ``port_types``
    (port_name → type_key). Both fields are required; manifests missing
    either field are treated as unreadable (node re-executes).

Both files are written atomically via tmp + os.replace.
All I/O is delegated to ArtifactSerializerRegistry handlers — this file
contains zero domain-model knowledge.
"""
import hashlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Optional

import pydantic  # noqa: F401 — kept for backward compat; ValidationError no longer used inline

logger = logging.getLogger(__name__)

from app.core.config import cache_dir as _cache_dir

# ── Helpers to detect cacheable output types ──────────────────────────────────

def _is_json_serializable(value: Any) -> bool:
    """Return True if value can be round-tripped through JSON."""
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


class PipelineCache:
    def __init__(self) -> None:
        self._base_override: Path | None = None

    @property
    def BASE(self) -> Path:
        if self._base_override is not None:
            return self._base_override
        return _cache_dir()

    @BASE.setter
    def BASE(self, value: Path) -> None:
        """Override the cache base directory.

        This setter exists for test isolation only — use ``monkeypatch`` on
        ``app.core.config.cache_dir`` in production test suites instead.
        It is not part of the public API and may be removed in a future version.

        SA-PC4: PipelineCache and ArtifactStore must NOT share the same base
        directory. If they did, clear() would delete artifact records without
        updating ArtifactStore's index.json.
        """
        from app.core.config import artifacts_dir as _artifacts_dir
        try:
            artifacts_base = _artifacts_dir().parent / "artifacts"
            assert value.resolve() != artifacts_base.resolve(), (
                f"PipelineCache.BASE ({value}) must not be the same directory as "
                f"ArtifactStore.base ({artifacts_base}). "
                "clear() would delete artifact records without updating the index."
            )
        except Exception as exc:
            if isinstance(exc, AssertionError):
                raise
            # Config not yet initialised (e.g. in tests) — skip the check
        self._base_override = value

    def compute_key(self, node_type: str, config: dict, inputs: dict) -> str:
        """Compute the cache key for a node given its type, config, and inputs dict.

        Combines per-port input hashes so port identity is preserved (NEW-6 fix).
        This is the single canonical implementation — both the sequential
        orchestrator and the parallel executor call this method so the hashing
        strategy is never duplicated.

        Args:
            node_type: The node's type string.
            config: The node's config dict.
            inputs: The node's input dict (port_name → value).

        Returns:
            A SHA-256 hex digest string suitable for use as a cache directory name.
        """
        import hashlib as _hashlib  # noqa: PLC0415
        combined_input_hash = _hashlib.sha256(
            "".join(self.input_hash(v) for v in inputs.values()).encode()
        ).hexdigest()
        return self.key(node_type, config, combined_input_hash)

    def key(self, node_type: str, config: dict, input_hash: str) -> str:
        """SHA-256 of node_type + sorted_json(config) + input_hash."""
        sorted_config = json.dumps(config, sort_keys=True)
        raw = node_type + sorted_config + input_hash
        return hashlib.sha256(raw.encode()).hexdigest()

    def input_hash(self, inputs: Any) -> str:
        """Compute a stable hash for any node input value.

        Supports:
        - list[AudioSample] — hashed by path + sample_rate + data shape
        - list of Pydantic models — hashed via model_dump JSON
        - numpy ndarray — hashed via raw bytes (stable across runs)
        - JSON-serializable dicts/lists — hashed via sorted JSON
        - Fallback — returns empty string (forces cache miss; logs warning)
        """
        if isinstance(inputs, list) and len(inputs) > 0:
            first = inputs[0]
            if hasattr(first, "path") and hasattr(first, "sample_rate") and hasattr(first, "data"):
                # AudioSample list (original behaviour)
                parts = []
                for sample in inputs:
                    # Guard: sample.data may be bytes, list, or any object without .shape
                    shape = getattr(sample.data, "shape", ()) if sample.data is not None else ()
                    path = getattr(sample, "path", None) or getattr(sample, "source_path", str(id(sample)))
                    sr = getattr(sample, "sample_rate", 0)
                    parts.append(f"{path}:{sr}:{shape}")
                raw = "".join(parts)
                return hashlib.sha256(raw.encode()).hexdigest()
            if hasattr(first, "model_dump"):
                # List of Pydantic models — may contain non-serializable types (e.g. numpy arrays)
                try:
                    raw = json.dumps([item.model_dump(mode="json") for item in inputs], sort_keys=True)
                    return hashlib.sha256(raw.encode()).hexdigest()
                except Exception:
                    pass  # Fall through to numpy / repr() fallback

        # Single Pydantic model (e.g. DatasetArtifact passed to trainer.dataset port)
        if hasattr(inputs, "model_dump"):
            try:
                raw = json.dumps(inputs.model_dump(mode="json"), sort_keys=True)
                return hashlib.sha256(raw.encode()).hexdigest()
            except Exception:
                pass  # Fall through to numpy / repr() fallback

        # numpy ndarray — hash raw bytes for cross-run stability
        try:
            import numpy as np  # noqa: PLC0415
            if isinstance(inputs, np.ndarray):
                return hashlib.sha256(inputs.tobytes()).hexdigest()
            # List of numpy arrays
            if isinstance(inputs, list) and inputs and isinstance(inputs[0], np.ndarray):
                h = hashlib.sha256()
                for arr in inputs:
                    h.update(arr.tobytes())
                return h.hexdigest()
        except ImportError:
            pass

        if _is_json_serializable(inputs):
            raw = json.dumps(inputs, sort_keys=True, default=str)
            return hashlib.sha256(raw.encode()).hexdigest()

        # Last-resort fallback: repr() is NOT stable across process restarts
        # (object addresses change). Return an empty string so the cache key
        # is effectively random, which forces a cache miss on every run.
        # Nodes that reach this path should be marked cacheable=False.
        # We log a warning so operators can identify and fix the node.
        logger.warning(
            "PipelineCache.input_hash: cannot compute stable hash for type %s — "
            "returning empty hash (cache will always miss for this input). "
            "Mark this node cacheable=False to suppress this warning.",
            type(inputs).__name__,
        )
        return ""

    def _cache_dir(self, cache_key: str) -> Path:
        return self.BASE / cache_key

    def has(self, cache_key: str) -> bool:
        """Return True if a cache entry exists for key.

        .. deprecated::
            SA-PC1: This method is a TOCTOU hazard — the entry may be deleted
            between ``has()`` and ``load()``. Always treat ``load()`` returning
            ``None`` as a cache miss, regardless of what ``has()`` returned.
            Prefer calling ``load()`` directly. This method will be removed in
            a future version; use ``_has()`` internally if needed.

        .. warning::
            TOCTOU: the entry may be deleted between has() and load().
            Always treat load() returning None as a cache miss, regardless
            of what has() returned. Prefer calling load() directly.
        """
        import warnings
        warnings.warn(
            "PipelineCache.has() is deprecated and will be removed in a future version. "
            "Call load() directly and treat None as a cache miss.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self._has(cache_key)

    def _has(self, cache_key: str) -> bool:
        """Internal: return True if a cache entry directory exists for key."""
        return self._cache_dir(cache_key).is_dir()

    def load(self, cache_key: str) -> Optional[Any]:
        """Load cached node outputs.

        Supports two storage formats:
        - ``outputs.json`` — generic JSON-serializable outputs dict
        - ``manifest.json`` with ``cached_ports`` — multi-port serialized format

        Manifests without a ``cached_ports`` key are treated as unreadable
        (no legacy single-port format support — clean migration only).

        Returns the outputs dict on success, or None on failure (cache miss).
        """
        cache_dir = self._cache_dir(cache_key)

        # ── New generic format ─────────────────────────────────────────────────
        outputs_path = cache_dir / "outputs.json"
        if outputs_path.exists():
            try:
                with open(outputs_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning(
                    "Cache read (outputs.json) failed for key %s (%s) — will re-execute",
                    cache_key, exc,
                )
                return None

        # ── Multi-port serialized format ───────────────────────────────────────
        top_manifest_path = cache_dir / "manifest.json"
        if not top_manifest_path.exists():
            return None

        try:
            with open(top_manifest_path, "r", encoding="utf-8") as f:
                top_manifest_data = json.load(f)
        except Exception as exc:
            logger.warning(
                "Cache read (manifest.json) failed for key %s (%s) — will re-execute",
                cache_key, exc,
            )
            return None

        cached_ports = top_manifest_data.get("cached_ports")
        port_types: dict[str, str] = top_manifest_data.get("port_types", {})

        if cached_ports is None:
            # Manifest exists but has no cached_ports key — unreadable format.
            logger.warning(
                "Cache at '%s' has manifest.json without 'cached_ports' key — "
                "unreadable format, will re-execute.",
                cache_dir,
            )
            return None

        # Valid new-format entry with zero ports — return empty dict (cache hit).
        if cached_ports == []:
            return {}

        try:
            from app.core.artifact_serializer import get_serializer_registry  # noqa: PLC0415
            _ser_registry = get_serializer_registry()
            result: dict = {}
            for port_name in cached_ports:
                port_dir = cache_dir / f"port_{port_name}"
                if not port_dir.exists():
                    logger.warning(
                        "Cache read: port dir missing for '%s' in key %s — will re-execute",
                        port_name, cache_key,
                    )
                    return None
                type_key = port_types.get(port_name)
                if type_key is None:
                    logger.warning(
                        "Cache manifest for key %s has no type_key for port '%s' — will re-execute",
                        cache_key, port_name,
                    )
                    return None
                handler = _ser_registry.get(type_key)
                if handler is None:
                    logger.warning(
                        "Cache read: no handler for type '%s' (port '%s', key %s) — will re-execute",
                        type_key, port_name, cache_key,
                    )
                    return None
                value = handler.deserialize(port_dir)
                if value is None:
                    logger.warning(
                        "Cache read: deserialize returned None for port '%s' key %s — will re-execute",
                        port_name, cache_key,
                    )
                    return None
                result[port_name] = value
            return result
        except Exception as exc:
            logger.warning(
                "Cache read (port subdirs) failed for key %s (%s) — will re-execute",
                cache_key, exc,
            )
            return None

    def save(self, cache_key: str, outputs: Any) -> None:
        """Save node outputs to cache.

        ``outputs`` may be:
        - A dict mapping port names to values (standard node output shape)
        - A list (normalised to ``{"output": outputs}``)

        Storage strategy:
        - Ports whose type is recognised by ArtifactSerializerRegistry →
          written to ``port_<name>/`` subdirectories; manifest.json records
          port names and type keys.
        - All other ports → ``outputs.json`` (JSON-serializable values only).

        Both manifest.json and outputs.json are written atomically via a
        temporary file + os.replace so a crash mid-write never leaves a
        partial cache entry that can be loaded as a wrong result.
        """
        cache_dir = self._cache_dir(cache_key)
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Normalise legacy list input to dict
        if isinstance(outputs, list):
            outputs = {"output": outputs}

        if not isinstance(outputs, dict):
            logger.debug("Cache.save: outputs is not a dict — skipping cache write")
            return

        from app.core.artifact_serializer import get_serializer_registry  # noqa: PLC0415
        _ser_registry = get_serializer_registry()

        # Partition ports: serializable via registry vs JSON-only
        registry_ports: dict[str, tuple[str, Any]] = {}  # port_name → (type_key, value)
        json_ports: dict[str, Any] = {}

        for port_name, value in outputs.items():
            type_key = _ser_registry.infer_type(value)
            if type_key is not None and _ser_registry.get(type_key) is not None:
                registry_ports[port_name] = (type_key, value)
            else:
                json_ports[port_name] = value

        # ── Registry-typed ports → port_<name>/ subdirectories ────────────────
        if registry_ports:
            port_manifest: dict[str, str] = {}
            for port_name, (type_key, value) in registry_ports.items():
                handler = _ser_registry.get(type_key)
                port_dir = cache_dir / f"port_{port_name}"
                port_dir.mkdir(parents=True, exist_ok=True)
                try:
                    handler.serialize(value, port_dir)
                    port_manifest[port_name] = type_key
                except Exception as exc:
                    logger.warning(
                        "Cache.save: failed to serialize port '%s' (type '%s'): %s — skipping",
                        port_name, type_key, exc,
                    )
                    return

            # Write manifest atomically so a crash between the last serialize
            # and the manifest write never leaves a partial entry that loads
            # as an incomplete (wrong) cache hit.
            top_manifest_path = cache_dir / "manifest.json"
            tmp_manifest = cache_dir / "manifest.json.tmp"
            with open(tmp_manifest, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "cached_ports": sorted(port_manifest.keys()),
                        "port_types": port_manifest,
                    },
                    f,
                    indent=2,
                )
            tmp_manifest.replace(top_manifest_path)
            return

        # ── JSON-only ports → outputs.json ─────────────────────────────────────
        serializable: dict = {}
        skipped_ports: list[str] = []
        for port_name, value in json_ports.items():
            if _is_json_serializable(value):
                serializable[port_name] = value
            elif hasattr(value, "model_dump"):
                try:
                    serializable[port_name] = value.model_dump(mode="json")
                except Exception:
                    skipped_ports.append(port_name)
            else:
                skipped_ports.append(port_name)

        if skipped_ports:
            logger.warning(
                "Cache.save: skipping non-serializable port(s) %s — "
                "these outputs will not be cached and the node will re-execute on the next run. "
                "Mark the node cacheable=False to suppress this warning.",
                skipped_ports,
            )

        if not serializable:
            logger.warning(
                "Cache.save: no serializable ports in outputs — skipping cache write entirely."
            )
            return

        outputs_path = cache_dir / "outputs.json"
        tmp_outputs = cache_dir / "outputs.json.tmp"
        with open(tmp_outputs, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2)
        tmp_outputs.replace(outputs_path)

    def clear(self) -> dict:
        """Delete all cache entries. Returns {entries_deleted, bytes_freed}.

        SA-PC4: PipelineCache and ArtifactStore must NOT share the same base
        directory. If they did, clear() would delete artifact records without
        updating ArtifactStore's index.json. This is enforced by the assertion
        in the BASE setter and by keeping the default directories separate
        (cache/ vs artifacts/).
        """
        if not self.BASE.is_dir():
            return {"entries_deleted": 0, "bytes_freed": 0}

        entries_deleted = 0
        bytes_freed = 0

        for entry in self.BASE.iterdir():
            if entry.is_dir():
                for file in entry.rglob("*"):
                    if file.is_file():
                        bytes_freed += file.stat().st_size
                try:
                    shutil.rmtree(entry)
                    entries_deleted += 1
                except Exception as exc:
                    logger.warning(
                        "Cache.clear: failed to remove entry '%s' (%s) — skipping",
                        entry, exc,
                    )

        return {"entries_deleted": entries_deleted, "bytes_freed": bytes_freed}
