"""
Plugin error hierarchy for the plugin ecosystem (Phase 5).

All plugin exceptions are subclasses of ``PluginError`` so callers can catch
at different levels of specificity:

    try:
        manager.install(source)
    except PluginCompatibilityError:
        ...  # platform version mismatch
    except PluginDependencyError:
        ...  # missing Python packages
    except PluginInstallError:
        ...  # network / git / archive failure
    except PluginError:
        ...  # any other plugin error
"""

from __future__ import annotations


class PluginError(Exception):
    """Base class for all plugin-related errors."""


class PluginManifestError(PluginError, ValueError):
    """Raised when a plugin manifest is missing, malformed, or contains
    invalid field values (wrong type, empty required string, malformed
    version, invalid slug, etc.).

    Inherits from ``ValueError`` so it can be caught by callers that
    handle generic value errors.
    """


class PluginCompatibilityError(PluginError):
    """Raised when a plugin's ``platform_version`` specifier does not
    include the current platform version, or when the plugin requires a
    Python version that is not satisfied by the running interpreter.

    Error messages must include the plugin name, the required constraint,
    and the actual version so the user knows exactly what to fix.
    """


class PluginDependencyError(PluginError):
    """Raised when one or more of a plugin's PEP 508 dependencies are not
    satisfied by the current Python environment.

    The exception message lists *all* unsatisfied requirements (no false
    positives, no false negatives) so the user can install them in one go.
    """


class PluginInstallError(PluginError):
    """Raised when a plugin cannot be fetched or extracted from its source
    (network failure, git error, bad archive, checksum mismatch, missing
    ``plugin.toml`` inside the archive, etc.).
    """


class PluginNotFoundError(PluginError, KeyError):
    """Raised when an operation targets a plugin name that is not present
    in ``PluginStore``.

    Inherits from ``KeyError`` for compatibility with dict-style lookup
    patterns.
    """


class PluginAlreadyInstalledError(PluginError):
    """Raised when attempting to install a plugin whose name is already
    recorded in ``PluginStore`` and the ``upgrade`` flag is ``False``.
    """


class PluginIndexError(PluginError):
    """Raised when the plugin index cannot be fetched, parsed, or when a
    requested plugin / version is not found in the index.
    """
