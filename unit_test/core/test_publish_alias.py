# unit_test/core/test_publish_alias.py
"""Tests for publish_alias env pointers."""
from __future__ import annotations

from pathlib import Path

from app.core.workspace_paths import publish_alias


def test_publish_alias_staging(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    # Ensure layout dirs exist under project
    slug = "edge-demo"
    run_id = "run-alias-1"
    from app.core.workspace_paths import artifact_fs_path, artifact_layout

    layout = artifact_layout(slug, run_id)
    run_dir = artifact_fs_path(layout["run_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "model.bin").write_bytes(b"x")

    path = publish_alias(slug, run_id, "staging")
    assert "staging" in path
    staging = artifact_fs_path(path)
    assert staging.exists() or (staging.parent / "staging.json").exists()
