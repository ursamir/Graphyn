# unit_test/models/test_data_sample.py
"""Unit tests for DataSample — Req 17 criteria 14–16."""
from __future__ import annotations

from app.models.data_sample import DataSample
from app.core.nodes.ports import PortDataType


# ── Criterion 14: default construction ───────────────────────────────────────

def test_construction_defaults():
    """DataSample() constructs with all-default values without raising."""
    sample = DataSample()
    assert sample.id == ""
    assert sample.source == ""
    assert sample.metadata == {}


# ── Criterion 15: PortDataType subclass ──────────────────────────────────────

def test_data_sample_is_port_data_type_subclass():
    """DataSample is a subclass of PortDataType."""
    assert issubclass(DataSample, PortDataType)


def test_data_sample_instance_is_port_data_type():
    """DataSample instances are instances of PortDataType."""
    sample = DataSample()
    assert isinstance(sample, PortDataType)


# ── Criterion 16: id, source, metadata fields ────────────────────────────────

def test_id_default_is_empty_string():
    """DataSample().id == ''."""
    assert DataSample().id == ""


def test_source_default_is_empty_string():
    """DataSample().source == ''."""
    assert DataSample().source == ""


def test_metadata_default_is_empty_dict():
    """DataSample().metadata == {}."""
    assert DataSample().metadata == {}


def test_fields_can_be_set():
    """DataSample fields can be set at construction time."""
    sample = DataSample(id="abc", source="file.wav", metadata={"key": "val"})
    assert sample.id == "abc"
    assert sample.source == "file.wav"
    assert sample.metadata == {"key": "val"}


# ── No shared mutable defaults ────────────────────────────────────────────────

def test_metadata_not_shared_between_instances():
    """Two DataSample instances do not share the same metadata dict."""
    a = DataSample()
    b = DataSample()
    a.metadata["key"] = "value"
    assert b.metadata == {}
