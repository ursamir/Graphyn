# unit_test/models/test_feature_array.py
"""Unit tests for FeatureArray — Req 17 criteria 6–8."""
from __future__ import annotations

import numpy as np
import pytest

from app.models.feature_array import FeatureArray
from app.core.nodes.ports import PortDataType


# ── Criterion 6: default construction ────────────────────────────────────────

def test_construction_defaults():
    """FeatureArray() constructs with data as empty float32 2-D array, label='', feature_type=''."""
    fa = FeatureArray()
    assert isinstance(fa.data, np.ndarray)
    assert fa.data.dtype == np.float32
    assert fa.data.ndim == 2
    assert fa.data.shape == (0, 0)
    assert fa.label == ""
    assert fa.feature_type == ""


# ── Criterion 7: None → zeros((0,0), float32) ────────────────────────────────

def test_none_data_coerced_to_zeros_2d():
    """data=None is coerced to np.zeros((0,0), dtype=np.float32)."""
    fa = FeatureArray(data=None)
    assert isinstance(fa.data, np.ndarray)
    assert fa.data.dtype == np.float32
    assert fa.data.shape == (0, 0)
    np.testing.assert_array_equal(fa.data, np.zeros((0, 0), dtype=np.float32))


# ── Criterion 8: PortDataType subclass ───────────────────────────────────────

def test_feature_array_is_port_data_type_subclass():
    """FeatureArray is a subclass of PortDataType."""
    assert issubclass(FeatureArray, PortDataType)


def test_feature_array_instance_is_port_data_type():
    """FeatureArray instances are instances of PortDataType."""
    fa = FeatureArray()
    assert isinstance(fa, PortDataType)


# ── Extra: explicit 2-D data is preserved ────────────────────────────────────

def test_explicit_2d_data_preserved():
    """Passing a 2-D list is coerced to float32 ndarray with correct shape."""
    fa = FeatureArray(data=[[1.0, 2.0], [3.0, 4.0]])
    assert fa.data.shape == (2, 2)
    assert fa.data.dtype == np.float32
