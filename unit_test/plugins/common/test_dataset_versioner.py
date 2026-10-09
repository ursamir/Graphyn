# unit_test/plugins/common/test_dataset_versioner.py
"""Tests for the restored dataset_versioner plugin (F20).

Real behaviour: content hash over every split, manifest.csv + lineage.json in
<output_dir>/<version_tag>, optional dataset.npz snapshot, refusal to overwrite
a version with different content, and rejection of hash-style tags.
"""
from __future__ import annotations

import csv
import json

import numpy as np
import pytest

from app.core.plugins.manager import PluginManager
from unit_test.plugins._helpers import materialize_isolated_class

PLUGIN_SOURCE = "PluginPackage/Common/dataset_versioner/"
NODE_TYPE = "dataset_versioner"


def _dataset(seed: int = 0):
    try:
        from dataset_builder.types import DatasetArtifact  # type: ignore
    except ImportError:
        from PluginPackage.Common.dataset_builder.types import DatasetArtifact  # type: ignore
    rng = np.random.default_rng(seed)
    return DatasetArtifact(
        X_train=rng.standard_normal((6, 4, 2, 1)).astype(np.float32),
        y_train=np.array([0, 1, 0, 1, 0, 1], dtype=np.int32),
        X_val=rng.standard_normal((2, 4, 2, 1)).astype(np.float32),
        y_val=np.array([0, 1], dtype=np.int32),
        X_test=rng.standard_normal((2, 4, 2, 1)).astype(np.float32),
        y_test=np.array([0, 1], dtype=np.int32),
        labels=["no", "yes"],
        n_classes=2,
    )


@pytest.fixture(scope="module")
def installed_cls(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("dataset_versioner_plugins")
    from app.core.nodes.registry import NodeRegistry

    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp_dir))
    mgr._plugins_dir = str(tmp_dir)
    mgr.install(PLUGIN_SOURCE)
    return materialize_isolated_class(reg.get_class(NODE_TYPE))


def test_registered(installed_cls):
    assert installed_cls.node_type == NODE_TYPE
    assert set(installed_cls.input_ports) == {"input"}
    assert set(installed_cls.output_ports) == {"output"}


def test_writes_manifest_and_lineage(installed_cls, tmp_path):
    node = installed_cls(config={"output_dir": str(tmp_path), "version_tag": "v1"}, seed=0)
    out = node.process({"input": _dataset()})["output"]
    vdir = tmp_path / "v1"
    lineage = json.loads((vdir / "lineage.json").read_text())
    rows = list(csv.DictReader((vdir / "manifest.csv").open()))
    assert len(lineage["hash"]) == 64
    assert len(rows) == 10  # 6 train + 2 val + 2 test
    assert {r["split"] for r in rows} == {"train", "val", "test"}
    assert out.metadata["versioner"]["content_hash"] == lineage["hash"]
    assert not (vdir / "dataset.npz").exists()


def test_hash_is_deterministic_and_content_sensitive(installed_cls, tmp_path):
    a = installed_cls(config={"output_dir": str(tmp_path / "a")}, seed=0).process({"input": _dataset(0)})["output"]
    b = installed_cls(config={"output_dir": str(tmp_path / "b")}, seed=0).process({"input": _dataset(0)})["output"]
    c = installed_cls(config={"output_dir": str(tmp_path / "c")}, seed=0).process({"input": _dataset(1)})["output"]
    ha, hb, hc = (x.metadata["versioner"]["content_hash"] for x in (a, b, c))
    assert ha == hb
    assert ha != hc


def test_snapshot_round_trips(installed_cls, tmp_path):
    ds = _dataset()
    installed_cls(config={"output_dir": str(tmp_path), "create_snapshot": True}, seed=0).process({"input": ds})["output"]
    snap = np.load(tmp_path / "v1" / "dataset.npz")
    np.testing.assert_array_equal(snap["X_train"], ds.X_train)


def test_refuses_to_overwrite_different_content(installed_cls, tmp_path):
    cfg = {"output_dir": str(tmp_path), "version_tag": "v2"}
    installed_cls(config=cfg, seed=0).process({"input": _dataset(0)})["output"]
    installed_cls(config=cfg, seed=0).process({"input": _dataset(0)})["output"]  # identical re-run is fine
    with pytest.raises(FileExistsError, match="different content"):
        installed_cls(config=cfg, seed=0).process({"input": _dataset(1)})["output"]
    installed_cls(config={**cfg, "overwrite": True}, seed=0).process({"input": _dataset(1)})["output"]


def test_rejects_hash_style_tag(installed_cls, tmp_path):
    node = installed_cls(config={"output_dir": str(tmp_path), "version_tag": "v_abc123"}, seed=0)
    with pytest.raises(ValueError, match="vN"):
        node.process({"input": _dataset()})["output"]
