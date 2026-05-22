# unit_test/plugins/common/test_experiment_tracker.py
"""Tests for the experiment_tracker plugin.

Covers:
  - Registration (Req 8.8)
  - Metadata (Req 8.12)
  - Construction and smoke process
  - Req 10.7: artifact creation — non-empty run_id
"""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/experiment_tracker/"
NODE_TYPE = "experiment_tracker"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("experiment_tracker_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 8.8 — experiment_tracker registers in a fresh registry."""
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

def test_process_smoke(installed_cls, tmp_path):
    from app.models.model_artifact import ModelArtifact
    artifact = ModelArtifact(
        model_path="/fake/model",
        labels=["a", "b"],
        history={"loss": [0.5], "val_loss": [0.4]},
        metrics={"test_accuracy": 0.9},
    )
    node = installed_cls(
        config={
            "backend": "json",
            "output_dir": str(tmp_path / "runs"),
        },
        seed=0,
    )
    result = node.process({"input": artifact})
    assert result is not None


# ── Req 10.7: artifact creation — non-empty run_id ───────────────────────────

def test_run_id_non_empty(installed_cls, tmp_path):
    """Req 10.7 — ExperimentTrackerNode produces ExperimentArtifact with non-empty run_id."""
    from app.models.model_artifact import ModelArtifact
    artifact = ModelArtifact(
        model_path="/fake/model",
        labels=["a", "b"],
        history={"loss": [0.5]},
        metrics={"test_accuracy": 0.85},
    )
    node = installed_cls(
        config={"backend": "json", "output_dir": str(tmp_path / "runs")},
        seed=0,
    )
    result = node.process({"input": artifact})["output"]
    assert result.run_id, (
        f"ExperimentArtifact.run_id should be non-empty, got {result.run_id!r}"
    )


def test_run_id_unique_per_call(installed_cls, tmp_path):
    """Each call to process() should produce a unique run_id."""
    from app.models.model_artifact import ModelArtifact
    artifact = ModelArtifact(model_path="/fake/model", labels=["a"])

    node = installed_cls(
        config={"backend": "json", "output_dir": str(tmp_path / "runs")},
        seed=0,
    )
    result1 = node.process({"input": artifact})["output"]
    result2 = node.process({"input": artifact})["output"]

    assert result1.run_id != result2.run_id, (
        "Each process() call should produce a unique run_id"
    )


def test_experiment_name_propagated(installed_cls, tmp_path):
    """experiment_name config is reflected in the output artifact."""
    from app.models.model_artifact import ModelArtifact
    artifact = ModelArtifact(model_path="/fake/model", labels=["a"])

    node = installed_cls(
        config={
            "backend": "json",
            "experiment_name": "my_experiment",
            "output_dir": str(tmp_path / "runs"),
        },
        seed=0,
    )
    result = node.process({"input": artifact})["output"]
    assert result.experiment_name == "my_experiment"
