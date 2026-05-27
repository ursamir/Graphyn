# app/core/nodes/discovery.py
"""
Bounded Context:  BC3 — Node Catalog
Responsibility:   Scan node directories and plugin directories, import modules,
                  and register Node/PortDataType subclasses into the registry.
Owns:             AutoDiscovery — run(), _scan_directory(), _import_file(),
                  _process_module(), _register_node().
Public Surface:   AutoDiscovery(registry).run(nodes_dir, plugins_dir, models_dir)
Must NOT:         Import from app.domain, app.api, app.core.orchestrator,
                  app.core.planner, or any BC4/BC5/BC6 module.
Dependencies:     BC2 (nodes.base, nodes.ports, nodes.metadata, nodes.errors),
                  BC3 (nodes.registry, nodes.catalogue), app.core.config
                  (plugins_home), stdlib (importlib, logging, os, pathlib, re).
Reason To Change: Plugin discovery protocol changes (new manifest format,
                  new directory layout), or node registration rules evolve.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import logging
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.nodes.errors import (
    DuplicateNodeTypeError,
    DuplicatePortTypeError,
    NodeMetadataError,
)
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort, PortDataType

if TYPE_CHECKING:
    from app.core.nodes.base import Node
    from app.core.nodes.registry import NodeRegistry

log = logging.getLogger(__name__)

# Files excluded from scanning in the nodes directory.
# Includes __init__.py, base.py, all framework/infrastructure files,
# and any _-prefixed files.
_EXCLUDED_FILES = {
    "__init__.py",
    "base.py",
    # infrastructure / framework files — not node implementations
    "errors.py",
    "ports.py",
    "config.py",
    "retry.py",
    "compat.py",
    "metadata.py",
    "catalogue.py",
    "registry.py",
    "discovery.py",
    "observers.py",
}
_EXCLUDED_PREFIXES = {"_"}

# Regexes for PascalCase → snake_case conversion.
# Two passes handle both acronyms and normal word boundaries:
#   Pass 1: insert underscore between an acronym run and the next word
#           e.g. "TFLite" → "TF_Lite"  (uppercase run followed by uppercase+lowercase)
#   Pass 2: insert underscore before any uppercase letter preceded by a lowercase letter
#           e.g. "AudioMixer" → "Audio_Mixer"
_PASCAL_RE1 = re.compile(r"([A-Z]+)([A-Z][a-z])")   # e.g. TFLite → TF_Lite
_PASCAL_RE2 = re.compile(r"([a-z\d])([A-Z])")        # e.g. AudioMixer → Audio_Mixer


def _pascal_to_snake(name: str) -> str:
    """Convert PascalCase to snake_case and strip trailing '_node' suffix.

    Handles acronyms correctly so that consecutive uppercase letters are
    kept together as a single token.

    Examples:
        FilterNode          → filter
        TFLiteProcessorNode → tf_lite_processor
        AudioMixerNode      → audio_mixer
        CleanNode           → clean
        HFExportNode        → hf_export
        TFRecordExportNode  → tf_record_export
    """
    s = _PASCAL_RE1.sub(r"\1_\2", name)
    s = _PASCAL_RE2.sub(r"\1_\2", s)
    snake = s.lower()
    if snake.endswith("_node"):
        snake = snake[:-5]
    return snake


def _fqn(cls: type) -> str:
    """Return the fully-qualified name: '{module}.{qualname}'."""
    return f"{cls.__module__}.{cls.__qualname__}"


def _port_to_dict(port: InputPort | OutputPort) -> dict:
    """Serialise a port to a dict, replacing data_type with its fqn string."""
    d = port.model_dump()
    dt = port.data_type
    if dt is None:
        d["data_type"] = None
    elif hasattr(dt, "__module__") and hasattr(dt, "__qualname__"):
        d["data_type"] = _fqn(dt)
    else:
        d["data_type"] = str(dt)
    return d


_PLUGINS_DIR_DEFAULT = object()  # sentinel: use config default


class AutoDiscovery:
    """Scans node directories and registers Node/PortDataType subclasses.

    Usage::

        discovery = AutoDiscovery(registry)
        discovery.run(nodes_dir="app/core/nodes", plugins_dir="plugins")
    """

    def __init__(self, registry: "NodeRegistry") -> None:
        self._registry = registry

    def run(
        self,
        nodes_dir: str | Path,
        plugins_dir: str | Path | None = _PLUGINS_DIR_DEFAULT,
        models_dir: str | Path | None = None,
    ) -> None:
        """Scan nodes_dir (and optionally plugins_dir / models_dir) and populate the registry.

        Args:
            nodes_dir: Path to the package directory containing node modules.
                AutoDiscovery scans the root directory and then recursively
                scans one level of Category_Folders (subdirectories that
                contain an ``__init__.py``).
            plugins_dir: Optional path to a plugins directory.
                - Omitted / ``_PLUGINS_DIR_DEFAULT``: falls back to
                  ``GRAPHYN_PLUGINS_DIR`` env var, then ``"plugins/"``.
                - ``None``: skip the plugins_dir scan entirely (used when
                  ``PluginManager.load_enabled_plugins()`` has already loaded
                  all enabled plugins at startup).
            models_dir: Optional path to the models directory. When provided,
                AutoDiscovery scans it for ``PortDataType`` subclasses and
                registers them in ``TypeCatalogue``.
        """
        nodes_path = Path(nodes_dir)

        # Derive the package prefix from the actual nodes_dir path so that
        # AutoDiscovery works correctly when nodes_dir is not the default
        # "app/core/nodes" (e.g. in test fixtures or alternative installs).
        # Strategy: walk up from nodes_path until we find a directory that is
        # NOT a Python package (no __init__.py), then build the dotted name
        # from the remaining path components.
        def _path_to_package(p: Path) -> str:
            parts: list[str] = []
            current = p.resolve()
            while (current / "__init__.py").exists():
                parts.append(current.name)
                current = current.parent
            return ".".join(reversed(parts)) if parts else p.name

        nodes_package_prefix = _path_to_package(nodes_path)

        # 1. Scan framework root (existing behaviour — skips framework files)
        self._scan_directory(nodes_path, package_prefix=nodes_package_prefix)

        # 2. Scan each Category_Folder (subdirectory with __init__.py)
        for subdir in sorted(nodes_path.iterdir()):
            if subdir.is_dir() and (subdir / "__init__.py").exists():
                category_prefix = f"{nodes_package_prefix}.{subdir.name}"
                self._scan_directory(subdir, package_prefix=category_prefix)

        # 3. Scan models_dir for PortDataType subclasses
        if models_dir is not None:
            models_path = Path(models_dir)
            if models_path.exists() and models_path.is_dir():
                self._scan_directory(models_path, package_prefix="app.models")

        # 4. Scan plugins_dir — manifest-based packages only.
        #
        # Each plugin must be a subdirectory containing a ``plugin.toml`` or
        # ``plugin.json`` manifest.  Bare ``.py`` files at the root of the
        # plugins directory and subdirectories without a manifest are ignored
        # with a WARNING so operators can identify and migrate them.
        #
        # plugins_dir=None means "skip entirely" (PluginManager already loaded them).
        # plugins_dir=_PLUGINS_DIR_DEFAULT means "use config default".
        if plugins_dir is None:
            pass  # explicitly skipped by caller
        else:
            if plugins_dir is _PLUGINS_DIR_DEFAULT:
                try:
                    from app.core.config import plugins_home as _plugins_home  # noqa: PLC0415
                    plugins_dir = str(_plugins_home())
                except Exception as exc:
                    log.warning(
                        "AutoDiscovery: could not resolve plugins_dir from config: %s — "
                        "falling back to 'plugins'. Nodes already registered are unaffected.",
                        exc,
                    )
                    plugins_dir = os.environ.get("GRAPHYN_PLUGINS_DIR", "plugins")

            plugins_path = Path(plugins_dir)
            if plugins_path.exists() and plugins_path.is_dir():
                # Warn about any bare .py files at the plugins root — they are no
                # longer loaded; a plugin.toml manifest is required.
                for py_file in sorted(plugins_path.glob("*.py")):
                    if py_file.name.startswith("_"):
                        continue
                    log.warning(
                        "AutoDiscovery: ignoring bare plugin file '%s' — "
                        "flat .py plugins are no longer supported. "
                        "Package your plugin as a directory with a plugin.toml manifest.",
                        py_file.name,
                    )

                # Process subdirectories: manifest-based only.
                for subdir in sorted(plugins_path.iterdir()):
                    if not subdir.is_dir():
                        continue
                    if (subdir / "plugin.toml").exists() or (subdir / "plugin.json").exists():
                        # Manifest-based plugin — delegate to PluginLoader
                        try:
                            from app.core.plugins.loader import PluginLoader  # noqa: PLC0415
                            loader = PluginLoader(self._registry)
                            loader.load(subdir)
                        except Exception as exc:
                            log.warning(
                                "AutoDiscovery: failed to load manifest plugin '%s': %s",
                                subdir.name,
                                exc,
                            )
                    else:
                        # Subdirectory without a manifest — ignored with a warning.
                        log.warning(
                            "AutoDiscovery: ignoring plugin subdirectory '%s' — "
                            "no plugin.toml or plugin.json found. "
                            "Add a manifest to enable this plugin.",
                            subdir.name,
                        )

    def _scan_directory(
        self,
        directory: Path,
        package_prefix: str | None,
    ) -> None:
        """Iterate sorted ``*.py`` files in *directory*, importing each one.

        Skips files in ``_EXCLUDED_FILES`` and files whose names start with
        any prefix in ``_EXCLUDED_PREFIXES``.

        Import failures are logged as warnings and the file is skipped.
        ``DuplicateNodeTypeError`` and ``DuplicatePortTypeError`` propagate
        immediately (structural errors that must not be silenced).
        ``NodeMetadataError`` is logged as a warning and the node is skipped
        (allows graceful migration of legacy node files).
        """
        for py_file in sorted(directory.glob("*.py")):
            if py_file.name in _EXCLUDED_FILES:
                continue
            if any(py_file.name.startswith(p) for p in _EXCLUDED_PREFIXES):
                continue

            try:
                module = self._import_file(py_file, package_prefix)
            except Exception as exc:
                log.warning(
                    "AutoDiscovery: failed to import '%s': %s",
                    py_file,
                    exc,
                    exc_info=True,
                )
                continue

            try:
                self._process_module(module)
            except (DuplicateNodeTypeError, DuplicatePortTypeError):
                # Structural errors — re-raise immediately
                raise
            except NodeMetadataError as exc:
                log.warning(
                    "AutoDiscovery: skipping node in '%s' — missing metadata: %s",
                    py_file,
                    exc,
                )
            except Exception as exc:
                log.warning(
                    "AutoDiscovery: error processing module '%s': %s",
                    py_file,
                    exc,
                    exc_info=True,
                )

    def _import_file(self, path: Path, package_prefix: str | None):
        """Import a Python file as a module.

        For package files (``package_prefix`` is set), uses
        ``importlib.import_module`` so that relative imports within the
        package work correctly.

        For plugin files (``package_prefix`` is ``None``), loads the file
        directly via ``importlib.util.spec_from_file_location``.
        """
        if package_prefix:
            # Use importlib.import_module for proper package resolution
            module_name = f"{package_prefix}.{path.stem}"
            return importlib.import_module(module_name)
        else:
            # Plugin file — load from path using a dotted module name so that
            # cls.__module__ matches module.__name__ during _process_module.
            #
            # Use a hash of the full path to guarantee uniqueness across
            # different plugin root directories that may share subdirectory
            # names (e.g. plugins_v1/audio_classifier/nodes.py and
            # plugins_v2/audio_classifier/nodes.py would otherwise both
            # produce "audio_classifier.nodes" and collide in sys.modules).
            parent = path.parent.name
            path_hash = hashlib.md5(str(path).encode()).hexdigest()[:8]
            stem = path.stem
            module_name = (
                f"_graphyn_plugin_{parent}_{path_hash}.{stem}"
                if parent
                else f"_graphyn_plugin_{path_hash}.{stem}"
            )
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            # Register in sys.modules BEFORE exec_module so that intra-package
            # relative imports can resolve.  On failure, remove the broken stub
            # so that a subsequent retry (e.g. after fixing the plugin file)
            # does not silently return the empty stub.
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(module_name, None)
                raise
            return module

    def _process_module(self, module) -> None:
        """Inspect *module* and register any PortDataType / Node subclasses found.

        Two registration paths:
        1. ``__module__ == module.__name__`` — classes *defined* in this module.
        2. ``__all__`` — classes *explicitly re-exported* by the module author
           (e.g. ``from .base_classifier import AudioClassifierNode`` in
           ``nodes.py`` with ``__all__ = ["AudioClassifierNode"]``).
           This allows plugin authors to split implementation across sibling
           modules and re-export the public classes from the entry-point file.
        """
        from app.core.nodes.base import Node

        # Build the set of explicitly re-exported names (may be empty).
        explicit_exports: set[str] = set(getattr(module, "__all__", None) or [])

        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if not isinstance(obj, type):
                continue

            # A class is eligible if it was defined in this module OR if the
            # plugin author explicitly listed it in __all__.
            defined_here = obj.__module__ == module.__name__
            exported = attr_name in explicit_exports

            # Register PortDataType subclasses
            if (
                issubclass(obj, PortDataType)
                and obj is not PortDataType
                and (defined_here or exported)
            ):
                try:
                    self._registry.type_catalogue.register(obj)
                except DuplicatePortTypeError:
                    # Same class re-loaded under a different module path
                    # (e.g. startup load_enabled_plugins + explicit install() call).
                    # If the existing registration is the exact same class object,
                    # skip silently; otherwise re-raise.
                    fqn = f"{obj.__module__}.{obj.__qualname__}"
                    existing = self._registry.type_catalogue._types.get(fqn)
                    if existing is not None and existing is obj:
                        pass  # same class object — skip silently
                    else:
                        raise

            # Register Node subclasses
            if (
                issubclass(obj, Node)
                and obj is not Node
                and (defined_here or exported)
            ):
                self._register_node(obj)

    def _register_node(self, cls: type) -> None:
        """Validate and register a single Node subclass.

        Derives ``node_type`` from the class name if not explicitly declared,
        validates that a ``NodeMetadata`` is present, populates port dicts,
        and calls ``registry.register``.

        Raises:
            DuplicateNodeTypeError: if another class already owns this node_type.
            NodeMetadataError: if the class has no ``metadata`` ClassVar.
        """
        # Derive node_type
        node_type = getattr(cls, "node_type", "") or _pascal_to_snake(cls.__name__)

        # Check for duplicates
        if node_type in self._registry:
            existing = self._registry.get_class(node_type)
            if existing is not cls:
                # Allow same class loaded under a different module path
                # (e.g. AutoDiscovery + PluginLoader both loading the same plugin file)
                if (
                    existing.__name__ == cls.__name__
                    and existing.__qualname__ == cls.__qualname__
                    and existing.__module__ == cls.__module__
                ):
                    return  # genuinely the same class, different import path — skip silently
                raise DuplicateNodeTypeError(
                    f"node_type '{node_type}' is claimed by both "
                    f"{existing!r} and {cls!r}"
                )
            return  # already registered (e.g. re-import)

        # Validate metadata
        raw_meta = getattr(cls, "metadata", None)
        if raw_meta is None:
            raise NodeMetadataError(
                f"Node '{cls.__name__}' has no 'metadata' ClassVar. "
                "Declare a 'metadata: ClassVar[NodeMetadata]' on the class."
            )

        if not isinstance(raw_meta, NodeMetadata):
            raise NodeMetadataError(
                f"Node '{cls.__name__}'.metadata must be a NodeMetadata instance, "
                f"got {type(raw_meta)!r}."
            )

        meta: NodeMetadata = raw_meta

        # Populate port dicts on metadata if not already set.
        # Wrap in try/except so a missing input_ports/output_ports class attribute
        # raises NodeMetadataError (caught by _scan_directory) rather than a
        # generic AttributeError that produces a confusing "error processing module"
        # warning.
        try:
            if not meta.input_ports:
                meta.input_ports = {k: _port_to_dict(v) for k, v in cls.input_ports.items()}
            if not meta.output_ports:
                meta.output_ports = {k: _port_to_dict(v) for k, v in cls.output_ports.items()}
        except AttributeError as exc:
            raise NodeMetadataError(
                f"Node '{cls.__name__}' is missing port definitions: {exc}. "
                "Ensure the class defines 'input_ports' and 'output_ports' ClassVars."
            ) from exc

        self._registry.register(node_type, cls, meta)
