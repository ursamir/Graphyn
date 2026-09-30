"""Regression tests for MLOps pack defect fixes (canary/drift/diff/checksum/ab/ship/feature store)."""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

from app.core.nodes.discovery import AutoDiscovery
from app.core.nodes.registry import NodeRegistry
from app.models.dataset_artifact import DatasetArtifact
from app.models.deployment_artifact import DeploymentArtifact
from app.models.model_artifact import ModelArtifact

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[2]
MLOPS = ROOT / "PluginPackage" / "MLOps"


def _load(plugin: str):
    root = MLOPS / plugin
    reg = NodeRegistry()
    disc = AutoDiscovery(reg)
    for entry in ("types.py", "nodes.py"):
        disc._process_module(disc._import_file(root / entry, package_prefix=None))
    return reg.get_class(plugin)


def _out(node, inputs):
    return node.process(inputs)["output"]


def _field(obj, name):
    return obj[name] if isinstance(obj, dict) else getattr(obj, name)


# ── 1. canary_gate ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def canary():
    return _load("canary_gate")


def test_canary_nan_holds(canary):
    d = _out(canary(config={"metric_key": "acc"}), {"metrics": {"acc": float("nan")}})
    assert d.promote is False and "finite" in d.reason


def test_canary_missing_key_no_fallback(canary):
    d = _out(canary(config={"metric_key": "acc"}), {"metrics": {"loss": 3.7}})
    assert d.promote is False and "missing" in d.reason


def test_canary_reads_model_artifact_metrics(canary):
    art = ModelArtifact(model_path="m.keras", metrics={"test_accuracy": 0.91})
    d = _out(canary(config={}), {"metrics": art})
    assert d.promote is True and d.metrics["test_accuracy"] == pytest.approx(0.91)


def test_canary_min_value(canary):
    d = _out(canary(config={"metric_key": "acc", "min_value": 0.8}), {"metrics": {"acc": 0.5}})
    assert d.promote is False


def test_canary_baseline_regression(canary):
    node = canary(config={"metric_key": "acc", "max_regression": 0.02})
    hold = _out(node, {"metrics": {"acc": 0.90}, "baseline": ModelArtifact(metrics={"acc": 0.95})})
    assert hold.promote is False and "regressed" in hold.reason
    ok = _out(node, {"metrics": {"acc": 0.94}, "baseline": {"acc": 0.95}})
    assert ok.promote is True and ok.metrics["regression"] == pytest.approx(0.01)


def test_canary_lower_is_better_with_config_baseline(canary):
    node = canary(config={"metric_key": "loss", "higher_is_better": False, "min_value": None,
                          "baseline_value": 1.0, "max_regression": 0.1})
    assert _out(node, {"metrics": {"loss": 1.05}}).promote is True
    assert _out(node, {"metrics": {"loss": 1.5}}).promote is False


def test_canary_nested_key_and_bool_rejected(canary):
    node = canary(config={"metric_key": "eval.acc"})
    assert _out(node, {"metrics": {"eval": {"acc": 0.7}}}).promote is True
    assert _out(canary(config={"metric_key": "ok"}), {"metrics": {"ok": True}}).promote is False


def test_canary_nonfinite_baseline_holds(canary):
    d = _out(canary(config={"metric_key": "acc"}), {"metrics": {"acc": 0.9}, "baseline": {"acc": math.inf}})
    assert d.promote is False and "baseline" in d.reason


# ── 2. drift_detect ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def drift():
    return _load("drift_detect")


def _ds(X):
    return DatasetArtifact(X_train=X, y_train=np.zeros(len(X), dtype=np.int32))


def test_drift_dataset_artifact_per_feature(drift):
    rng = np.random.default_rng(0)
    ref = rng.normal(size=(2000, 3))
    cur = ref.copy()
    cur[:, 2] += 3.0  # only feature 2 drifts
    rep = _out(drift(config={}), {"reference": _ds(ref), "current": _ds(cur)})
    assert rep.drifted is True
    pf = rep.scores["per_feature"]
    assert set(pf) == {"f0", "f1", "f2"}
    assert pf["f0"] == pytest.approx(0.0, abs=1e-9) and pf["f2"] > 1.0
    assert rep.scores["drifted_features"] == ["f2"]
    assert rep.scores["psi"] == rep.scores["score"] == max(pf.values())


