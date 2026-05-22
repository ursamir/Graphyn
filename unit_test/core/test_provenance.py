"""Unit tests for app/core/provenance.py — Req 20 criteria 9–14."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.provenance import ProvenanceRecord, ProvenanceStore


# ── Helpers ───────────────────────────────────────────────────────────────────

def _store(tmp_workspace: Path) -> ProvenanceStore:
    """Return a ProvenanceStore rooted at tmp_workspace."""
    return ProvenanceStore(base_dir=str(tmp_workspace))


# ── Req 20.9 — record() writes {artifact_id}.json and by_run/{run_id}.json ───

def test_record_writes_artifact_json_and_by_run_json(tmp_workspace: Path):
    """Req 20.9 — record() writes {artifact_id}.json and appends to by_run/{run_id}.json."""
    store = _store(tmp_workspace)
    artifact_id = "art-001"
    run_id = "run-001"

    store.record(
        artifact_id=artifact_id,
        run_id=run_id,
        node_id="node-1",
        node_type="clean",
        graph_hash="abc123",
        input_artifact_ids=[],
    )

    artifact_file = store.base / f"{artifact_id}.json"
    by_run_file = store.base / "by_run" / f"{run_id}.json"

    assert artifact_file.exists(), f"{artifact_id}.json was not written"
    assert by_run_file.exists(), f"by_run/{run_id}.json was not written"

    # Verify artifact_id appears in by_run file
    ids = json.loads(by_run_file.read_text())
    assert artifact_id in ids


# ── Req 20.10 — calling record() twice does not duplicate by_run entry ────────

def test_record_twice_does_not_duplicate_by_run_entry(tmp_workspace: Path):
    """Req 20.10 — calling record() twice with same artifact_id does not duplicate by_run entry."""
    store = _store(tmp_workspace)
    artifact_id = "art-dup"
    run_id = "run-dup"

    store.record(
        artifact_id=artifact_id,
        run_id=run_id,
        node_id="node-1",
        node_type="clean",
        graph_hash="hash-dup",
        input_artifact_ids=[],
    )
    store.record(
        artifact_id=artifact_id,
        run_id=run_id,
        node_id="node-1",
        node_type="clean",
        graph_hash="hash-dup",
        input_artifact_ids=[],
    )

    by_run_file = store.base / "by_run" / f"{run_id}.json"
    ids = json.loads(by_run_file.read_text())

    assert ids.count(artifact_id) == 1, (
        f"Expected exactly 1 entry for {artifact_id!r} in by_run, got {ids.count(artifact_id)}"
    )


# ── Req 20.11 — get_lineage("unknown_id") returns error dict without raising ──

def test_get_lineage_unknown_id_returns_error_dict(tmp_workspace: Path):
    """Req 20.11 — get_lineage('unknown_id') returns error dict without raising."""
    store = _store(tmp_workspace)

    result = store.get_lineage("unknown_id")

    assert result == {
        "artifact_id": "unknown_id",
        "inputs": [],
        "error": "no_provenance_record",
    }


# ── Req 20.12 — get_lineage returns dict with required keys for known artifact ─

def test_get_lineage_returns_dict_with_required_keys(tmp_workspace: Path):
    """Req 20.12 — get_lineage(artifact_id) returns dict with 'run_id', 'node_type', 'inputs' keys."""
    store = _store(tmp_workspace)
    artifact_id = "art-known"

    store.record(
        artifact_id=artifact_id,
        run_id="run-known",
        node_id="node-1",
        node_type="augment",
        graph_hash="ghash-known",
        input_artifact_ids=[],
    )

    result = store.get_lineage(artifact_id)

    assert "run_id" in result
    assert "node_type" in result
    assert "inputs" in result
    assert result["run_id"] == "run-known"
    assert result["node_type"] == "augment"
    assert result["inputs"] == []


# ── Req 20.13 — find_by_run("unknown_run") returns [] without raising ─────────

def test_find_by_run_unknown_run_returns_empty_list(tmp_workspace: Path):
    """Req 20.13 — find_by_run('unknown_run') returns [] without raising."""
    store = _store(tmp_workspace)

    result = store.find_by_run("unknown_run")

    assert result == []


# ── Req 20.14 — find_reproducible returns all records with matching graph_hash ─

def test_find_reproducible_returns_all_records_with_matching_graph_hash(
    tmp_workspace: Path,
):
    """Req 20.14 — find_reproducible(graph_hash) returns all records with that graph_hash."""
    store = _store(tmp_workspace)
    target_hash = "reproducible-hash-xyz"

    # Register two artifacts with the target hash
    store.record(
        artifact_id="art-rep-1",
        run_id="run-rep-1",
        node_id="node-1",
        node_type="clean",
        graph_hash=target_hash,
        input_artifact_ids=[],
    )
    store.record(
        artifact_id="art-rep-2",
        run_id="run-rep-2",
        node_id="node-2",
        node_type="clean",
        graph_hash=target_hash,
        input_artifact_ids=[],
    )
    # Register one artifact with a different hash (should not appear)
    store.record(
        artifact_id="art-other",
        run_id="run-other",
        node_id="node-3",
        node_type="clean",
        graph_hash="different-hash",
        input_artifact_ids=[],
    )

    results = store.find_reproducible(target_hash)

    result_ids = {r.artifact_id for r in results}
    assert "art-rep-1" in result_ids
    assert "art-rep-2" in result_ids
    assert "art-other" not in result_ids
    assert len(results) == 2
