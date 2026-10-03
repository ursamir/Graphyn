"""UX overhaul — labels.txt next to every model artifact + human display names.

* trainer writes labels.txt next to model.keras, inside saved_model/ and next
  to checkpoints/best.keras; evaluator re-asserts it beside the model and
  writes one next to metrics.json; edge_optimizer writes it next to
  model.tflite / model.onnx. All use the model's class-index order
  (= dataset_builder's sorted labels), never a hand-typed order.
* Output metadata carries ``labels`` and ``display_name`` (ModelArtifact:
  ``metrics``; DeploymentArtifact: ``metadata``). File names stay unique
  (compiled_<uuid>.keras); the UI shows the display name.

TensorFlow-backed checks are ``heavy`` (GRAPHYN_RUN_HEAVY=1).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from app.core.nodes.discovery import AutoDiscovery
from app.core.nodes.registry import NodeRegistry
from app.models.feature_array import FeatureArray
from app.models.model_artifact import ModelArtifact

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "PluginPackage"
# dataset_builder sorts labels → this is the model's class-index order.
MODEL_ORDER = ["down", "go", "no", "stop", "up", "yes"]
# The order users type (old Ship default) — must NOT be what we write.
TYPED_ORDER = ["yes", "no", "up", "down", "go", "stop"]


def _load(plugin: str, node_type: str):
    reg = NodeRegistry()
    disc = AutoDiscovery(reg)
    for entry in ("types.py", "nodes.py"):
        path = PKG / plugin / entry
        if path.is_file():
            disc._process_module(disc._import_file(path, package_prefix=None))
    return reg.get_class(node_type)


def _mod(plugin: str, node_type: str):
    return sys.modules[_load(plugin, node_type).__module__]


def _read_labels(directory: Path) -> list[str]:
    return (Path(directory) / "labels.txt").read_text(encoding="utf-8").split("\n")


# ── pure helpers (no TensorFlow) ─────────────────────────────────────────────


def test_architecture_display_names():
    m = _mod("Common/trainer", "trainer")
    assert m.architecture_display_name("ds_cnn") == "DS-CNN"
    assert m.architecture_display_name("simple_cnn") == "CNN-small"
    assert m.architecture_display_name("mobilenet") == "MobileNetV2"
    assert m.architecture_display_name("custom") == "Custom model"
    assert m.architecture_display_name(None) == "Model"


def test_trained_display_name():
    m = _mod("Common/trainer", "trainer")
    assert m.trained_display_name("DS-CNN", 30, 30) == "DS-CNN (30 epochs)"
    assert m.trained_display_name("CNN-small", 5, 5) == "CNN-small (5 epochs)"
    assert m.trained_display_name("DS-CNN", 21, 50) == "DS-CNN (21 of 50 epochs)"
    assert m.trained_display_name(None, 1, 1) == "Model (1 epoch)"


def test_write_labels_txt(tmp_path):
    m = _mod("Common/trainer", "trainer")
    assert m.write_labels_txt(tmp_path, MODEL_ORDER) == str(tmp_path / "labels.txt")
    assert _read_labels(tmp_path) == MODEL_ORDER
    assert m.write_labels_txt(tmp_path / "missing", MODEL_ORDER) is None, "never creates dirs"
    assert m.write_labels_txt(tmp_path, []) is None


def test_model_builder_display_name_without_tf():
    cls = _load("Common/trainer", "model_builder")
    assert cls(config={"architecture": "simple_cnn"})._display_name() == "CNN-small"
    assert cls(config={})._display_name() == "DS-CNN"


def test_trainer_upstream_display_name():
    cls = _load("Common/trainer", "trainer")
    art = ModelArtifact(model_path="x.keras", metrics={"display_name": "DS-CNN", "architecture": "ds_cnn"})
    assert cls._upstream_display_name(art) == "DS-CNN"
    assert cls._upstream_display_name(ModelArtifact(metrics={"architecture": "simple_cnn"})) == "CNN-small"
    assert cls._upstream_display_name(ModelArtifact()) is None


def test_edge_optimizer_labels_fallback_and_display(tmp_path):
    m = _mod("Common/edge_optimizer", "edge_optimizer")
    (tmp_path / "saved_model").mkdir()
    (tmp_path / "saved_model" / "labels.txt").write_text("\n".join(MODEL_ORDER))
    art = ModelArtifact(model_path=str(tmp_path / "saved_model"), labels=[])
    assert m._artifact_labels(art) == MODEL_ORDER, "falls back to labels.txt beside the model"
    art2 = ModelArtifact(model_path="nowhere", labels=["b", "a"])
    assert m._artifact_labels(art2) == ["b", "a"], "artifact order wins (it is the class-index order)"
    named = ModelArtifact(metrics={"display_name": "DS-CNN (30 epochs)"})
    assert m._export_display_name(named, "tflite", "int8") == "DS-CNN (30 epochs) · TFLite INT8"
    assert m._export_display_name(ModelArtifact(), "onnx", "float32") == "ONNX FP32"


def test_edge_optimizer_tflite_passthrough_writes_labels_and_metadata(tmp_path):
    """Copy path (source already .tflite) needs no TensorFlow."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    src = src_dir / "model.tflite"
    src.write_bytes(b"TFL3" + b"\0" * 64)
    (src_dir / "labels.txt").write_text("\n".join(MODEL_ORDER))
    cls = _load("Common/edge_optimizer", "edge_optimizer")
    out = tmp_path / "out"
    art = ModelArtifact(model_path=str(src), labels=[], metrics={"display_name": "DS-CNN (3 epochs)"})
    dep = cls(config={"output_path": str(out)}).process({"input": art})["output"]
    assert _read_labels(out) == MODEL_ORDER
    assert dep.labels == MODEL_ORDER
    assert dep.metadata["labels"] == MODEL_ORDER
    assert dep.metadata["labels_path"] == str(out / "labels.txt")
    assert dep.metadata["display_name"] == "DS-CNN (3 epochs) · TFLite INT8"


