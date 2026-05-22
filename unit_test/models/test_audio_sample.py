# unit_test/models/test_audio_sample.py
"""Unit tests for AudioSample — Req 17 criteria 1–5."""
from __future__ import annotations

import numpy as np
import pytest
import pydantic

from app.models.audio_sample import AudioSample
from app.core.nodes.ports import PortDataType


# ── Criterion 1: default construction ────────────────────────────────────────

def test_construction_defaults():
    """AudioSample(path='x', sample_rate=16000) has float32 ndarray data, label='', metadata={}."""
    s = AudioSample(path="x", sample_rate=16000)
    assert isinstance(s.data, np.ndarray)
    assert s.data.dtype == np.float32
    assert s.label == ""
    assert s.metadata == {}


# ── Criterion 2: None → empty float32 array ──────────────────────────────────

def test_none_data_coerced_to_empty_float32():
    """data=None is coerced to an empty float32 ndarray."""
    s = AudioSample(path="x", sample_rate=16000, data=None)
    assert isinstance(s.data, np.ndarray)
    assert s.data.dtype == np.float32
    assert len(s.data) == 0


# ── Criterion 3: list → float32 ndarray ──────────────────────────────────────

def test_list_data_coerced_to_float32_ndarray():
    """data=[1.0, 2.0] is coerced to a float32 ndarray."""
    s = AudioSample(path="x", sample_rate=16000, data=[1.0, 2.0])
    assert isinstance(s.data, np.ndarray)
    assert s.data.dtype == np.float32
    np.testing.assert_array_equal(s.data, np.array([1.0, 2.0], dtype=np.float32))


# ── Criterion 4: model_validate round-trip ───────────────────────────────────

def test_model_validate_round_trip():
    """model_validate({'path':'x','sample_rate':8000}) round-trips via model_dump()."""
    raw = {"path": "x", "sample_rate": 8000}
    s = AudioSample.model_validate(raw)
    dumped = s.model_dump()
    assert dumped["path"] == "x"
    assert dumped["sample_rate"] == 8000
    # Re-validate from dump (data will be ndarray in dump — just check it reconstructs)
    s2 = AudioSample.model_validate({"path": dumped["path"], "sample_rate": dumped["sample_rate"]})
    assert s2.path == s.path
    assert s2.sample_rate == s.sample_rate


# ── Criterion 5: PortDataType subclass ───────────────────────────────────────

def test_audio_sample_is_port_data_type_subclass():
    """AudioSample is a subclass of PortDataType."""
    assert issubclass(AudioSample, PortDataType)


def test_audio_sample_instance_is_port_data_type():
    """AudioSample instances are instances of PortDataType."""
    s = AudioSample(path="x", sample_rate=16000)
    assert isinstance(s, PortDataType)
