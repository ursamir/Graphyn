"""Regression tests for Common/evaluator defect fixes.

``dataset_versioner`` was never shipped — versioning is ``audio_exporter`` +
``app.core.mlops.dataset_versions`` (see PluginPackage/NODES.md).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from app.core.nodes.discovery import AutoDiscovery
from app.core.nodes.registry import NodeRegistry
from app.models.dataset_artifact import DatasetArtifact
from app.models.model_artifact import ModelArtifact

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


# ── evaluator ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("model_path", ["", ".", "/", "  "])
def test_evaluator_missing_model_path_raises(model_path):
    pytest.importorskip("sklearn")
    cls = _load("evaluator", "evaluator")
    node = cls(config={})
    ds = DatasetArtifact(X_test=np.zeros((2, 3)), y_test=np.zeros(2), labels=["a", "b"])
    with pytest.raises(ValueError, match="no usable model_path"):
        node.process({"model_artifact": ModelArtifact(model_path=model_path), "dataset": ds})
