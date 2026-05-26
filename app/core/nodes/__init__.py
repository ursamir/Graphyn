# app/core/nodes/__init__.py
"""
Bounded Context:  BC3 — Node Catalog
Responsibility:   Package initialiser. Exposes the NodeRegistry singleton and
                  the full public node API. Startup population is performed
                  explicitly by initialize_registry(), called once by each
                  entry point (API, CLI, MCP) — NOT at import time.
Owns:             registry singleton (NodeRegistry), initialize_registry(),
                  GRAPHYN_SKIP_PLUGIN_LOAD test-isolation flag,
                  re-exports of Node, InputPort, OutputPort, PortDataType,
                  NodeMetadata, NodeObserver, AutoDiscovery, NodeRegistry.
Public Surface:   registry, initialize_registry(), Node, InputPort, OutputPort,
                  PortDataType, NodeMetadata, NodeObserver, AutoDiscovery,
                  NodeRegistry.
Must NOT:         Import from app.domain or app.api at module level.
                  Must not perform network I/O at import time.
                  Must not run AutoDiscovery or PluginManager at import time —
                  use initialize_registry() instead.
Dependencies:     app.core.nodes.{registry, discovery, base, ports, metadata,
                  observers}, app.core.plugins.manager (lazy, inside
                  initialize_registry()), app.core.config.
Reason To Change: New public symbol added to the node API, or startup
                  sequence changes (e.g. new plugin loader step).

Set GRAPHYN_SKIP_PLUGIN_LOAD=1 to skip plugin loading in tests.

## Startup protocol

Entry points MUST call initialize_registry() exactly once before serving
requests or executing pipelines:

    from app.core.nodes import initialize_registry
    initialize_registry()

Calling initialize_registry() a second time is a no-op (idempotent).
"""
from __future__ import annotations

import logging
import os
import threading
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

# ── Initialization state ──────────────────────────────────────────────────────
_initialized = False
_init_lock = threading.Lock()


def initialize_registry() -> None:
    """Populate the NodeRegistry singleton.

    Runs PluginManager.load_enabled_plugins() then AutoDiscovery.run().
    Idempotent — safe to call multiple times; only the first call does work.

    Entry points (app/api/main.py, app/cli/main.py, app/mcp/server.py) MUST
    call this once before serving requests. Tests that need an empty registry
    should set GRAPHYN_SKIP_PLUGIN_LOAD=1 and NOT call this function.

    Raises:
        ImportError: if AutoDiscovery fails critically (duplicate node_type,
                     import error in a node file).
    """
    global _initialized
    with _init_lock:
        if _initialized:
            return
        _initialized = True

    _plugins_loaded_by_manager = False

    if not _skip_plugin_load:
        try:
            from app.core.plugins.manager import PluginManager  # noqa: PLC0415
            PluginManager().load_enabled_plugins()
            _plugins_loaded_by_manager = True
        except Exception as exc:
            _log.warning(
                "Startup: PluginManager.load_enabled_plugins() failed — "
                "AutoDiscovery will scan the plugins directory as a fallback. "
                "This may produce duplicate-registration warnings. Error: %s",
                exc,
                exc_info=True,
            )

    _nodes_dir = Path(__file__).parent
    from app.core.config import plugins_home as _plugins_home  # noqa: PLC0415

    if _skip_plugin_load:
        _plugins_dir = None
    elif _plugins_loaded_by_manager:
        _plugins_dir = None
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
        raise ImportError(
            f"app.core.nodes.initialize_registry() failed: {_exc}. "
            "Check plugin files for duplicate node_type declarations or import errors."
        ) from _exc


__all__ = [
    "registry",
    "initialize_registry",
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
