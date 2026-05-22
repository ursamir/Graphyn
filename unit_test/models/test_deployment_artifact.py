# unit_test/models/test_deployment_artifact.py
"""Unit tests for DeploymentArtifact — Req 17 criteria 14–15, 17."""
from __future__ import annotations

from app.models.deployment_artifact import DeploymentArtifact
from app.core.nodes.ports import PortDataType


# ── Criterion 14: default construction ───────────────────────────────────────

def test_construction_defaults():
    """DeploymentArtifact() constructs with all-default values without raising."""
    artifact = DeploymentArtifact()
    assert artifact.artifact_path == ""
    assert artifact.model_format == ""
    assert artifact.target_hardware == "cpu"
    assert artifact.quantization == "none"
    assert artifact.labels == []
    assert artifact.metadata == {}
    assert artifact.file_size_bytes == 0
    assert artifact.benchmark is None


# ── Criterion 15: PortDataType subclass ──────────────────────────────────────

def test_deployment_artifact_is_port_data_type_subclass():
    """DeploymentArtifact is a subclass of PortDataType."""
    assert issubclass(DeploymentArtifact, PortDataType)


def test_deployment_artifact_instance_is_port_data_type():
    """DeploymentArtifact instances are instances of PortDataType."""
    artifact = DeploymentArtifact()
    assert isinstance(artifact, PortDataType)


# ── Criterion 17: labels and metadata default to empty list/dict (not shared) ─

def test_labels_default_to_empty_list():
    """labels defaults to an empty list."""
    artifact = DeploymentArtifact()
    assert artifact.labels == []


def test_metadata_default_to_empty_dict():
    """metadata defaults to an empty dict."""
    artifact = DeploymentArtifact()
    assert artifact.metadata == {}


def test_labels_not_shared_between_instances():
    """Two DeploymentArtifact instances do not share the same labels list."""
    a = DeploymentArtifact()
    b = DeploymentArtifact()
    a.labels.append("cat")
    assert b.labels == []


def test_metadata_not_shared_between_instances():
    """Two DeploymentArtifact instances do not share the same metadata dict."""
    a = DeploymentArtifact()
    b = DeploymentArtifact()
    a.metadata["key"] = "value"
    assert b.metadata == {}
