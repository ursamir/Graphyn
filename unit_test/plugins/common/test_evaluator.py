# unit_test/plugins/common/test_evaluator.py
"""Tests for the evaluator plugin.

Covers:
  - Registration (Req 8.3)
  - Metadata (Req 8.12)
  - Isolated stub Config fields
  - process() returns ModelArtifact (no live Keras model, no TF download)
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.core.plugins.manager import PluginManager
from app.core.plugins.venv_manager import PluginVenvManager
from app.models.dataset_artifact import DatasetArtifact
from app.models.model_artifact import ModelArtifact

PLUGIN_SOURCE = "PluginPackage/Common/evaluator/"
NODE_TYPE = "evaluator"

_EVALUATOR_CONFIG_FIELDS = {
    "output_path",
    "plot_confusion_matrix",
    "plot_training_curves",
    "compute_roc",
    "compute_fairness",
    "fairness_attribute_key",
}


def _mock_ensure(plugin_name, requirements, **kwargs):
    return Path("/tmp/fake-venv/bin/python")


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("evaluator_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    with patch.object(PluginVenvManager, "ensure", side_effect=_mock_ensure):
        mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 8.3 — evaluator registers in a fresh registry as isolated."""
    mgr = PluginManager(registry=fresh_registry, base_dir=str(tmp_plugin_dir))
    mgr._plugins_dir = str(tmp_plugin_dir)
    with patch.object(PluginVenvManager, "ensure", side_effect=_mock_ensure):
        mgr.install(PLUGIN_SOURCE)
    assert NODE_TYPE in fresh_registry
    cls = fresh_registry.get_class(NODE_TYPE)
    assert getattr(cls, "_graphyn_isolated", False) is True


# ── metadata ─────────────────────────────────────────────────────────────────

def test_metadata(installed_cls):
    """Req 8.12 — metadata fields are non-empty."""
    meta = installed_cls.metadata
    assert meta.label
    assert meta.category
    assert meta.version


# ── construction / stub Config ───────────────────────────────────────────────

def test_construct(installed_cls):
    node = installed_cls(config={}, seed=0)
    assert node is not None


def test_stub_config_has_evaluator_fields(installed_cls):
    missing = _EVALUATOR_CONFIG_FIELDS - set(installed_cls.Config.model_fields)
    assert not missing, f"isolated evaluator stub missing Config fields: {missing}"
    cfg = installed_cls.Config.model_validate({
        "output_path": "workspace/artifacts/evaluation",
        "plot_confusion_matrix": True,
        "plot_training_curves": False,
        "compute_roc": True,
        "compute_fairness": False,
        "fairness_attribute_key": "speaker_id",
    })
    assert cfg.output_path == "workspace/artifacts/evaluation"
    assert cfg.fairness_attribute_key == "speaker_id"


# ── process() without TensorFlow ──────────────────────────────────────────────

