"""UX overhaul — live progress events from the Example 06 plugins.

Every plugin imports ``emit_node_progress`` defensively (no-op when the host
predates ``app.core.nodes.progress``). These tests swap the module-level
emitter for a fake collector and check the payload contract:

* data nodes (feature_frontend, dataset_builder, augmentation_pipeline,
  audio_exporter): ``{"phase", "done", "total", "pct"}``, throttled, ending at 100;
* trainer: one ``phase="train"`` event per epoch with loss/accuracy/val_* and
  pct, plus an ``event="early_stopping"`` notice;
* evaluator: ``phase="evaluate"`` 0 → 100 with the final ``test_accuracy``;
* edge_optimizer: ``phase="convert"`` 0 → 100 and ``phase="calibrate"`` for int8.

TensorFlow-backed checks are ``heavy`` (GRAPHYN_RUN_HEAVY=1).
"""
from __future__ import annotations

import math
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from app.core.nodes.discovery import AutoDiscovery
from app.core.nodes.registry import NodeRegistry
from app.models.audio_sample import AudioSample
from app.models.feature_array import FeatureArray

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "PluginPackage"
LABELS = ["down", "go", "no", "stop", "up", "yes"]


def _load(plugin: str, node_type: str):
    reg = NodeRegistry()
    disc = AutoDiscovery(reg)
    for entry in ("types.py", "nodes.py"):
        path = PKG / plugin / entry
        if path.is_file():
            disc._process_module(disc._import_file(path, package_prefix=None))
    return reg.get_class(node_type)


def _capture(monkeypatch, cls) -> list[dict]:
    """Replace the plugin module's emitter with a collector."""
    events: list[dict] = []
    mod = sys.modules[cls.__module__]
    monkeypatch.setattr(mod, "emit_node_progress", lambda payload: events.append(dict(payload)))
    return events


def _samples(n: int, label: str = "yes", sr: int = 16000) -> list[AudioSample]:
    rng = np.random.default_rng(0)
    out = []
    for i in range(n):
        data = (0.1 * rng.standard_normal(sr // 4)).astype(np.float32)
        out.append(AudioSample(data=data, sample_rate=sr, label=label, path=f"/raw/{label}/{label}_{i}.wav",
                               metadata={"parent": f"{label}_{i}"}))
    return out


def _features(n_per_label: int = 6, with_split_paths: bool = True) -> list[FeatureArray]:
    rng = np.random.default_rng(1)
    out = []
    for k, lbl in enumerate(LABELS):
        for i in range(n_per_label):
            x = rng.normal(0, 0.3, (101, 40)).astype(np.float32)
            x[:, :: k + 2] += 2.0
            split = ("train", "train", "train", "train", "val", "test")[i % 6]
            path = f"/ds/v1/{split}/{lbl}/{lbl}_{i}.wav" if with_split_paths else f"/raw/{lbl}/{lbl}_{i}.wav"
            out.append(FeatureArray(data=x, label=lbl, source_path=path, feature_type="mfcc"))
    return out


def _assert_item_progress(events: list[dict], phase: str, total: int) -> None:
    mine = [e for e in events if e.get("phase") == phase]
    assert mine, f"no {phase!r} progress events: {events}"
    pcts = [e["pct"] for e in mine]
    assert pcts == sorted(pcts), "pct must be non-decreasing"
    assert mine[-1]["pct"] == 100.0 and mine[-1]["done"] == total and mine[-1]["total"] == total
    assert all(0.0 <= p <= 100.0 for p in pcts)
    assert len(mine) <= 22, "item progress is throttled to ~20 events"


# ── defensive import ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("plugin,node_type", [
    ("Audio/feature_frontend", "feature_frontend"),
    ("Audio/augmentation_pipeline", "augmentation_pipeline"),
    ("Audio/audio_exporter", "audio_exporter"),
    ("Common/dataset_builder", "dataset_builder"),
    ("Common/trainer", "trainer"),
    ("Common/evaluator", "evaluator"),
    ("Common/edge_optimizer", "edge_optimizer"),
])
def test_plugins_expose_progress_emitter(plugin, node_type):
    cls = _load(plugin, node_type)
    mod = sys.modules[cls.__module__]
    assert callable(getattr(mod, "emit_node_progress", None))
    src = (PKG / plugin / "nodes.py").read_text()
    assert "except ImportError" in src and "app.core.nodes.progress" in src, "import must be defensive"


