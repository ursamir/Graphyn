"""Unit tests for app/core/artifact_store.py — Req 20 criteria 1–8."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.artifact_store import (
    ArtifactNotFoundError,
    ArtifactRecord,
    ArtifactStore,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _store(tmp_workspace: Path) -> ArtifactStore:
    """Return an ArtifactStore rooted at tmp_workspace."""
    return ArtifactStore(base_dir=str(tmp_workspace))


# ── Req 20.1 — register returns ArtifactRecord with non-empty fields ─────────

def test_register_returns_artifact_record_with_non_empty_id_and_hash(
    tmp_workspace: Path,
):
    """Req 20.1 — register() returns ArtifactRecord with non-empty artifact_id and content_hash."""
    store = _store(tmp_workspace)
    record = store.register(
        run_id="run-1",
        node_id="node-1",
        node_type="clean",
        artifact_type="generic",
        data={"key": "value"},
    )

    assert isinstance(record, ArtifactRecord)
    assert record.artifact_id != ""
    assert record.content_hash != ""


# ── Req 20.2 — content-addressing deduplication ───────────────────────────────

def test_register_twice_with_identical_data_returns_same_artifact_id(
    tmp_workspace: Path,
):
    """Req 20.2 — calling register() twice with identical data returns same artifact_id."""
    store = _store(tmp_workspace)
    data = {"payload": "same"}

    record1 = store.register(
        run_id="run-1",
        node_id="node-1",
        node_type="clean",
        artifact_type="generic",
        data=data,
    )
    record2 = store.register(
        run_id="run-1",
        node_id="node-1",
        node_type="clean",
        artifact_type="generic",
        data=data,
    )

    assert record1.artifact_id == record2.artifact_id


# ── Req 20.3 — get returns the registered record ─────────────────────────────

def test_get_returns_registered_artifact_record(tmp_workspace: Path):
    """Req 20.3 — get(artifact_id) returns the same ArtifactRecord that was registered."""
    store = _store(tmp_workspace)
    registered = store.register(
        run_id="run-1",
        node_id="node-1",
        node_type="clean",
        artifact_type="generic",
        data={"x": 1},
    )

    fetched = store.get(registered.artifact_id)

    assert fetched.artifact_id == registered.artifact_id
    assert fetched.content_hash == registered.content_hash
    assert fetched.run_id == registered.run_id


# ── Req 20.4 — get("nonexistent") raises ArtifactNotFoundError ───────────────

def test_get_nonexistent_raises_artifact_not_found_error(tmp_workspace: Path):
    """Req 20.4 — get('nonexistent') raises ArtifactNotFoundError."""
    store = _store(tmp_workspace)

    with pytest.raises(ArtifactNotFoundError):
        store.get("nonexistent")


# ── Req 20.5 — ArtifactNotFoundError is a subclass of KeyError ───────────────

def test_artifact_not_found_error_is_subclass_of_key_error():
    """Req 20.5 — ArtifactNotFoundError is a subclass of KeyError."""
    assert issubclass(ArtifactNotFoundError, KeyError)


def test_artifact_not_found_error_can_be_caught_as_key_error(tmp_workspace: Path):
    """Req 20.5 — ArtifactNotFoundError can be caught with except KeyError."""
    store = _store(tmp_workspace)

    with pytest.raises(KeyError):
        store.get("nonexistent")


# ── Req 20.6 — unsupported artifact_type raises ValueError ───────────────────

def test_register_unsupported_artifact_type_raises_value_error(tmp_workspace: Path):
    """Req 20.6 — register(..., artifact_type='unsupported_type') raises ValueError."""
    store = _store(tmp_workspace)

    with pytest.raises(ValueError, match="unsupported_type"):
        store.register(
            run_id="run-1",
            node_id="node-1",
            node_type="clean",
            artifact_type="unsupported_type",
            data={"x": 1},
        )


# ── Req 20.7 — list(run_id=...) filters by run_id ────────────────────────────

def test_list_with_run_id_returns_only_matching_records(tmp_workspace: Path):
    """Req 20.7 — list(run_id='r1') returns only records whose run_id == 'r1'."""
    store = _store(tmp_workspace)

    store.register(
        run_id="r1",
        node_id="node-a",
        node_type="clean",
        artifact_type="generic",
        data={"run": "r1", "seq": 1},
    )
    store.register(
        run_id="r2",
        node_id="node-b",
        node_type="clean",
        artifact_type="generic",
        data={"run": "r2", "seq": 2},
    )

    results = store.list(run_id="r1")

    assert len(results) == 1
    assert results[0].run_id == "r1"


# ── Req 20.8 — list() returns records sorted by created_at descending ─────────

def test_list_returns_records_sorted_by_created_at_descending(tmp_workspace: Path):
    """Req 20.8 — list() returns records sorted by created_at descending."""
    store = _store(tmp_workspace)

    # Register multiple artifacts with distinct data so each gets a unique record
    store.register(
        run_id="run-1",
        node_id="node-1",
        node_type="clean",
        artifact_type="generic",
        data={"seq": 1},
    )
    store.register(
        run_id="run-1",
        node_id="node-2",
        node_type="clean",
        artifact_type="generic",
        data={"seq": 2},
    )
    store.register(
        run_id="run-1",
        node_id="node-3",
        node_type="clean",
        artifact_type="generic",
        data={"seq": 3},
    )

    results = store.list()

    assert len(results) >= 2
    # Verify descending order
    for i in range(len(results) - 1):
        assert results[i].created_at >= results[i + 1].created_at
