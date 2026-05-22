# app/core/nodes/__init__.py
"""Enhanced Node System — public API.

.. warning::
    WARNING: Importing this module triggers full plugin discovery and loading.
    This includes filesystem scanning, module imports, and potentially network
    calls (if GRAPHYN_PLUGIN_AUTO_INSTALL is set). Set GRAPHYN_SKIP_PLUGIN_LOAD=1
    to skip plugin loading (useful in tests and lightweight scripts).

Importing this module guarantees:
  1. AutoDiscovery has scanned all node files and the plugins directory.
  2. The NodeRegistry singleton is fully populated.
  3. The TypeCatalogue contains all PortDataType subclasses.

Usage::

    from app.core.nodes import registry
    node_class = registry.get_class("clean")
    metadata   = registry.get_metadata("clean")

Test isolation
--------------
Set ``GRAPHYN_SKIP_PLUGIN_LOAD=1`` (or ``true``) to skip the
``PluginManager.load_enabled_plugins()`` call and the plugins-dir scan.
This avoids touching the filesystem during unit tests that don't need
real plugins::

    GRAPHYN_SKIP_PLUGIN_LOAD=1 pytest tests/
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from app.core.nodes.registry import NodeRegistry
from app.core.nodes.discovery import AutoDiscovery

_log = logging.getLogger(__name__)

# ── Singleton ─────────────────────────────────────────────────────────────────
registry = NodeRegistry()

# ── Skip flag for test isolation (N-16 fix) ───────────────────────────────────
_skip_plugin_load = os.environ.get("GRAPHYN_SKIP_PLUGIN_LOAD", "").strip().lower() in (
    "1", "true", "yes",
)

# ── Plugin Manager startup ────────────────────────────────────────────────────
# Load enabled plugins first so their node types are in the registry before
# AutoDiscovery runs. AutoDiscovery's plugins_dir scan is then skipped to
# avoid double-loading (and the associated duplicate-registration log noise).
_plugins_loaded_by_manager: bool = False

if not _skip_plugin_load:
    try:
        from app.core.plugins.manager import PluginManager
        PluginManager().load_enabled_plugins()
        _plugins_loaded_by_manager = True
    except Exception as exc:
        # N-17 fix: log the full traceback so the root cause is visible,
        # and explicitly note that AutoDiscovery will fall back to scanning
        # the plugins dir directly (which may produce duplicate-registration
        # warnings if some plugins were partially loaded).
        _log.warning(
            "Startup: PluginManager.load_enabled_plugins() failed — "
            "AutoDiscovery will scan the plugins directory as a fallback. "
            "This may produce duplicate-registration warnings. Error: %s",
            exc,
            exc_info=True,
        )

# ── Auto-discovery ────────────────────────────────────────────────────────────
# Always scan the framework nodes dir and models dir.
# Only scan plugins_dir when PluginManager did not already load them, to avoid
# double-loading and duplicate-registration warnings.
_nodes_dir = Path(__file__).parent
from app.core.config import plugins_home as _plugins_home

if _skip_plugin_load:
    _plugins_dir = None  # skip entirely in test mode
elif _plugins_loaded_by_manager:
    _plugins_dir = None  # already loaded by PluginManager
else:
    _plugins_dir = str(_plugins_home())

_models_dir = Path(__file__).parent.parent.parent / "models"

try:
    AutoDiscovery(registry).run(
        nodes_dir=_nodes_dir,
        plugins_dir=_plugins_dir,
        models_dir=_models_dir,
    )
except Exception as _exc:
    import logging as _logging
    _logging.getLogger(__name__).critical(
        "AutoDiscovery failed during startup: %s", _exc, exc_info=True
    )
    raise ImportError(
        f"app.core.nodes failed to initialise: {_exc}. "
        "Check plugin files for duplicate node_type declarations or import errors."
    ) from _exc

__all__ = [
    "registry",
    # Node base classes
    "Node",
    # Port types
    "InputPort",
    "OutputPort",
    "PortDataType",
    # Metadata
    "NodeMetadata",
    # Observer
    "NodeObserver",
    # Discovery
    "AutoDiscovery",
    # Registry
    "NodeRegistry",
]

# Re-export the full public API surface so callers can use
#   from app.core.nodes import Node, InputPort, ...
# instead of deep imports like
#   from app.core.nodes.base import Node
from app.core.nodes.base import Node  # noqa: E402
from app.core.nodes.ports import InputPort, OutputPort, PortDataType  # noqa: E402
from app.core.nodes.metadata import NodeMetadata  # noqa: E402
from app.core.nodes.observers import NodeObserver  # noqa: E402
