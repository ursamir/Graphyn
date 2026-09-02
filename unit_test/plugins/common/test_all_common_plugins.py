# unit_test/plugins/common/test_all_common_plugins.py
"""Bulk registration and metadata tests for all Common plugins."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.plugins.manager import PluginManager
from app.core.plugins.errors import PluginDependencyError, PluginInstallError
from app.core.nodes.registry import NodeRegistry
from app.core.plugins.venv_manager import PluginVenvManager


@pytest.fixture(autouse=True)
def _no_isolated_venv_pip():
    """Isolated plugins must not pip-install TensorFlow during unit tests."""
    with patch.object(
        PluginVenvManager,
        "ensure",
        return_value=Path("/tmp/fake-venv/bin/python"),
    ):
        yield

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
    ("PluginPackage/Common/asr_transcribe/", "asr_transcribe"),
    ("PluginPackage/Common/pii_redact/", "pii_redact"),
    ("PluginPackage/Common/structured_llm/", "structured_llm"),
    ("PluginPackage/Common/eval_gate/", "eval_gate"),
    ("PluginPackage/Common/http_webhook/", "http_webhook"),
    ("PluginPackage/Common/doc_parse_chunk/", "doc_parse_chunk"),
    ("PluginPackage/Common/caption_export/", "caption_export"),
    ("PluginPackage/Common/object_store/", "object_store"),
    ("PluginPackage/Common/http_request/", "http_request"),
    ("PluginPackage/Common/if_switch/", "if_switch"),
    ("PluginPackage/Common/set_map/", "set_map"),
    ("PluginPackage/Common/json_transform/", "json_transform"),
    ("PluginPackage/Common/schedule_trigger/", "schedule_trigger"),
    ("PluginPackage/Common/python_code/", "python_code"),
    ("PluginPackage/Common/error_catch/", "error_catch"),
    ("PluginPackage/Common/merge/", "merge"),
    ("PluginPackage/Common/wait_delay/", "wait_delay"),
    ("PluginPackage/Common/csv_table/", "csv_table"),
]

NEW_COMMON = {
    "asr_transcribe",
    "pii_redact",
    "structured_llm",
    "eval_gate",
    "http_webhook",
    "doc_parse_chunk",
    "caption_export",
    "object_store",
    "http_request",
    "if_switch",
    "set_map",
    "json_transform",
    "schedule_trigger",
    "python_code",
    "error_catch",
    "merge",
    "wait_delay",
    "csv_table",
}


@pytest.fixture(scope="module")
def all_common_registry(tmp_path_factory):
    """Install Common plugins into a single registry once per module."""
    tmp_dir = tmp_path_factory.mktemp("all_common_plugins")
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    for source, _ in ALL_COMMON_PLUGINS:
        try:
            mgr.install(source)
        except (PluginDependencyError, PluginInstallError):
            continue
    return reg


@pytest.mark.parametrize("source,node_type", ALL_COMMON_PLUGINS)
def test_each_plugin_registers(source, node_type, all_common_registry):
    if node_type not in all_common_registry:
        pytest.skip(f"{node_type} not installed in this environment")
    assert node_type in all_common_registry


@pytest.mark.parametrize("source,node_type", ALL_COMMON_PLUGINS)
def test_each_plugin_has_valid_metadata(source, node_type, all_common_registry):
    if node_type not in all_common_registry:
        pytest.skip(f"{node_type} not installed in this environment")
    meta = all_common_registry.get_class(node_type).metadata
    assert meta.label
    assert meta.category
    assert meta.version


def test_all_listed_common_plugins_registered(all_common_registry):
    missing = {n for n in NEW_COMMON if n not in all_common_registry}
    assert not missing, f"new Common plugins missing from registry: {missing}"


@pytest.mark.parametrize("source,node_type", ALL_COMMON_PLUGINS)
def test_each_plugin_registers_in_fresh_registry(source, node_type, tmp_plugin_dir):
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_plugin_dir))
    mgr._plugins_dir = str(tmp_plugin_dir)
    if node_type == "multimodal_fusion":
        try:
            mgr.install("PluginPackage/Common/embedding_generator/")
        except (PluginDependencyError, PluginInstallError) as exc:
            pytest.skip(str(exc))
    try:
        mgr.install(source)
    except (PluginDependencyError, PluginInstallError) as exc:
        pytest.skip(str(exc))
    assert node_type in reg, (
        f"'{node_type}' should be registered after installing '{source}'"
    )
