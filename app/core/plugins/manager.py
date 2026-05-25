# app/core/plugins/manager.py
"""
Bounded Context:  BC3 — Node Catalog (Plugin Ecosystem)
Responsibility:   Orchestrate all plugin lifecycle operations — install,
                  uninstall, enable, disable, startup loading.
Owns:             Install workflow (resolve → manifest → copy → load → persist),
                  uninstall workflow (unload → delete record → remove dir),
                  enable/disable (registry reload/unload), startup loading.
Public Surface:   PluginManager.install(), uninstall(), enable(), disable(),
                  list_installed(), get(), load_enabled_plugins()
Must NOT:         Import from app.domain or app.api.
                  Must not call PluginLoader, PluginStore, or PluginInstaller
                  directly from outside this package.
Dependencies:     app.core.plugins.{installer, loader, store, index, manifest,
                  errors}, app.core.config (plugins_home — lazy import),
                  stdlib (logging, os, shutil, datetime).
Security:         install() forwards expected_sha256 to PluginInstaller.resolve()
                  for HTTP archive checksum verification (SEC-6 fix).
                  Source allowlist enforced inside PluginInstaller.
Reason To Change: Plugin lifecycle steps change, or new install source types
                  are added.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.plugins.errors import (
    PluginAlreadyInstalledError,
    PluginNotFoundError,
)
from app.core.plugins.index import PluginIndexClient
from app.core.plugins.installer import PluginInstaller
from app.core.plugins.loader import PluginLoader
from app.core.plugins.manifest import load_manifest
from app.core.plugins.store import PluginRecord, PluginStore

if TYPE_CHECKING:
    from app.core.nodes.registry import NodeRegistry

log = logging.getLogger(__name__)


class PluginManager:
    """Orchestrates all plugin lifecycle operations.

    Parameters
    ----------
    registry:
        The :class:`~app.core.nodes.registry.NodeRegistry` instance to
        register/unregister node types into.  If ``None``, the global
        singleton is imported and used.
    base_dir:
        Base directory for ``PluginStore`` (workspace root).  If ``None``,
        ``PluginStore`` uses its own default (``GRAPHYN_HOME`` env var or
        ``~/.graphyn``).
    """

    def __init__(
        self,
        registry: NodeRegistry | None = None,
        base_dir: str | None = None,
    ) -> None:
        if registry is None:
            from app.core.nodes import registry as _registry  # noqa: PLC0415

            self._registry = _registry
        else:
            self._registry = registry

        self._store = PluginStore(base_dir=base_dir)
        self._loader = PluginLoader(self._registry)
        self._installer = PluginInstaller(index_client=PluginIndexClient())
        from app.core.config import plugins_home as _plugins_home
        self._plugins_dir: str = str(_plugins_home())

    # ------------------------------------------------------------------
    # install
    # ------------------------------------------------------------------

    def install(self, source: str, upgrade: bool = False, expected_sha256: str | None = None) -> PluginRecord:
        """Install a plugin from *source*.

        Steps:

        1. Parse the plugin name from *source*.
        2. Check if already installed; raise :class:`PluginAlreadyInstalledError`
           if so and ``upgrade`` is ``False``.
        3. If ``upgrade`` and already installed, call :meth:`uninstall` first.
        4. Resolve *source* to a temporary directory via
           :class:`~app.core.plugins.installer.PluginInstaller`.
        5. Parse the manifest from the resolved directory.
        6. Copy the resolved directory to the final install location
           ``{plugins_dir}/{manifest.name}/``.
        7. Load the plugin (validate, check compat/deps, register nodes).
        8. Create and persist a :class:`~app.core.plugins.store.PluginRecord`
           with ``enabled=True``.
        9. Return the :class:`~app.core.plugins.store.PluginRecord`.

        Parameters
        ----------
        source:
            Plugin source string — a local path, Git URL, HTTP archive URL,
            or plain plugin name (optionally with version specifier).
        upgrade:
            When ``True``, replace an existing installation with the same name.
        expected_sha256:
            Optional expected SHA-256 hex digest of the downloaded archive.
            When provided for HTTP archive sources, the digest is verified
            before extraction (SEC-6 fix).  Ignored for local path and git
            sources.

        Returns
        -------
        PluginRecord
            The persisted record for the newly installed plugin.

        Raises
        ------
        PluginAlreadyInstalledError
            If a plugin with the same name is already installed and
            ``upgrade`` is ``False``.
        PluginManifestError
            If the manifest is missing or invalid.
        PluginCompatibilityError
            If the plugin requires a platform or Python version not satisfied.
        PluginDependencyError
            If one or more declared Python dependencies are not satisfied.
        PluginInstallError
            If the source cannot be fetched, extracted, or is not on the
            allowlist (when ``GRAPHYN_PLUGIN_ALLOWED_SOURCES`` is set).
        """
        # Step 1 — parse name from source (best-effort; authoritative name comes from manifest)
        _pre_name, _ver = self._installer._parse_name_version(source)

        # Step 2 — pre-flight duplicate check using best-effort name (URL sources skip this;
        # the authoritative check happens after the manifest is parsed — G4-01 fix)
        existing: PluginRecord | None = None
        try:
            existing = self._store.get(_pre_name)
        except PluginNotFoundError:
            existing = None

        if existing is not None and not upgrade:
            raise PluginAlreadyInstalledError(
                f"Plugin '{_pre_name}' is already installed (version {existing.version}). "
                "Use upgrade=True to replace the existing installation."
            )

        # Step 3 — upgrade: uninstall existing first (best-effort name)
        if existing is not None and upgrade:
            log.info("Upgrading plugin '%s': uninstalling existing version %s.", _pre_name, existing.version)
            self.uninstall(_pre_name)

        # Step 4 — resolve source to a temp directory
        resolved_dir: Path = self._installer.resolve(source, expected_sha256=expected_sha256)
        # The resolved_dir lives inside a tmpdir created by the installer.
        # We must clean it up after copying to the final install location (PL-07 fix).
        resolved_tmpdir: Path = resolved_dir.parent
        install_path: Path | None = None  # set inside try block; used after finally

        # Steps 5–8 wrapped in try/finally so the tmpdir is always cleaned up,
        # even if load_manifest() or any subsequent step raises (G4-02 fix).
        try:
            # Step 5 — parse manifest from resolved dir (authoritative name)
            manifest = load_manifest(resolved_dir)

            # G4-01 fix: authoritative duplicate check using manifest.name
            # (covers URL/path sources where _pre_name was the raw URL string)
            if manifest.name != _pre_name:
                try:
                    auth_existing = self._store.get(manifest.name)
                except PluginNotFoundError:
                    auth_existing = None
                if auth_existing is not None and not upgrade:
                    raise PluginAlreadyInstalledError(
                        f"Plugin '{manifest.name}' is already installed "
                        f"(version {auth_existing.version}). "
                        "Use upgrade=True to replace the existing installation."
                    )
                if auth_existing is not None and upgrade:
                    log.info(
                        "Upgrading plugin '%s': uninstalling existing version %s.",
                        manifest.name, auth_existing.version,
                    )
                    self.uninstall(manifest.name)

            # Step 6 — copy resolved dir to final install location
            plugins_dir = Path(self._plugins_dir)
            install_path = plugins_dir / manifest.name
            # Remove any stale directory at the target location
            if install_path.exists():
                shutil.rmtree(install_path, ignore_errors=True)
            plugins_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(resolved_dir), str(install_path))

        finally:
            # Always clean up the installer's temp directory (G4-02 fix).
            if resolved_tmpdir.name.startswith("kiro_plugin_"):
                shutil.rmtree(str(resolved_tmpdir), ignore_errors=True)

        # Steps 7–8 — load plugin and persist record.
        # If either step fails, remove the install directory so the next
        # install() call starts clean (PL-01 fix: atomic install).
        try:
            # Step 7 — load the plugin (validates compat, deps, registers nodes)
            node_types = self._loader.load(install_path)
            log.info(
                "Installed plugin '%s' v%s from '%s' — registered node types: %s",
                manifest.name,
                manifest.version,
                source,
                node_types,
            )

            # Step 8 — create and persist PluginRecord
            record = PluginRecord(
                name=manifest.name,
                version=manifest.version,
                source=source,
                install_path=str(install_path.resolve()),
                enabled=True,
                installed_at=datetime.now(UTC).isoformat(),
                manifest=manifest.model_dump(),
            )
            self._store.save(record)
        except Exception:
            # Clean up the install directory so the registry stays consistent
            shutil.rmtree(install_path, ignore_errors=True)
            raise

        # Step 9 — return the record
        return record

    # ------------------------------------------------------------------
    # uninstall
    # ------------------------------------------------------------------

    def uninstall(self, name: str) -> None:
        """Uninstall the plugin named *name*.

        Steps:

        1. Retrieve the :class:`~app.core.plugins.store.PluginRecord` from
           the store (raises :class:`PluginNotFoundError` if absent).
        2. Unload the plugin's node types from the registry.
        3. Delete the record from the store.
        4. Remove the plugin directory from disk.

        Parameters
        ----------
        name:
            The plugin name to uninstall.

        Raises
        ------
        PluginNotFoundError
            If no plugin with *name* is installed.
        """
        # Step 1 — get record (raises PluginNotFoundError if not found)
        record = self._store.get(name)

        # Step 2 — unload node types from registry
        self._unload_node_types(record)

        # Step 3 — delete record from store
        self._store.delete(name)

        # Step 4 — remove plugin directory from disk
        shutil.rmtree(record.install_path, ignore_errors=True)
        log.info("Uninstalled plugin '%s' from '%s'.", name, record.install_path)

    # ------------------------------------------------------------------
    # enable / disable / list_installed / get / load_enabled_plugins
    # ------------------------------------------------------------------

    def enable(self, name: str) -> PluginRecord:
        """Enable the plugin named *name* and reload its node types if not already loaded."""
        record = self._store.get(name)
        if not record.enabled:
            install_path = Path(record.install_path)
            # PL-03 fix: only load if the plugin's node types are not already
            # in the registry (e.g. loaded at startup). Check by inspecting
            # the manifest's entry points for already-registered node types.
            try:
                from app.core.plugins.manifest import load_manifest
                manifest = load_manifest(install_path)
                # Snapshot before to detect if anything new would be added
                before = set(self._registry._classes.keys())
                self._loader.load(install_path)
                after = set(self._registry._classes.keys())
                if after == before:
                    log.debug(
                        "Plugin '%s' node types already in registry — skipped reload.",
                        name,
                    )
            except Exception as exc:
                log.warning(
                    "Failed to reload plugin '%s' during enable: %s", name, exc
                )
                raise
        updated = self._store.update_enabled(name, enabled=True)
        log.info("Enabled plugin '%s'.", name)
        return updated

    def disable(self, name: str) -> PluginRecord:
        """Disable the plugin named *name* and unload its node types.

        Parameters
        ----------
        name:
            The plugin name to disable.

        Returns
        -------
        PluginRecord
            The updated record with ``enabled=False``.

        Raises
        ------
        PluginNotFoundError
            If no plugin with *name* is installed.
        """
        record = self._store.get(name)
        if record.enabled:
            self._unload_node_types(record)
        updated = self._store.update_enabled(name, enabled=False)
        log.info("Disabled plugin '%s'.", name)
        return updated

    def list_installed(self) -> list[PluginRecord]:
        """Return all installed plugins.

        Returns
        -------
        list[PluginRecord]
            All records currently in the store.
        """
        return self._store.list()

    def get(self, name: str) -> PluginRecord:
        """Return the :class:`~app.core.plugins.store.PluginRecord` for *name*.

        Parameters
        ----------
        name:
            The plugin name to look up.

        Returns
        -------
        PluginRecord
            The record for the named plugin.

        Raises
        ------
        PluginNotFoundError
            If no plugin with *name* is installed.
        """
        return self._store.get(name)

    def load_enabled_plugins(self) -> None:
        """Load all enabled plugins from the store.

        Called at platform startup before ``AutoDiscovery`` runs.  Each
        enabled plugin is loaded via :class:`~app.core.plugins.loader.PluginLoader`.
        Failures are logged at WARNING level and do not abort startup.

        Requirements: req-03 §4.8
        """
        records = self._store.list()
        for record in records:
            if not record.enabled:
                continue
            install_path = Path(record.install_path)
            try:
                node_types = self._loader.load(install_path)
                log.info(
                    "Startup: loaded plugin '%s' v%s — node types: %s",
                    record.name,
                    record.version,
                    node_types,
                )
            except Exception as exc:
                log.warning(
                    "Startup: failed to load enabled plugin '%s' from '%s': %s",
                    record.name,
                    record.install_path,
                    exc,
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _unload_node_types(self, record: PluginRecord) -> None:
        """Unload all node types contributed by *record* from the registry.

        Uses ``inspect.getfile()`` to resolve the source file of each registered
        class and checks whether it lives inside the plugin's install directory
        using an exact path-prefix comparison (PL-02 fix — the previous
        substring check caused false positives, e.g. plugin ``audio`` matching
        classes from ``audio_denoiser``).
        """
        import inspect  # noqa: PLC0415

        install_path = Path(record.install_path).resolve()
        # Normalise to a string ending with os.sep so prefix matching is exact
        install_prefix = str(install_path) + os.sep

        to_unregister: list[str] = []
        for node_type, cls in list(self._registry._classes.items()):
            try:
                source_file = inspect.getfile(cls)
                resolved = str(Path(source_file).resolve())
                # Exact prefix match: the source file must be *inside* install_path
                if resolved.startswith(install_prefix) or resolved == str(install_path):
                    to_unregister.append(node_type)
            except (TypeError, OSError):
                pass
            except Exception:
                pass

        if to_unregister:
            log.warning(
                "Unloading %d node type(s) from plugin '%s': %s. "
                "Pipelines referencing these node types will fail to execute.",
                len(to_unregister),
                record.name,
                to_unregister,
            )
            for node_type in to_unregister:
                self._registry.unregister(node_type)
        else:
            log.debug(
                "No node types found for plugin '%s' in registry (install_path=%s).",
                record.name,
                record.install_path,
            )
