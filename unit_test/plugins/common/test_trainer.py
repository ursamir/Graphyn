# unit_test/plugins/common/test_trainer.py
"""Tests for the trainer plugin.

Covers:
  - Registration (Req 8.2)
  - Metadata (Req 8.12)
  - Construction and smoke process
"""
from __future__ import annotations

import pytest

from app.core.plugins.manager import PluginManager

PLUGIN_SOURCE = "PluginPackage/Common/trainer/"
NODE_TYPE = "trainer"


# ── module-scoped install ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("trainer_plugins")
    from app.core.nodes.registry import NodeRegistry
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg)
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return reg.get_class(NODE_TYPE)


# ── registration ──────────────────────────────────────────────────────────────

def test_registers(tmp_plugin_dir, fresh_registry):
    """Req 8.2 — trainer registers in a fresh registry."""
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
    """Smoke test: TrainerNode.process() with a minimal Keras model and dataset."""
    keras = pytest.importorskip("keras")
    import numpy as np

    # Build a tiny Keras model
    model = keras.Sequential([
        keras.layers.Input(shape=(4, 2, 1)),
        keras.layers.Flatten(),
        keras.layers.Dense(4, activation="relu"),
        keras.layers.Dense(2, activation="softmax"),
    ])
    model.compile(optimizer="adam", loss="sparse_categorical_crossentropy", metrics=["accuracy"])

    # Build a minimal DatasetArtifact-like object
    class _FakeDataset:
        X_train = np.zeros((4, 4, 2, 1), dtype=np.float32)
        y_train = np.array([0, 1, 0, 1], dtype=np.int32)
        X_val = np.zeros((2, 4, 2, 1), dtype=np.float32)
        y_val = np.array([0, 1], dtype=np.int32)
        labels = ["a", "b"]

    node = installed_cls(
        config={
            "backend": "keras",
            "epochs": 1,
            "batch_size": 2,
            "output_path": str(tmp_path / "trainer_out"),
        },
        seed=0,
    )
    result = node.process({"model": model, "dataset": _FakeDataset()})
    assert "output" in result


# ── ModelArtifact isolated path (no TensorFlow download) ─────────────────────

import importlib.util
from pathlib import Path as _Path
from unittest.mock import MagicMock, patch

from app.models.dataset_artifact import DatasetArtifact
from app.models.model_artifact import ModelArtifact


def _load_trainer_nodes():
    path = _Path(__file__).resolve().parents[3] / "PluginPackage/Common/trainer/nodes.py"
    spec = importlib.util.spec_from_file_location("graphyn_trainer_nodes_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_model_builder_returns_model_artifact(tmp_path):
    """ModelBuilderNode must save on disk and return ModelArtifact, not a live keras Model."""
    nodes = _load_trainer_nodes()
    fake_model = MagicMock()

    def _save(path):
        _Path(path).write_bytes(b"fake-keras")

    fake_model.save.side_effect = _save
    dataset = DatasetArtifact(
        labels=["yes", "no"],
        n_classes=2,
        input_shape=(4, 4, 1),
    )
    node = nodes.ModelBuilderNode(
        config={"output_path": str(tmp_path / "models"), "backend": "keras"},
        seed=0,
    )
    with patch.object(node, "_build_keras_model", return_value=fake_model):
        result = node.process({"input": dataset})
    art = result["output"]
    assert isinstance(art, ModelArtifact)
    saved = _Path(art.model_path)
    assert saved.exists()
    assert saved.suffix == ".keras"
    assert art.labels == ["yes", "no"]
    fake_model.save.assert_called_once()


def test_model_builder_unique_filenames(tmp_path):
    nodes = _load_trainer_nodes()
    dataset = DatasetArtifact(labels=["a"], n_classes=1, input_shape=(2, 2, 1))

    def _make():
        fake = MagicMock()
        fake.save.side_effect = lambda path: _Path(path).write_bytes(b"x")
        node = nodes.ModelBuilderNode(
            config={"output_path": str(tmp_path), "backend": "keras"},
            seed=0,
        )
        with patch.object(node, "_build_keras_model", return_value=fake):
            return node.process({"input": dataset})["output"].model_path

    a, b = _make(), _make()
    assert a != b
    assert _Path(a).exists() and _Path(b).exists()


def test_trainer_loads_model_artifact(tmp_path):
    """TrainerNode must load keras.Model from ModelArtifact.model_path."""
    nodes = _load_trainer_nodes()
    compiled = tmp_path / "compiled.keras"
    compiled.write_bytes(b"weights")
    artifact = ModelArtifact(model_path=str(compiled), labels=["a", "b"])
    loaded = object()
    trained = ModelArtifact(model_path=str(tmp_path / "trained"), labels=["a", "b"])
    node = nodes.TrainerNode(
        config={"backend": "keras", "output_path": str(tmp_path / "out"), "epochs": 1},
        seed=0,
    )
    fake_keras = MagicMock()
    fake_keras.models.load_model.return_value = loaded
    with patch.dict("sys.modules", {"keras": fake_keras, "keras.models": fake_keras.models}):
        with patch.object(node, "_train_keras", return_value=trained) as train:
            result = node.process({"model": artifact, "dataset": DatasetArtifact(labels=["a", "b"], n_classes=2)})
    fake_keras.models.load_model.assert_called_with(str(compiled))
    assert train.call_args[0][0] is loaded
    assert result["output"] is trained


def test_keras_model_from_input_passthrough_live_model():
    nodes = _load_trainer_nodes()

    class _Live:
        def fit(self, *a, **k):
            return None

    live = _Live()
    assert nodes.TrainerNode._keras_model_from_input(live) is live
