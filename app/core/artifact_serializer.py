# app/core/artifact_serializer.py
"""
Bounded Context:  BC6 — Observability & Storage
Responsibility:   Pluggable serializer registry for artifact types.
                  Defines the interface that domain handlers must implement
                  and the singleton registry that platform code calls.
Owns:             ArtifactTypeHandler (ABC), ArtifactSerializerRegistry
                  (singleton), get_serializer_registry().
Public Surface:   ArtifactTypeHandler, ArtifactSerializerRegistry,
                  get_serializer_registry().
Must NOT:         Import from app.domain, app.models, app.api, or any
                  audio/ML library. This module is pure platform infrastructure.
                  Must not contain any domain-specific serialization logic.
Dependencies:     stdlib only (abc, pathlib, threading, typing, Any).
Reason To Change: New serialization interface methods are needed, or the
                  registry lifecycle (singleton vs. per-request) changes.

## Design

Platform code (artifact_store, pipeline_cache, checkpoint) calls:

    registry = get_serializer_registry()
    handler  = registry.get("audio_samples")   # returns None if not registered
    if handler:
        handler.serialize(data, dest_dir)
        data = handler.deserialize(src_dir)
        artifact_type = handler.infer_type(value)

Domain code (app/models/audio_artifact_serializer.py) calls:

    get_serializer_registry().register("audio_samples", AudioSampleHandler())

This is called once at application startup from each entry point
(app/api/main.py, app/cli/main.py, app/mcp/server.py) via:

    from app.models.audio_artifact_serializer import register_audio_serializer
    register_audio_serializer()

The registry is intentionally fail-open: if no handler is registered for a
type, platform code falls back to JSON serialization (or returns None on
deserialize). This means the platform works without any domain handlers
installed — it just cannot serialize audio-specific types.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Abstract handler interface
# ---------------------------------------------------------------------------


class ArtifactTypeHandler(ABC):
    """Interface that domain code must implement to plug into the platform.

    Each handler is responsible for exactly one artifact_type string
    (e.g. ``"audio_samples"``).

    All methods receive/return plain Python objects — no platform types.
    """

    @abstractmethod
    def serialize(self, data: Any, dest_dir: Path) -> None:
        """Write ``data`` to ``dest_dir``.

        ``dest_dir`` is guaranteed to exist when this method is called.
        Raise any exception on failure — the platform will wrap it in
        ``ArtifactSerializationError``.
        """

    @abstractmethod
    def deserialize(self, src_dir: Path) -> Any | None:
        """Read and reconstruct data from ``src_dir``.

        Return ``None`` if the directory does not contain a recognisable
        artifact (e.g. missing manifest). The platform treats ``None`` as a
        cache/checkpoint miss and will re-execute the node.

        Raise any exception on unrecoverable errors.
        """

    @abstractmethod
    def compute_content_hash_input(self, data: Any) -> str:
        """Return a stable string representation of ``data`` for SHA-256 hashing.

        The string must be deterministic across process restarts for the same
        logical data. The platform will SHA-256 this string to produce the
        content hash used for deduplication.
        """

    def infer_type(self, value: Any) -> str | None:
        """Return the artifact_type string if ``value`` belongs to this handler.

        Return ``None`` if this handler does not recognise ``value``.
        The platform calls each registered handler in registration order and
        uses the first non-None result.

        The default implementation always returns ``None`` — override to
        enable automatic type inference.
        """
        return None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ArtifactSerializerRegistry:
    """Thread-safe registry mapping artifact_type strings to handlers.

    Handlers are tried in registration order for ``infer_type``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handlers: dict[str, ArtifactTypeHandler] = {}
        self._ordered: list[ArtifactTypeHandler] = []  # for infer_type iteration

    def register(self, artifact_type: str, handler: ArtifactTypeHandler) -> None:
        """Register a handler for ``artifact_type``.

        Replaces any existing handler for the same type.
        Thread-safe.
        """
        with self._lock:
            if artifact_type not in self._handlers:
                # Only append if this handler object is not already in _ordered.
                # The same handler instance may be registered for multiple types;
                # appending it again would cause infer_type() to call it twice.
                if handler not in self._ordered:
                    self._ordered.append(handler)
            else:
                # Replace in-place in the ordered list
                old = self._handlers[artifact_type]
                idx = self._ordered.index(old)
                self._ordered[idx] = handler
            self._handlers[artifact_type] = handler

    def get(self, artifact_type: str) -> ArtifactTypeHandler | None:
        """Return the handler for ``artifact_type``, or ``None`` if not registered."""
        return self._handlers.get(artifact_type)

    def infer_type(self, value: Any) -> str | None:
        """Ask each registered handler (in order) to identify ``value``.

        Returns the first non-None result, or ``None`` if no handler
        recognises the value.
        """
        # Fast-path: primitives are never artifacts — skip all handlers.
        if isinstance(value, (int, float, str, bool, type(None))):
            return None
        with self._lock:
            handlers = list(self._ordered)
        for handler in handlers:
            result = handler.infer_type(value)
            if result is not None:
                return result
        return None

    def registered_types(self) -> list[str]:
        """Return a sorted list of all registered artifact_type strings."""
        with self._lock:
            return sorted(self._handlers.keys())


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: ArtifactSerializerRegistry | None = None
_registry_lock = threading.Lock()


def get_serializer_registry() -> ArtifactSerializerRegistry:
    """Return the process-wide ArtifactSerializerRegistry singleton.

    Thread-safe. Creates the registry on first call.
    """
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ArtifactSerializerRegistry()
    return _registry
