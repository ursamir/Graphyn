# app/core/registry_runtime.py
"""Registry runtime — returns the NodeRegistry singleton.

The singleton is populated by AutoDiscovery when app.core.nodes is imported.
Plugin files in the plugins/ directory are scanned automatically by AutoDiscovery
during that import, so no separate load_plugins() call is needed here.
"""
from __future__ import annotations

from app.core.nodes import registry


def get_registry():
    """Return the fully-populated NodeRegistry singleton."""
    return registry
