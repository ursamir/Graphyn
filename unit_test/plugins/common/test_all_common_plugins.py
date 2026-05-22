# unit_test/plugins/common/test_all_common_plugins.py
"""Bulk registration and metadata tests for all 11 Common plugins.

Covers:
  - Req 8.1–8.11: each plugin registers its node_type
  - Req 8.12: all 11 Common plugins have valid metadata (label, category, version)
"""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager
from app.core.nodes.registry import NodeRegistry

ALL_COMMON_PLUGINS = [
    ("PluginPackage/Common/dataset_builder/", "dataset_builder"),
    ("PluginPackage/Common/trainer/", "trainer"),
    ("PluginPackage/Common/evaluator/", "evaluator"),
    ("PluginPackage/Common/edge_optimizer/", "edge_optimizer"),
    ("PluginPackage/Common/realtime_inference/", "realtime_inference"),
    ("PluginPackage/Common/dataset_balancer/", "dataset_balancer"),
    ("PluginPackage/Common/dataset_versioner/", "dataset_versioner"),
    ("PluginPackage/Common/experiment_tracker/", "experiment_tracker"),
    ("PluginPackage/Common/deployment_packager/", "deployment_packager"),
    ("PluginPackage/Common/embedding_generator/", "embedding_generator"),
    ("PluginPackage/Common/multimodal_fusion/", "multimodal_fusion"),
]


# ── module-scoped fixture: install all 11 plugins once ───────────────────────

@pytest.fixture(scope="module")
def all_common_registry(tmp_path_factory):
    """Install all 11 Common plugins into a single registry once per module."""
    tmp_dir = tmp_path_factory.mktemp("all_common_plugins")
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    for source, _ in ALL_COMMON_PLUGINS:
        mgr._plugins_dir = str(tmp_dir)
        mgr.install(source)
    return reg


# ── Req 8.1–8.11: all 11 node_types present ──────────────────────────────────

@pytest.mark.parametrize("source,node_type", ALL_COMMON_PLUGINS)
def test_each_plugin_registers(source, node_type, all_common_registry):
    """Req 8.1–8.11 — each Common plugin node_type is present in the registry."""
    assert node_type in all_common_registry, (
        f"Expected '{node_type}' to be registered after installing '{source}'"
    )


# ── Req 8.12: valid metadata for all 11 plugins ──────────────────────────────

@pytest.mark.parametrize("source,node_type", ALL_COMMON_PLUGINS)
def test_each_plugin_has_valid_metadata(source, node_type, all_common_registry):
    """Req 8.12 — each Common plugin has non-empty label, category, and version."""
    cls = all_common_registry.get_class(node_type)
    meta = cls.metadata

    assert meta.label, (
        f"'{node_type}' metadata.label is empty"
    )
    assert meta.category, (
        f"'{node_type}' metadata.category is empty"
    )
    assert meta.version, (
        f"'{node_type}' metadata.version is empty"
    )


# ── Req 8.12: exactly 11 Common plugins registered ───────────────────────────

def test_exactly_11_common_plugins_registered(all_common_registry):
    """Req 8.12 — registry contains exactly 11 Common plugin node_types."""
    common_node_types = {node_type for _, node_type in ALL_COMMON_PLUGINS}
    registered_common = {
        node_type for node_type in common_node_types
        if node_type in all_common_registry
    }
    assert len(registered_common) == 11, (
        f"Expected 11 Common plugins registered, got {len(registered_common)}: "
        f"{registered_common}"
    )


# ── individual registration tests (isolated fresh_registry) ──────────────────

@pytest.mark.parametrize("source,node_type", ALL_COMMON_PLUGINS)
def test_each_plugin_registers_in_fresh_registry(source, node_type, tmp_plugin_dir):
    """Each plugin registers correctly in an isolated fresh registry."""
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    # multimodal_fusion depends on EmbeddingVector from embedding_generator
    if node_type == "multimodal_fusion":
        mgr._plugins_dir = str(tmp_plugin_dir)
        mgr.install("PluginPackage/Common/embedding_generator/")
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(source)
    assert node_type in reg, (
        f"'{node_type}' should be registered after installing '{source}'"
    )
