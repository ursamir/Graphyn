# unit_test/models/test_prediction_result.py
"""Unit tests for PredictionResult — Req 17 criteria 14–15."""
from __future__ import annotations

from app.models.prediction_result import PredictionResult
from app.core.nodes.ports import PortDataType


# ── Criterion 14: default construction ───────────────────────────────────────

def test_construction_defaults():
    """PredictionResult() constructs with all-default values without raising."""
    result = PredictionResult()
    assert result.source_path == ""
    assert result.predicted_label == ""
    assert result.probabilities == {}
    assert result.metadata == {}


# ── Criterion 15: PortDataType subclass ──────────────────────────────────────

def test_prediction_result_is_port_data_type_subclass():
    """PredictionResult is a subclass of PortDataType."""
    assert issubclass(PredictionResult, PortDataType)


def test_prediction_result_instance_is_port_data_type():
    """PredictionResult instances are instances of PortDataType."""
    result = PredictionResult()
    assert isinstance(result, PortDataType)


# ── No shared mutable defaults ────────────────────────────────────────────────

def test_probabilities_not_shared_between_instances():
    """Two PredictionResult instances do not share the same probabilities dict."""
    a = PredictionResult()
    b = PredictionResult()
    a.probabilities["cat"] = 0.9
    assert b.probabilities == {}


def test_metadata_not_shared_between_instances():
    """Two PredictionResult instances do not share the same metadata dict."""
    a = PredictionResult()
    b = PredictionResult()
    a.metadata["key"] = "value"
    assert b.metadata == {}
