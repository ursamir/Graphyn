# app/core/execution/pipeline_cache.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Content-keyed cache for node outputs. Avoids re-executing
                  nodes whose inputs and config have not changed.
Owns:             PipelineCache class — key derivation, load, save (with source run/node provenance), source_of, clear.
Public Surface:   PipelineCache().key(), .input_hash(), .load(), .save(), .source_of(), .clear()
Must NOT:         Import app.models at module level or reference any artifact
                  type string by name (e.g. "audio_samples"). All type
                  inference is done via ArtifactSerializerRegistry.infer_type().
                  Must not share its base directory with ArtifactStore (SA-PC4).
Dependencies:     stdlib, pydantic (lazy), app.core.config (cache_dir),
                  app.core.artifacts.artifact_serializer (registry — no domain knowledge).
Reason To Change: Cache storage format evolves, new cacheable output types
                  are added, or cache key derivation strategy changes.

## Storage formats (current — no legacy support)

``manifest.json`` (commit marker, always written)
    ``all_ports`` (every output port), ``json_ports`` (ports stored in
    outputs.json), ``cached_ports`` + ``port_types`` (registry-serialized
    ports → type_key). Entries without the full inventory are misses.

``outputs.json``
    JSON-serializable ports (plain values or pydantic ``model_dump``).

``port_<name>/``
    Ports whose type IS recognised by ArtifactSerializerRegistry.

Entries are all-or-nothing: if any port cannot be serialized nothing is
written, and load() returns a hit only when every port in ``all_ports`` is
restored. Entries are assembled in a staging dir and renamed into place.
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


class _Unhashable(Exception):
    """Internal: value has no stable content representation."""


