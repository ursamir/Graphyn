"""Unit tests for Trace assembler (Accountability / Trace UX)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.audit import list_audit, record_audit
from app.core.provenance import ProvenanceStore
from app.core.trace import assemble_trace


def test_assemble_trace_requires_subject():
    with pytest.raises(ValueError, match="artifact_id and/or run_id"):
        assemble_trace()


def test_assemble_trace_partial_missing_everything(tmp_workspace: Path):
    """Missing artifact/run still returns a partial chain with warnings."""
    payload = assemble_trace(artifact_id="missing-art-001")
    assert payload["subject"] == {"kind": "artifact", "id": "missing-art-001"}
    assert payload["artifact"] is None
    assert any("artifact_not_found" in w for w in payload["warnings"])
    assert isinstance(payload["chain"], list)


def test_assemble_trace_from_artifact_with_lineage(tmp_workspace: Path):
    from app.core.artifact_store import ArtifactStore

    store = ArtifactStore()
    # Register a tiny generic artifact (bytes payload)
    art = store.register(
        run_id="run-trace-1",
        node_id="node_a",
        node_type="python_code",
        artifact_type="generic",
        data={"hello": "world"},
    )
    pstore = ProvenanceStore()
    pstore.record(
        artifact_id=art.artifact_id,
        run_id="run-trace-1",
        node_id="node_a",
        node_type="python_code",
        graph_hash="abc123hash",
        input_artifact_ids=[],
    )

    # Seed a run meta with placement
    run_dir = tmp_workspace / "runs" / "run-trace-1"
    run_dir.mkdir(parents=True)
    (run_dir / "meta.json").write_text(
        json.dumps(
            {
                "run_id": "run-trace-1",
                "status": "completed",
                "graph_name": "demo_trace",
                "created_at": "2026-09-07T00:00:00+00:00",
                "graph_hash": "abc123hash",
                "distributed_node_workers": {"node_a": "worker-gpu-1"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "graph.json").write_text(
        json.dumps(
            {
                "schema_version": "1.2",
                "metadata": {"name": "demo_trace"},
                "nodes": [{"id": "node_a", "type": "python_code"}],
                "edges": [],
            }
        ),
        encoding="utf-8",
    )

    payload = assemble_trace(artifact_id=art.artifact_id)
    assert payload["subject"]["kind"] == "artifact"
    assert payload["artifact"]["artifact_id"] == art.artifact_id
    assert payload["run"]["run_id"] == "run-trace-1"
    assert payload["run"]["status"] == "completed"
    assert payload["graph"]["name"] == "demo_trace"
    assert payload["graph"]["node_count"] == 1
    assert payload["node"]["id"] == "node_a"
    assert payload["node"]["worker_id"] == "worker-gpu-1"
    steps = [c["step"] for c in payload["chain"]]
    assert steps == ["artifact", "node", "run", "graph", "worker"]


def test_assemble_trace_from_run_id(tmp_workspace: Path):
    run_dir = tmp_workspace / "runs" / "run-only-1"
    run_dir.mkdir(parents=True)
    (run_dir / "meta.json").write_text(
        json.dumps(
            {
                "run_id": "run-only-1",
                "status": "running",
                "graph_name": "solo",
                "created_at": "2026-09-07T01:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    payload = assemble_trace(run_id="run-only-1")
    assert payload["subject"] == {"kind": "run", "id": "run-only-1"}
    assert payload["run"]["graph_name"] == "solo"
    assert "run" in [c["step"] for c in payload["chain"]]


def test_audit_append_and_list(tmp_workspace: Path):
    record_audit("api", "template.save", "template", "demo", {"version": "v1"})
    record_audit("worker", "worker.register", "worker", "w1", {})
    events = list_audit(limit=10)
    assert len(events) >= 2
    assert events[0]["action"] == "worker.register"  # newest first
    assert events[1]["resource_id"] == "demo"
