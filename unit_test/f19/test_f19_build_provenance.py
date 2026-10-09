"""F19 (F-16): build provenance reaches the run environment."""
from __future__ import annotations

import json


def test_git_sha_from_env_and_build_info(monkeypatch, tmp_path):
    from app.core.runs import audit_record as ar

    monkeypatch.setenv("GRAPHYN_GIT_SHA", "abc123def456")
    env = ar.capture_environment(refresh=True)
    assert env["git_commit"] == "abc123def456" and env["git_source"] == "env:GRAPHYN_GIT_SHA"
    assert env["provenance_warnings"] == []

    monkeypatch.delenv("GRAPHYN_GIT_SHA")
    info = tmp_path / "BUILD_INFO.json"
    info.write_text(json.dumps({"git_sha": "feedface0001", "image": "graphyn-api:t"}))
    monkeypatch.setenv("GRAPHYN_BUILD_INFO", str(info))
    env = ar.capture_environment(refresh=True)
    assert env["git_commit"] == "feedface0001" and env["git_source"] == "BUILD_INFO.json"
    ar.capture_environment(refresh=True)


def test_missing_sha_is_flagged(monkeypatch, tmp_path):
    from app.core.runs import audit_record as ar

    monkeypatch.delenv("GRAPHYN_GIT_SHA", raising=False)
    info = tmp_path / "BUILD_INFO.json"
    info.write_text(json.dumps({"git_sha": None}))
    monkeypatch.setenv("GRAPHYN_BUILD_INFO", str(info))
    monkeypatch.setattr(ar, "_git_commit_info", lambda info=None: (None, None))
    env = ar.capture_environment(refresh=True)
    assert env["git_commit"] is None and env["provenance_warnings"]
    monkeypatch.undo()
    ar.capture_environment(refresh=True)


def test_build_script_refuses_without_sha():
    from pathlib import Path

    text = Path("scripts/build_stack.sh").read_text()
    assert "GRAPHYN_GIT_SHA" in text and "refusing to build" in text
    assert "graphyn-worker" in text and "FaceRecognition" not in text
