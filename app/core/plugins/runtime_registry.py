# app/core/plugins/runtime_registry.py
"""
Bounded Context:  BC3 — Node Catalog (Plugin Ecosystem)
Responsibility:   Track which node_types execute in an isolated plugin venv.
Owns:             PluginRuntimeRegistry singleton mapping
Public Surface:   PluginRuntimeRegistry, IsolatedPluginSpec, get_runtime_registry()
Must NOT:         Import from app.domain or app.api.
Dependencies:     dataclasses, threading
Reason To Change: Isolated execution metadata shape changes.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass(frozen=True)
class IsolatedPluginSpec:
    """Runtime info for a plugin with ``runtime = "isolated"``."""

    plugin_name: str
    install_path: str
    venv_python: str
    node_types: tuple[str, ...] = field(default_factory=tuple)


class PluginRuntimeRegistry:
    """In-process map of node_type → isolated plugin spec."""

    def __init__(self) -> None:
        self._by_node: dict[str, IsolatedPluginSpec] = {}
        self._by_plugin: dict[str, IsolatedPluginSpec] = {}
        self._lock = threading.Lock()

    def register(self, spec: IsolatedPluginSpec) -> None:
        with self._lock:
            self._by_plugin[spec.plugin_name] = spec
            for nt in spec.node_types:
                self._by_node[nt] = spec

    def unregister_plugin(self, plugin_name: str) -> None:
        with self._lock:
            spec = self._by_plugin.pop(plugin_name, None)
            if spec is None:
                return
            for nt in list(self._by_node):
                if self._by_node[nt].plugin_name == plugin_name:
                    del self._by_node[nt]

    def get_for_node(self, node_type: str) -> IsolatedPluginSpec | None:
        with self._lock:
            return self._by_node.get(node_type)

    def get_for_plugin(self, plugin_name: str) -> IsolatedPluginSpec | None:
        with self._lock:
            return self._by_plugin.get(plugin_name)

    def clear(self) -> None:
        with self._lock:
            self._by_node.clear()
            self._by_plugin.clear()


_REGISTRY = PluginRuntimeRegistry()


def get_runtime_registry() -> PluginRuntimeRegistry:
    return _REGISTRY
