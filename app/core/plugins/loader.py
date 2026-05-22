# app/core/plugins/loader.py
"""PluginLoader — validates and loads manifest-based plugins into the NodeRegistry.

Responsibilities:
  1. Parse and validate the plugin manifest (``plugin.toml`` / ``plugin.json``).
  2. Check platform version compatibility.
  3. Check Python version compatibility.
  4. Verify all declared Python dependencies are satisfied.
  5. Import each entry-point file and register its Node subclasses.
  6. Return the list of newly registered node_types.

Usage::

    from pathlib import Path
    from app.core.plugins.loader import PluginLoader
    from app.core.nodes.registry import NodeRegistry

    registry = NodeRegistry()
    loader = PluginLoader(registry)
    new_types = loader.load(Path("/path/to/my-plugin"))
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from app.core.nodes.discovery import AutoDiscovery
from app.core.nodes.errors import DuplicateNodeTypeError
from app.core.plugins.dependencies import DependencyChecker
from app.core.plugins.errors import PluginCompatibilityError
from app.core.plugins.manifest import PluginManifest, load_manifest

if TYPE_CHECKING:
    from app.core.nodes.registry import NodeRegistry

log = logging.getLogger(__name__)


def _get_platform_version() -> str | None:
    """Return the current platform version string, or None if unknown.

    Tries ``app.__version__`` (plain string attribute), then
    ``app.__version__.VERSION``.

    Returns ``None`` when the version cannot be determined so that
    ``_check_platform_compat`` can skip the check with a WARNING rather than
    blocking all plugins with a ``"0.0.0"`` fallback (G4-06 fix — the previous
    ``"0.0.0"`` fallback caused every plugin with ``platform_version = ">=1.0"``
    to fail in dev/CI environments where ``app.__version__`` is not set).
    """
    try:
        import app as _app  # noqa: PLC0415

        ver = getattr(_app, "__version__", None)
        if ver is None:
            return None
        if isinstance(ver, str):
            return ver
        return getattr(ver, "VERSION", None)
    except Exception:
        return None


class PluginLoader:
    """Validates and loads a manifest-based plugin into the NodeRegistry.

    Parameters
    ----------
    registry:
        The :class:`~app.core.nodes.registry.NodeRegistry` instance that
        newly discovered node types will be registered into.
    """

    def __init__(self, registry: "NodeRegistry") -> None:
        self._registry = registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, plugin_dir: Path) -> list[str]:
        """Load a manifest-based plugin from *plugin_dir*.

        Steps:

        1. Parse and validate ``plugin.toml`` / ``plugin.json`` via
           :func:`~app.core.plugins.manifest.load_manifest`.
        2. Check platform version compatibility.
        3. Check Python version compatibility (if ``min_python`` is set).
        4. Verify all declared Python dependencies via
           :class:`~app.core.plugins.dependencies.DependencyChecker`.
        5. Import each entry-point file and register its Node subclasses.
        6. Log plugin name, version, and number of registered node types.
        7. Return the list of newly registered node_types.

        Parameters
        ----------
        plugin_dir:
            Path to the plugin package directory containing a manifest file.

        Returns
        -------
        list[str]
            The node_type strings that were newly registered by this plugin.

        Raises
        ------
        PluginManifestError
            If the manifest is missing, malformed, or fails validation.
        PluginCompatibilityError
            If the plugin requires a platform or Python version that is not
            satisfied by the current environment.
        PluginDependencyError
            If one or more declared Python dependencies are not satisfied.
        """
        # Step 1 — parse manifest (raises PluginManifestError on failure)
        manifest: PluginManifest = load_manifest(plugin_dir)

        # Step 2 — platform version compatibility
        self._check_platform_compat(manifest, plugin_dir)

        # Step 3 — Python version compatibility
        self._check_python_compat(manifest, plugin_dir)

        # Step 4 — dependency check (raises PluginDependencyError on failure)
        DependencyChecker().check(manifest.dependencies)

        # Step 5 — import entry points and register nodes
        new_node_types = self._import_entry_points(plugin_dir, manifest)

        # Step 6 — log summary
        log.info(
            "Loaded plugin '%s' v%s — registered %d node type(s): %s",
            manifest.name,
            manifest.version,
            len(new_node_types),
            new_node_types,
        )

        # Step 7 — return newly registered node_types
        return new_node_types

    # ------------------------------------------------------------------
    # Compatibility checks
    # ------------------------------------------------------------------

    def _check_platform_compat(
        self,
        manifest: PluginManifest,
        plugin_dir: Path,  # noqa: ARG002
    ) -> None:
        """Raise PluginCompatibilityError if the platform version does not satisfy
        the plugin's ``platform_version`` specifier.

        G4-06 fix: when the platform version cannot be determined (dev/CI
        environments without ``app.__version__`` set), log a WARNING and skip
        the check rather than blocking with a ``"0.0.0"`` fallback.
        """
        platform_ver = _get_platform_version()
        if platform_ver is None:
            log.warning(
                "PluginLoader: platform version unknown (app.__version__ not set) — "
                "skipping platform_version check for plugin '%s'. "
                "Set app.__version__ to enforce compatibility checks.",
                manifest.name,
            )
            return
        specifier = SpecifierSet(manifest.platform_version)
        if Version(platform_ver) not in specifier:
            raise PluginCompatibilityError(
                f"Plugin '{manifest.name}' requires platform "
                f"{manifest.platform_version} but current platform is "
                f"{platform_ver}. Upgrade the platform or use an older "
                f"version of the plugin."
            )

    def _check_python_compat(
        self,
        manifest: PluginManifest,
        plugin_dir: Path,  # noqa: ARG002  (kept for future use / logging)
    ) -> None:
        """Raise :class:`~app.core.plugins.errors.PluginCompatibilityError` if
        the running Python interpreter does not satisfy the plugin's
        ``min_python`` requirement.

        If ``manifest.min_python`` is ``None`` this method returns immediately.

        Parameters
        ----------
        manifest:
            The validated plugin manifest.
        plugin_dir:
            Plugin directory (reserved for future diagnostic use).

        Raises
        ------
        PluginCompatibilityError
            When the running Python version is older than ``manifest.min_python``.
        """
        if manifest.min_python is None:
            return

        required = Version(manifest.min_python)
        # Build a comparable version string from sys.version_info
        actual_str = (
            f"{sys.version_info.major}."
            f"{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        )
        actual = Version(actual_str)

        if actual < required:
            raise PluginCompatibilityError(
                f"Plugin '{manifest.name}' requires Python >={manifest.min_python} "
                f"but the current Python is {actual_str}."
            )

    # ------------------------------------------------------------------
    # Entry-point import
    # ------------------------------------------------------------------

    def _import_entry_points(
        self,
        plugin_dir: Path,
        manifest: PluginManifest,
    ) -> list[str]:
        """Import each entry-point file and register its Node subclasses.

        Records the set of node_types already in the registry before
        importing, then returns the set difference (newly added types).

        Individual entry-point failures are logged as WARNING and skipped;
        they do not abort loading of the remaining entry points.

        Parameters
        ----------
        plugin_dir:
            Root directory of the plugin package.
        manifest:
            The validated plugin manifest.

        Returns
        -------
        list[str]
            Sorted list of node_type strings that were newly registered.
        """
        discovery = AutoDiscovery(self._registry)

        # Snapshot of node_types already registered before this plugin loads
        before: set[str] = set(self._registry._classes.keys())

        for entry_point in manifest.entry_points:
            path = plugin_dir / entry_point
            try:
                module = discovery._import_file(path, package_prefix=None)
                discovery._process_module(module)
            except DuplicateNodeTypeError as exc:
                # PL-06 fix: surface the duplicate node type name explicitly
                log.warning(
                    "PluginLoader: duplicate node type detected while loading "
                    "entry point '%s' from plugin '%s': %s — "
                    "the first registration is kept.",
                    entry_point,
                    manifest.name,
                    exc,
                )
                continue
            except Exception as exc:
                log.warning(
                    "PluginLoader: failed to load entry point '%s' from plugin '%s': %s",
                    entry_point,
                    manifest.name,
                    exc,
                    exc_info=True,
                )
                continue

        # Compute newly registered node_types
        after: set[str] = set(self._registry._classes.keys())
        new_types = sorted(after - before)
        return new_types
