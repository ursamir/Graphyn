"""Unit tests for app/core/project_manager.py — Req 22 criteria 1–12."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from app.domain.project_manager import ProjectManager


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture
def pm(tmp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> ProjectManager:
    """Return a ProjectManager whose BASE points to a tmp directory."""
    output_dir = tmp_workspace / "datasets" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
    return ProjectManager()


# ── Req 22.1 — create sets status="draft" and versions=[] ────────────────────

def test_create_project_has_draft_status_and_empty_versions(pm: ProjectManager):
    """Req 22.1 — create('my-project') creates project.json with status='draft' and versions=[]."""
    meta = pm.create("my-project")

    assert meta["status"] == "draft"
    assert meta["versions"] == []

    # Verify the file on disk
    proj_file = pm.BASE / "my-project" / "project.json"
    assert proj_file.exists()
    on_disk = json.loads(proj_file.read_text())
    assert on_disk["status"] == "draft"
    assert on_disk["versions"] == []


# ── Req 22.2 — create twice raises ValueError ─────────────────────────────────

def test_create_project_twice_raises_value_error(pm: ProjectManager):
    """Req 22.2 — create('my-project') called twice raises ValueError."""
    pm.create("my-project")

    with pytest.raises(ValueError, match="already exists"):
        pm.create("my-project")


# ── Req 22.3 — delete with correct confirm removes directory ──────────────────

def test_delete_project_with_correct_confirm_removes_directory(pm: ProjectManager):
    """Req 22.3 — delete('my-project', confirm='my-project') removes the project directory."""
    pm.create("my-project")
    project_dir = pm.BASE / "my-project"
    assert project_dir.exists()

    pm.delete("my-project", confirm="my-project")

    assert not project_dir.exists()


# ── Req 22.4 — delete with wrong confirm raises ValueError ───────────────────

def test_delete_project_with_wrong_confirm_raises_value_error(pm: ProjectManager):
    """Req 22.4 — delete('my-project', confirm='wrong') raises ValueError."""
    pm.create("my-project")

    with pytest.raises(ValueError):
        pm.delete("my-project", confirm="wrong")

    # Project must still exist
    assert (pm.BASE / "my-project").exists()


# ── Req 22.5 — rename moves directory and updates project.json name ───────────

def test_rename_moves_directory_and_updates_name(pm: ProjectManager):
    """Req 22.5 — rename('old', 'new') moves directory and updates project.json['name']."""
    pm.create("old")
    assert (pm.BASE / "old").exists()

    pm.rename("old", "new")

    assert not (pm.BASE / "old").exists()
    assert (pm.BASE / "new").exists()

    proj_file = pm.BASE / "new" / "project.json"
    meta = json.loads(proj_file.read_text())
    assert meta["name"] == "new"


# ── Req 22.6 — set_status updates project.json status ────────────────────────

def test_set_status_updates_project_json_status(pm: ProjectManager):
    """Req 22.6 — set_status('proj', 'archived') updates project.json['status']."""
    pm.create("proj")

    pm.set_status("proj", "archived")

    proj_file = pm.BASE / "proj" / "project.json"
    meta = json.loads(proj_file.read_text())
    assert meta["status"] == "archived"


# ── Req 22.7 — set_status with invalid status raises ValueError ───────────────

def test_set_status_invalid_status_raises_value_error(pm: ProjectManager):
    """Req 22.7 — set_status('proj', 'invalid_status') raises ValueError."""
    pm.create("proj")

    with pytest.raises(ValueError, match="invalid_status"):
        pm.set_status("proj", "invalid_status")


# ── Req 22.8 — set_taxonomy with duplicate sibling raises ValueError ──────────

def test_set_taxonomy_duplicate_sibling_raises_value_error(pm: ProjectManager):
    """Req 22.8 — set_taxonomy with duplicate sibling names raises ValueError."""
    pm.create("proj")

    with pytest.raises(ValueError, match="[Dd]uplicate"):
        pm.set_taxonomy("proj", [{"name": "a"}, {"name": "a"}])


# ── Req 22.9 — set_contract with min > max raises ValueError ─────────────────

def test_set_contract_min_greater_than_max_raises_value_error(pm: ProjectManager):
    """Req 22.9 — set_contract with min_duration_ms > max_duration_ms raises ValueError."""
    pm.create("proj")

    with pytest.raises(ValueError):
        pm.set_contract("proj", {"min_duration_ms": 500, "max_duration_ms": 200})


# ── Req 22.10 — add_annotations writes to annotations.jsonl ──────────────────

def test_add_annotations_writes_to_annotations_jsonl(pm: ProjectManager):
    """Req 22.10 — add_annotations writes to annotations.jsonl."""
    pm.create("proj")

    pm.add_annotations("proj", [{"sample_path": "x.wav", "label": "yes"}])

    annotations_file = pm.BASE / "proj" / "annotations.jsonl"
    assert annotations_file.exists()

    lines = [l.strip() for l in annotations_file.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["sample_path"] == "x.wav"
    assert record["label"] == "yes"


# ── Req 22.11 — export_annotations csv returns CSV with header row ────────────

def test_export_annotations_csv_returns_csv_with_header_row(pm: ProjectManager):
    """Req 22.11 — export_annotations('proj', 'csv') returns a CSV string with a header row."""
    pm.create("proj")
    pm.add_annotations("proj", [{"sample_path": "x.wav", "label": "yes"}])

    csv_str = pm.export_annotations("proj", "csv")

    assert isinstance(csv_str, str)
    reader = csv.DictReader(io.StringIO(csv_str))
    # fieldnames are populated after reading the first row
    rows = list(reader)
    assert reader.fieldnames is not None
    assert len(reader.fieldnames) > 0
    # Header must include sample_path and label
    assert "sample_path" in reader.fieldnames
    assert "label" in reader.fieldnames


# ── Req 22.12 — diff_versions returns {added, removed, changed} ──────────────

def test_diff_versions_returns_added_removed_changed(pm: ProjectManager):
    """Req 22.12 — diff_versions('proj', 'v1', 'v2') returns {'added': N, 'removed': N, 'changed': N}."""
    pm.create("proj")
    proj_dir = pm.BASE / "proj"

    # Create v1/labels.csv
    v1_dir = proj_dir / "v1"
    v1_dir.mkdir(parents=True)
    v1_csv = v1_dir / "labels.csv"
    v1_csv.write_text("filename,label\naudio1.wav,yes\naudio2.wav,no\n")

    # Create v2/labels.csv — audio1 changed, audio2 removed, audio3 added
    v2_dir = proj_dir / "v2"
    v2_dir.mkdir(parents=True)
    v2_csv = v2_dir / "labels.csv"
    v2_csv.write_text("filename,label\naudio1.wav,no\naudio3.wav,yes\n")

    result = pm.diff_versions("proj", "v1", "v2")

    assert "added" in result
    assert "removed" in result
    assert "changed" in result
    assert isinstance(result["added"], int)
    assert isinstance(result["removed"], int)
    assert isinstance(result["changed"], int)
    # audio3 added, audio2 removed, audio1 changed
    assert result["added"] == 1
    assert result["removed"] == 1
    assert result["changed"] == 1