def test_drift_no_drift_same_distribution(drift):
    rng = np.random.default_rng(1)
    rep = _out(drift(config={}), {"reference": rng.normal(size=(3000, 2)), "current": rng.normal(size=(3000, 2))})
    assert rep.drifted is False and rep.scores["score"] < 0.1


def test_drift_ks_method(drift):
    rng = np.random.default_rng(2)
    node = drift(config={"method": "ks", "threshold": 0.1})
    rep = _out(node, {"reference": rng.normal(size=500).tolist(), "current": (rng.normal(size=500) + 1).tolist()})
    assert rep.scores["method"] == "ks" and rep.drifted is True
    assert rep.scores["p_values"]["f0"] < 1e-6
    same = _out(node, {"reference": [1.0, 2.0, 3.0] * 50, "current": [1.0, 2.0, 3.0] * 50})
    assert same.scores["ks"] == 0.0 and same.drifted is False


def test_drift_unknown_method_rejected(drift):
    node = drift(config={"method": "psi"})
    node.config.method = "wasserstein"  # bypass Literal to hit the runtime guard
    with pytest.raises(ValueError, match="unsupported method"):
        node.process({"reference": [1.0, 2.0], "current": [1.0, 2.0]})


def test_drift_empty_raises(drift):
    with pytest.raises(ValueError):
        drift(config={}).process({"reference": [], "current": [1.0]})
    with pytest.raises(ValueError):
        drift(config={}).process({"reference": DatasetArtifact(), "current": DatasetArtifact()})


def test_drift_records_and_mismatch(drift):
    ref = [{"a": float(i), "b": 1.0} for i in range(100)]
    cur = [{"a": float(i), "b": 1.0} for i in range(100)]
    rep = _out(drift(config={}), {"reference": ref, "current": cur})
    assert set(rep.scores["per_feature"]) == {"a", "b"} and rep.drifted is False
    with pytest.raises(ValueError, match="feature count"):
        drift(config={}).process({"reference": np.zeros((5, 2)), "current": np.zeros((5, 3))})


def test_drift_constant_reference_detects_shift(drift):
    rep = _out(drift(config={}), {"reference": [0.0] * 100, "current": [5.0] * 100})
    assert rep.drifted is True


def test_drift_zero_threshold_allowed(drift):
    rep = _out(drift(config={"threshold": 0.0}), {"reference": [1.0, 2.0, 3.0], "current": [1.0, 2.0, 3.0]})
    assert rep.scores["threshold"] == 0.0 and rep.drifted is True


# ── 3. dataset_diff ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ddiff():
    return _load("dataset_diff")


def _dsxy(X, y):
    return DatasetArtifact(X_train=np.asarray(X, dtype=np.float32), y_train=np.asarray(y, dtype=np.int32), labels=["a", "b"])


def test_diff_identical_equal(ddiff):
    X = np.arange(12, dtype=np.float32).reshape(4, 3)
    r = _out(ddiff(config={"fail_on_drift": True}), {"left": _dsxy(X, [0, 1, 0, 1]), "right": _dsxy(X.copy(), [0, 1, 0, 1])})
    assert (r.added, r.removed, r.changed) == (0, 0, 0) and r.details["equal"] is True


def test_diff_small_value_change_detected(ddiff):
    """Large arrays whose repr is truncated must still diff by content."""
    X = np.zeros((2000, 50), dtype=np.float32)
    X2 = X.copy()
    X2[1000, 25] = 1e-3
    y = np.zeros(2000, dtype=np.int32)
    r = _out(ddiff(config={}), {"left": _dsxy(X, y), "right": _dsxy(X2, y)})
    assert r.added == 1 and r.removed == 1 and r.details["equal"] is False
    assert r.details["splits"]["train"]["left"]["content_hash"] != r.details["splits"]["train"]["right"]["content_hash"]
    with pytest.raises(RuntimeError, match="drift detected"):
        ddiff(config={"fail_on_drift": True}).process({"left": _dsxy(X, y), "right": _dsxy(X2, y)})


