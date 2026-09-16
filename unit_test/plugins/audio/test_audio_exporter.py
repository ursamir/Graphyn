# unit_test/plugins/audio/test_audio_exporter.py
"""Tests for the audio_exporter plugin.

Covers:
  - Registration (Req 7.19)
  - Metadata (Req 7.19)
  - Construction
"""
from __future__ import annotations
from unit_test.plugins._helpers import materialize_isolated_class

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Audio/audio_exporter/"
NODE_TYPE = "audio_exporter"


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("audio_exporter_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return materialize_isolated_class(reg.get_class(NODE_TYPE))


def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 7.19 — audio_exporter registers in a fresh registry."""
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_plugin_dir))
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(PLUGIN_SOURCE)
    assert NODE_TYPE in fresh_registry


def test_metadata(installed_cls):
    """Req 7.19 — metadata fields are non-empty."""
    meta = installed_cls.metadata
    assert meta.label
    assert meta.category
    assert meta.version


def test_construct(installed_cls):
    node = installed_cls(config={}, seed=0)
    assert node is not None
