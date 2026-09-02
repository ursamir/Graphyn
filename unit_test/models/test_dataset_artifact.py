# unit_test/models/test_dataset_artifact.py
"""Unit tests for platform DatasetArtifact."""
from __future__ import annotations

import numpy as np

from app.core.nodes.ports import PortDataType
from app.models.dataset_artifact import DatasetArtifact
from app.models import DatasetArtifact as Reexported


def test_construction_defaults():
    artifact = DatasetArtifact()
    assert artifact.labels == []
    assert artifact.input_shape == ()
    assert artifact.n_classes == 0
    assert artifact.version == ""
    assert artifact.content_hash == ""
    assert artifact.manifest_path == ""
    assert artifact.metadata == {}


def test_none_arrays_coerce_to_empty():
    artifact = DatasetArtifact(X_train=None, y_train=None, X_val=None, y_val=None, X_test=None, y_test=None)
    assert artifact.X_train.dtype == np.float32
    assert artifact.y_train.dtype == np.int32
    assert artifact.X_train.shape == (0,)
    assert artifact.y_train.shape == (0,)


def test_dataset_artifact_is_port_data_type_subclass():
    assert issubclass(DatasetArtifact, PortDataType)
    assert Reexported is DatasetArtifact


def test_labels_not_shared_between_instances():
    a = DatasetArtifact()
    b = DatasetArtifact()
    a.labels.append("cat")
    assert b.labels == []


def test_coerce_arrays():
    artifact = DatasetArtifact(
        X_train=[[1.0, 2.0]],
        y_train=[1],
        labels=["a", "b"],
        n_classes=2,
        input_shape=(2,),
    )
    assert artifact.X_train.dtype == np.float32
    assert artifact.y_train.dtype == np.int32
    assert artifact.n_classes == 2


def test_plugin_types_reexport_is_platform_class():
    from PluginPackage.Common.dataset_builder.types import DatasetArtifact as PluginDA
    assert PluginDA is DatasetArtifact
    assert PluginDA.__module__ == "app.models.dataset_artifact"