def test_evaluator_writes_labels_beside_model_dirs(tmp_path):
    cls = _load("Common/evaluator", "evaluator")
    saved = tmp_path / "saved_model"
    saved.mkdir()
    keras_file = tmp_path / "model.keras"
    keras_file.write_bytes(b"")
    art = ModelArtifact(model_path=str(saved), metrics={"keras_model_path": str(keras_file)})
    cls._write_model_labels(art, MODEL_ORDER)
    assert _read_labels(saved) == MODEL_ORDER
    assert _read_labels(tmp_path) == MODEL_ORDER


# ── TensorFlow chain (heavy) ─────────────────────────────────────────────────


def _features(n_per_label: int = 12) -> list[FeatureArray]:
    """Fed in the *typed* order to prove the model order comes from sorting."""
    rng = np.random.default_rng(2)
    out = []
    for lbl in TYPED_ORDER:
        k = MODEL_ORDER.index(lbl)
        for i in range(n_per_label):
            x = rng.normal(0, 0.3, (101, 40)).astype(np.float32)
            x[:, :: k + 2] += 2.0
            split = ("train", "train", "train", "train", "val", "test")[i % 6]
            out.append(FeatureArray(data=x, label=lbl, source_path=f"/ds/v1/{split}/{lbl}/{lbl}_{i}.wav", feature_type="mfcc"))
    return out


@pytest.mark.heavy
class TestLabelsAndNamesChain:
    @pytest.fixture(scope="class")
    def chain(self, tmp_path_factory):
        pytest.importorskip("tensorflow")
        out = tmp_path_factory.mktemp("ux_labels")
        ds = _load("Common/dataset_builder", "dataset_builder")(config={}).process({"input": _features()})["output"]
        model = _load("Common/trainer", "model_builder")(
            config={"architecture": "simple_cnn", "filters": 8, "output_path": str(out / "mb")}
        ).process({"input": ds})["output"]
        trained = _load("Common/trainer", "trainer")(
            config={"backend": "keras", "device": "cpu", "epochs": 2, "batch_size": 8, "output_path": str(out / "train")}, seed=3,
        ).process({"model": model, "dataset": ds})["output"]
        evaluated = _load("Common/evaluator", "evaluator")(
            config={"output_path": str(out / "eval"), "plot_confusion_matrix": False, "plot_training_curves": False},
        ).process({"model_artifact": trained, "dataset": ds})["output"]
        tfl = _load("Common/edge_optimizer", "edge_optimizer")(
            config={"quantization": "float32", "operator_fusion": False, "output_path": str(out / "tflite")},
        ).process({"input": evaluated})["output"]
        return {"out": out, "ds": ds, "model": model, "trained": trained, "evaluated": evaluated, "tflite": tfl}

    def test_dataset_order_is_sorted_not_typed(self, chain):
        assert chain["ds"].labels == MODEL_ORDER != TYPED_ORDER

    def test_model_builder_metadata(self, chain):
        m = chain["model"].metrics
        assert m["display_name"] == "CNN-small" and m["architecture"] == "simple_cnn"
        assert m["labels"] == MODEL_ORDER
        assert Path(chain["model"].model_path).name.startswith("compiled_"), "file names stay unique"

    def test_trainer_labels_next_to_every_model_file(self, chain):
        out = chain["out"] / "train"
        for d in (out, out / "saved_model", out / "checkpoints"):
            assert _read_labels(d) == MODEL_ORDER, d
        m = chain["trained"].metrics
        assert m["labels"] == MODEL_ORDER and chain["trained"].labels == MODEL_ORDER
        assert m["display_name"] == "CNN-small (2 epochs)"
        assert m["labels_path"] == str(out / "labels.txt")
        assert m["epochs_run"] == 2

    def test_evaluator_keeps_labels_and_name(self, chain):
        m = chain["evaluated"].metrics
        assert m["labels"] == MODEL_ORDER and m["display_name"] == "CNN-small (2 epochs)"
        assert list(m["per_class"]) == MODEL_ORDER
        assert _read_labels(chain["out"] / "eval") == MODEL_ORDER
        import json

        saved = json.loads((chain["out"] / "eval" / "metrics.json").read_text())
        assert "labels" not in saved and "display_name" not in saved, "metrics.json stays numeric (experiments table)"

    def test_tflite_labels_and_metadata(self, chain):
        dep = chain["tflite"]
        assert _read_labels(chain["out"] / "tflite") == MODEL_ORDER
        assert dep.labels == MODEL_ORDER and dep.metadata["labels"] == MODEL_ORDER
        assert dep.metadata["display_name"] == "CNN-small (2 epochs) · TFLite FP32"
