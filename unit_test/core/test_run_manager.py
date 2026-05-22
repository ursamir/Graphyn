"""Unit tests for app/core/run_manager.py — Req 5 criteria 8–9, Req 20."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.run_journal import RunManager


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def run(tmp_workspace: Path) -> RunManager:
    """Return a RunManager whose base_dir is inside the tmp workspace."""
    runs_dir = str(tmp_workspace / "runs")
    return RunManager(base_dir=runs_dir)


# ── Pause / Resume ────────────────────────────────────────────────────────────

def test_pause_sets_is_paused_true(run: RunManager):
    """Req 5.8 — pause() sets is_paused to True."""
    assert run.is_paused is False
    run.pause()
    assert run.is_paused is True


def test_resume_sets_is_paused_false(run: RunManager):
    """Req 5.8 — resume() sets is_paused to False."""
    run.pause()
    assert run.is_paused is True
    run.resume()
    assert run.is_paused is False


def test_pause_resume_cycle(run: RunManager):
    """Multiple pause/resume cycles work correctly."""
    run.pause()
    run.resume()
    run.pause()
    assert run.is_paused is True
    run.resume()
    assert run.is_paused is False


# ── Cancel ────────────────────────────────────────────────────────────────────

def test_cancel_sets_is_cancelled_true(run: RunManager):
    """Req 5.9 — cancel() sets is_cancelled to True."""
    assert run.is_cancelled is False
    run.cancel()
    assert run.is_cancelled is True


def test_cancel_from_paused_state(run: RunManager):
    """Req 5.9 — cancel() sets is_cancelled=True regardless of prior pause state."""
    run.pause()
    run.cancel()
    assert run.is_cancelled is True


def test_cancel_from_running_state(run: RunManager):
    """cancel() works when not paused."""
    run.cancel()
    assert run.is_cancelled is True


def test_cancel_also_unblocks_pause(run: RunManager):
    """cancel() unblocks the pause event so wait_if_paused() does not hang."""
    run.pause()
    run.cancel()
    # After cancel, the pause event should be set (unblocked)
    assert run._pause_event.is_set()


# ── save_graph_ir ─────────────────────────────────────────────────────────────

def test_save_graph_ir_writes_graph_json(run: RunManager):
    """Req 5 — save_graph_ir writes graph.json to the run directory."""
    graph_data = {"schema_version": "1.0", "nodes": [], "edges": []}
    run.save_graph_ir(graph_data)
    graph_path = Path(run.base_path) / "graph.json"
    assert graph_path.exists()


def test_save_graph_ir_content_is_valid_json(run: RunManager):
    """save_graph_ir writes valid JSON that round-trips correctly."""
    graph_data = {"schema_version": "1.0", "nodes": [{"id": "n1"}], "edges": []}
    run.save_graph_ir(graph_data)
    graph_path = Path(run.base_path) / "graph.json"
    loaded = json.loads(graph_path.read_text())
    assert loaded["schema_version"] == "1.0"
    assert loaded["nodes"][0]["id"] == "n1"


def test_save_graph_ir_computes_graph_hash(run: RunManager):
    """save_graph_ir sets _graph_hash to a non-empty string."""
    graph_data = {"schema_version": "1.0", "nodes": [], "edges": []}
    run.save_graph_ir(graph_data)
    assert len(run._graph_hash) == 64  # SHA-256 hex digest


# ── register_artifact ─────────────────────────────────────────────────────────

def test_register_artifact_returns_artifact_record(run: RunManager):
    """Req 20.1 — register_artifact returns an ArtifactRecord."""
    from app.core.artifact_store import ArtifactRecord
    record = run.register_artifact(
        node_id="node_0",
        node_type="audio_conditioner",
        artifact_type="generic",
        data={"result": "test"},
    )
    assert isinstance(record, ArtifactRecord)
    assert record.artifact_id
    assert record.content_hash


def test_register_artifact_deduplication(run: RunManager):
    """Req 20.2 — same content → same artifact_id (content-addressing)."""
    data = {"result": "identical_content"}
    record1 = run.register_artifact(
        node_id="node_0",
        node_type="audio_conditioner",
        artifact_type="generic",
        data=data,
    )
    record2 = run.register_artifact(
        node_id="node_1",
        node_type="segmenter",
        artifact_type="generic",
        data=data,
    )
    assert record1.artifact_id == record2.artifact_id


def test_register_artifact_appends_to_artifacts_list(run: RunManager):
    """register_artifact appends the record to run._artifacts."""
    run.register_artifact(
        node_id="node_0",
        node_type="audio_conditioner",
        artifact_type="generic",
        data={"x": 1},
    )
    assert len(run._artifacts) == 1


# ── run_id ────────────────────────────────────────────────────────────────────

def test_run_id_is_non_empty_string(run: RunManager):
    """run_id is a non-empty string."""
    assert isinstance(run.run_id, str)
    assert len(run.run_id) > 0


def test_run_creates_base_path_directory(run: RunManager):
    """RunManager creates its base_path directory on construction."""
    assert Path(run.base_path).is_dir()


def test_run_writes_initial_meta_json(run: RunManager):
    """RunManager writes meta.json with status='running' on construction."""
    meta_path = Path(run.base_path) / "meta.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta["status"] == "running"
    assert meta["run_id"] == run.run_id
