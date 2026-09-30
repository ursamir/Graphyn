"""Regression tests for Common/evaluator + Common/dataset_versioner defect fixes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

from app.core.nodes.discovery import AutoDiscovery
from app.core.nodes.registry import NodeRegistry
from app.models.dataset_artifact import DatasetArtifact
from app.models.model_artifact import ModelArtifact

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "PluginPackage" / "Common"


def _load(plugin: str, node_type: str):
    root = COMMON / plugin
    reg = NodeRegistry()
    disc = AutoDiscovery(reg)
    for entry in ("types.py", "nodes.py"):
        if (root / entry).is_file():
            disc._process_module(disc._import_file(root / entry, package_prefix=None))
    return reg.get_class(node_type)


# ── 8. evaluator ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("model_path", ["", ".", "/", "  "])
def test_evaluator_missing_model_path_raises(model_path):
    pytest.importorskip("sklearn")
    cls = _load("evaluator", "evaluator")
    node = cls(config={})
    ds = DatasetArtifact(X_test=np.zeros((2, 3)), y_test=np.zeros(2), labels=["a", "b"])
    with pytest.raises(ValueError, match="no usable model_path"):
        node.process({"model_artifact": ModelArtifact(model_path=model_path), "dataset": ds})


# ── 9. dataset_versioner ──────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def versioner():
    return _load("dataset_versioner", "dataset_versioner")


def _ds(seed=0, **over):
    rng = np.random.default_rng(seed)
    kw = dict(
        X_train=rng.standard_normal((6, 2)).astype(np.float32),
        y_train=np.array([0, 1, 0, 1, 0, 1], dtype=np.int32),
        X_val=rng.standard_normal((2, 2)).astype(np.float32),
        y_val=np.array([0, 1], dtype=np.int32),
        labels=["a", "b"],
        n_classes=2,
    )
    kw.update(over)
    return DatasetArtifact(**kw)


def test_versioner_hash_split_boundary_sensitive(versioner, tmp_path):
    node = versioner(config={"output_dir": str(tmp_path)})
    X = np.arange(8, dtype=np.float32).reshape(4, 2)
    y = np.array([0, 1, 0, 1], dtype=np.int32)
    a = DatasetArtifact(X_train=X[:3], y_train=y[:3], X_val=X[3:], y_val=y[3:], labels=["a", "b"])
    b = DatasetArtifact(X_train=X[:2], y_train=y[:2], X_val=X[2:], y_val=y[2:], labels=["a", "b"])
    assert node._compute_hash(a) != node._compute_hash(b)


def test_versioner_hash_shape_and_labels_sensitive(versioner, tmp_path):
    node = versioner(config={"output_dir": str(tmp_path)})
    X = np.arange(8, dtype=np.float32)
    a = DatasetArtifact(X_train=X.reshape(4, 2))
    b = DatasetArtifact(X_train=X.reshape(2, 4))
    assert node._compute_hash(a) != node._compute_hash(b)
    c = DatasetArtifact(X_train=X.reshape(4, 2), labels=["ab", "c"])
    d = DatasetArtifact(X_train=X.reshape(4, 2), labels=["a", "bc"])
    assert node._compute_hash(c) != node._compute_hash(d)
    assert node._compute_hash(_ds(1)) == node._compute_hash(_ds(1))


def test_versioner_refuses_overwrite_different_content(versioner, tmp_path):
    cfg = {"output_dir": str(tmp_path), "version_tag": "v1"}
    versioner(config=cfg).process({"input": _ds(0)})
    lineage = json.loads((tmp_path / "v1" / "lineage.json").read_text())
    # Same content re-run is idempotent.
    versioner(config=cfg).process({"input": _ds(0)})
    with pytest.raises(FileExistsError, match="already exists"):
        versioner(config=cfg).process({"input": _ds(1)})
    # Pre-existing version survives the refusal.
    assert json.loads((tmp_path / "v1" / "lineage.json").read_text())["hash"] == lineage["hash"]
    out = versioner(config={**cfg, "overwrite": True}).process({"input": _ds(1)})["output"]
    assert json.loads((tmp_path / "v1" / "lineage.json").read_text())["hash"] == out.content_hash
    assert out.content_hash != lineage["hash"]


def test_versioner_never_rmtree_preexisting_on_failure(versioner, tmp_path, monkeypatch):
    vdir = tmp_path / "v2"
    vdir.mkdir()
    keep = vdir / "keep.txt"
    keep.write_text("precious")
    node = versioner(config={"output_dir": str(tmp_path), "version_tag": "v2", "overwrite": True})

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(node, "_write_lineage", boom)
    with pytest.raises(RuntimeError, match="disk full"):
        node.process({"input": _ds(0)})
    assert keep.read_text() == "precious"


def test_versioner_cleans_up_dir_it_created_on_failure(versioner, tmp_path, monkeypatch):
    node = versioner(config={"output_dir": str(tmp_path), "version_tag": "v3"})
    monkeypatch.setattr(node, "_write_lineage", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError):
        node.process({"input": _ds(0)})
    assert not (tmp_path / "v3").exists()


def test_versioner_mkdir_error_propagates(versioner, tmp_path):
    blocker = tmp_path / "file_not_dir"
    blocker.write_text("x")
    node = versioner(config={"output_dir": str(blocker), "version_tag": "v1"})
    with pytest.raises(OSError):
        node.process({"input": _ds(0)})


def test_versioner_toml_in_sync_with_config(versioner):
    spec = tomllib.loads((COMMON / "dataset_versioner" / "plugin.toml").read_text())["config_schema"]["dataset_versioner"]
    fields = versioner.Config.model_fields
    for name in ("output_dir", "project", "version_tag", "include_metadata", "create_snapshot", "overwrite"):
        assert name in spec and name in fields
        assert spec[name]["default"] == fields[name].default
