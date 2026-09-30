"""Unit tests for app/core/execution/validation.py — Req 4 criterion 9."""
from __future__ import annotations

import pytest

from app.core.execution.validation import validate_pipeline


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def registry():
    """Return the live NodeRegistry singleton."""
    from app.core.nodes import registry as _registry
    return _registry


# ── Valid configs ─────────────────────────────────────────────────────────────

@pytest.mark.requires_plugins
def test_valid_single_node_config(registry):
    """validate_pipeline returns a list for a valid single-node config."""
    config = {
        "pipeline": {
            "seed": 42,
            "nodes": [{"type": "audio_conditioner", "config": {}}],
        }
    }
    result = validate_pipeline(config, registry)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["type"] == "audio_conditioner"


@pytest.mark.requires_plugins
def test_valid_two_node_config(registry):
    """validate_pipeline returns two entries for a valid two-node config."""
    config = {
        "pipeline": {
            "seed": 0,
            "nodes": [
                {"type": "audio_conditioner", "config": {}},
                {"type": "segmenter", "config": {}},
            ],
        }
    }
    result = validate_pipeline(config, registry)
    assert len(result) == 2


@pytest.mark.requires_plugins
def test_valid_config_with_explicit_node_config_fields(registry):
    """validate_pipeline accepts valid explicit config fields."""
    config = {
        "pipeline": {
            "seed": 1,
            "nodes": [
                {
                    "type": "audio_conditioner",
                    "config": {"target_sample_rate": 8000, "mono": True},
                }
            ],
        }
    }
    result = validate_pipeline(config, registry)
    assert result[0]["config"]["target_sample_rate"] == 8000


# ── Invalid configs ───────────────────────────────────────────────────────────

def test_invalid_config_raises_for_unknown_node_type(registry):
    """validate_pipeline raises ValueError for unknown node type."""
    config = {
        "pipeline": {
            "seed": 42,
            "nodes": [{"type": "nonexistent_node_xyz", "config": {}}],
        }
    }
    with pytest.raises(ValueError, match="Unknown node type"):
        validate_pipeline(config, registry)


@pytest.mark.requires_plugins
def test_invalid_config_raises_for_bad_node_config(registry):
    """validate_pipeline raises ValueError for invalid node config."""
    config = {
        "pipeline": {
            "seed": 42,
            "nodes": [
                {
                    "type": "audio_conditioner",
                    "config": {"target_sample_rate": "bad_value"},
                }
            ],
        }
    }
    with pytest.raises(ValueError, match="Invalid config"):
        validate_pipeline(config, registry)


def test_invalid_config_raises_for_missing_pipeline_key(registry):
    """validate_pipeline raises ValueError when 'pipeline' key is absent."""
    with pytest.raises(ValueError, match="Missing 'pipeline'"):
        validate_pipeline({"other": {}}, registry)


def test_invalid_config_raises_for_non_dict_input(registry):
    """validate_pipeline raises ValueError when config is not a dict."""
    with pytest.raises(ValueError):
        validate_pipeline("not a dict", registry)


@pytest.mark.requires_plugins
def test_invalid_config_seed_optional_but_must_be_int(registry):
    """``pipeline.seed`` is optional (defaults downstream) but must be an int.

    Seed became optional in commit d725b7f; only a non-integer seed is rejected.
    """
    config = {
        "pipeline": {
            "nodes": [{"type": "audio_conditioner", "config": {}}],
        }
    }
    validate_pipeline(config, registry)
    config["pipeline"]["seed"] = "not-an-int"
    with pytest.raises(ValueError, match="seed"):
        validate_pipeline(config, registry)


def test_invalid_config_raises_for_empty_nodes(registry):
    """validate_pipeline raises ValueError when nodes list is empty."""
    config = {
        "pipeline": {
            "seed": 42,
            "nodes": [],
        }
    }
    with pytest.raises(ValueError):
        validate_pipeline(config, registry)


# ── DAG format ────────────────────────────────────────────────────────────────

@pytest.mark.requires_plugins
def test_dag_format_valid_config(registry):
    """validate_pipeline accepts a DAG-format config with explicit edges."""
    config = {
        "pipeline": {
            "seed": 42,
            "nodes": [
                {"id": "cond_0", "type": "audio_conditioner", "config": {}},
                {"id": "seg_1", "type": "segmenter", "config": {}},
            ],
            "edges": [
                {"from": ["cond_0", "output"], "to": ["seg_1", "input"]},
            ],
        }
    }
    result = validate_pipeline(config, registry)
    assert len(result) == 2


def test_dag_format_raises_for_unknown_edge_source(registry):
    """validate_pipeline raises ValueError when an edge references an unknown source node."""
    config = {
        "pipeline": {
            "seed": 42,
            "nodes": [
                {"id": "cond_0", "type": "audio_conditioner", "config": {}},
                {"id": "seg_1", "type": "segmenter", "config": {}},
            ],
            "edges": [
                {"from": ["nonexistent_node", "output"], "to": ["seg_1", "input"]},
            ],
        }
    }
    with pytest.raises(ValueError):
        validate_pipeline(config, registry)
