"""Unit tests for app/core/pipeline_cache.py — Req 5 criteria 3–5."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.pipeline_cache import PipelineCache


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def cache(tmp_workspace: Path) -> PipelineCache:
    """Return a PipelineCache whose BASE points at the tmp workspace."""
    c = PipelineCache()
    c.BASE = tmp_workspace / "cache"
    return c


# ── Determinism ───────────────────────────────────────────────────────────────

def test_key_is_deterministic_for_identical_inputs(cache: PipelineCache):
    """Req 5.3 — key() returns the same string for identical inputs."""
    k1 = cache.key("audio_conditioner", {"target_sample_rate": 16000}, "abc123")
    k2 = cache.key("audio_conditioner", {"target_sample_rate": 16000}, "abc123")
    assert k1 == k2


def test_key_differs_for_different_node_types(cache: PipelineCache):
    """key() changes when node_type changes."""
    k1 = cache.key("audio_conditioner", {}, "abc")
    k2 = cache.key("segmenter", {}, "abc")
    assert k1 != k2


def test_key_differs_for_different_configs(cache: PipelineCache):
    """key() changes when config changes."""
    k1 = cache.key("audio_conditioner", {"target_sample_rate": 16000}, "abc")
    k2 = cache.key("audio_conditioner", {"target_sample_rate": 8000}, "abc")
    assert k1 != k2


def test_key_differs_for_different_input_hashes(cache: PipelineCache):
    """key() changes when input_hash changes."""
    k1 = cache.key("audio_conditioner", {}, "hash_a")
    k2 = cache.key("audio_conditioner", {}, "hash_b")
    assert k1 != k2


def test_key_is_hex_string(cache: PipelineCache):
    """key() returns a 64-character hex string (SHA-256)."""
    k = cache.key("audio_conditioner", {}, "abc")
    assert len(k) == 64
    assert all(c in "0123456789abcdef" for c in k)


# ── Round-trip ────────────────────────────────────────────────────────────────

def test_save_then_load_returns_equivalent_dict(cache: PipelineCache):
    """Req 5.4 — save(key, outputs) then load(key) returns equivalent dict."""
    key = cache.key("audio_conditioner", {}, "hash1")
    outputs = {"output": [1, 2, 3], "count": 3}
    cache.save(key, outputs)
    loaded = cache.load(key)
    assert loaded == outputs


def test_save_then_load_nested_dict(cache: PipelineCache):
    """Round-trip works for nested JSON-serializable dicts."""
    key = cache.key("segmenter", {"mode": "fixed"}, "hash2")
    outputs = {"output": {"a": 1, "b": [1, 2]}}
    cache.save(key, outputs)
    loaded = cache.load(key)
    assert loaded == outputs


def test_load_returns_none_for_missing_key(cache: PipelineCache):
    """load() returns None when the key has never been saved."""
    loaded = cache.load("nonexistent_key_xyz")
    assert loaded is None


def test_has_returns_true_after_save(cache: PipelineCache):
    """has() returns True after save()."""
    key = cache.key("audio_conditioner", {}, "hash3")
    cache.save(key, {"output": "value"})
    assert cache.has(key) is True


def test_has_returns_false_for_missing_key(cache: PipelineCache):
    """has() returns False for a key that was never saved."""
    assert cache.has("never_saved_key") is False


# ── Clear ─────────────────────────────────────────────────────────────────────

def test_clear_returns_entries_deleted_and_bytes_freed(cache: PipelineCache):
    """Req 5.5 — clear() returns dict with entries_deleted >= 0 and bytes_freed >= 0."""
    key = cache.key("audio_conditioner", {}, "hash4")
    cache.save(key, {"output": [1, 2, 3]})
    result = cache.clear()
    assert "entries_deleted" in result
    assert "bytes_freed" in result
    assert result["entries_deleted"] >= 0
    assert result["bytes_freed"] >= 0


def test_clear_removes_all_entries(cache: PipelineCache):
    """Req 5.5 — after clear(), has(key) returns False for all previously cached keys."""
    key1 = cache.key("audio_conditioner", {}, "hash5")
    key2 = cache.key("segmenter", {}, "hash6")
    cache.save(key1, {"output": "a"})
    cache.save(key2, {"output": "b"})
    cache.clear()
    assert cache.has(key1) is False
    assert cache.has(key2) is False


def test_clear_on_empty_cache_returns_zero_counts(cache: PipelineCache):
    """clear() on an empty cache returns entries_deleted=0 and bytes_freed=0."""
    result = cache.clear()
    assert result["entries_deleted"] == 0
    assert result["bytes_freed"] == 0


def test_clear_deletes_positive_entries_when_populated(cache: PipelineCache):
    """clear() reports entries_deleted > 0 when cache has entries."""
    key = cache.key("audio_conditioner", {}, "hash7")
    cache.save(key, {"output": "data"})
    result = cache.clear()
    assert result["entries_deleted"] > 0


# ── Property-based: key determinism ──────────────────────────────────────────

@settings(max_examples=100)
@given(
    node_type=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="_"),
        min_size=1,
        max_size=30,
    ),
    config=st.dictionaries(
        keys=st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnopqrstuvwxyz_"),
        values=st.one_of(st.integers(), st.floats(allow_nan=False, allow_infinity=False), st.text(max_size=20)),
        max_size=5,
    ),
    input_hash=st.text(min_size=1, max_size=64, alphabet="0123456789abcdef"),
)
def test_key_determinism_property(node_type: str, config: dict, input_hash: str):
    """Req 5.3 (property) — key() is deterministic for any valid inputs."""
    cache = PipelineCache()
    k1 = cache.key(node_type, config, input_hash)
    k2 = cache.key(node_type, config, input_hash)
    assert k1 == k2
    assert len(k1) == 64
