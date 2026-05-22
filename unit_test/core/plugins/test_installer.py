# unit_test/core/plugins/test_installer.py
"""Tests for PluginInstaller checksum verification (Req 6)."""
from __future__ import annotations

import hashlib

import pytest

from app.core.plugins.installer import PluginInstaller
from app.core.plugins.errors import PluginInstallError


def test_correct_checksum_passes() -> None:
    """Correct sha256 checksum does not raise."""
    installer = PluginInstaller()
    data = b"hello plugin world"
    digest = hashlib.sha256(data).hexdigest()
    checksum = f"sha256:{digest}"
    # Should not raise
    installer._verify_checksum(data, checksum)


def test_wrong_checksum_raises() -> None:
    """Wrong sha256 checksum raises PluginInstallError."""
    installer = PluginInstaller()
    data = b"hello plugin world"
    wrong_checksum = "sha256:" + "a" * 64  # all-'a' hex digest
    with pytest.raises(PluginInstallError) as exc_info:
        installer._verify_checksum(data, wrong_checksum)
    assert "Checksum mismatch" in str(exc_info.value)


def test_unsupported_checksum_format_raises() -> None:
    """Non-sha256 checksum format raises PluginInstallError."""
    installer = PluginInstaller()
    data = b"some data"
    with pytest.raises(PluginInstallError) as exc_info:
        installer._verify_checksum(data, "md5:abc123")
    assert "Unsupported checksum format" in str(exc_info.value)


def test_parse_name_version_plain_name() -> None:
    """Plain name returns (name, None)."""
    installer = PluginInstaller()
    name, ver = installer._parse_name_version("my-plugin")
    assert name == "my-plugin"
    assert ver is None


def test_parse_name_version_with_eq() -> None:
    """name==1.0.0 returns (name, '==1.0.0')."""
    installer = PluginInstaller()
    name, ver = installer._parse_name_version("my-plugin==1.0.0")
    assert name == "my-plugin"
    assert ver == "==1.0.0"


def test_parse_name_version_with_gte() -> None:
    """name>=1.0 returns (name, '>=1.0')."""
    installer = PluginInstaller()
    name, ver = installer._parse_name_version("my-plugin>=1.0")
    assert name == "my-plugin"
    assert ver == ">=1.0"
