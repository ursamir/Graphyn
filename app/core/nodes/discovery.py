# app/core/nodes/discovery.py
"""AutoDiscovery — scans node directories and registers Node/PortDataType subclasses."""
from __future__ import annotations

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

        # 1. Scan framework root (existing behaviour — skips framework files)
        self._scan_directory(nodes_path, package_prefix="app.core.nodes")

        # 2. Scan each Category_Folder (subdirectory with __init__.py)
        for subdir in sorted(nodes_path.iterdir()):
            if subdir.is_dir() and (subdir / "__init__.py").exists():
                category_prefix = f"app.core.nodes.{subdir.name}"
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
                from app.core.config import plugins_home as _plugins_home
                plugins_dir = str(_plugins_home())

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
            # Use the parent directory name as the package prefix when available.
            parent = path.parent.name
            module_name = f"{parent}.{path.stem}" if parent else path.stem
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module

    def _process_module(self, module) -> None:
        """Inspect *module* and register any PortDataType / Node subclasses found."""
        from app.core.nodes.base import Node

        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if not isinstance(obj, type):
                continue

            # Register PortDataType subclasses
            if (
                issubclass(obj, PortDataType)
                and obj is not PortDataType
                and obj.__module__ == module.__name__
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
                and obj.__module__ == module.__name__
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
                if existing.__name__ == cls.__name__ and existing.__qualname__ == cls.__qualname__:
                    return  # same class, different import path — skip silently
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

        # Populate port dicts on metadata if not already set
        if not meta.input_ports:
            meta.input_ports = {k: _port_to_dict(v) for k, v in cls.input_ports.items()}
        if not meta.output_ports:
            meta.output_ports = {k: _port_to_dict(v) for k, v in cls.output_ports.items()}

        self._registry.register(node_type, cls, meta)