def test_fallback_emitter_is_a_noop_without_backend(monkeypatch):
    """Simulate a host without app.core.nodes.progress: plugin still imports and runs."""
    import importlib.util

    monkeypatch.setitem(sys.modules, "app.core.nodes.progress", None)  # ImportError on import
    name = "_ux_progress_fallback_feature_frontend"
    spec = importlib.util.spec_from_file_location(name, PKG / "Audio/feature_frontend/nodes.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, mod)
    spec.loader.exec_module(mod)
    assert mod.emit_node_progress.__module__ == name, "fallback no-op must be defined"
    assert mod.emit_node_progress({"phase": "x", "pct": 1}) is None
    out = mod.FeatureFrontendNode(config={"feature_type": "mfcc", "n_mfcc": 13}).process({"input": _samples(3)})["output"]
    assert len(out) == 3


# ── data nodes ───────────────────────────────────────────────────────────────


def test_feature_frontend_reports_pct_over_items(monkeypatch):
    cls = _load("Audio/feature_frontend", "feature_frontend")
    events = _capture(monkeypatch, cls)
    cls(config={"feature_type": "mfcc", "n_mfcc": 13}).process({"input": _samples(50)})
    _assert_item_progress(events, "features", 50)


def test_dataset_builder_reports_pct_over_items(monkeypatch):
    cls = _load("Common/dataset_builder", "dataset_builder")
    events = _capture(monkeypatch, cls)
    feats = _features(6)
    cls(config={"fixed_length": 101}).process({"input": feats})
    _assert_item_progress(events, "dataset", len(feats))


def test_augmentation_reports_pct_over_items(monkeypatch):
    cls = _load("Audio/augmentation_pipeline", "augmentation_pipeline")
    events = _capture(monkeypatch, cls)
    cls(config={"copies_per_sample": 1, "augmentations": [{"type": "gain", "apply_prob": 1.0, "gain_db": [-3, 3]}]}).process({"input": _samples(30)})
    _assert_item_progress(events, "augment", 30)


def test_audio_exporter_reports_pct_over_items(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    cls = _load("Audio/audio_exporter", "audio_exporter")
    events = _capture(monkeypatch, cls)
    cls(config={"output_dir": "out"}).process({"input": _samples(25)})
    _assert_item_progress(events, "export", 25)


def test_emitter_errors_never_fail_a_node(monkeypatch):
    cls = _load("Audio/feature_frontend", "feature_frontend")

    def boom(_payload):
        raise RuntimeError("sink down")

    monkeypatch.setattr(sys.modules[cls.__module__], "emit_node_progress", boom)
    assert len(cls(config={"feature_type": "mfcc", "n_mfcc": 13}).process({"input": _samples(5)})["output"]) == 5


def test_empty_input_emits_nothing(monkeypatch):
    cls = _load("Audio/feature_frontend", "feature_frontend")
    events = _capture(monkeypatch, cls)
    assert cls(config={}).process({"input": []})["output"] == []
    assert events == []


# ── trainer payloads (no TensorFlow) ─────────────────────────────────────────


@pytest.fixture(scope="module")
def trainer_mod():
    cls = _load("Common/trainer", "trainer")
    return sys.modules[cls.__module__]


def test_epoch_payload_contract(trainer_mod):
    p = trainer_mod._epoch_payload(3, 30, {"loss": np.float32(0.41), "accuracy": 0.82,
                                           "val_loss": 0.5, "val_accuracy": float("nan")})
    assert p == {"phase": "train", "epoch": 3, "epochs": 30, "loss": pytest.approx(0.41, abs=1e-6),
                 "accuracy": 0.82, "val_loss": 0.5, "val_accuracy": None, "pct": 10.0}
    assert all(not isinstance(v, float) or math.isfinite(v) for v in p.values())


def test_early_stop_payload_contract(trainer_mod):
    p = trainer_mod._early_stop_payload(21, 50, 15, 0.856)
    assert p["event"] == "early_stopping" and p["phase"] == "train"
    assert p["epoch"] == 21 and p["epochs"] == 50 and p["pct"] == 100.0
    assert "21 of 50" in p["message"] and "15 epochs" in p["message"]


def test_keras_callback_emits_per_epoch_and_early_stop(monkeypatch, trainer_mod):
    """Drive the callback with a fake keras namespace (no TF import)."""
    events: list[dict] = []
    monkeypatch.setattr(trainer_mod, "emit_node_progress", lambda p: events.append(dict(p)))
    fake_keras = types.SimpleNamespace(callbacks=types.SimpleNamespace(Callback=object))
    early = types.SimpleNamespace(stopped_epoch=4, best=0.9)
    cb = trainer_mod._keras_progress_callback(fake_keras, 10, early_stop=early, patience=2)
    cb.on_train_begin()
    for e in range(5):
        cb.on_epoch_end(e, {"loss": 1.0 / (e + 1), "accuracy": 0.5, "val_loss": 0.9, "val_accuracy": 0.6 + e / 100})
    cb.on_train_end()
    epochs = [e for e in events if e.get("event") is None and e["epoch"] > 0]
    assert [e["epoch"] for e in epochs] == [1, 2, 3, 4, 5]
    assert [e["pct"] for e in epochs] == [10.0, 20.0, 30.0, 40.0, 50.0]
    assert events[0] == {"phase": "train", "epoch": 0, "epochs": 10, "pct": 0.0}
    assert events[-1]["event"] == "early_stopping" and events[-1]["epoch"] == 5


def test_keras_callback_no_notice_when_all_epochs_ran(monkeypatch, trainer_mod):
    events: list[dict] = []
    monkeypatch.setattr(trainer_mod, "emit_node_progress", lambda p: events.append(dict(p)))
    fake_keras = types.SimpleNamespace(callbacks=types.SimpleNamespace(Callback=object))
    cb = trainer_mod._keras_progress_callback(fake_keras, 2, early_stop=types.SimpleNamespace(stopped_epoch=0))
    cb.on_epoch_end(0, {})
    cb.on_epoch_end(1, {})
    cb.on_train_end()
    assert not any(e.get("event") == "early_stopping" for e in events)
    assert events[-1]["pct"] == 100.0


def test_real_backend_emitter_accepts_plugin_payloads(trainer_mod):
    """The backend contract (when present) turns our payloads into node_progress events."""
    progress = pytest.importorskip("app.core.nodes.progress")
    seen: list[dict] = []
    with progress.progress_context("trainer_0", "trainer", seen.append):
        progress.emit_node_progress(trainer_mod._epoch_payload(1, 5, {"loss": 1.2, "val_accuracy": 0.4}))
        progress.emit_node_progress(trainer_mod._early_stop_payload(3, 5, 2, 0.5))
    assert seen[0]["type"] == "node_progress" and seen[0]["epoch"] == 1
    assert "epoch 1/5" in seen[0]["message"]
    assert seen[-1]["event"] == "early_stopping"  # pct=100 bypasses the throttle


# ── TensorFlow chain (heavy) ─────────────────────────────────────────────────


@pytest.mark.heavy
class TestMLProgressChain:
    @pytest.fixture(scope="class")
    def chain(self, tmp_path_factory):
        pytest.importorskip("tensorflow")
        mp = pytest.MonkeyPatch()
        out = tmp_path_factory.mktemp("ux_progress")
        ds = _load("Common/dataset_builder", "dataset_builder")(config={}).process({"input": _features(12)})["output"]
        builder = _load("Common/trainer", "model_builder")
        trainer = _load("Common/trainer", "trainer")
        evaluator = _load("Common/evaluator", "evaluator")
        optimizer = _load("Common/edge_optimizer", "edge_optimizer")
        ev = {"trainer": _capture(mp, trainer), "evaluator": _capture(mp, evaluator), "edge": _capture(mp, optimizer)}
        try:
            model = builder(config={"filters": 8, "num_layers": 1, "output_path": str(out / "mb")}).process({"input": ds})["output"]
            trained = trainer(config={"backend": "keras", "device": "cpu", "epochs": 3, "batch_size": 8, "patience": 10,
                                      "output_path": str(out / "train")}, seed=1).process({"model": model, "dataset": ds})["output"]
            evaluated = evaluator(config={"output_path": str(out / "eval"), "plot_confusion_matrix": False,
                                          "plot_training_curves": False}).process({"model_artifact": trained, "dataset": ds})["output"]
            dep = optimizer(config={"quantization": "int8", "representative_samples": 20,
                                    "output_path": str(out / "tflite")}).process({"input": evaluated})["output"]
        finally:
            mp.undo()
        return {"events": ev, "evaluated": evaluated, "dep": dep}

    def test_trainer_epoch_events(self, chain):
        events = [e for e in chain["events"]["trainer"] if e.get("epoch")]
        assert [e["epoch"] for e in events] == [1, 2, 3]
        for e in events:
            assert e["phase"] == "train" and e["epochs"] == 3
            assert {"loss", "accuracy", "val_loss", "val_accuracy", "pct"} <= set(e)
            assert e["loss"] is not None and e["val_accuracy"] is not None
        assert events[-1]["pct"] == 100.0

    def test_evaluator_events(self, chain):
        events = chain["events"]["evaluator"]
        assert [e["pct"] for e in events] == [0.0, 100.0]
        assert all(e["phase"] == "evaluate" for e in events)
        assert events[-1]["test_accuracy"] == pytest.approx(chain["evaluated"].metrics["test_accuracy"], abs=1e-6)

    def test_edge_optimizer_events(self, chain):
        events = chain["events"]["edge"]
        convert = [e for e in events if e["phase"] == "convert"]
        calibrate = [e for e in events if e["phase"] == "calibrate"]
        assert convert[0]["pct"] == 0.0 and convert[-1]["pct"] == 100.0
        assert convert[-1]["file_size_bytes"] == chain["dep"].file_size_bytes
        assert calibrate and calibrate[-1]["pct"] == 100.0 and calibrate[-1]["total"] == 20
