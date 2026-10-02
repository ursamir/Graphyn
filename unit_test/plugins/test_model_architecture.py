"""Unit tests for trainer model_architecture presets + custom layers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ARCH = ROOT / "PluginPackage" / "Common" / "trainer" / "model_architecture.py"
PRESETS = ROOT / "PluginPackage" / "Common" / "trainer" / "presets"


def _load_arch():
    import importlib.util

    spec = importlib.util.spec_from_file_location("graphyn_model_architecture_under_test", ARCH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ma():
    return _load_arch()


@pytest.mark.parametrize("arch", ["ds_cnn", "mobilenet", "simple_cnn"])
def test_export_matches_fixture(ma, arch):
    fixture = json.loads((PRESETS / f"{arch}.layers.json").read_text())
    layers = ma.export_layer_specs(
        arch,
        filters=fixture["filters"],
        num_layers=fixture["num_layers"],
        expansion_factor=fixture["expansion_factor"],
        stem_stride=fixture["stem_stride"],
        dropout_rate=fixture["dropout_rate"],
    )
    assert layers == fixture["layers"]


def test_custom_requires_layers(ma):
    with pytest.raises(ValueError, match="non-empty"):
        ma.validate_layers([])
    with pytest.raises(ValueError, match="unknown type"):
        ma.validate_layers([{"type": "not_a_layer"}])
    with pytest.raises(ValueError, match="filters"):
        ma.validate_layers([{"type": "conv2d"}])


def test_unknown_architecture(ma):
    with pytest.raises(ValueError, match="unknown architecture"):
        ma.build_keras_model(
            architecture="resnet50",
            input_shape=(32, 32, 1),
            n_classes=2,
        )


@pytest.fixture(scope="module")
def tf_mod():
    return pytest.importorskip("tensorflow")


def test_preset_equals_custom_export(ma, tf_mod):
    """Preset compile path == custom path given the same export_layer_specs body."""
    specs = ma.export_layer_specs("ds_cnn", filters=32, num_layers=2)
    a = ma.build_preset_model("ds_cnn", (40, 20, 1), 4, filters=32, num_layers=2)
    b = ma.build_from_layer_specs(specs, (40, 20, 1), 4, dropout_rate=0.25)
    assert a.count_params() == b.count_params()
    assert a.output_shape == b.output_shape == (None, 4)


def test_mobilenet_paper_defaults(ma, tf_mod):
    m = ma.build_preset_model(
        "mobilenet",
        (101, 40, 1),
        6,
        filters=64,
        num_layers=1,
        expansion_factor=6,
        stem_stride=2,
    )
    assert 50_000 <= m.count_params() <= 70_000
    assert m.output_shape == (None, 6)


def test_custom_inverted_residual_and_ds_block(ma, tf_mod):
    layers = [
        {"type": "conv2d", "filters": 16, "kernel_size": 3, "padding": "same", "use_bias": False},
        {"type": "batch_norm"},
        {"type": "relu6"},
        {"type": "inverted_residual", "filters": 16, "expansion_factor": 6, "stride": 1},
        {"type": "ds_separable_block", "filters": 16},
    ]
    m = ma.build_from_layer_specs(layers, (32, 32, 1), 3)
    assert m.output_shape == (None, 3)
    assert m.count_params() > 0
