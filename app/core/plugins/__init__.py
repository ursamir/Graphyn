# app/core/plugins/__init__.py
"""
Bounded Context:  BC3 — Node Catalog (Plugin Ecosystem)
Responsibility:   Public API surface for the plugin ecosystem package.
                  Re-exports the full error hierarchy so callers use a single
                  import path. Higher-level components (PluginManager, etc.)
                  are imported directly from their sub-modules to keep startup
                  cost low.
Owns:             Re-export declarations for the complete PluginError hierarchy.
Public Surface:   PluginError, PluginManifestError, PluginCompatibilityError,
                  PluginDependencyError, PluginInstallError, PluginNotFoundError,
                  PluginAlreadyInstalledError, PluginIndexError.
Must NOT:         Import PluginManager, PluginStore, or PluginInstaller at
                  module level — those are heavy and must be imported on demand.
Dependencies:     app.core.plugins.errors.
Reason To Change: New exception class added to the plugin error hierarchy.
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
