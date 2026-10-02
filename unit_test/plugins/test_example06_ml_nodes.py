"""Example 06 — ML-side node tests: dataset_builder, model_builder, trainer,
evaluator, edge_optimizer, realtime_inference (PluginPackage/Common).

Pure-numpy tests always run. TensorFlow tests use ``importorskip`` and the
end-to-end train → evaluate → TFLite → infer chain is marked ``heavy``
(run with GRAPHYN_RUN_HEAVY=1).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.core.nodes.discovery import AutoDiscovery
from app.core.nodes.registry import NodeRegistry
from app.models.dataset_artifact import DatasetArtifact
from app.models.feature_array import FeatureArray
from app.models.model_artifact import ModelArtifact

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "PluginPackage" / "Common"


def _load(plugin: str, node_type: str | None = None):
    root = COMMON / plugin
    reg = NodeRegistry()
    disc = AutoDiscovery(reg)
    for entry in ("types.py", "nodes.py"):
        if (root / entry).is_file():
            disc._process_module(disc._import_file(root / entry, package_prefix=None))
    return reg.get_class(node_type or plugin)


LABELS = ["down", "go", "no", "stop", "up", "yes"]


def _features(n_per_label=12, t=101, f=40, with_split_paths=False, seed=0, labels=LABELS):
    """Separable synthetic MFCC-like features.

    Class k carries stripes every (k + 2) feature bands — a texture that a
    GlobalAveragePooling CNN can tell apart (a single bump at a different
    position would be translation-invariant and unlearnable for DS-CNN).
    """
    rng = np.random.default_rng(seed)
    out = []
    for k, lbl in enumerate(labels):
        for i in range(n_per_label):
            x = rng.normal(0, 0.3, (t, f)).astype(np.float32)
            x[:, :: k + 2] += 2.0
            split = ("train", "train", "train", "train", "val", "test")[i % 6]
            path = f"/ds/v1/{split}/{lbl}/{lbl}_{i}.wav" if with_split_paths else f"/raw/{lbl}/{lbl}_{i}.wav"
            out.append(FeatureArray(data=x, label=lbl, source_path=path, feature_type="mfcc",
                                    metadata={"speaker_id": f"spk{i % 3}"}))
    return out


# ── dataset_builder ──────────────────────────────────────────────────────────


class TestDatasetBuilder:
    @pytest.fixture(scope="class")
    def cls(self):
        return _load("dataset_builder")

    def _build(self, cls, feats, **cfg):
        return cls(config=cfg).process({"input": feats})["output"]

    def test_metadata_split_from_paths(self, cls):
        ds = self._build(cls, _features(with_split_paths=True), fixed_length=101)
        assert ds.labels == LABELS and ds.n_classes == 6
        assert ds.X_train.shape == (48, 101, 40, 1)
        assert len(ds.X_val) == 12 and len(ds.X_test) == 12
        assert tuple(ds.input_shape) == (101, 40, 1)
        assert ds.metadata["split_mode"] == "metadata"

    def test_auto_split_ratios_stratified(self, cls):
        ds = self._build(cls, _features(20), split_ratios={"train": 0.5, "val": 0.25, "test": 0.25})
        assert (len(ds.X_train), len(ds.X_val), len(ds.X_test)) == (60, 30, 30)
        assert sorted(np.bincount(ds.y_test).tolist()) == [5] * 6, "stratify keeps classes balanced"
        assert ds.metadata["split_mode"] == "auto"

    def test_auto_split_unstratified_and_unshuffled(self, cls):
        ds = self._build(cls, _features(20), stratify=False, shuffle=False)
        # no shuffle: the test split is the tail of the input order → last label only
        assert set(ds.y_test.tolist()) == {5}

    def test_seed_changes_auto_split(self, cls):
        a = self._build(cls, _features(20), random_seed=1).y_test
        b = self._build(cls, _features(20), random_seed=2).y_test
        assert not np.array_equal(a, b) or True  # labels may coincide; check sources instead
        sa = self._build(cls, _features(20), random_seed=1).metadata["test_metadata"]
        sb = self._build(cls, _features(20), random_seed=2).metadata["test_metadata"]
        assert [m["source_path"] for m in sa] != [m["source_path"] for m in sb]

    def test_train_only_split(self, cls):
        """Regression: val=test=0 crashed train_test_split(test_size=0)."""
        ds = self._build(cls, _features(5), split_ratios={"train": 1.0, "val": 0.0, "test": 0.0})
        assert len(ds.X_train) == 30 and len(ds.X_val) == len(ds.X_test) == 0

    def test_fixed_length_pads_and_truncates(self, cls):
        feats = _features(2, t=80) + _features(2, t=120, seed=1)
        assert self._build(cls, feats, fixed_length=101).X_train.shape[1] == 101
        assert self._build(cls, feats, fixed_length=0).X_train.shape[1] == 120

    def test_test_metadata_feeds_fairness(self, cls):
        ds = self._build(cls, _features(with_split_paths=True))
        assert len(ds.metadata["test_metadata"]) == len(ds.y_test)
        assert {m["speaker_id"] for m in ds.metadata["test_metadata"]} <= {"spk0", "spk1", "spk2"}

    def test_toml_default_split_ratios(self, cls):
        import tomllib

        spec = tomllib.loads((COMMON / "dataset_builder/plugin.toml").read_text())["config_schema"]["dataset_builder"]["split_ratios"]
        assert spec["default"] == cls.Config().split_ratios
        assert set(spec) <= {"type", "title", "default", "description", "widget"}, "stray keys in split_ratios spec"

    def test_empty_split_ratios_uses_default(self, cls):
        assert cls.Config(split_ratios={}).split_ratios == {"train": 0.7, "val": 0.15, "test": 0.15}

    def test_output_format_tensorflow(self, cls):
        pytest.importorskip("tensorflow")
        ds = self._build(cls, _features(3, with_split_paths=True), output_format="tensorflow")
        assert "tf_dataset_train" in ds.metadata

    @pytest.mark.parametrize("bad", [
        {"split_ratios": {"train": 0.5, "val": 0.1, "test": 0.1}},
        {"split_ratios": {"train": 0.7, "dev": 0.3}},
        {"split_ratios": {"train": 1.2, "val": -0.2, "test": 0}},
        {"fixed_length": -1}, {"output_format": "jax"},
    ])
    def test_invalid_config_rejected(self, cls, bad):
        with pytest.raises(Exception):
            cls.Config(**bad)


# ── trainer / model_builder config (no TF needed) ────────────────────────────


class TestTrainerConfig:
    @pytest.fixture(scope="class")
    def trainer(self):
        return _load("trainer", "trainer")

    @pytest.fixture(scope="class")
    def builder(self):
        return _load("trainer", "model_builder")

    @pytest.mark.parametrize("bad", [
        {"epochs": 0}, {"batch_size": 0}, {"patience": -1}, {"learning_rate": 0},
        {"reduce_lr_factor": 1.0}, {"reduce_lr_factor": 0}, {"min_val_accuracy": 1.5},
        {"early_stopping_min_delta": -0.1}, {"device": "tpu"}, {"backend": "jax"},
    ])
    def test_trainer_invalid(self, trainer, bad):
        with pytest.raises(Exception):
            trainer.Config(**bad)

    def test_trainer_learning_rate_defaults_to_model(self, trainer):
        assert trainer.Config().learning_rate is None

    @pytest.mark.parametrize("bad", [
        {"filters": 0}, {"num_layers": -1}, {"dropout_rate": 1.0}, {"learning_rate": 0}, {"architecture": "resnet"},
    ])
    def test_builder_invalid(self, builder, bad):
        with pytest.raises(Exception):
            builder.Config(**bad)

    def test_representative_rows_cover_all_labels(self, trainer):
        """Regression: first-1000 rows of a label-sorted X_train covered 3/6 labels."""
        y = np.repeat(np.arange(6), 1400)          # label-sorted like dataset_builder output
        X = y.astype(np.float32)[:, None]
        rows = trainer._representative_rows(X)
        assert len(rows) == 1000
        assert set(rows[:, 0].astype(int).tolist()) == set(range(6))
        assert len(trainer._representative_rows(X[:500])) == 500

    def test_pytorch_backend_rejects_keras_artifact(self, trainer, tmp_path):
        pytest.importorskip("torch")
        node = trainer(config={"backend": "pytorch", "output_path": str(tmp_path), "epochs": 1})
        ds = TestDatasetBuilder()._build(_load("dataset_builder"), _features(2, with_split_paths=True))
        with pytest.raises(TypeError, match="nn.Module"):
            node.process({"model": ModelArtifact(model_path="m.keras"), "dataset": ds})


# ── TensorFlow-backed tests ──────────────────────────────────────────────────


@pytest.fixture(scope="module")
def tf_mod():
    return pytest.importorskip("tensorflow")


@pytest.fixture(scope="module")
def small_ds():
    cls = _load("dataset_builder")
    return cls(config={}).process({"input": _features(40, t=101, f=40, with_split_paths=True)})["output"]


class TestModelBuilder:
    @pytest.mark.parametrize("arch,n_layers,params", [
        ("ds_cnn", 4, (20_000, 25_000)),   # README: ~22K params
        ("ds_cnn", 1, (5_000, 9_000)),
        ("mobilenet", 1, (50_000, 70_000)),  # MobileNetV2 IR, expansion 6, stem stride 2
        ("simple_cnn", 4, (70_000, 80_000)),  # ignores num_layers
    ])
    def test_architectures(self, tf_mod, small_ds, tmp_path, arch, n_layers, params):
        import keras

        cls = _load("trainer", "model_builder")
        out = cls(config={"architecture": arch, "num_layers": n_layers, "filters": 64, "output_path": str(tmp_path)}).process({"input": small_ds})["output"]
        model = keras.models.load_model(out.model_path)
        assert model.output_shape == (None, 6)
        assert params[0] <= model.count_params() <= params[1]
        assert out.labels == LABELS

    def test_custom_layers_from_preset_export(self, tf_mod, small_ds, tmp_path):
        import importlib.util
        import keras

        arch_path = ROOT / "PluginPackage" / "Common" / "trainer" / "model_architecture.py"
        spec = importlib.util.spec_from_file_location("ma_export", arch_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        layers = mod.export_layer_specs("ds_cnn", filters=32, num_layers=2)
        cls = _load("trainer", "model_builder")
        out = cls(
            config={
                "architecture": "custom",
                "layers": layers,
                "dropout_rate": 0.2,
                "output_path": str(tmp_path),
            }
        ).process({"input": small_ds})["output"]
        model = keras.models.load_model(out.model_path)
        assert model.output_shape == (None, 6)

    def test_custom_without_layers_rejected(self, tf_mod, tmp_path):
        cls = _load("trainer", "model_builder")
        with pytest.raises(Exception, match="layers"):
            cls(config={"architecture": "custom", "layers": [], "output_path": str(tmp_path)})

    def test_learning_rate_and_dropout_compiled(self, tf_mod, small_ds, tmp_path):
        import keras

        cls = _load("trainer", "model_builder")
        out = cls(config={"learning_rate": 0.005, "dropout_rate": 0.4, "output_path": str(tmp_path)}).process({"input": small_ds})["output"]
        model = keras.models.load_model(out.model_path)
        assert float(keras.ops.convert_to_numpy(model.optimizer.learning_rate)) == pytest.approx(0.005)
        assert [l.rate for l in model.layers if l.__class__.__name__ == "Dropout"] == [pytest.approx(0.4)]

    def test_zero_classes_rejected(self, tf_mod, tmp_path):
        cls = _load("trainer", "model_builder")
        with pytest.raises(ValueError, match="0 classes"):
            cls(config={"output_path": str(tmp_path)}).process({"input": DatasetArtifact(labels=[], n_classes=0)})


@pytest.mark.heavy
class TestTrainEvaluateExportInfer:
    """End-to-end on synthetic separable features — mirrors pipeline_train_ml + pipeline_infer."""

    @pytest.fixture(scope="class")
    def chain(self, tf_mod, small_ds, tmp_path_factory):
        out = tmp_path_factory.mktemp("e06chain")
        builder = _load("trainer", "model_builder")
        model = builder(config={"filters": 16, "num_layers": 2, "output_path": str(out / "models"), "learning_rate": 0.01}).process({"input": small_ds})["output"]
        trainer = _load("trainer", "trainer")
        trained = trainer(config={"backend": "keras", "device": "cpu", "epochs": 30, "batch_size": 8, "patience": 5, "output_path": str(out)}, seed=42).process({"model": model, "dataset": small_ds})["output"]
        evaluator = _load("evaluator")
        evaluated = evaluator(config={"output_path": str(out), "compute_fairness": True}).process({"model_artifact": trained, "dataset": small_ds})["output"]
        return {"out": out, "model": model, "trained": trained, "evaluated": evaluated}

    def test_trainer_outputs(self, chain):
        out, trained = chain["out"], chain["trained"]
        assert (out / "model.keras").is_file() and (out / "checkpoints/best.keras").is_file()
        assert (out / "saved_model/saved_model.pb").is_file()
        assert Path(trained.model_path) == out / "saved_model"
        assert set(trained.history) >= {"loss", "val_loss", "accuracy", "val_accuracy"}
        assert 1 <= len(trained.history["loss"]) <= 30
        # trainer.learning_rate unset → model_builder.learning_rate (0.01) is kept
        assert trained.history["learning_rate"][0] == pytest.approx(0.01)

    def test_representative_data_saved(self, chain, small_ds):
        repr_x = np.load(chain["out"] / "saved_model/X_train_repr.npy")
        assert repr_x.shape == small_ds.X_train.shape  # < 1000 rows: saved in full

    def test_evaluator_metrics(self, chain):
        m = chain["evaluated"].metrics
        assert m["test_accuracy"] >= 0.8, m["test_accuracy"]
        assert set(m["per_class"]) == set(LABELS)
        assert np.array(m["confusion_matrix"]).shape == (6, 6)
        assert 0.5 <= m["roc_auc"] <= 1.0
        assert set(m["fairness"]) <= {"spk0", "spk1", "spk2"} and m["fairness"]
        assert m["keras_model_path"].endswith("model.keras"), "upstream hand-off path must survive evaluation"
        saved = json.loads((chain["out"] / "metrics.json").read_text())
        assert saved["test_accuracy"] == m["test_accuracy"]
        for png in ("confusion_matrix.png", "training_curves.png", "roc_curves.png"):
            assert (chain["out"] / png).is_file(), png

    def test_evaluator_plot_toggles(self, chain, small_ds, tmp_path):
        ev = _load("evaluator")
        m = ev(config={"output_path": str(tmp_path), "plot_confusion_matrix": False, "plot_training_curves": False, "compute_roc": False}).process(
            {"model_artifact": chain["trained"], "dataset": small_ds})["output"].metrics
        assert "roc_auc" not in m
        assert not any((tmp_path / p).exists() for p in ("confusion_matrix.png", "training_curves.png", "roc_curves.png"))

    @pytest.mark.parametrize("quant,fusion,in_dtype,label", [
        ("int8", True, np.uint8, "int8"),
        ("float16", True, np.float32, "float16"),
        ("float32", False, np.float32, "float32"),
        ("float32", True, np.float32, "dynamic_range"),
    ])
    def test_edge_optimizer_quantization(self, chain, tmp_path, quant, fusion, in_dtype, label, tf_mod):
        eo = _load("edge_optimizer")
        dep = eo(config={"backend": "tflite", "quantization": quant, "operator_fusion": fusion, "output_path": str(tmp_path), "representative_samples": 20}).process({"input": chain["evaluated"]})["output"]
        assert Path(dep.artifact_path).is_file() and dep.model_format == "tflite"
        assert dep.quantization == label
        assert (tmp_path / "labels.txt").read_text().split("\n") == LABELS
        interp = tf_mod.lite.Interpreter(model_path=dep.artifact_path)
        assert interp.get_input_details()[0]["dtype"] == in_dtype
        assert list(interp.get_input_details()[0]["shape"]) == [1, 101, 40, 1]

    def test_edge_optimizer_stub_backend(self, chain, tmp_path):
        eo = _load("edge_optimizer")
        dep = eo(config={"backend": "tflm", "output_path": str(tmp_path)}).process({"input": chain["evaluated"]})["output"]
        assert dep.metadata.get("stub") is True

    @pytest.fixture(scope="class")
    def int8_model(self, chain, tmp_path_factory):
        d = tmp_path_factory.mktemp("tflite")
        eo = _load("edge_optimizer")
        return eo(config={"output_path": str(d)}).process({"input": chain["evaluated"]})["output"].artifact_path

    def _infer(self, model_path, feats, **cfg):
        ri = _load("realtime_inference")
        node = ri(config={"model_path": model_path, **cfg}, seed=7)
        node.setup()
        try:
            return node.process({"input": feats})["output"]
        finally:
            node.teardown()

    def test_infer_int8_classification_accuracy(self, int8_model, small_ds):
        feats = [f for f in _features(4, seed=99)]
        preds = self._infer(int8_model, feats)
        acc = np.mean([p.predicted_label == p.metadata["true_label"] for p in preds])
        assert len(preds) == len(feats) and acc >= 0.8, acc
        assert all(0 <= p.metadata["confidence"] <= 1 for p in preds)
        assert all(abs(sum(p.probabilities.values()) - 1.0) < 0.05 for p in preds)

    def test_infer_pads_short_features_to_model_length(self, int8_model):
        """FeatureArrays shorter than the model's 101 frames are zero-padded (was a set_tensor crash)."""
        preds = self._infer(int8_model, _features(1, t=60, seed=5))
        assert len(preds) == 6

    @pytest.mark.parametrize("threshold,expect", [(0.0, "wake_word_detected"), (1.0, "no_wake_word")])
    def test_wake_word_threshold(self, int8_model, threshold, expect):
        preds = self._infer(int8_model, _features(1, seed=3), mode="wake_word", wake_word_threshold=threshold)
        assert {p.predicted_label for p in preds} == {expect}

    def test_streaming_asr_aggregates(self, int8_model):
        preds = self._infer(int8_model, _features(2, seed=4), mode="streaming_asr", streaming_buffer_size=4)
        assert len(preds) == 3 and all(p.metadata["frames_aggregated"] == 4 for p in preds)

    @pytest.mark.parametrize("ratio,expect", [(0.0, 12), (1.0, 0)])
    def test_adaptive_skip(self, int8_model, ratio, expect):
        assert len(self._infer(int8_model, _features(2, seed=6), adaptive=True, adaptive_skip_ratio=ratio)) == expect

    def test_tflm_host_backend_uses_tflite_interpreter(self, int8_model):
        """Regression: tflm_host set up a TFLite interpreter but dispatched to the ONNX path."""
        assert len(self._infer(int8_model, _features(1, seed=8), backend="tflm_host")) == 6

    def test_missing_model_and_labels(self, tmp_path):
        ri = _load("realtime_inference")
        with pytest.raises(FileNotFoundError):
            ri(config={"model_path": str(tmp_path / "nope.tflite")}).setup()
        (tmp_path / "m.tflite").write_bytes(b"x")
        with pytest.raises(FileNotFoundError, match="labels.txt"):
            ri(config={"model_path": str(tmp_path / "m.tflite")}).setup()


@pytest.mark.parametrize("bad", [
    {"wake_word_threshold": 1.5}, {"batch_size": 0}, {"adaptive_skip_ratio": -0.1},
    {"streaming_buffer_size": 0}, {"mode": "asr"},
])
def test_realtime_inference_invalid_config(bad):
    with pytest.raises(Exception):
        _load("realtime_inference").Config(**bad)


@pytest.mark.parametrize("bad", [{"representative_samples": 0}, {"quantization": "int4"}, {"backend": "coreml"}])
def test_edge_optimizer_invalid_config(bad):
    with pytest.raises(Exception):
        _load("edge_optimizer").Config(**bad)
