# unit_test/core/plugins/test_dependencies.py
"""Tests for DependencyChecker (Req 6)."""
from __future__ import annotations

import pytest

from app.core.plugins.dependencies import DependencyChecker
from app.core.plugins.errors import PluginDependencyError, PluginManifestError


def test_empty_dependencies_passes() -> None:
    """Empty dependency list is a no-op."""
    checker = DependencyChecker()
    checker.check([])  # should not raise


def test_satisfied_dependency_passes() -> None:
    """A dependency that is installed passes without raising."""
    checker = DependencyChecker()
    # pytest is always installed in the test environment
    checker.check(["pytest"])  # should not raise


def test_unsatisfied_dependency_raises() -> None:
    """Req 6 — DependencyChecker raises PluginDependencyError listing unsatisfied deps."""
    checker = DependencyChecker()
    # Use a package name that is extremely unlikely to be installed
    fake_dep = "this-package-does-not-exist-graphyn-test-xyz123"
    with pytest.raises(PluginDependencyError) as exc_info:
        checker.check([fake_dep])
    # The error message must list the unsatisfied dependency
    assert fake_dep in str(exc_info.value)


def test_multiple_unsatisfied_deps_all_listed() -> None:
    """All unsatisfied deps appear in the error message."""
    checker = DependencyChecker()
    fake1 = "fake-dep-aaa-graphyn-test"
    fake2 = "fake-dep-bbb-graphyn-test"
    with pytest.raises(PluginDependencyError) as exc_info:
        checker.check([fake1, fake2])
    msg = str(exc_info.value)
    assert fake1 in msg
    assert fake2 in msg


def test_malformed_requirement_raises_manifest_error() -> None:
    """Malformed PEP 508 string raises PluginManifestError."""
    checker = DependencyChecker()
    with pytest.raises(PluginManifestError):
        checker.check(["!!!invalid requirement!!!"])


def test_version_constraint_satisfied() -> None:
    """A version-constrained dep that is satisfied passes."""
    checker = DependencyChecker()
    # pytest is always installed; require any version >=0.1
    checker.check(["pytest>=0.1"])  # should not raise


def test_version_constraint_unsatisfied_raises() -> None:
    """A version constraint that cannot be satisfied raises PluginDependencyError."""
    checker = DependencyChecker()
    # Require pytest at an impossibly high version
    with pytest.raises(PluginDependencyError):
        checker.check(["pytest>=9999.0.0"])
