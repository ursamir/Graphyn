# app/core/plugins/loader.py
"""
Bounded Context:  BC3 — Node Catalog (Plugin Ecosystem)
Responsibility:   Validate and load a manifest-based plugin into the
                  NodeRegistry. Runs all compatibility and dependency checks
                  before importing any plugin code.
Owns:             PluginLoader.load() — manifest parse, platform compat check,
                  Python compat check, dependency check, entry-point import,
                  node type registration.
Public Surface:   PluginLoader.load(plugin_dir) → list[str]
Must NOT:         Import from app.domain, app.api, or app.models.
                  Must not bypass AutoDiscovery for node registration.
Dependencies:     app.core.plugins.{manifest, dependencies, errors},
                  app.core.nodes.{discovery, errors, registry},
                  packaging, stdlib (logging, sys, pathlib).
Reason To Change: New compatibility check added, or entry-point import
                  strategy changes.

Responsibilities:
  1. Parse and validate the plugin manifest (``plugin.toml`` / ``plugin.json``).
  2. Check platform version compatibility.
  3. Check Python version compatibility.
  4. Verify all declared Python dependencies are satisfied.
  5. Import each entry-point file and register its Node subclasses.
  6. Return the list of newly registered node_types.
"""
from __future__ import annotations

import ast
import logging
import os
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from app.core.nodes.discovery import AutoDiscovery
from app.core.nodes.errors import DuplicateNodeTypeError, DuplicatePortTypeError
from app.core.plugins.dependencies import DependencyChecker
from app.core.plugins.errors import PluginCompatibilityError, PluginInstallError
from app.core.plugins.manifest import PluginManifest, load_manifest

if TYPE_CHECKING:
    from app.core.nodes.registry import NodeRegistry

log = logging.getLogger(__name__)