def _content_digest(value: Any) -> Optional[str]:
    """Stable SHA-256 over the full content of ``value``; None if unhashable.

    Duck-typed so the platform needs no knowledge of domain models: Pydantic
    models are walked field by field (``model_fields`` + ``getattr``, which
    keeps numpy arrays intact instead of JSON-coercing them), ndarrays
    contribute dtype/shape/bytes, containers are walked recursively.
    """
    try:
        import numpy as np  # noqa: PLC0415
    except ImportError:  # pragma: no cover - numpy is a core dependency
        np = None  # type: ignore[assignment]

    h = hashlib.sha256()

    def _tag(t: str) -> None:
        h.update(b"\x00" + t.encode() + b"\x00")

    def _walk(v: Any, depth: int) -> None:
        if depth > 64:
            raise _Unhashable("nesting too deep")
        if v is None or isinstance(v, (bool, int, float, str)):
            _tag(type(v).__name__)
            h.update(json.dumps(v).encode())
            return
        if isinstance(v, (bytes, bytearray, memoryview)):
            _tag("bytes")
            h.update(bytes(v))
            return
        if np is not None and isinstance(v, np.ndarray):
            _tag("ndarray")
            h.update(str(v.dtype).encode())
            h.update(str(tuple(v.shape)).encode())
            if v.dtype == object:
                for item in v.ravel().tolist():
                    _walk(item, depth + 1)
            else:
                h.update(np.ascontiguousarray(v).tobytes())
            return
        if np is not None and isinstance(v, np.generic):
            _tag("npscalar:" + str(v.dtype))
            h.update(np.asarray(v).tobytes())
            return
        if isinstance(v, dict):
            _tag("dict")
            for k in sorted(v.keys(), key=lambda x: (type(x).__name__, str(x))):
                _walk(k, depth + 1)
                _walk(v[k], depth + 1)
            return
        if isinstance(v, (list, tuple)):
            _tag(type(v).__name__ + ":" + str(len(v)))
            for item in v:
                _walk(item, depth + 1)
            return
        if isinstance(v, (set, frozenset)):
            _tag("set")
            parts = sorted(_content_digest(item) or "" for item in v)
            if any(p == "" for p in parts):
                raise _Unhashable("unhashable set member")
            h.update("".join(parts).encode())
            return
        fields = getattr(type(v), "model_fields", None)
        if isinstance(fields, dict) and hasattr(v, "model_dump"):
            _tag("model:" + type(v).__module__ + "." + type(v).__qualname__)
            for name in sorted(fields):
                _walk(name, depth + 1)
                _walk(getattr(v, name, None), depth + 1)
            extra = getattr(v, "__pydantic_extra__", None)
            if extra:
                _walk(dict(extra), depth + 1)
            return
        import dataclasses  # noqa: PLC0415
        if dataclasses.is_dataclass(v) and not isinstance(v, type):
            _tag("dataclass:" + type(v).__qualname__)
            for f in dataclasses.fields(v):
                _walk(f.name, depth + 1)
                _walk(getattr(v, f.name, None), depth + 1)
            return
        from pathlib import PurePath  # noqa: PLC0415
        if isinstance(v, PurePath):
            _tag("path")
            h.update(str(v).encode())
            return
        raise _Unhashable(type(v).__name__)

    try:
        _walk(value, 0)
    except _Unhashable:
        return None
    except Exception:
        logger.debug("content digest failed for %s", type(value).__name__, exc_info=True)
        return None
    return h.hexdigest()


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

    def compute_key(
        self,
        node_type: str,
        config: dict,
        inputs: dict,
        *,
        node_seed: int | None = None,
        node_version: str | None = None,
    ) -> str:
        """Compute the cache key for a node given its type, config, and inputs dict.

        Combines per-port input hashes so port identity is preserved (NEW-6 fix).
        This is the single canonical implementation — both the sequential
        orchestrator and the parallel executor call this method so the hashing
        strategy is never duplicated.

        Args:
            node_type: The node's type string.
            config: The node's config dict.
            inputs: The node's input dict (port_name → value).
            node_seed: Planner-assigned node seed (P1-7).
            node_version: Registered NodeMetadata.version (P1-7).

        Returns:
            A SHA-256 hex digest string suitable for use as a cache directory name.
        """
        # Port identity is part of the key: sort by port name and fold the name
        # in, so {"input": X, "reference": None} != {"reference": X, "input": None}
        # and dict insertion order never changes the key.
        h = hashlib.sha256()
        for port_name in sorted(inputs.keys(), key=str):
            h.update(str(port_name).encode())
            h.update(b"\x1f")
            h.update(self.input_hash(inputs[port_name]).encode())
            h.update(b"\x1e")
        combined_input_hash = h.hexdigest()
        return self.key(
            node_type,
            config,
            combined_input_hash,
            node_seed=node_seed,
            node_version=node_version,
        )

    def key(
        self,
        node_type: str,
        config: dict,
        input_hash: str,
        *,
        node_seed: int | None = None,
        node_version: str | None = None,
    ) -> str:
        """SHA-256 of node_type + sorted_json(config) + input_hash + seed + version."""
        sorted_config = json.dumps(config, sort_keys=True)
        seed_part = "" if node_seed is None else str(node_seed)
        version_part = "" if node_version is None else str(node_version)
        raw = node_type + sorted_config + input_hash + seed_part + version_part
        return hashlib.sha256(raw.encode()).hexdigest()

    def input_hash(self, inputs: Any) -> str:
        """Compute a stable content hash for any node input value.

        Hashes the full *content* of the value, duck-typed (no domain imports):

        - numpy ndarray → dtype + shape + raw bytes
        - Pydantic models → class name + every field value (recursively, so an
          ``AudioSample``-like model contributes data bytes, label, metadata,
          sample rate and path — a gain change or relabel changes the hash)
        - dict / list / tuple / set → structure + recursive content
        - JSON scalars / bytes → their value
        - anything else → unique miss token (forces a cache miss; logs warning)
        """
        digest = _content_digest(inputs)
        if digest is not None:
            return digest

        # Last-resort fallback: unhashable input must NOT collide across runs.
        # Return a unique token so the cache key forces a miss (P1-5).
        import uuid as _uuid  # noqa: PLC0415

        logger.warning(
            "PipelineCache.input_hash: cannot compute stable hash for type %s — "
            "returning unique miss token. Mark this node cacheable=False to suppress.",
            type(inputs).__name__,
        )
        return f"miss-{_uuid.uuid4().hex}"

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
        """Load cached node outputs; ``None`` means cache miss.

        ``manifest.json`` is the commit marker and lists ``all_ports`` — every
        output port the node produced. A hit is returned only when *every*
        recorded port is restored (JSON ports from ``outputs.json``,
        registry-typed ports from ``port_<name>/``). A partial restore is a
        miss: returning a dict with a missing port would make skip_logic treat
        the port as a branch-not-taken and silently skip consumers.
        """
        cache_dir = self._cache_dir(cache_key)
        top_manifest_path = cache_dir / "manifest.json"
        if not top_manifest_path.exists():
            return None
        try:
            with open(top_manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as exc:
            logger.warning("Cache read (manifest.json) failed for key %s (%s)", cache_key, exc)
            return None
        if not isinstance(manifest, dict):
            return None
        all_ports = manifest.get("all_ports")
        cached_ports = manifest.get("cached_ports")
        port_types = manifest.get("port_types")
        json_ports = manifest.get("json_ports")
        if (
            not isinstance(all_ports, list)
            or not isinstance(cached_ports, list)
            or not isinstance(port_types, dict)
            or not isinstance(json_ports, list)
        ):
            # Pre-fix entry without a complete port inventory — re-execute.
            return None

        merged: dict[str, Any] = {}

        # ── Generic JSON ports ─────────────────────────────────────────────────
        if json_ports:
            outputs_path = cache_dir / "outputs.json"
            try:
                with open(outputs_path, "r", encoding="utf-8") as f:
                    from app.core.plugins.hydrate import hydrate_platform_models  # noqa: PLC0415
                    loaded = hydrate_platform_models(json.load(f))
            except Exception as exc:
                logger.warning(
                    "Cache read (outputs.json) failed for key %s (%s) — will re-execute",
                    cache_key, exc,
                )
                return None
            if not isinstance(loaded, dict):
                return None
            for port_name in json_ports:
                if port_name not in loaded:
                    return None
                merged[port_name] = loaded[port_name]

        # ── Registry-serialized ports ──────────────────────────────────────────
        if cached_ports:
            from app.core.artifacts.artifact_serializer import get_serializer_registry  # noqa: PLC0415
            _ser_registry = get_serializer_registry()
            for port_name in cached_ports:
                type_key = port_types.get(port_name)
                handler = _ser_registry.get(type_key) if type_key else None
                if handler is None:
                    return None
                try:
                    value = handler.deserialize(cache_dir / f"port_{port_name}")
                except Exception as exc:
                    logger.warning(
                        "Cache deserialize failed for port '%s' key %s: %s",
                        port_name, cache_key, exc,
                    )
                    return None
                if value is None:
                    return None
                merged[port_name] = value

        if sorted(merged.keys()) != sorted(all_ports):
            logger.warning(
                "Cache entry %s is incomplete (restored %s of %s) — will re-execute",
                cache_key, sorted(merged.keys()), sorted(all_ports),
            )
            return None
        return merged or None

    def source_of(self, cache_key: str) -> dict | None:
        """Provenance of a cache entry: ``{run_id, node_id, saved_at}`` (None if unknown)."""
        try:
            with open(self._cache_dir(cache_key) / "manifest.json", "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            return None
        src = manifest.get("source") if isinstance(manifest, dict) else None
        return dict(src) if isinstance(src, dict) else None

    def save(self, cache_key: str, outputs: Any, *, source: dict | None = None) -> None:
        """Save node outputs to cache — all ports or nothing.

        ``outputs`` may be a dict (port → value) or a list (normalised to
        ``{"output": outputs}``).

        - Ports recognised by ArtifactSerializerRegistry → ``port_<name>/``.
        - Other ports → ``outputs.json`` (JSON values or ``model_dump``).
        - If ANY port cannot be serialized, no entry is written: a partial
          entry would load without that port and skip downstream consumers.

        The entry is assembled in a unique staging directory and renamed into
        place, so readers never observe a half-written entry and concurrent
        writers of the same key cannot interleave files.
        """
        if isinstance(outputs, list):
            outputs = {"output": outputs}
        if not isinstance(outputs, dict):
            logger.debug("Cache.save: outputs is not a dict — skipping cache write")
            return
        if not outputs:
            logger.debug("Cache.save: empty outputs — skipping cache write")
            return

        from app.core.artifacts.artifact_serializer import get_serializer_registry  # noqa: PLC0415
        _ser_registry = get_serializer_registry()

        registry_ports: dict[str, tuple[str, Any]] = {}
        json_values: dict[str, Any] = {}
        skipped_ports: list[str] = []
        for port_name, value in outputs.items():
            type_key = _ser_registry.infer_type(value)
            if type_key is not None and _ser_registry.get(type_key) is not None:
                registry_ports[port_name] = (type_key, value)
            elif _is_json_serializable(value):
                json_values[port_name] = value
            elif hasattr(value, "model_dump"):
                try:
                    dumped = value.model_dump(mode="json")
                    json.dumps(dumped)
                    json_values[port_name] = dumped
                except Exception:
                    skipped_ports.append(port_name)
            else:
                skipped_ports.append(port_name)

        if skipped_ports:
            logger.warning(
                "Cache.save: non-serializable port(s) %s — NOT caching this node "
                "(it will re-execute next run). Mark the node cacheable=False to "
                "suppress this warning.",
                skipped_ports,
            )
            return

        cache_dir = self._cache_dir(cache_key)
        if (cache_dir / "manifest.json").exists():
            return  # already cached (content-keyed — identical by construction)
        self.BASE.mkdir(parents=True, exist_ok=True)
        import tempfile  # noqa: PLC0415
        staging = Path(tempfile.mkdtemp(prefix=f".{cache_key}.", suffix=".staging", dir=str(self.BASE)))
        try:
            port_manifest: dict[str, str] = {}
            for port_name, (type_key, value) in registry_ports.items():
                handler = _ser_registry.get(type_key)
                port_dir = staging / f"port_{port_name}"
                port_dir.mkdir(parents=True, exist_ok=True)
                try:
                    handler.serialize(value, port_dir)
                except Exception as exc:
                    logger.warning(
                        "Cache.save: failed to serialize port '%s' (type '%s'): %s — not caching",
                        port_name, type_key, exc,
                    )
                    return
                port_manifest[port_name] = type_key

            if json_values:
                with open(staging / "outputs.json", "w", encoding="utf-8") as f:
                    json.dump(json_values, f, indent=2, default=str)

            # manifest.json is written last — it is the commit marker.
            with open(staging / "manifest.json", "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "cached_ports": sorted(port_manifest.keys()),
                        "port_types": port_manifest,
                        "json_ports": sorted(json_values.keys()),
                        "all_ports": sorted(outputs.keys()),
                        # Audit: which run/node produced this entry (cache hits
                        # record it as cache_source_run_id).
                        "source": dict(source) if isinstance(source, dict) else None,
                    },
                    f,
                    indent=2,
                )

            if cache_dir.exists():
                # Stale/partial entry from an older format or crashed writer.
                shutil.rmtree(cache_dir, ignore_errors=True)
            try:
                os.rename(staging, cache_dir)
            except OSError:
                # Another writer committed the same key first — keep theirs.
                pass
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

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
