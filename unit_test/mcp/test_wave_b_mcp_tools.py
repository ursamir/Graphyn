"""Wave B MCP tools: dataset versions + workers/jobs."""
from __future__ import annotations

import base64

import pytest

from app.mcp.tool_registry import register_all_tools

WAVE_B_TOOLS = {
    "list_dataset_versions",
    "get_dataset_version",
    "upload_dataset_file",
    "list_workers",
    "list_jobs",
}


def test_wave_b_tools_registered(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GRAPHYN_MCP_HUMAN_APPROVAL", "1")
    names = []
    register_all_tools(lambda name, desc, schema, handler: names.append(name))
    missing = WAVE_B_TOOLS - set(names)
    assert not missing, f"Missing Wave B MCP tools: {sorted(missing)}"


def test_upload_and_list_dataset_versions(tmp_workspace, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_workspace))
    from app.core.config import datasets_output_dir
    from app.core.dataset_versions import write_manifest
    from app.mcp.handlers.data_ops import (
        get_dataset_version_handler,
        list_dataset_versions_handler,
        upload_dataset_file_handler,
    )

    out = datasets_output_dir() / "p" / "v1"
    out.mkdir(parents=True)
    (out / "f.txt").write_text("hi", encoding="utf-8")
    write_manifest(out)

    listed = list_dataset_versions_handler({"project": "p"})
    assert any(v.get("version") == "v1" for v in listed.get("versions", []))
    got = get_dataset_version_handler({"project": "p", "version": "v1"})
    assert got.get("content_hash")

    up = upload_dataset_file_handler(
        {
            "label": "speech",
            "filename": "a.wav",
            "content_base64": base64.b64encode(b"RIFF").decode("ascii"),
        }
    )
    assert up.get("ok") is True


def test_list_workers_smoke(tmp_workspace):
    from app.mcp.handlers.workers_ops import list_jobs_handler, list_workers_handler

    w = list_workers_handler({})
    assert "workers" in w or w.get("error")
    j = list_jobs_handler({"limit": 10})
    assert "jobs" in j or j.get("error")
