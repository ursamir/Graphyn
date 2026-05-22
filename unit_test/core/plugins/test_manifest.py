# unit_test/core/plugins/test_manifest.py
"""Tests for PluginManifest validation (Req 6 criteria 1–4, Req 16 criterion 5)."""
from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.plugins.manifest import PluginManifest
from app.core.plugins.errors import PluginManifestError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_MANIFEST = {
    "name": "my-plugin",
    "version": "1.0.0",
    "description": "A test plugin.",
    "author": "Test Author",
    "platform_version": ">=0.0",
    "entry_points": ["nodes.py"],
}


def make_manifest(**overrides) -> dict:
    return {**VALID_MANIFEST, **overrides}


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_valid_manifest_constructs():
    """Req 6.1 — valid manifest dict constructs without raising."""
    m = PluginManifest(**VALID_MANIFEST)
    assert m.name == "my-plugin"
    assert m.version == "1.0.0"


def test_valid_manifest_model_validate():
    """model_validate also works for valid data."""
    m = PluginManifest.model_validate(VALID_MANIFEST)
    assert m.name == "my-plugin"


def test_invalid_slug_raises():
    """Req 6.2 — name not matching ^[a-z][a-z0-9_-]*$ raises PluginManifestError."""
    with pytest.raises(PluginManifestError):
        PluginManifest(**make_manifest(name="My-Plugin"))  # uppercase


def test_invalid_slug_starts_with_digit():
    """Req 6.2 — name starting with digit raises PluginManifestError."""
    with pytest.raises(PluginManifestError):
        PluginManifest(**make_manifest(name="1plugin"))


def test_invalid_slug_empty():
    """Req 6.2 — empty name raises PluginManifestError."""
    with pytest.raises(PluginManifestError):
        PluginManifest(**make_manifest(name=""))


def test_invalid_version_raises():
    """Req 6.3 — invalid PEP 440 version raises PluginManifestError."""
    with pytest.raises(PluginManifestError):
        PluginManifest(**make_manifest(version="not-a-version!!"))


def test_entry_point_not_py_raises():
    """Req 6.4 — entry_points item not ending in .py raises PluginManifestError."""
    with pytest.raises(PluginManifestError):
        PluginManifest(**make_manifest(entry_points=["nodes.js"]))


def test_entry_points_empty_raises():
    """Req 6.4 — empty entry_points list raises PluginManifestError."""
    with pytest.raises(PluginManifestError):
        PluginManifest(**make_manifest(entry_points=[]))


def test_optional_fields_have_defaults():
    """Optional fields default correctly."""
    m = PluginManifest(**VALID_MANIFEST)
    assert m.tags == []
    assert m.dependencies == []
    assert m.optional_dependencies == []
    assert m.homepage is None
    assert m.license is None
    assert m.min_python is None


# ---------------------------------------------------------------------------
# Property-based test — Req 16 criterion 5
# ---------------------------------------------------------------------------

# Strategy for valid slug names: starts with lowercase letter, followed by
# lowercase letters, digits, hyphens, or underscores.
_slug_strategy = st.from_regex(r"[a-z][a-z0-9_-]{0,30}", fullmatch=True)

# Strategy for valid PEP 440 versions
_version_strategy = st.builds(
    lambda major, minor, patch: f"{major}.{minor}.{patch}",
    major=st.integers(min_value=0, max_value=99),
    minor=st.integers(min_value=0, max_value=99),
    patch=st.integers(min_value=0, max_value=99),
)

# Strategy for valid entry points (non-empty list of .py filenames)
_entry_points_strategy = st.lists(
    st.from_regex(r"[a-z][a-z0-9_]{0,20}\.py", fullmatch=True),
    min_size=1,
    max_size=5,
)


@given(
    name=_slug_strategy,
    version=_version_strategy,
    description=st.text(min_size=1, max_size=100).filter(lambda s: s.strip()),
    author=st.text(min_size=1, max_size=50).filter(lambda s: s.strip()),
    entry_points=_entry_points_strategy,
)
@settings(max_examples=100)
def test_valid_manifest_acceptance_property(
    name: str,
    version: str,
    description: str,
    author: str,
    entry_points: list[str],
) -> None:
    """Req 16 criterion 5 — valid manifest dicts always construct without raising."""
    data = {
        "name": name,
        "version": version,
        "description": description,
        "author": author,
        "platform_version": ">=0.0",
        "entry_points": entry_points,
    }
    m = PluginManifest.model_validate(data)
    assert m.name == name
    assert m.version == version
