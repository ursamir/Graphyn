"""F20 request #12: run-scoping must not redirect a model_path that is an
existing *input* (a model a previous run exported) into runs/<run_id>/."""
from __future__ import annotations

import pytest

from app.core.paths.workspace_paths import scope_outputs_to_run


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.config.project_dir", lambda: tmp_path)
    (tmp_path / "artifacts" / "kws" / "export").mkdir(parents=True)
    (tmp_path / "artifacts" / "kws" / "export" / "model.onnx").write_bytes(b"onnx")
    return tmp_path


def _cfg(graph, nid):
    return next(n for n in graph["nodes"] if n["id"] == nid)["config"]


def test_existing_model_is_read_in_place(project):
    g = {"nodes": [
        {"id": "infer", "node_type": "wakeword_infer", "config": {"model_path": "workspace/artifacts/kws/export/model.onnx"}},
        {"id": "eval", "node_type": "evaluator", "config": {"output_dir": "workspace/artifacts/kws/eval"}},
    ], "edges": []}
    out = scope_outputs_to_run(g, "r1")
    assert _cfg(out, "infer")["model_path"] == "workspace/artifacts/kws/export/model.onnx"
    assert _cfg(out, "eval")["output_dir"].startswith("workspace/artifacts/kws/runs/r1/")


def test_model_written_in_this_run_follows_the_writer(project):
    g = {"nodes": [
        {"id": "exp", "node_type": "exporter", "config": {"output_dir": "workspace/artifacts/kws/export"}},
        {"id": "infer", "node_type": "wakeword_infer", "config": {"model_path": "workspace/artifacts/kws/export/model.onnx"}},
    ], "edges": []}
    out = scope_outputs_to_run(g, "r2")
    assert "/runs/r2/" in _cfg(out, "infer")["model_path"]


def test_missing_model_path_is_still_scoped_as_an_output(project):
    g = {"nodes": [{"id": "t", "node_type": "trainer", "config": {"model_path": "workspace/artifacts/kws/new/model.pt"}}], "edges": []}
    assert _cfg(scope_outputs_to_run(g, "r3"), "t")["model_path"] == "workspace/artifacts/kws/runs/r3/new/model.pt"