def test_diff_added_rows_counted(ddiff):
    X = np.arange(6, dtype=np.float32).reshape(3, 2)
    X2 = np.vstack([X, [[100, 101], [102, 103]]])
    r = _out(ddiff(config={}), {"left": _dsxy(X, [0, 1, 0]), "right": _dsxy(X2, [0, 1, 0, 1, 1])})
    assert (r.added, r.removed, r.changed) == (2, 0, 0)


def test_diff_label_change_detected(ddiff):
    X = np.arange(6, dtype=np.float32).reshape(3, 2)
    r = _out(ddiff(config={}), {"left": _dsxy(X, [0, 1, 0]), "right": _dsxy(X, [0, 1, 1])})
    assert r.added == 1 and r.removed == 1


def test_diff_records_with_hash_fields(ddiff):
    left = [{"id": 1, "v": "a"}, {"id": 2, "v": "b"}, {"id": 3, "v": "c"}]
    right = [{"id": 1, "v": "a"}, {"id": 2, "v": "B"}, {"id": 4, "v": "d"}]
    r = _out(ddiff(config={"hash_fields": ["id"]}), {"left": left, "right": right})
    assert (r.added, r.removed, r.changed) == (1, 1, 1)
    with pytest.raises(ValueError, match="lacks hash_fields"):
        ddiff(config={"hash_fields": ["id"]}).process({"left": left, "right": [{"v": "x"}]})


def test_diff_records_reordered_equal(ddiff):
    rows = [{"id": i} for i in range(5)]
    r = _out(ddiff(config={}), {"left": rows, "right": list(reversed(rows))})
    assert (r.added, r.removed) == (0, 0)


# ── 4. artifact_checksum ──────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def cksum():
    return _load("artifact_checksum")


def test_checksum_model_artifact_hashes_file(cksum, tmp_path):
    f = tmp_path / "model.keras"
    f.write_bytes(b"weights" * 1000)
    rec = _out(cksum(config={"write_sidecar": True}), {"input": ModelArtifact(model_path=str(f))})
    assert rec.digest == hashlib.sha256(f.read_bytes()).hexdigest() and rec.path == str(f)
    assert (tmp_path / "model.keras.sha256").read_text().split()[0] == rec.digest


def test_checksum_deployment_artifact_path(cksum, tmp_path):
    f = tmp_path / "m.tflite"
    f.write_bytes(b"\x00\x01tflite")
    rec = _out(cksum(config={"algo": "md5", "write_sidecar": False}), {"input": DeploymentArtifact(artifact_path=str(f))})
    assert rec.digest == hashlib.md5(f.read_bytes()).hexdigest() and rec.algo == "md5"


def test_checksum_directory_content_sensitive(cksum, tmp_path):
    d = tmp_path / "saved"
    (d / "sub").mkdir(parents=True)
    (d / "a.bin").write_bytes(b"A")
    (d / "sub" / "b.bin").write_bytes(b"B")
    node = cksum(config={"write_sidecar": False})
    d1 = _out(node, {"input": {"path": str(d)}}).digest
    assert d1 == _out(node, {"input": {"path": str(d)}}).digest
    (d / "sub" / "b.bin").write_bytes(b"C")
    assert _out(node, {"input": {"path": str(d)}}).digest != d1
    assert d1 != hashlib.sha256(str(d).encode()).hexdigest()


def test_checksum_rejects_unknown_and_shake(cksum, tmp_path):
    f = tmp_path / "x"
    f.write_bytes(b"x")
    for algo in ("shake_128", "nope"):
        node = cksum(config={})
        node.config.algo = algo  # bypass Literal to hit runtime guard
        with pytest.raises(ValueError, match="unsupported algo"):
            node.process({"input": {"path": str(f)}})


