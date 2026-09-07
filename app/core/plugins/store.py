# app/core/plugins/store.py
"""
Bounded Context:  BC3 — Node Catalog (Plugin Ecosystem)
Responsibility:   Persist and retrieve PluginRecord objects from disk.
                  Single source of truth for installed plugin state.
Owns:             PluginRecord model, PluginStore class, registry.json I/O,
                  process-wide + cross-process locking, atomic write via
                  os.replace().
Public Surface:   PluginRecord, PluginStore.get(), .list(), .save(),
                  .delete(), .update_enabled(), .mutate()
Must NOT:         Import from app.domain, app.api, or app.models.
                  Must not load or execute plugin code.
Dependencies:     pydantic, stdlib (json, logging, os, tempfile, threading,
                  pathlib, fcntl), app.core.plugins.errors, app.core.config.
Reason To Change: PluginRecord schema changes, or storage backend changes
                  (e.g. SQLite migration).

Stores plugin state in ``{GRAPHYN_HOME}/plugins/registry.json`` as a JSON
object mapping plugin name → PluginRecord dict. All read-modify-write
operations acquire a process-wide lock (shared across PluginStore instances)
and an exclusive flock on ``registry.lock`` for the full RMW, then write
atomically (write-to-temp + os.replace). This closes lost-update races
across API-created store instances and multi-process writers (PLUGIN-002).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from app.core.plugins.errors import PluginManifestError, PluginNotFoundError

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Process-wide locks keyed by resolved registry path so separate PluginStore
# instances in the same process serialize on the same file (PLUGIN-002).
_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


def _process_lock_for(registry_path: Path) -> threading.RLock:
    key = str(registry_path.resolve())
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_LOCKS[key] = lock
        return lock


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class PluginRecord(BaseModel, frozen=True):
    """Immutable record representing an installed plugin's persisted state.

    The ``manifest`` field stores the full parsed manifest as a plain dict for
    JSON round-trip compatibility. When the manifest dict is needed as a typed
    ``PluginManifest`` object, call ``PluginRecord.load_manifest()`` which
    validates the dict and raises ``PluginManifestError`` on corrupt entries.
    """

    name: str
    version: str
    source: str          # install source URL or path
    install_path: str    # absolute path to installed plugin directory
    enabled: bool
    installed_at: str    # ISO 8601 timestamp
    manifest: dict       # full parsed manifest as a dict

    def load_manifest(self):
        """Return the manifest dict validated as a ``PluginManifest`` instance.

        Raises:
            PluginManifestError: if the stored manifest dict is invalid.
        """
        from app.core.plugins.manifest import (  # noqa: PLC0415
            PluginManifest,
            _rewrap_validation_error,
        )
        try:
            return PluginManifest.model_validate(self.manifest)
        except Exception as exc:
            _rewrap_validation_error(exc, source=f"<stored record for {self.name!r}>")
            raise  # unreachable; satisfies type checkers


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class PluginStore:
    """Persist and retrieve :class:`PluginRecord` objects from disk.

    The registry file lives at ``{GRAPHYN_HOME}/plugins/registry.json``.
    ``base_dir`` defaults to ``GRAPHYN_HOME`` (falling back to ``~/.graphyn``
    if unset). Pass ``base_dir`` explicitly in tests to use a temp directory.

    Concurrency (PLUGIN-002): a process-wide ``threading.RLock`` (keyed by
    registry path) plus an exclusive ``fcntl.flock`` on ``registry.lock``
    wrap every read-modify-write so separate instances and processes cannot
    lose updates.
    """

    def __init__(self, base_dir: str | None = None) -> None:
        from app.core.config import plugin_registry_path as _plugin_registry_path
        if base_dir is not None:
            # explicit override (tests) — keep legacy behaviour
            self._registry_path = Path(base_dir) / "plugins" / "registry.json"
        else:
            self._registry_path = _plugin_registry_path()
        self._lock = _process_lock_for(self._registry_path)
        self._lock_path = self._registry_path.parent / "registry.lock"
        # Ensure the directory exists so _save() never has to create it.
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _with_registry_lock(self, exclusive: bool, fn: Callable[[], T]) -> T:
        """Run *fn* under process-wide + advisory file lock (cross-process)."""
        try:
            import fcntl
        except ImportError:  # pragma: no cover — non-POSIX
            fcntl = None  # type: ignore[assignment]

        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with open(self._lock_path, "a+", encoding="utf-8") as lf:
                if fcntl is not None:
                    fcntl.flock(
                        lf.fileno(),
                        fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH,
                    )
                try:
                    return fn()
                finally:
                    if fcntl is not None:
                        fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    def _load_unlocked(self) -> dict[str, dict]:
        """Read registry.json; caller must hold the registry lock."""
        if not self._registry_path.exists():
            return {}
        try:
            text = self._registry_path.read_text(encoding="utf-8")
            return json.loads(text)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            # Back up the corrupt file before treating as empty
            backup_path = self._registry_path.with_suffix(".json.corrupt")
            try:
                import shutil as _shutil  # noqa: PLC0415
                _shutil.copy2(str(self._registry_path), str(backup_path))
                logger.warning(
                    "PluginStore: registry.json is corrupt — backed up to '%s'. "
                    "Treating registry as empty. Error: %s",
                    backup_path,
                    exc,
                )
            except Exception as backup_exc:
                logger.warning(
                    "PluginStore: registry.json is corrupt and backup failed (%s). "
                    "Treating registry as empty. Original error: %s",
                    backup_exc,
                    exc,
                )
            return {}

    def _save_unlocked(self, data: dict[str, dict]) -> None:
        """Atomically write *data* to registry.json. Caller holds registry lock."""
        directory = self._registry_path.parent
        # Write to a temp file in the same directory so os.replace() is
        # guaranteed to be on the same filesystem (required for atomicity).
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        # Close the raw fd immediately so os.fdopen() failure cannot leak it.
        os.close(fd)
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self._registry_path)
        except Exception:
            # Clean up the temp file if anything goes wrong.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def mutate(
        self, mutator: Callable[[dict[str, dict]], tuple[dict[str, dict], T]]
    ) -> T:
        """Atomically load → mutate → save the registry (exclusive flock).

        ``mutator(data)`` returns ``(new_data, result)``. Same spirit as
        ``DiskStateStore.mutate_queue``.
        """

        def _mutate() -> T:
            data = self._load_unlocked()
            new_data, result = mutator(data)
            self._save_unlocked(new_data)
            return result

        return self._with_registry_lock(True, _mutate)

    def get(self, name: str) -> PluginRecord:
        """Return the :class:`PluginRecord` for *name*.

        Raises :class:`~app.core.plugins.errors.PluginNotFoundError` when
        no plugin with that name is installed.
        """

        def _get() -> dict[str, dict]:
            return self._load_unlocked()

        data = self._with_registry_lock(False, _get)
        if name not in data:
            raise PluginNotFoundError(name)
        try:
            return PluginRecord(**data[name])
        except Exception as exc:
            raise PluginManifestError(
                f"Corrupt record for plugin '{name}' in registry: {exc}"
            ) from exc

    def list(self) -> list[PluginRecord]:
        """Return all installed plugins as a list of :class:`PluginRecord`."""

        def _list() -> dict[str, dict]:
            return self._load_unlocked()

        data = self._with_registry_lock(False, _list)
        records = []
        for name, v in data.items():
            try:
                records.append(PluginRecord(**v))
            except Exception as exc:
                logger.warning(
                    "PluginStore: skipping corrupt plugin record '%s': %s", name, exc
                )
        return records

    def save(self, record: PluginRecord) -> None:
        """Persist *record*, overwriting any existing entry with the same name."""

        def _save(data: dict[str, dict]) -> tuple[dict[str, dict], None]:
            data[record.name] = record.model_dump()
            return data, None

        self.mutate(_save)

    def delete(self, name: str) -> None:
        """Remove the record for *name*.

        Raises :class:`~app.core.plugins.errors.PluginNotFoundError` when
        no plugin with that name is installed.
        """

        def _delete(data: dict[str, dict]) -> tuple[dict[str, dict], None]:
            if name not in data:
                raise PluginNotFoundError(name)
            del data[name]
            return data, None

        self.mutate(_delete)

    def update_enabled(self, name: str, enabled: bool) -> PluginRecord:
        """Toggle the ``enabled`` flag for *name* and return the updated record.

        Raises :class:`~app.core.plugins.errors.PluginNotFoundError` when
        no plugin with that name is installed.
        """

        def _update(
            data: dict[str, dict],
        ) -> tuple[dict[str, dict], PluginRecord]:
            if name not in data:
                raise PluginNotFoundError(name)
            data[name] = {**data[name], "enabled": enabled}
            try:
                updated = PluginRecord(**data[name])
            except Exception as exc:
                raise PluginManifestError(
                    f"Corrupt record for plugin '{name}' in registry: {exc}"
                ) from exc
            return data, updated

        return self.mutate(_update)
