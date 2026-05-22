"""Unit tests for app/core/sdk.py — Req 5 criteria 1–2, 10–11."""
from __future__ import annotations

import pytest

from app.core.sdk import ArtifactCollection, Pipeline, PipelineNode


# ── PipelineNode validation ───────────────────────────────────────────────────

def test_pipeline_node_unknown_type_raises_value_error():
    """Req 5.1 — PipelineNode with unknown node_type raises ValueError."""
    with pytest.raises(ValueError, match="Unknown node type"):
        PipelineNode("this_node_type_does_not_exist_xyz")


def test_pipeline_node_invalid_config_raises_value_error():
    """Req 5.2 — PipelineNode with invalid config raises ValueError."""
    with pytest.raises(ValueError, match="Invalid config"):
        # target_sample_rate must be an int, not a string
        PipelineNode("audio_conditioner", {"target_sample_rate": "not_an_int"})


def test_pipeline_node_valid_type_and_config_constructs():
    """PipelineNode with valid type and default config constructs without error."""
    node = PipelineNode("audio_conditioner", {})
    assert node.node_type == "audio_conditioner"


def test_pipeline_node_valid_config_with_fields():
    """PipelineNode with valid explicit config constructs without error."""
    node = PipelineNode("audio_conditioner", {"target_sample_rate": 8000, "mono": False})
    assert node.config["target_sample_rate"] == 8000


def test_pipeline_node_error_message_lists_available_types():
    """ValueError for unknown type includes available types in message."""
    with pytest.raises(ValueError) as exc_info:
        PipelineNode("totally_unknown_node_xyz")
    assert "Available types" in str(exc_info.value)


# ── ArtifactCollection dict protocol ─────────────────────────────────────────

@pytest.fixture
def collection() -> ArtifactCollection:
    """Return an ArtifactCollection wrapping a simple raw dict."""
    return ArtifactCollection(
        artifacts=[],
        run_id="test-run-001",
        _raw={"output": [1, 2, 3], "count": 3},
    )


def test_artifact_collection_getitem_returns_raw_value(collection: ArtifactCollection):
    """Req 5.10 — __getitem__ returns the same value as the raw dict."""
    assert collection["output"] == [1, 2, 3]
    assert collection["count"] == 3


def test_artifact_collection_getitem_raises_key_error_for_missing(collection: ArtifactCollection):
    """__getitem__ raises KeyError for a missing key."""
    with pytest.raises(KeyError):
        _ = collection["nonexistent_key"]


def test_artifact_collection_contains(collection: ArtifactCollection):
    """__contains__ returns True for keys in the raw dict."""
    assert "output" in collection
    assert "missing" not in collection


def test_artifact_collection_keys(collection: ArtifactCollection):
    """keys() returns the raw dict keys."""
    assert set(collection.keys()) == {"output", "count"}


def test_artifact_collection_get_returns_raw_value(collection: ArtifactCollection):
    """get() returns the raw dict value when key is present."""
    assert collection.get("output") == [1, 2, 3]


def test_artifact_collection_get_returns_default_for_missing(collection: ArtifactCollection):
    """get() returns the default when key is missing."""
    assert collection.get("missing", "default") == "default"


def test_artifact_collection_repr_contains_run_id(collection: ArtifactCollection):
    """repr() includes the run_id."""
    assert "test-run-001" in repr(collection)


# ── ArtifactCollection.lineage ────────────────────────────────────────────────

def test_artifact_collection_lineage_never_raises_for_unknown_id(collection: ArtifactCollection):
    """Req 5 — lineage() never raises for unknown artifact IDs."""
    result = collection.lineage("completely_unknown_artifact_id_xyz")
    assert isinstance(result, dict)


def test_artifact_collection_lineage_returns_dict(collection: ArtifactCollection):
    """lineage() always returns a dict."""
    result = collection.lineage("any_id")
    assert isinstance(result, dict)


# ── Pipeline.subscribe ────────────────────────────────────────────────────────

def test_pipeline_subscribe_returns_callable():
    """Req 5.11 — subscribe() returns an unsubscribe callable."""
    node = PipelineNode("audio_conditioner", {})
    pipeline = Pipeline([node])
    unsubscribe = pipeline.subscribe(lambda e: None)
    assert callable(unsubscribe)


def test_pipeline_subscribe_unsubscribe_removes_callback():
    """Req 5.11 — calling the unsubscribe callable removes the callback."""
    node = PipelineNode("audio_conditioner", {})
    pipeline = Pipeline([node])
    events = []
    unsubscribe = pipeline.subscribe(events.append)
    assert len(pipeline._subscribers) == 1
    unsubscribe()
    assert len(pipeline._subscribers) == 0


def test_pipeline_subscribe_multiple_callbacks():
    """Multiple callbacks can be subscribed independently."""
    node = PipelineNode("audio_conditioner", {})
    pipeline = Pipeline([node])
    cb1 = lambda e: None
    cb2 = lambda e: None
    unsub1 = pipeline.subscribe(cb1)
    unsub2 = pipeline.subscribe(cb2)
    assert len(pipeline._subscribers) == 2
    unsub1()
    assert len(pipeline._subscribers) == 1
    unsub2()
    assert len(pipeline._subscribers) == 0


def test_pipeline_subscribe_unsubscribe_is_idempotent():
    """Calling unsubscribe twice does not raise."""
    node = PipelineNode("audio_conditioner", {})
    pipeline = Pipeline([node])
    unsubscribe = pipeline.subscribe(lambda e: None)
    unsubscribe()
    unsubscribe()  # second call must not raise