def test_checksum_missing_path_and_metadata_only(cksum, tmp_path):
    with pytest.raises(FileNotFoundError):
        cksum(config={}).process({"input": ModelArtifact(model_path=str(tmp_path / "missing.pt"))})
    with pytest.raises(ValueError, match="no file path"):
        cksum(config={}).process({"input": ModelArtifact()})


def test_checksum_algo_enum_in_toml():
    data = tomllib.loads((MLOPS / "artifact_checksum" / "plugin.toml").read_text())
    enum = data["config_schema"]["artifact_checksum"]["algo"]["enum"]
    assert "sha256" in enum and not any(a.startswith("shake") for a in enum)


# ── 5. ab_assign ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ab():
    return _load("ab_assign")


def test_ab_default_splits_both_variants(ab):
    node = ab(config={})
    seen = {_out(node, {"input": f"user-{i}"}).variant for i in range(200)}
    assert seen == {"control", "treatment"}


def test_ab_deterministic_and_unit_field(ab):
    node = ab(config={"unit_id_field": "user_id"})
    a = _out(node, {"input": {"user_id": "u42", "other": 1}})
    b = _out(node, {"input": {"user_id": "u42", "other": 2}})
    assert a.variant == b.variant and a.unit_id == "u42"
    with pytest.raises(ValueError, match="lacks 'user_id'"):
        node.process({"input": {"id": "u42"}})


def test_ab_weight_validation(ab):
    with pytest.raises(ValueError, match="weights for"):
        ab(config={"variants": ["a", "b", "c"], "weights": [0.5, 0.5]}).process({"input": "u"})
    with pytest.raises(ValueError, match="non-negative"):
        ab(config={"variants": ["a", "b"], "weights": [-1, 2]}).process({"input": "u"})
    node = ab(config={"variants": ["a", "b"], "weights": [0, 1]})
    assert {_out(node, {"input": f"u{i}"}).variant for i in range(100)} == {"b"}


def test_ab_toml_defaults_in_sync():
    spec = tomllib.loads((MLOPS / "ab_assign" / "plugin.toml").read_text())["config_schema"]["ab_assign"]
    assert spec["variants"]["default"] == ["control", "treatment"]
    assert spec["weights"]["default"] == [0.5, 0.5]
    assert spec["unit_id_field"]["default"] == "unit_id"


# ── 6. ship_package_* ─────────────────────────────────────────────────────────


@pytest.fixture()
def ship_project(tmp_path, monkeypatch):
    import app.core.config as cfg

    monkeypatch.setattr(cfg, "project_dir", lambda: tmp_path)
    return tmp_path


def test_ship_create_uses_input_values_and_dict_target(ship_project, monkeypatch):
    import app.core.mlops.ship_packages as sp

    captured = {}

    def fake_create(project_dir, **kw):
        captured.update(kw)
        return {"package_id": "p1", "status": "built"}

    monkeypatch.setattr(sp, "create_package", fake_create)
    cls = _load("ship_package_create")
    dep = {"project": "kws", "model_name": "ds_cnn", "model_stage_or_version": "v3",
           "target": {"runtime": "tflite", "arch": "arm"}}
    ref = _out(cls(config={}), {"deployment": dep})
    assert captured["project_name"] == "kws" and captured["model_name"] == "ds_cnn"
    assert captured["model_stage_or_version"] == "v3"
    assert captured["target"] == {"runtime": "tflite", "arch": "arm"}
    assert ref.package_id == "p1"
    # Config dict target is used as a dict, not stringified into runtime.
    _out(cls(config={"target": {"runtime": "onnx", "arch": "x86"}, "project": "cfgproj"}), {"deployment": dep})
    assert captured["target"] == {"runtime": "onnx", "arch": "x86"} and captured["project_name"] == "cfgproj"
    # DeploymentArtifact: model_format/target_hardware become the target.
    _out(cls(config={}), {"deployment": DeploymentArtifact(model_format="tflite", target_hardware="edge")})
    assert captured["target"] == {"runtime": "tflite", "arch": "edge"}
    assert captured["project_name"] == "default" and captured["model_stage_or_version"] == "latest"


