"""
app.core.plugins — Plugin Ecosystem (Phase 5)
=============================================

This package provides the managed plugin lifecycle on top of the existing
``AutoDiscovery`` flat-file mechanism.  It is strictly additive: no existing
public API changes, no existing tests break.

Public re-exports
-----------------
Only the error hierarchy is exported here.  Higher-level components
(``PluginManager``, ``PluginStore``, etc.) are imported directly from their
respective sub-modules to keep startup cost low.

    from app.core.plugins.errors import (
        PluginError,
        PluginManifestError,
        PluginCompatibilityError,
        PluginDependencyError,
        PluginInstallError,
        PluginNotFoundError,
        PluginAlreadyInstalledError,
        PluginIndexError,
    )
"""

from __future__ import annotations

from app.core.plugins.errors import (
    PluginAlreadyInstalledError,
    PluginCompatibilityError,
    PluginDependencyError,
    PluginError,
    PluginIndexError,
    PluginInstallError,
    PluginManifestError,
    PluginNotFoundError,
)

__all__ = [
    "PluginError",
    "PluginManifestError",
    "PluginCompatibilityError",
    "PluginDependencyError",
    "PluginInstallError",
    "PluginNotFoundError",
    "PluginAlreadyInstalledError",
    "PluginIndexError",
]
