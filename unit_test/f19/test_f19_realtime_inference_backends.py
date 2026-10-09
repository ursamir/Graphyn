"""F19 (F-18): realtime_inference only offers backends that score audio."""
from __future__ import annotations

import tomllib

import pytest

from app.core.plugins.manager import PluginManager
from unit_test.plugins._helpers import materialize_isolated_class


@pytest.fixture(scope="module")
def cls(tmp_path_factory):
    from app.core.nodes.registry import NodeRegistry

    tmp = tmp_path_factory.mktemp("rti")
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp))
    mgr._plugins_dir = str(tmp)
    mgr.install("PluginPackage/Common/realtime_inference/")
    return materialize_isolated_class(reg.get_class("realtime_inference"))


def test_enum_has_no_vision_backends(cls):
    toml = tomllib.load(open("PluginPackage/Common/realtime_inference/plugin.toml", "rb"))
    schema = toml["config_schema"]["realtime_inference"]
    assert "ultralytics" not in schema["backend"]["enum"]
    assert set(schema["mode"]["enum"]) == {"classification", "wake_word", "streaming_asr"}
    fields = cls.Config.model_fields
    assert "ultralytics" not in str(fields["backend"].annotation)


@pytest.mark.parametrize("cfg,match", [
    ({"backend": "ultralytics"}, "vision"),
    ({"mode": "detect"}, "vision task"),
])
def test_vision_options_rejected_with_routing_hint(cls, cfg, match):
    with pytest.raises(Exception, match=match):
        cls(config={"model_path": "m.onnx", **cfg}, seed=0)


def test_auto_resolves_from_extension(cls):
    for ext, want in ((".tflite", "tflite"), (".pt", "pytorch"), (".onnx", "onnx")):
        node = cls(config={"model_path": f"model{ext}"}, seed=0)
        assert node._detect_backend() == want
