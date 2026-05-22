# unit_test/models/test_model_artifact.py
"""Unit tests for ModelArtifact — Req 17 criteria 14–15."""
from __future__ import annotations

from app.models.model_artifact import ModelArtifact
from app.core.nodes.ports import PortDataType


# ── Criterion 14: default construction ───────────────────────────────────────

def test_construction_defaults():
    """ModelArtifact() constructs with all-default values without raising."""
    artifact = ModelArtifact()
    assert artifact.model_path == ""
    assert artifact.labels == []
    assert artifact.history == {}
    assert artifact.metrics == {}


# ── Criterion 15: PortDataType subclass ──────────────────────────────────────

def test_model_artifact_is_port_data_type_subclass():
    """ModelArtifact is a subclass of PortDataType."""
    assert issubclass(ModelArtifact, PortDataType)


def test_model_artifact_instance_is_port_data_type():
    """ModelArtifact instances are instances of PortDataType."""
    artifact = ModelArtifact()
    assert isinstance(artifact, PortDataType)


# ── No shared mutable defaults ────────────────────────────────────────────────

def test_labels_not_shared_between_instances():
    """Two ModelArtifact instances do not share the same labels list."""
    a = ModelArtifact()
    b = ModelArtifact()
    a.labels.append("cat")
    assert b.labels == []


def test_history_not_shared_between_instances():
    """Two ModelArtifact instances do not share the same history dict."""
    a = ModelArtifact()
    b = ModelArtifact()
    a.history["loss"] = [0.5]
    assert b.history == {}


def test_metrics_not_shared_between_instances():
    """Two ModelArtifact instances do not share the same metrics dict."""
    a = ModelArtifact()
    b = ModelArtifact()
    a.metrics["accuracy"] = 0.9
    assert b.metrics == {}