def isolated_venv_requirements(manifest: PluginManifest) -> list[str]:
    """Requirements to pip-install into an isolated plugin venv.

    Isolated workers execute plugin ``process()`` without host site-packages,
    so they need the plugin's ML stack. Those packages stay in
    ``optional_dependencies`` so they are **not** installed into the host
    API image.

    TensorFlow + Keras are always included. ``torch`` is skipped unless
    ``GRAPHYN_ISOLATED_INSTALL_TORCH=1`` (keeps the default venv smaller).
    """
    from packaging.requirements import Requirement

    reqs = list(manifest.dependencies) + list(manifest.optional_dependencies)
    install_torch = os.environ.get("GRAPHYN_ISOLATED_INSTALL_TORCH", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if install_torch:
        return reqs

    filtered: list[str] = []
    for item in reqs:
        try:
            name = Requirement(item).name.lower().replace("_", "-")
        except Exception:
            name = item.split()[0].lower()
        if name in {"torch", "pytorch"}:
            log.info(
                "Skipping torch extra for isolated plugin '%s' "
                "(set GRAPHYN_ISOLATED_INSTALL_TORCH=1 to install)",
                manifest.name,
            )
            continue
        filtered.append(item)
    return filtered


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
        # Serializes concurrent _import_entry_points calls on the same loader
        # instance so that the before/after registry snapshots cannot interleave
        # with a parallel install (Finding 1 fix).
        self._load_lock = threading.Lock()
        # Plugin names successfully imported into this registry (auto-install
        # then load_enabled_plugins must not re-fail on a second pass).
        self._loaded_plugins: set[str] = set()

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

        if manifest.name in self._loaded_plugins:
            log.debug(
                "PluginLoader: plugin '%s' already loaded — skipping",
                manifest.name,
            )
            declared = list(manifest.node_types or [])
            return [n for n in declared if n in self._registry._classes]

        # Step 2 — platform version compatibility
        self._check_platform_compat(manifest, plugin_dir)

        # Step 3 — Python version compatibility
        self._check_python_compat(manifest, plugin_dir)

        # Step 4 — dependency check / isolated venv
        if (manifest.runtime or "inprocess") == "isolated":
            from app.core.plugins.venv_manager import PluginVenvManager

            # Isolated plugins need required + optional extras (TF/Keras, etc.)
            # in the plugin venv. Do not install those into the host API image.
            venv_mgr = PluginVenvManager()
            venv_py = venv_mgr.ensure(
                manifest.name,
                isolated_venv_requirements(manifest),
            )
        else:
            DependencyChecker().check(manifest.dependencies)
            venv_py = None

        # Step 5 — register nodes. Isolated plugins must not exec_module in
        # the host (B2): use manifest/AST node_types + stub classes.
        if (manifest.runtime or "inprocess") == "isolated":
            new_node_types = self._register_isolated_nodes(plugin_dir, manifest)
        else:
            new_node_types = self._import_entry_points(plugin_dir, manifest)

        if (manifest.runtime or "inprocess") == "isolated" and venv_py is not None:
            from app.core.plugins.runtime_registry import (
                IsolatedPluginSpec,
                get_runtime_registry,
            )

            get_runtime_registry().register(
                IsolatedPluginSpec(
                    plugin_name=manifest.name,
                    install_path=str(Path(plugin_dir).resolve()),
                    venv_python=str(venv_py),
                    node_types=tuple(new_node_types),
                )
            )

        # Step 6 — log summary
        log.info(
            "Loaded plugin '%s' v%s (runtime=%s) — registered %d node type(s): %s",
            manifest.name,
            manifest.version,
            manifest.runtime,
            len(new_node_types),
            new_node_types,
        )

        # Step 7 — return newly registered node_types
        self._loaded_plugins.add(manifest.name)
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
            msg = (
                "PluginLoader: platform version unknown (app.__version__ not set) — "
                "skipping platform_version check for plugin '%s'. "
                "Set app.__version__ to enforce compatibility checks."
            )
            if os.environ.get("GRAPHYN_STRICT_COMPAT", "").lower() in ("1", "true"):
                raise PluginCompatibilityError(
                    f"Plugin '{manifest.name}' requires platform "
                    f"{manifest.platform_version} but the platform version is "
                    "unknown (app.__version__ not set). Set app.__version__ or "
                    "unset GRAPHYN_STRICT_COMPAT to allow loading."
                )
            log.warning(msg, manifest.name)
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

        Thread safety: ``_load_lock`` serializes concurrent calls on the same
        loader instance so that the ``before``/``after`` snapshots cannot
        interleave with a parallel install (Finding 1 fix).

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

        Raises
        ------
        PluginInstallError
            If ``manifest.entry_points`` is non-empty but no node types were
            registered (all entry points failed).
        """
        discovery = AutoDiscovery(self._registry)

        with self._load_lock:
            # Snapshot of node_types already registered before this plugin loads.
            # Held under _load_lock to prevent concurrent loaders from
            # interleaving their before/after snapshots (Finding 1 fix).
            before: set[str] = set(self._registry._classes.keys())

            for entry_point in manifest.entry_points:
                path = plugin_dir / entry_point
                try:
                    module = discovery._import_file(path, package_prefix=None)
                    discovery._process_module(module)
                except (DuplicateNodeTypeError, DuplicatePortTypeError) as exc:
                    # Duplicate node or port types from a second entry point /
                    # second load: keep the first registration and continue so
                    # nodes.py can still register after types.py catalogued types.
                    log.warning(
                        "PluginLoader: duplicate type detected while loading "
                        "entry point '%s' from plugin '%s': %s — "
                        "the first registration is kept.",
                        entry_point,
                        manifest.name,
                        exc,
                    )
                    continue
                except KeyboardInterrupt:
                    # Re-raise keyboard interrupts — suppressing them would make
                    # the process unresponsive to Ctrl-C (Finding 2 fix).
                    log.warning(
                        "PluginLoader: KeyboardInterrupt while loading entry point "
                        "'%s' from plugin '%s' — aborting.",
                        entry_point,
                        manifest.name,
                    )
                    raise
                except BaseException as exc:  # noqa: BLE001
                    # Catches SystemExit and other BaseException subclasses that
                    # would otherwise abort the load sequence silently (Finding 2 fix).
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

        # Finding 3 fix: if the manifest declared entry points but none registered
        # any node types, the plugin is non-functional — raise rather than silently
        # returning an empty list.
        if manifest.entry_points and not new_types:
            declared = list(manifest.node_types or [])
            already = [n for n in declared if n in self._registry._classes]
            if already:
                log.debug(
                    "PluginLoader: plugin '%s' node types already registered — "
                    "skipping empty re-load.",
                    manifest.name,
                )
                return already
            raise PluginInstallError(
                f"Plugin '{manifest.name}' declared {len(manifest.entry_points)} "
                "entry point(s) but no node types were registered. "
                "Check the plugin's entry point files for errors (see WARNING logs above)."
            )

        return new_types

    def _register_isolated_nodes(
        self,
        plugin_dir: Path,
        manifest: PluginManifest,
    ) -> list[str]:
        """Register stub Node classes for an isolated plugin without importing it.

        Node types come from ``manifest.node_types`` when set; otherwise they
        are extracted via AST from entry-point files (no exec_module).

        Stubs attach a real ``Config`` (AST ``class Config`` and/or
        ``plugin.toml`` ``config_schema``) and named ports so UI/API
        validation does not ``extra_forbidden`` legitimate knobs.
        """
        from app.core.nodes.base import Node
        from app.core.nodes.metadata import NodeMetadata, human_node_label

        names = list(manifest.node_types or [])
        if not names:
            names = self._ast_node_types(plugin_dir, manifest)
        if not names:
            raise PluginInstallError(
                f"Isolated plugin '{manifest.name}' has no node_types in the "
                "manifest and none could be extracted from entry points. "
                "Add node_types = [\"...\"] to plugin.toml."
            )

        install_path = str(Path(plugin_dir).resolve())

        from app.core.plugins.isolated_schema import (
            config_class_for_spec,
            ports_for_spec,
            specs_from_entry_points,
        )

        ast_specs = specs_from_entry_points(plugin_dir, manifest)
        toml_schemas = getattr(manifest, "config_schema", None) or {}

        def _isolated_process(self, inputs):  # noqa: ARG002
            raise RuntimeError(
                f"Isolated node '{getattr(type(self), 'node_type', '?')}' "
                "must not run in-process"
            )

        with self._load_lock:
            before: set[str] = set(self._registry._classes.keys())
            for node_type in names:
                if node_type in self._registry._classes:
                    log.debug(
                        "PluginLoader: isolated node type '%s' already registered "
                        "— keeping the first registration.",
                        node_type,
                    )
                    continue
                spec = ast_specs.get(node_type)
                input_ports, output_ports = ports_for_spec(spec)
                config_cls = config_class_for_spec(
                    node_type,
                    spec,
                    toml_schemas.get(node_type) if isinstance(toml_schemas, dict) else None,
                )
                stub = type(
                    f"Isolated_{node_type}",
                    (Node,),
                    {
                        "node_type": node_type,
                        "input_ports": input_ports,
                        "output_ports": output_ports,
                        "Config": config_cls,
                        "_siso": False,
                        "metadata": NodeMetadata(
                            node_type=node_type,
                            label=human_node_label(node_type),
                            description=(
                                f"Isolated plugin node from '{manifest.name}' "
                                "(executed in a plugin venv worker)"
                            ),
                            category="plugin",
                            version=manifest.version,
                        ),
                        "_graphyn_isolated": True,
                        "_graphyn_plugin_install_path": install_path,
                        "process": _isolated_process,
                    },
                )
                stub.__module__ = f"_graphyn_isolated.{manifest.name}"
                self._registry.register(node_type, stub, stub.metadata)
            after: set[str] = set(self._registry._classes.keys())
            new_types = sorted(after - before)

        return sorted(set(names) | set(new_types))

    @staticmethod
    def _ast_node_types(plugin_dir: Path, manifest: PluginManifest) -> list[str]:
        """Parse entry-point files for ``node_type = \"...\"`` without importing."""
        found: list[str] = []
        seen: set[str] = set()
        for entry_point in manifest.entry_points:
            path = plugin_dir / entry_point
            if not path.is_file():
                log.warning(
                    "PluginLoader: isolated entry point '%s' missing in plugin '%s'",
                    entry_point,
                    manifest.name,
                )
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                log.warning(
                    "PluginLoader: cannot AST-parse isolated entry point '%s' "
                    "from plugin '%s': %s",
                    entry_point,
                    manifest.name,
                    exc,
                )
                continue
            for node in ast.walk(tree):
                value = None
                if isinstance(node, ast.Assign):
                    if any(
                        isinstance(tgt, ast.Name) and tgt.id == "node_type"
                        for tgt in node.targets
                    ):
                        value = node.value
                elif (
                    isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name)
                    and node.target.id == "node_type"
                ):
                    value = node.value
                if value is None:
                    continue
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    if value.value not in seen:
                        seen.add(value.value)
                        found.append(value.value)
        return found
