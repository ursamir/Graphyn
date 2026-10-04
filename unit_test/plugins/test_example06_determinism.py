"""Example 06 — same graph + seed must give the same model.

Live runs with an identical graph hash and seed 42 gave 71.1 % vs 75.6 % test
accuracy: model_builder never seeded TF (different initial weights every run)
and GPU kernels were non-deterministic. These tests pin the fixes.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.models.feature_array import FeatureArray

from unit_test.plugins.test_example06_ml_nodes import _features, _load


# ── dataset_builder (no TF) ──────────────────────────────────────────────────


@pytest.fixture(scope="module")
def builder_cls():
    return _load("dataset_builder")


def test_auto_split_independent_of_input_order(builder_cls) -> None:
    feats = _features(10)
    rev = list(reversed(feats))
    a = builder_cls(config={"random_seed": 3}).process({"input": feats})["output"]
    b = builder_cls(config={"random_seed": 3}).process({"input": rev})["output"]
    np.testing.assert_array_equal(a.X_train, b.X_train)
    np.testing.assert_array_equal(a.y_test, b.y_test)


def test_infer_split_uses_nearest_segment(builder_cls) -> None:
    node = builder_cls(config={})
    f = FeatureArray(
        data=np.zeros((2, 2), np.float32), label="yes",
        source_path="/data/test/v1/train/yes/a.wav", feature_type="mfcc",
    )
    # Deterministic regardless of PYTHONHASHSEED (was a set iteration).
    assert node._infer_split(f) == "train"
    g = FeatureArray(
        data=np.zeros((2, 2), np.float32), label="yes",
        source_path="C:\\ds\\val\\yes\\b.wav", feature_type="mfcc",
    )
    assert node._infer_split(g) == "val"


# ── model_builder / trainer (TF) ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def tf_mod():
    return pytest.importorskip("tensorflow")


@pytest.fixture(scope="module")
def tiny_ds(builder_cls):
    return builder_cls(config={}).process(
        {"input": _features(6, t=24, f=12, with_split_paths=True)}
    )["output"]


def _build_weights(tmp_path, ds, seed):
    import keras

    cls = _load("trainer", "model_builder")
    out = cls(
        config={"filters": 8, "num_layers": 1, "output_path": str(tmp_path)}, seed=seed
    ).process({"input": ds})["output"]
    return out, keras.models.load_model(out.model_path).get_weights()


def test_model_builder_initial_weights_follow_seed(tf_mod, tiny_ds, tmp_path) -> None:
    _, w1 = _build_weights(tmp_path / "a", tiny_ds, 7)
    _, w2 = _build_weights(tmp_path / "b", tiny_ds, 7)
    _, w3 = _build_weights(tmp_path / "c", tiny_ds, 8)
    assert all(np.array_equal(a, b) for a, b in zip(w1, w2))
    assert not all(np.array_equal(a, c) for a, c in zip(w1, w3))


def test_trainer_same_seed_same_weights(tf_mod, tiny_ds, tmp_path) -> None:
    import keras

    trainer = _load("trainer", "trainer")

    def run(tag):
        model, _ = _build_weights(tmp_path / f"m{tag}", tiny_ds, 11)
        out = trainer(
            config={
                "backend": "keras", "device": "cpu", "epochs": 2, "batch_size": 8,
                "patience": 5, "output_path": str(tmp_path / f"t{tag}"),
            },
            seed=42,
        ).process({"model": model, "dataset": tiny_ds})["output"]
        m = keras.models.load_model(str(tmp_path / f"t{tag}" / "model.keras"))
        return out.history, m.get_weights()

    h1, w1 = run(1)
    h2, w2 = run(2)
    assert h1["loss"] == h2["loss"]
    assert all(np.array_equal(a, b) for a, b in zip(w1, w2))


def test_seed_everything_enables_op_determinism(tf_mod) -> None:
    import os

    mod_cls = _load("trainer", "trainer")
    import sys

    seed_everything = sys.modules[mod_cls.__module__].seed_everything
    assert seed_everything(2**32 + 3) == 3
    assert os.environ.get("TF_DETERMINISTIC_OPS") is not None
    is_on = getattr(tf_mod.config.experimental, "is_op_determinism_enabled", None)
    if is_on is not None:
        assert is_on() is True
