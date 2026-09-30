"""Runtime fixes: PipelineCache content hashing and all-or-nothing entries."""
from __future__ import annotations

import json
from typing import Any, Optional

import numpy as np
import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.core.execution.pipeline_cache import PipelineCache


class _Sample(BaseModel):
    """AudioSample-shaped model (duck-typed — the platform never imports AudioSample)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    path: str
    sample_rate: int
    data: Optional[Any] = None
    label: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


def _s(**kw) -> _Sample:
    base = dict(path="/a.wav", sample_rate=16000, data=np.ones(8, dtype=np.float32), label="yes")
    base.update(kw)
    return _Sample(**base)


@pytest.fixture
def cache(tmp_path):
    c = PipelineCache()
    c.BASE = tmp_path / "cache"
    return c


def test_input_hash_covers_data_label_metadata(cache):
    h = cache.input_hash
    base = h([_s()])
    assert h([_s()]) == base  # deterministic
    assert h([_s(data=np.ones(8, dtype=np.float32) * 0.5)]) != base  # gain change
    assert h([_s(label="no")]) != base  # relabel
    assert h([_s(metadata={"speaker": "b"})]) != base
    assert h([_s(data=np.ones(8, dtype=np.float64))]) != base  # dtype
    assert h([_s(data=np.ones((2, 4), dtype=np.float32))]) != base  # shape


def test_input_hash_single_model_and_arrays(cache):
    assert cache.input_hash(_s()) != cache.input_hash(_s(label="x"))
    a = np.arange(4, dtype=np.int32)
    assert cache.input_hash(a) == cache.input_hash(a.copy())
    assert cache.input_hash(a) != cache.input_hash(a.astype(np.int64))
    assert cache.input_hash({"k": [1, 2]}) != cache.input_hash({"k": [2, 1]})


def test_unhashable_input_forces_miss(cache):
    obj = object()
    assert cache.input_hash(obj).startswith("miss-")
    assert cache.input_hash(obj) != cache.input_hash(obj)


def test_compute_key_includes_port_names(cache):
    x = [_s()]
    k1 = cache.compute_key("t", {}, {"input": x, "reference": None})
    k2 = cache.compute_key("t", {}, {"reference": x, "input": None})
    assert k1 != k2
    # Insertion order does not matter.
    k3 = cache.compute_key("t", {}, {"reference": None, "input": x})
    assert k1 == k3


def test_non_serializable_port_writes_no_entry(cache):
    key = "k-nonser"
    cache.save(key, {"good": {"v": 1}, "bad": object()})
    assert cache.load(key) is None
    assert not (cache.BASE / key).exists()


def test_load_misses_when_a_recorded_port_is_missing(cache):
    key = "k-partial"
    cache.save(key, {"a": 1, "b": [1, 2]})
    assert cache.load(key) == {"a": 1, "b": [1, 2]}
    outputs_path = cache.BASE / key / "outputs.json"
    data = json.loads(outputs_path.read_text())
    del data["b"]
    outputs_path.write_text(json.dumps(data))
    assert cache.load(key) is None


def test_legacy_entry_without_inventory_is_a_miss(cache):
    key = "k-legacy"
    d = cache.BASE / key
    d.mkdir(parents=True)
    (d / "outputs.json").write_text(json.dumps({"a": 1}))
    assert cache.load(key) is None


def test_none_valued_port_round_trips(cache):
    key = "k-none"
    cache.save(key, {"output": [1], "error": None})
    assert cache.load(key) == {"output": [1], "error": None}
