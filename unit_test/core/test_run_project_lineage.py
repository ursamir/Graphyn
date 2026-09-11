# unit_test/core/test_run_project_lineage.py
"""source_run_id / source_artifact_id lineage fields on run payloads."""
from __future__ import annotations

from app.core.run_project import extract_project_fields_from_payload


def test_extracts_source_run_and_artifact():
    fields = extract_project_fields_from_payload(
        {
            "project": "acme",
            "source_run_id": "run-abc-123",
            "source_artifact_id": "art-xyz-9",
            "schema_version": "1.0",
            "nodes": [],
            "edges": [],
        }
    )
    assert fields["project"] == "acme"
    assert fields["source_run_id"] == "run-abc-123"
    assert fields["source_artifact_id"] == "art-xyz-9"


def test_rejects_garbage_source_run_id():
    fields = extract_project_fields_from_payload(
        {"project": "acme", "source_run_id": "../evil"}
    )
    assert fields.get("project") == "acme"
    assert "source_run_id" not in fields
