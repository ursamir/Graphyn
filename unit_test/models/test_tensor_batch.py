# unit_test/models/test_tensor_batch.py
"""Unit tests for TensorBatch — Req 17 criteria 9–11."""
from __future__ import annotations

import numpy as np
import pytest

from app.models.tensor_batch import TensorBatch
from app.core.nodes.ports import PortDataType


# ── Criterion 9: default construction ────────────────────────────────────────

def test_construction_defaults():
    """TensorBatch() constructs with data as empty float32 array, labels=[], split=''."""
    tb = TensorBatch()
    assert isinstance(tb.data, np.ndarray)
    assert tb.data.dtype == np.float32
    assert tb.labels == []
    assert tb.split == ""


# ── Criterion 10: batch_size property ────────────────────────────────────────

def test_batch_size_empty():
    """batch_size returns 0 for empty data."""
    tb = TensorBatch()
    assert tb.batch_size == 0


def test_batch_size_with_data():
    """batch_size returns data.shape[0]."""
    data = np.zeros((5, 40), dtype=np.float32)
    tb = TensorBatch(data=data)
    assert tb.batch_size == 5


def test_batch_size_matches_shape():
    """batch_size == data.shape[0] for arbitrary batch sizes."""
    for n in [1, 3, 10, 100]:
        tb = TensorBatch(data=np.zeros((n, 20), dtype=np.float32))
        assert tb.batch_size == n


# ── Criterion 11: None → zeros((0,), float32) ────────────────────────────────

def test_none_data_coerced_to_zeros_1d():
    """data=None is coerced to np.zeros((0,), dtype=np.float32)."""
    tb = TensorBatch(data=None)
    assert isinstance(tb.data, np.ndarray)
    assert tb.data.dtype == np.float32
    assert tb.data.shape == (0,)
    np.testing.assert_array_equal(tb.data, np.zeros((0,), dtype=np.float32))


# ── PortDataType subclass ─────────────────────────────────────────────────────

def test_tensor_batch_is_port_data_type_subclass():
    """TensorBatch is a subclass of PortDataType."""
    assert issubclass(TensorBatch, PortDataType)