def test_ship_transition_empty_resource_version_is_none(ship_project, monkeypatch):
    import app.core.mlops.ship_packages as sp

    seen = {}

    def fake_transition(project_dir, package_id, action, **kw):
        seen.update(kw, package_id=package_id, action=action)
        return {"package_id": package_id, "status": "validated"}

    monkeypatch.setattr(sp, "transition_package", fake_transition)
    cls = _load("ship_package_transition")
    ref = _out(cls(config={"action": "validate"}), {"package": {"package_id": "p1"}})
    assert seen["expected_resource_version"] is None and ref.state == "validated"
    _out(cls(config={"resource_version": "7"}), {"package": {"package_id": "p1"}})
    assert seen["expected_resource_version"] == "7"
    with pytest.raises(ValueError, match="package_id"):
        cls(config={}).process({"package": {}})


# ── 7. feature_store_write / read ─────────────────────────────────────────────


def test_feature_store_requires_entity_key(tmp_path):
    W = _load("feature_store_write")
    store = tmp_path / "fs.json"
    with pytest.raises(ValueError, match="entity key"):
        W(config={"persist_path": str(store)}).process({"features": [{"x": 1}]})


def test_feature_store_no_cross_batch_overwrite_content_hash(tmp_path):
    W = _load("feature_store_write")
    R = _load("feature_store_read")
    store = tmp_path / "fs.json"
    w = W(config={"persist_path": str(store), "entity_keys": []})
    _out(w, {"features": [{"x": 1}]})
    _out(w, {"features": [{"x": 2}]})
    rows = _out(R(config={"persist_path": str(store)}), {"store": {"path": str(store)}, "keys": []})
    assert sorted(r["x"] for r in rows) == [1, 2]


def test_feature_store_numpy_lossless_and_as_of(tmp_path):
    W = _load("feature_store_write")
    R = _load("feature_store_read")
    store = tmp_path / "fs.json"
    w = W(config={"persist_path": str(store), "entity_keys": ["id"], "event_time_field": "ts"})
    big = np.arange(2000, dtype=np.float32)
    _out(w, {"features": [{"id": "e1", "ts": "2026-01-01T00:00:00+00:00", "v": big}]})
    ref = _out(w, {"features": [{"id": "e1", "ts": "2026-03-01T00:00:00+00:00", "v": [0.0]}]})
    assert ref.metadata["entities"] == 1
    latest = _out(R(config={}), {"store": ref, "keys": ["e1"]})
    assert latest[0]["v"] == [0.0]
    past = _out(R(config={"as_of": "2026-02-01T00:00:00Z"}), {"store": ref, "keys": ["e1"]})
    assert len(past[0]["v"]) == 2000 and past[0]["v"][-1] == 1999.0
    before = _out(R(config={"as_of": "2025-01-01T00:00:00Z"}), {"store": ref, "keys": ["e1"]})
    assert before == []


def test_feature_store_reads_legacy_flat_store(tmp_path):
    R = _load("feature_store_read")
    store = tmp_path / "legacy.json"
    store.write_text(json.dumps({"a": {"id": "a", "v": 1}}))
    assert _out(R(config={}), {"store": {"path": str(store)}, "keys": ["a"]}) == [{"id": "a", "v": 1}]


def test_feature_store_read_missing_store_path(tmp_path):
    R = _load("feature_store_read")
    with pytest.raises(FileNotFoundError):
        R(config={"persist_path": ""}).process({"store": {}, "keys": []})


# ── 10. every declared output port is returned ───────────────────────────────


@pytest.mark.parametrize(
    "plugin, inputs",
    [
        ("canary_gate", {"metrics": {"test_accuracy": 0.9}}),
        ("drift_detect", {"reference": [1.0, 2.0], "current": [1.0, 2.0]}),
        ("dataset_diff", {"left": [{"a": 1}], "right": [{"a": 1}]}),
        ("ab_assign", {"input": "u1"}),
    ],
)
def test_declared_output_ports_returned(plugin, inputs):
    cls = _load(plugin)
    out = cls(config={}).process(inputs)
    assert set(cls.output_ports) <= set(out)
