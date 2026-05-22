"""
PluginStore — persistence layer for installed plugin records.

Stores plugin state in ``{base_dir}/plugins/registry.json`` as a JSON object
mapping plugin name → PluginRecord dict.  All read-modify-write operations
acquire a threading lock and writes are atomic (write-to-temp + os.replace).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path

from pydantic import BaseModel

from app.core.plugins.errors import PluginNotFoundError

logger = logging.getLogger(__name__)


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
        from app.core.plugins.manifest import PluginManifest  # noqa: PLC0415
        return PluginManifest.model_validate(self.manifest)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class PluginStore:
    """Persist and retrieve :class:`PluginRecord` objects from disk.

    The registry file lives at ``{GRAPHYN_HOME}/plugins/registry.json``.
    ``base_dir`` defaults to ``GRAPHYN_HOME`` (falling back to ``~/.graphyn``
    if unset). Pass ``base_dir`` explicitly in tests to use a temp directory.
    """

    def __init__(self, base_dir: str | None = None) -> None:
        from app.core.config import plugin_registry_path as _plugin_registry_path
        if base_dir is not None:
            # explicit override (tests) — keep legacy behaviour
            self._registry_path = Path(base_dir) / "plugins" / "registry.json"
        else:
            self._registry_path = _plugin_registry_path()
        self._lock = threading.Lock()
        # Ensure the directory exists so _save() never has to create it.
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, dict]:
        """Read registry.json and return its contents as a plain dict.

        Returns an empty dict when the file does not exist yet.
        When the file contains invalid JSON (e.g. truncated write), backs it
        up to ``registry.json.corrupt`` before returning an empty dict so the
        data is not silently lost (PL-13 fix).
        """
        if not self._registry_path.exists():
            return {}
        try:
            text = self._registry_path.read_text(encoding="utf-8")
            return json.loads(text)
        except json.JSONDecodeError as exc:
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

    def _save(self, data: dict[str, dict]) -> None:
        """Atomically write *data* to registry.json.

        Writes to a temporary file in the same directory, then calls
        ``os.replace()`` so the update is atomic on POSIX systems.

        The caller is responsible for holding ``self._lock`` before
        invoking this method.
        """
        directory = self._registry_path.parent
        # Write to a temp file in the same directory so os.replace() is
        # guaranteed to be on the same filesystem (required for atomicity).
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
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

    def get(self, name: str) -> PluginRecord:
        """Return the :class:`PluginRecord` for *name*.

        Raises :class:`~app.core.plugins.errors.PluginNotFoundError` when
        no plugin with that name is installed.
        """
        with self._lock:
            data = self._load()
        if name not in data:
            raise PluginNotFoundError(name)
        return PluginRecord(**data[name])

    def list(self) -> list[PluginRecord]:
        """Return all installed plugins as a list of :class:`PluginRecord`."""
        with self._lock:
            data = self._load()
        return [PluginRecord(**v) for v in data.values()]

    def save(self, record: PluginRecord) -> None:
        """Persist *record*, overwriting any existing entry with the same name."""
        with self._lock:
            data = self._load()
            data[record.name] = record.model_dump()
            self._save(data)

    def delete(self, name: str) -> None:
        """Remove the record for *name*.

        Raises :class:`~app.core.plugins.errors.PluginNotFoundError` when
        no plugin with that name is installed.
        """
        with self._lock:
            data = self._load()
            if name not in data:
                raise PluginNotFoundError(name)
            del data[name]
            self._save(data)

    def update_enabled(self, name: str, enabled: bool) -> PluginRecord:
        """Toggle the ``enabled`` flag for *name* and return the updated record.

        Raises :class:`~app.core.plugins.errors.PluginNotFoundError` when
        no plugin with that name is installed.
        """
        with self._lock:
            data = self._load()
            if name not in data:
                raise PluginNotFoundError(name)
            data[name] = {**data[name], "enabled": enabled}
            self._save(data)
            return PluginRecord(**data[name])
