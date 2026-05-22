# unit_test/plugins/common/test_deployment_packager.py
"""Tests for the deployment_packager plugin.

Covers:
  - Registration (Req 8.9)
  - Metadata (Req 8.12)
  - Construction and smoke process
"""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/deployment_packager/"
NODE_TYPE = "deployment_packager"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("deployment_packager_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 8.9 — deployment_packager registers in a fresh registry."""
    mgr = PluginManager(registry=fresh_registry)
    mgr._plugins_dir = str(tmp_plugin_dir)
    mgr.install(PLUGIN_SOURCE)
    assert NODE_TYPE in fresh_registry


# ── metadata ─────────────────────────────────────────────────────────────────

def test_metadata(installed_cls):
    """Req 8.12 — metadata fields are non-empty."""
    meta = installed_cls.metadata
    assert meta.label
    assert meta.category
    assert meta.version


# ── construction ─────────────────────────────────────────────────────────────

def test_construct(installed_cls):
    node = installed_cls(config={}, seed=0)
    assert node is not None


# ── smoke process ─────────────────────────────────────────────────────────────

def test_process_smoke_mobile(installed_cls, tmp_path):
    """Smoke test: DeploymentPackagerNode.process() with mobile target."""
    from app.models.deployment_artifact import DeploymentArtifact

    artifact = DeploymentArtifact(
        artifact_path="",  # no real model file — packager handles missing gracefully
        model_format="tflite",
        target_hardware="cpu",
        quantization="float32",
        labels=["a", "b"],
    )

    node = installed_cls(
        config={
            "target": "mobile",
            "output_path": str(tmp_path / "packages"),
        },
        seed=0,
    )
    result = node.process({"input": artifact})
    assert result is not None


def test_process_smoke_edge(installed_cls, tmp_path):
    """Smoke test: DeploymentPackagerNode.process() with edge target."""
    from app.models.deployment_artifact import DeploymentArtifact

    artifact = DeploymentArtifact(
        artifact_path="",
        model_format="tflite",
        labels=["a", "b"],
    )

    node = installed_cls(
        config={
            "target": "edge",
            "output_path": str(tmp_path / "packages_edge"),
        },
        seed=0,
    )
    result = node.process({"input": artifact})
    assert result is not None


def test_output_artifact_path_set(installed_cls, tmp_path):
    """Output DeploymentArtifact should have artifact_path pointing to the package."""
    from app.models.deployment_artifact import DeploymentArtifact

    artifact = DeploymentArtifact(
        artifact_path="",
        model_format="tflite",
        labels=["a", "b"],
    )

    node = installed_cls(
        config={
            "target": "mobile",
            "output_path": str(tmp_path / "packages_check"),
        },
        seed=0,
    )
    result = node.process({"input": artifact})["output"]
    assert result.artifact_path, "Output artifact_path should be non-empty"
