# unit_test/models/test_tflite_artifact.py
"""Unit tests for TFLiteArtifact — Req 17 criteria 12–13."""
from __future__ import annotations

import pytest
import pydantic

from app.models.tflite_artifact import TFLiteArtifact
from app.core.nodes.ports import PortDataType


# ── Criterion 12: valid quantisation values ───────────────────────────────────

@pytest.mark.parametrize("q", ["float32", "float16", "int8"])
def test_valid_quantisation(q):
    """quantisation field accepts 'float32', 'float16', 'int8'."""
    artifact = TFLiteArtifact(quantisation=q)
    assert artifact.quantisation == q


def test_default_quantisation():
    """Default quantisation is 'float32'."""
    artifact = TFLiteArtifact()
    assert artifact.quantisation == "float32"


# ── Criterion 13: invalid quantisation raises ValidationError ─────────────────

def test_invalid_quantisation_raises():
    """quantisation='bad' raises pydantic.ValidationError."""
    with pytest.raises(pydantic.ValidationError):
        TFLiteArtifact(quantisation="bad")


@pytest.mark.parametrize("bad_q", ["fp32", "INT8", "bfloat16", "", "none"])
def test_various_invalid_quantisation_values_raise(bad_q):
    """Various invalid quantisation strings all raise pydantic.ValidationError."""
    with pytest.raises(pydantic.ValidationError):
        TFLiteArtifact(quantisation=bad_q)


# ── PortDataType subclass ─────────────────────────────────────────────────────

def test_tflite_artifact_is_port_data_type_subclass():
    """TFLiteArtifact is a subclass of PortDataType."""
    assert issubclass(TFLiteArtifact, PortDataType)