def _load_evaluator_nodes():
    path = Path(__file__).resolve().parents[3] / "PluginPackage/Common/evaluator/nodes.py"
    spec = importlib.util.spec_from_file_location("graphyn_evaluator_nodes_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _fake_sklearn_metrics():
    metrics_mod = types.ModuleType("sklearn.metrics")

    def prfs(*_a, **_k):
        return (
            np.array([1.0, 1.0]),
            np.array([1.0, 1.0]),
            np.array([1.0, 1.0]),
            None,
        )

    def cm(*_a, **_k):
        return np.array([[2, 0], [0, 2]])

    metrics_mod.precision_recall_fscore_support = prfs
    metrics_mod.confusion_matrix = cm
    sklearn_mod = types.ModuleType("sklearn")
    sklearn_mod.metrics = metrics_mod
    return sklearn_mod, metrics_mod


def test_process_returns_model_artifact_not_live_model(tmp_path):
    """EvaluatorNode.process() must return ModelArtifact with pickle-safe metrics."""
    nodes = _load_evaluator_nodes()
    sklearn_mod, metrics_mod = _fake_sklearn_metrics()
    fake_model = MagicMock()
    fake_model.predict.return_value = np.array(
        [[0.9, 0.1], [0.1, 0.9], [0.8, 0.2], [0.2, 0.8]]
    )
    artifact = ModelArtifact(
        model_path=str(tmp_path / "model.keras"),
        labels=["a", "b"],
        history={"loss": [0.5], "val_loss": [0.6], "accuracy": [0.8], "val_accuracy": [0.7]},
    )
    dataset = DatasetArtifact(
        labels=["a", "b"],
        n_classes=2,
        input_shape=(4, 2, 1),
        X_test=np.zeros((4, 4, 2, 1), dtype=np.float32),
        y_test=[0, 1, 0, 1],
    )
    node = nodes.EvaluatorNode(
        config={
            "output_path": str(tmp_path / "eval_out"),
            "plot_confusion_matrix": False,
            "plot_training_curves": False,
            "compute_roc": False,
        },
        seed=0,
    )
    with patch.dict(sys.modules, {"sklearn": sklearn_mod, "sklearn.metrics": metrics_mod}):
        with patch.object(node, "_load_model", return_value=fake_model):
            result = node.process({"model_artifact": artifact, "dataset": dataset})
    out = result["output"]
    assert isinstance(out, ModelArtifact)
    assert isinstance(out.metrics, dict)
    assert "test_accuracy" in out.metrics
    assert not hasattr(out, "predict")
    fake_model.predict.assert_called_once()


def test_plots_degrade_without_matplotlib(tmp_path):
    """Missing matplotlib/seaborn must skip plots, not crash process()."""
    nodes = _load_evaluator_nodes()
    sklearn_mod, metrics_mod = _fake_sklearn_metrics()
    fake_model = MagicMock()
    fake_model.predict.return_value = np.array(
        [[0.9, 0.1], [0.1, 0.9], [0.8, 0.2], [0.2, 0.8]]
    )
    artifact = ModelArtifact(
        model_path=str(tmp_path / "model.keras"),
        labels=["a", "b"],
        history={"loss": [0.1], "val_loss": [0.2], "accuracy": [0.9], "val_accuracy": [0.8]},
    )
    dataset = DatasetArtifact(
        labels=["a", "b"],
        n_classes=2,
        input_shape=(4, 2, 1),
        X_test=np.zeros((4, 4, 2, 1), dtype=np.float32),
        y_test=[0, 1, 0, 1],
    )
    node = nodes.EvaluatorNode(
        config={
            "output_path": str(tmp_path / "eval_out"),
            "plot_confusion_matrix": True,
            "plot_training_curves": True,
            "compute_roc": False,
        },
        seed=0,
    )

    def _boom(*_a, **_k):
        raise ImportError("No module named matplotlib")

    with patch.dict(sys.modules, {"sklearn": sklearn_mod, "sklearn.metrics": metrics_mod}):
        with patch.object(node, "_load_model", return_value=fake_model):
            with patch.object(nodes, "_plot_confusion_matrix", side_effect=_boom):
                with patch.object(nodes, "_plot_training_curves", side_effect=_boom):
                    result = node.process({"model_artifact": artifact, "dataset": dataset})
    assert isinstance(result["output"], ModelArtifact)
    assert (tmp_path / "eval_out" / "metrics.json").is_file()


def test_process_dict_inputs_do_not_attributeerror(tmp_path):
    """Cache/IPC dicts hydrated to artifacts — process() must not hit .model_path on dict."""
    from app.core.plugins.hydrate import coerce_node_inputs

    nodes = _load_evaluator_nodes()
    sklearn_mod, metrics_mod = _fake_sklearn_metrics()
    fake_model = MagicMock()
    fake_model.predict.return_value = np.array(
        [[0.9, 0.1], [0.1, 0.9], [0.8, 0.2], [0.2, 0.8]]
    )
    artifact_dict = {
        "model_path": str(tmp_path / "model.keras"),
        "labels": ["a", "b"],
        "history": {"loss": [0.5]},
        "metrics": {},
    }
    dataset_dict = {
        "labels": ["a", "b"],
        "n_classes": 2,
        "input_shape": [4, 2, 1],
        "X_test": np.zeros((4, 4, 2, 1), dtype=np.float32).tolist(),
        "y_test": [0, 1, 0, 1],
    }
    hydrated = coerce_node_inputs(
        {"model_artifact": artifact_dict, "dataset": dataset_dict},
        nodes.EvaluatorNode,
    )
    assert isinstance(hydrated["model_artifact"], ModelArtifact)
    assert isinstance(hydrated["dataset"], DatasetArtifact)
    node = nodes.EvaluatorNode(
        config={
            "output_path": str(tmp_path / "eval_out"),
            "plot_confusion_matrix": False,
            "plot_training_curves": False,
            "compute_roc": False,
        },
        seed=0,
    )
    with patch.dict(sys.modules, {"sklearn": sklearn_mod, "sklearn.metrics": metrics_mod}):
        with patch.object(node, "_load_model", return_value=fake_model):
            result = node.process(hydrated)
    assert isinstance(result["output"], ModelArtifact)
    assert "test_accuracy" in result["output"].metrics
