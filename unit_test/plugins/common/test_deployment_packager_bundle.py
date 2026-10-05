# unit_test/plugins/common/test_deployment_packager_bundle.py
"""deployment_packager 1.1 — runnable, traceable Ship packages.

Covers:
  - preprocessing parity: the shipped run_inference.py feature code equals the
    platform Feature Frontend (+ Dataset Builder pad) on synthetic waveforms
    (mfcc / log_mel / deltas / resampling / short + long clips)
  - preprocessing.json resolved from the source run graph snapshot
  - provenance.json / SHA256SUMS / README / requirements / manifest sidecar
  - self-test on real clips (parity + input shape + model run) with a tiny
    float32 and int8 TFLite model; strict mode fails on a shape mismatch
  - the generated script runs end-to-end on a WAV (``--json``)
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import numpy as np
import pytest

from app.core.plugins.manager import PluginManager
from unit_test.plugins._helpers import materialize_isolated_class

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "PluginPackage/Common/deployment_packager/bundle/run_inference.py"
SRC_RUN = "a" * 32
PKG_RUN = "b" * 32

FEATURE_CFG = {
    "feature_type": "mfcc", "sample_rate": 16000, "fixed_length": 0, "n_fft": 512,
    "hop_length": 160, "win_length": 400, "n_mels": 80, "n_mfcc": 40, "fmin": 0,
    "fmax": 8000, "log_scale": True, "normalize": True, "center": True,
    "delta": False, "delta_delta": False,
}

librosa = pytest.importorskip("librosa")
sf = pytest.importorskip("soundfile")


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def plugin_registry(tmp_path_factory):
    """Fresh registry with feature_frontend + deployment_packager installed."""
    from app.core.nodes.registry import NodeRegistry

    tmp = tmp_path_factory.mktemp("pkg_bundle_plugins")
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp))
    mgr._plugins_dir = str(tmp)
    mgr.install("PluginPackage/Audio/feature_frontend/")
    mgr.install("PluginPackage/Common/deployment_packager/")
    return reg


@pytest.fixture()
def use_registry(plugin_registry, monkeypatch):
    import app.core.nodes as nodes_pkg

    monkeypatch.setattr(nodes_pkg, "registry", plugin_registry)
    return plugin_registry


@pytest.fixture(scope="module")
def run_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("_test_run_inference", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tone(freq: float, sr: int = 16000, dur: float = 1.0, seed: int = 0) -> np.ndarray:
    t = np.arange(int(sr * dur)) / sr
    rng = np.random.default_rng(seed)
    y = 0.4 * np.sin(2 * np.pi * freq * t) + 0.05 * rng.standard_normal(t.size)
    return y.astype(np.float32)


def _frontend(reg, cfg: dict, y: np.ndarray, sr: int) -> np.ndarray:
    from app.models.audio_sample import AudioSample

    cls = materialize_isolated_class(reg.get_class("feature_frontend"))
    out = cls(config=cfg, seed=0).process({"input": [AudioSample(path="x.wav", sample_rate=sr, data=y, label="a")]})
    return np.asarray(out["output"][0].data, dtype=np.float32)


def _builder_pad(arr: np.ndarray, fixed: int) -> np.ndarray:
    """Mirror of dataset_builder._pad_or_truncate (asserted equal below)."""
    t, f = arr.shape
    if t > fixed:
        return arr[:fixed]
    if t < fixed:
        return np.concatenate([arr, np.zeros((fixed - t, f), np.float32)], axis=0)
    return arr


# ── 1. preprocessing parity (no TF needed) ───────────────────────────────────

@pytest.mark.parametrize(
    "overrides,sr,dur",
    [
        ({}, 16000, 1.0),
        ({}, 22050, 1.0),          # resampled like training
        ({}, 16000, 0.6),          # short clip → zero pad
        ({}, 16000, 1.7),          # long clip → truncate
        ({"feature_type": "log_mel"}, 16000, 1.0),
        ({"delta": True, "delta_delta": True, "n_mfcc": 13}, 16000, 1.0),
        ({"normalize": False, "fixed_length": 98}, 8000, 1.2),
    ],
)
def test_shipped_features_match_feature_frontend(plugin_registry, run_module, overrides, sr, dur):
    cfg = {**FEATURE_CFG, **overrides}
    y = _tone(440.0, sr=sr, dur=dur, seed=3)
    ref = _builder_pad(_frontend(plugin_registry, cfg, y, sr), 101)
    pre = {"features": cfg, "frames": {"fixed_length": 101}}
    got = run_module.extract_features(y, sr, pre)
    assert got.shape == ref.shape == (101, ref.shape[1])
    np.testing.assert_allclose(got, ref, atol=1e-5, rtol=0)


def test_builder_pad_mirrors_dataset_builder(run_module):
    src = (ROOT / "PluginPackage/Common/dataset_builder/nodes.py").read_text()
    assert "pad = np.zeros((length - T, F), dtype=np.float32)" in src
    assert "return data[:length, :]" in src
    a = np.ones((5, 3), np.float32)
    assert run_module._pad_or_truncate(a, 7)[5:].sum() == 0
    assert run_module._pad_or_truncate(a, 2).shape == (2, 3)


def test_to_model_input_quantizes_uint8(run_module):
    feats = np.linspace(-2, 2, 101 * 40, dtype=np.float32).reshape(101, 40)
    detail = {"shape": [1, 101, 40, 1], "dtype": np.uint8, "quantization": (0.02, 128)}
    x = run_module.to_model_input(feats, detail)
    assert x.dtype == np.uint8 and x.shape == (1, 101, 40, 1)
    np.testing.assert_array_equal(x[0, :, :, 0], np.clip(np.round(feats / 0.02 + 128), 0, 255).astype(np.uint8))
    with pytest.raises(ValueError, match="does not match model input"):
        run_module.to_model_input(feats[:50], detail)


# ── 2. full package build ─────────────────────────────────────────────────────

def _tiny_tflite(path: Path, *, frames: int = 101, int8: bool = False) -> Path:
    tf = pytest.importorskip("tensorflow")
    keras = tf.keras
    keras.utils.set_random_seed(0)
    model = keras.Sequential([
        keras.layers.Input(shape=(frames, 40, 1)),
        keras.layers.Flatten(),
        keras.layers.Dense(2, activation="softmax"),
    ])
    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    if int8:
        rng = np.random.default_rng(0)

        def rep():
            for _ in range(8):
                yield [rng.standard_normal((1, frames, 40, 1)).astype(np.float32)]

        conv.optimizations = [tf.lite.Optimize.DEFAULT]
        conv.representative_dataset = rep
        conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        conv.inference_input_type = tf.uint8
        conv.inference_output_type = tf.uint8
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(conv.convert())
    return path


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """Source training run snapshot + dataset + package run meta."""
    runs = tmp_path / "runs"
    ds = tmp_path / "dataset"
    for lbl, freq in (("no", 300.0), ("yes", 1200.0)):
        for i in range(2):
            d = ds / "test" / lbl
            d.mkdir(parents=True, exist_ok=True)
            sf.write(d / f"{lbl}_{i}.wav", _tone(freq, seed=i), 16000)
    (ds / "train" / "yes").mkdir(parents=True)
    sf.write(ds / "train" / "yes" / "t.wav", _tone(1200.0, sr=22050, seed=9), 22050)
    graph = {
        "schema_version": "1.1",
        "metadata": {"name": "speech-commands-train"},
        "nodes": [
            {"id": "ingest", "node_type": "dataset_ingest", "config": {"source_type": "filesystem", "path": str(ds)}},
            {"id": "ff", "node_type": "feature_frontend", "config": dict(FEATURE_CFG)},
            {"id": "db", "node_type": "dataset_builder", "config": {"fixed_length": 101}},
            {"id": "tr", "node_type": "trainer", "config": {}},
        ],
        "edges": [
            {"src_id": "ingest", "src_port": "output", "dst_id": "ff", "dst_port": "input"},
            {"src_id": "ff", "src_port": "output", "dst_id": "db", "dst_port": "input"},
            {"src_id": "db", "src_port": "output", "dst_id": "tr", "dst_port": "input"},
        ],
    }
    src = runs / SRC_RUN
    src.mkdir(parents=True)
    (src / "graph.json").write_text(json.dumps(graph))
    (src / "meta.json").write_text(json.dumps({
        "run_id": SRC_RUN, "status": "succeeded", "project": "demo", "graph_name": "speech-commands-train",
        "metrics": {"test_accuracy": 0.8125, "roc_auc": 0.9},
    }))
    (src / "prove.json").write_text(json.dumps({
        "run_id": SRC_RUN, "record_hash": "f" * 64, "graph_hash": "e" * 64,
        "external_inputs": [{"node_id": "ingest", "node_type": "dataset_ingest", "path": str(ds), "kind": "dir",
                             "content_hash": "sha256:" + "d" * 64, "file_count": 5, "total_bytes": 1}],
        "environment": {"libraries": {"librosa": librosa.__version__, "numpy": np.__version__}},
    }))
    pkg = runs / PKG_RUN
    pkg.mkdir()
    (pkg / "meta.json").write_text(json.dumps({
        "run_id": PKG_RUN, "source_run_id": SRC_RUN, "trigger": "ship",
        "lineage_request": {"model": {"name": "kws", "stage": "staging"}},
    }))
    import app.core.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "runs_dir", lambda: runs)
    return {"root": tmp_path, "runs": runs, "dataset": ds}


def _package(reg, workspace, model: Path, *, quant: str, target: str = "edge", **cfg):
    from app.models.deployment_artifact import DeploymentArtifact

    cls = materialize_isolated_class(reg.get_class("deployment_packager"))
    node = cls(config={"target": target, "output_path": str(workspace["root"] / "packages"),
                       "package_name": "kws", **cfg}, seed=0)
    node._run_id = PKG_RUN
    art = DeploymentArtifact(artifact_path=str(model), model_format="tflite", quantization=quant,
                             labels=["no", "yes"], metadata={"display_name": "tiny"})
    return node.process({"input": art})["output"]


def _members(tar_path: Path) -> dict[str, bytes]:
    with tarfile.open(tar_path) as tf:
        return {m.name: tf.extractfile(m).read() for m in tf.getmembers() if m.isfile()}


@pytest.mark.parametrize("int8", [False, True], ids=["float32", "int8"])
def test_edge_package_is_runnable_and_traceable(use_registry, workspace, int8, tmp_path):
    model = _tiny_tflite(tmp_path / "opt" / "model.tflite", int8=int8)
    out = _package(use_registry, workspace, model, quant="int8" if int8 else "float32")
    tar_path = Path(out.artifact_path)
    assert tar_path.name == "kws_edge.tar.gz"
    files = _members(tar_path)
    for name in ("model.tflite", "labels.txt", "preprocessing.json", "run_inference.py", "serve.py",
                 "requirements.txt", "requirements-serve.txt", "README.md", "metadata.json",
                 "selftest.json", "provenance.json", "SHA256SUMS"):
        assert name in files, name

    pre = json.loads(files["preprocessing.json"])
    assert pre["source"]["run_id"] == SRC_RUN and pre["source"]["resolved_from"] == "package_run_meta"
    for k, v in FEATURE_CFG.items():
        assert pre["features"][k] == v, k
    assert pre["frames"]["fixed_length"] == 101
    assert pre["labels"] == ["no", "yes"]
    assert pre["input"]["shape"] == [1, 101, 40, 1]
    if int8:
        assert pre["input"]["dtype"] == "uint8"
        assert pre["input"]["quantization"]["scale"] > 0
    else:
        assert pre["input"]["dtype"] == "float32"

    req = files["requirements.txt"].decode()
    assert f"librosa=={librosa.__version__}" in req
    assert "fastapi" not in req and "uvicorn" not in req
    assert "fastapi" in files["requirements-serve.txt"].decode()

    prov = json.loads(files["provenance.json"])
    assert prov["source_run"]["run_id"] == SRC_RUN
    assert prov["source_run"]["record_hash"] == "f" * 64
    assert prov["package"]["package_run_id"] == PKG_RUN
    assert prov["registered_model"]["name"] == "kws" and prov["registered_model"]["stage"] == "staging"
    assert prov["dataset"][0]["content_hash"] == "sha256:" + "d" * 64
    assert prov["model"]["sha256"] == hashlib.sha256(files["model.tflite"]).hexdigest()
    for name, row in prov["files"].items():
        assert row["sha256"] == hashlib.sha256(files[name]).hexdigest(), name
    sums = dict(line.split("  ")[::-1] for line in files["SHA256SUMS"].decode().splitlines())
    assert set(sums) == set(files) - {"SHA256SUMS"}
    assert all(hashlib.sha256(files[n]).hexdigest() == h for n, h in sums.items())

    st = json.loads(files["selftest.json"])
    checks = {c["name"]: c for c in st["checks"]}
    assert checks["preprocessing_parity"]["status"] == "passed", st
    assert checks["preprocessing_parity"]["max_abs_diff"] <= 1e-4
    assert checks["input_shape"]["status"] == "passed"
    assert checks["model_runs"]["status"] == "passed", st
    assert st["status"] == "passed"
    assert len(st["samples"]) == 3 and {s["label"] for s in st["samples"]} == {"no", "yes"}
    assert all(s.get("predicted") in ("no", "yes") for s in st["samples"])

    readme = files["README.md"].decode()
    assert "python run_inference.py clip.wav" in readme
    assert "81.2 %" in readme and SRC_RUN in readme and "sha256sum -c SHA256SUMS" in readme

    manifest = json.loads(Path(str(tar_path) + ".manifest.json").read_text())
    assert manifest["sha256"] == hashlib.sha256(tar_path.read_bytes()).hexdigest()
    assert manifest["contents"][0]["path"] == "model.tflite"
    assert manifest["selftest"]["status"] == "passed"
    assert manifest["input"]["sample_rate"] == 16000 and manifest["input"]["fixed_length"] == 101
    assert out.metadata["packager"]["manifest_path"].endswith(".manifest.json")
    assert out.input_shape == [1, 101, 40, 1]

    # The shipped script, run as a user would, on a real WAV.
    dest = tmp_path / "extracted"
    with tarfile.open(tar_path) as tf:
        tf.extractall(dest)  # noqa: S202 — test archive
    wav = workspace["dataset"] / "test" / "yes" / "yes_0.wav"
    proc = subprocess.run([sys.executable, str(dest / "run_inference.py"), str(wav), "--json", "--top-k", "2"],
                          cwd=dest, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    rep = json.loads(proc.stdout[proc.stdout.index("{"):])
    row = rep["results"][0]
    assert row["feature_shape"] == [101, 40]
    assert abs(sum(row["probabilities"]) - 1.0) < 0.05
    assert [t["label"] for t in row["top"]] and row["top"][0]["label"] in ("no", "yes")


def test_strict_selftest_fails_on_input_shape_mismatch(use_registry, workspace, tmp_path):
    model = _tiny_tflite(tmp_path / "opt" / "model.tflite", frames=50)
    with pytest.raises(RuntimeError, match="self-test failed"):
        _package(use_registry, workspace, model, quant="float32", selftest_samples=1)
    out = _package(use_registry, workspace, model, quant="float32", selftest="warn", selftest_samples=1)
    st = json.loads(_members(Path(out.artifact_path))["selftest.json"])
    assert st["status"] == "failed"
    assert any(c["name"] == "input_shape" and c["status"] == "failed" for c in st["checks"])


def test_package_without_source_run_warns(use_registry, tmp_path, monkeypatch):
    import app.core.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "runs_dir", lambda: tmp_path / "no-runs")
    from app.models.deployment_artifact import DeploymentArtifact

    cls = materialize_isolated_class(use_registry.get_class("deployment_packager"))
    node = cls(config={"target": "mobile", "output_path": str(tmp_path / "p")}, seed=0)
    out = node.process({"input": DeploymentArtifact(artifact_path="", model_format="tflite", labels=["a"])})["output"]
    import zipfile

    with zipfile.ZipFile(out.artifact_path) as zf:
        names = set(zf.namelist())
        pre = json.loads(zf.read("preprocessing.json"))
    assert {"preprocessing.json", "provenance.json", "README.md", "inference_android.java"} <= names
    assert "warning" in pre and pre["features"] is None
    manifest = json.loads(Path(out.artifact_path + ".manifest.json").read_text())
    assert manifest["selftest"]["status"] == "skipped"
    assert manifest["warning"]


def test_source_run_from_model_path(tmp_path, monkeypatch):
    from app.models.deployment_artifact import DeploymentArtifact

    spec_path = ROOT / "PluginPackage/Common/deployment_packager/nodes.py"
    import importlib.util

    spec = importlib.util.spec_from_file_location("_pkg_nodes_t", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    art = DeploymentArtifact(
        artifact_path="workspace/artifacts/x/opt/model.tflite",
        metadata={"source_model_path": f"workspace/artifacts/sc/runs/{SRC_RUN}/trainer/saved_model"},
    )
    ctx = mod.resolve_source_context(artifact=art, own_run_id="", runs_root=tmp_path)
    assert ctx["source_run_id"] == SRC_RUN and ctx["resolved_from"] == "model_path"
    ctx = mod.resolve_source_context(artifact=art, explicit_source_run_id="c" * 32, runs_root=tmp_path)
    assert ctx["source_run_id"] == "c" * 32 and ctx["resolved_from"] == "config"


def test_source_model_metrics_uses_the_shipped_models_path(tmp_path, monkeypatch):
    """Multi-path run: the package reports the path whose trainer made the model."""
    import importlib.util, sys, types
    from pathlib import Path as _P

    spec = importlib.util.spec_from_file_location("dp_nodes_metrics", _P("PluginPackage/Common/deployment_packager/nodes.py"))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        import pytest
        pytest.skip("packager module not importable standalone")
    summary = {"paths": [
        {"path_id": "path-a", "node_ids": ["mb_a", "trainer_0", "eval_a"], "metrics": {"test_accuracy": 0.578}},
        {"path_id": "path-c", "node_ids": ["mb_c", "trainer_c", "eval_c"], "metrics": {"test_accuracy": 0.756}},
    ]}
    import app.core.runs.run_summary as rs
    monkeypatch.setattr(rs, "run_summary_fields", lambda *a, **k: {"summary": summary})
    monkeypatch.setattr(mod, "_runs_root", lambda: tmp_path)
    art = types.SimpleNamespace(metadata={"source_model_path": "workspace/artifacts/models/runs/r1/trainer_c/model.keras"})
    assert mod._source_model_metrics("r1", {"metrics": {"test_accuracy": 0.578}}, art)["test_accuracy"] == 0.756
    art2 = types.SimpleNamespace(metadata={})
    # unknown model path → best path, not Path A
    assert mod._source_model_metrics("r1", {"metrics": {"test_accuracy": 0.578}}, art2)["test_accuracy"] == 0.756
