# unit_test/plugins/wakeword/test_wakeword_pack.py
"""WakeWord pack (F20): five nodes wrapping livekit-wakeword.

Light tests cover install/registration, schema ↔ Config parity, the run
manifest hand-off, detection merging and clear errors. The heavy test runs
the real pipeline end to end on CPU (MMS-TTS clips → augmentation + ONNX
features → 3-phase training → ONNX export + INT8 → detection).
"""
from __future__ import annotations

import importlib
import sys
import tomllib
from pathlib import Path

import numpy as np
import pytest

from app.core.nodes.registry import NodeRegistry
from app.core.plugins.manager import PluginManager
from app.models.audio_sample import AudioSample

ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / "PluginPackage" / "WakeWord"
NODES = {
    "wakeword_data_gen": "WakewordDataGenNode",
    "wakeword_feature_extract": "WakewordFeatureExtractNode",
    "wakeword_train": "WakewordTrainNode",
    "wakeword_export_onnx": "WakewordExportOnnxNode",
    "wakeword_infer": "WakewordInferNode",
}


def _mod(name: str):
    parent = str(PACK)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    for k in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
        del sys.modules[k]
    return importlib.import_module(f"{name}.nodes")


def _node(name: str, cfg: dict):
    return getattr(_mod(name), NODES[name])(config=cfg, seed=0)


@pytest.mark.parametrize("name", list(NODES))
def test_installs_and_registers(name, tmp_path):
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_path))
    mgr._plugins_dir = str(tmp_path)
    mgr.install(str(PACK / name) + "/")
    cls = reg.get_class(name)
    assert cls.node_type == name


@pytest.mark.parametrize("name", list(NODES))
def test_schema_matches_config(name):
    data = tomllib.loads((PACK / name / "plugin.toml").read_text())
    assert data["plugin"]["runtime"] == "isolated"
    assert any(d.startswith("livekit-wakeword") for d in data["plugin"]["dependencies"])
    schema = data["config_schema"][name]
    cls = getattr(_mod(name), NODES[name])
    fields = {k for k in cls.Config.model_fields if k != "seed"}
    assert set(schema) == fields
    for key, spec in schema.items():
        assert cls.Config.model_fields[key].get_default(call_default_factory=True) == spec["default"], key


def test_shared_modules_are_identical():
    for fname in ("_ww.py", "types.py"):
        blobs = {(PACK / n / fname).read_bytes() for n in NODES}
        assert len(blobs) == 1, f"{fname} copies diverged"


def test_stages_need_a_run():
    for name in ("wakeword_feature_extract", "wakeword_train", "wakeword_export_onnx"):
        with pytest.raises(ValueError, match="no run"):
            _node(name, {}).process({})


def test_manifest_round_trip_and_missing_features(tmp_path):
    _mod("wakeword_train")
    ww = importlib.import_module("wakeword_train._ww")
    info = ww.write_manifest({"model_name": "m", "model_dir": str(tmp_path / "m"), "target_phrases": ["hey m"], "stage": "clips"})
    back = ww.as_run({"model_dir": info["model_dir"]})
    assert back["target_phrases"] == ["hey m"]
    with pytest.raises(ValueError, match="feature_extract"):
        _node("wakeword_train", {"model_dir": info["model_dir"]}).process({})
    with pytest.raises(ValueError, match="wakeword_data_gen"):
        ww.as_run(str(tmp_path / "nowhere"))


def test_infer_requires_model(tmp_path):
    s = AudioSample(path="x", sample_rate=16000, data=np.zeros(16000, np.float32))
    with pytest.raises(ValueError, match="no model"):
        _node("wakeword_infer", {}).process({"audio": [s]})
    with pytest.raises(FileNotFoundError):
        _node("wakeword_infer", {"model_path": str(tmp_path / "nope.onnx")}).process({"audio": [s]})


def test_detection_merging():
    m = _mod("wakeword_infer")
    tl = [(2.0, 0.1), (2.1, 0.9), (2.2, 0.95), (2.3, 0.2), (5.0, 0.8), (9.0, 0.7)]
    dets = m.detections_from(tl, threshold=0.5, window_s=2.0, refractory_s=1.0)
    assert [d["peak_end_s"] for d in dets] == [2.2, 5.0, 9.0]
    assert dets[0]["start_s"] == pytest.approx(0.1) and dets[0]["score"] == 0.95


def test_silence_windows_score_zero():
    m = _mod("wakeword_infer")

    class _Det:
        calls = 0

        def predict(self, chunk):
            _Det.calls += 1
            return {"m": 0.99}

    audio = np.zeros(16000 * 4, np.float32)
    audio[32000:40000] = 0.3
    tl = m.score_timeline(_Det(), audio, window_s=2.0, hop_s=0.5)
    assert tl[0] == (2.0, 0.0)  # first window is digital silence → not scored
    assert any(s == 0.99 for _, s in tl)


def test_data_gen_schema_rejects_bad_names():
    with pytest.raises(Exception):
        _mod("wakeword_data_gen").WakewordDataGenNode.Config(model_name="bad name/..")
    with pytest.raises(Exception):
        _mod("wakeword_data_gen").WakewordDataGenNode.Config(target_phrases=[])


@pytest.mark.heavy
def test_end_to_end_mms_pipeline(tmp_path):
    pytest.importorskip("livekit.wakeword")
    pytest.importorskip("transformers")
    rng = np.random.default_rng(0)
    bg = [AudioSample(path=f"/bg/{i}.wav", sample_rate=16000,
                      data=(0.02 * rng.standard_normal(16000 * 2)).astype(np.float32)) for i in range(2)]
    run = _node("wakeword_data_gen", {
        "model_name": "hey_test", "target_phrases": ["hey graphyn"], "n_samples": 12, "n_samples_val": 4,
        "n_background_samples": 6, "n_background_samples_val": 2, "tts_backend": "mms",
        "output_dir": str(tmp_path / "out"), "data_dir": str(tmp_path / "data"),
    }).process({"background": bg})["run"]
    assert run.clip_counts["positive_train"] == 12 and run.clip_counts["negative_test"] == 4
    assert run.clip_counts["background_train"] == 6
    run = _node("wakeword_feature_extract", {}).process({"run": run})["run"]
    assert run.features["positive_train"] == [12, 16, 96]
    run = _node("wakeword_train", {"steps": 60, "device": "cpu"}).process({"run": run.model_dump()})["run"]
    assert Path(run.checkpoint_path).is_file() and 0.0 < run.threshold < 1.0
    run = _node("wakeword_export_onnx", {"quantize": True}).process({"run": run})["run"]
    assert Path(run.onnx_path).is_file() and Path(run.onnx_int8_path).is_file()
    assert run.metadata["onnx_verify"]["fp32_max_abs_diff"] < 1e-3
    clip = sorted(Path(run.model_dir, "positive_test").glob("clip_??????.wav"))[0]
    out = _node("wakeword_infer", {}).process({"audio": [AudioSample(path=str(clip), sample_rate=16000)], "model": run})["output"]
    assert len(out) == 1
    ww = out[0].metadata["wakeword"]
    assert 0.0 <= ww["max_score"] <= 1.0 and ww["timeline"]
    assert out[0].predicted_label in {"hey_test", "none"}
