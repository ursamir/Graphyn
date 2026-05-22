# unit_test/core/plugins/test_loader.py
"""Tests for PluginLoader platform version compatibility (Req 6)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.plugins.loader import PluginLoader
from app.core.plugins.errors import PluginCompatibilityError
from app.core.plugins.manifest import PluginManifest


def _make_manifest(**overrides) -> PluginManifest:
    """Build a minimal valid PluginManifest."""
    data = {
        "name": "test-plugin",
        "version": "1.0.0",
        "description": "Test plugin.",
        "author": "Tester",
        "platform_version": ">=0.0",
        "entry_points": ["nodes.py"],
        **overrides,
    }
    return PluginManifest.model_validate(data)


def test_platform_compat_accepts_matching_version(fresh_registry) -> None:
    """Req 6 — platform version compat check accepts a matching version."""
    loader = PluginLoader(fresh_registry)
    manifest = _make_manifest(platform_version=">=0.0")

    # Should not raise — >=0.0 matches any version including 0.0.0
    with patch(
        "app.core.plugins.loader._get_platform_version", return_value="1.0.0"
    ):
        loader._check_platform_compat(manifest, Path("/fake"))


def test_platform_compat_rejects_incompatible_major(fresh_registry) -> None:
    """Req 6 — platform version compat check rejects incompatible major version."""
    loader = PluginLoader(fresh_registry)
    # Plugin requires platform >=10.0 but current platform is 1.0.0
    manifest = _make_manifest(platform_version=">=10.0")

    with patch(
        "app.core.plugins.loader._get_platform_version", return_value="1.0.0"
    ):
        with pytest.raises(PluginCompatibilityError):
            loader._check_platform_compat(manifest, Path("/fake"))


def test_platform_compat_exact_version_match(fresh_registry) -> None:
    """Exact version specifier matches correctly."""
    loader = PluginLoader(fresh_registry)
    manifest = _make_manifest(platform_version="==5.0.0")

    with patch(
        "app.core.plugins.loader._get_platform_version", return_value="5.0.0"
    ):
        loader._check_platform_compat(manifest, Path("/fake"))  # no raise


def test_platform_compat_exact_version_mismatch(fresh_registry) -> None:
    """Exact version specifier rejects non-matching version."""
    loader = PluginLoader(fresh_registry)
    manifest = _make_manifest(platform_version="==5.0.0")

    with patch(
        "app.core.plugins.loader._get_platform_version", return_value="4.0.0"
    ):
        with pytest.raises(PluginCompatibilityError):
            loader._check_platform_compat(manifest, Path("/fake"))


def test_python_compat_no_min_python_passes(fresh_registry) -> None:
    """min_python=None skips the Python version check."""
    loader = PluginLoader(fresh_registry)
    manifest = _make_manifest()  # min_python defaults to None
    # Should not raise
    loader._check_python_compat(manifest, Path("/fake"))


def test_python_compat_satisfied(fresh_registry) -> None:
    """min_python satisfied by current interpreter."""
    loader = PluginLoader(fresh_registry)
    # Require Python 2.7 — always satisfied by any modern Python
    manifest = _make_manifest(min_python="2.7")
    loader._check_python_compat(manifest, Path("/fake"))  # no raise


def test_python_compat_unsatisfied(fresh_registry) -> None:
    """min_python higher than current interpreter raises PluginCompatibilityError."""
    loader = PluginLoader(fresh_registry)
    # Require a future Python version that doesn't exist yet
    manifest = _make_manifest(min_python="99.0.0")
    with pytest.raises(PluginCompatibilityError):
        loader._check_python_compat(manifest, Path("/fake"))
