"""Interface-parity fixes: shared graph preparation, run listing, read-only
project backfill, readiness caching (items 1, 3, 4, 6)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest

from app.core.ir.loader import CURRENT_IR_VERSION

NODE_TYPE = "_iface_fix_node"


@pytest.fixture
def iface_node():
    """Register a tiny node with path-like config keys into the global registry."""
    from app.core.nodes import registry
    from app.core.nodes.base import Node
    from app.core.nodes.config import NodeConfig
    from app.core.nodes.metadata import NodeMetadata
    from app.core.nodes.ports import InputPort, OutputPort

    class _IfaceNode(Node):
        node_type: ClassVar[str] = NODE_TYPE
        input_ports: ClassVar[dict] = {
            "input": InputPort(name="input", data_type=list | None, required=False)
        }
        output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}
        metadata: ClassVar[NodeMetadata] = NodeMetadata(
            node_type=NODE_TYPE, label="Iface", description="iface test node", category="Test"
        )

        class Config(NodeConfig):
            path: str = ""
            output_dir: str = ""

        def process(self, data):
            return data

    registry.register(NODE_TYPE, _IfaceNode, _IfaceNode.metadata)
    try:
        yield _IfaceNode
    finally:
        registry.unregister(NODE_TYPE)


def _graph(node_type: str = NODE_TYPE, **meta) -> dict:
    return {
        "schema_version": CURRENT_IR_VERSION,
        "metadata": {"name": "iface-demo", "seed": 1, **meta},
        "nodes": [
            {
                "id": "n0",
                "node_type": node_type,
                "config": {
                    "path": "examples/01_wake_word/data/raw",
                    "output_dir": "examples/01_wake_word/output/models",
                },
            }
        ],
        "edges": [],
    }


# ── Item 1: shared prepare ───────────────────────────────────────────────────


def test_prepare_graph_rewires_stamps_and_validates(iface_node, tmp_workspace):
    from app.core.execution.graph_prepare import prepare_graph

    prepared = prepare_graph(_graph(), payload={"project": "proj-a", "version_tag": "v1"})
    cfg = dict(prepared.graph.nodes[0].config)
    assert cfg["path"] == "workspace/datasets/input/wake-word/raw"
    assert cfg["output_dir"] == "workspace/artifacts/iface-demo/models"
    assert prepared.project_fields == {"project": "proj-a", "version_tag": "v1"}
    assert prepared.graph.metadata.project == "proj-a"
    assert prepared.validation and prepared.validation["valid"] is True


def test_prepare_graph_refuses_unknown_type(tmp_workspace):
    from app.core.execution.graph_prepare import GraphPrepareError, prepare_graph

    with pytest.raises(GraphPrepareError) as info:
        prepare_graph(_graph(node_type="_definitely_not_registered_"))
    assert info.value.code == "validation_failed"
    assert any(e["code"] == "VAL-UNK-TYPE" for e in info.value.errors)


def _audit_events(ws: Path) -> list[dict]:
    path = ws / "audit" / "events.jsonl"
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def test_sdk_execute_uses_shared_prepare(iface_node, tmp_workspace):
    """SDK used to skip rewire / stamping / validation / run.start audit."""
    from app.core.ir.loader import load_ir
    from app.core.sdk import Pipeline

    captured = {}

    def fake_execute(graph, **kwargs):
        captured["graph"] = graph
        return {}

    backend = MagicMock()
    backend.execute.side_effect = fake_execute
    pipe = Pipeline._from_ir(load_ir(_graph(project="proj-sdk")))
    with patch("app.core.execution.runtime_backend.get_backend", return_value=backend):
        _coll, mgr = pipe.run_with_manager()
    cfg = dict(captured["graph"].nodes[0].config)
    assert cfg["path"].startswith("workspace/datasets/input/")
    assert cfg["output_dir"].startswith("workspace/artifacts/iface-demo/")
    meta = json.loads((Path(mgr.base_path) / "meta.json").read_text())
    assert meta.get("project") == "proj-sdk"
    starts = [e for e in _audit_events(tmp_workspace) if e.get("action") == "run.start"]
    assert starts and starts[-1]["actor"] == "sdk"
    assert starts[-1]["resource_id"] == mgr.run_id


def test_sdk_refuses_invalid_graph_before_backend(tmp_workspace):
    from app.core.execution.graph_prepare import GraphPrepareError
    from app.core.ir.loader import load_ir
    from app.core.sdk import Pipeline

    backend = MagicMock()
    pipe = Pipeline._from_ir(load_ir(_graph(node_type="_nope_not_registered_")))
    runs_before = set(os.listdir(tmp_workspace / "runs")) if (tmp_workspace / "runs").exists() else set()
    with patch("app.core.execution.runtime_backend.get_backend", return_value=backend):
        with pytest.raises(GraphPrepareError):
            pipe.run()
    backend.execute.assert_not_called()
    runs_after = set(os.listdir(tmp_workspace / "runs")) if (tmp_workspace / "runs").exists() else set()
    assert runs_after == runs_before, "no run journal entry for a refused graph"


def test_cli_seed_preserves_metadata(iface_node, tmp_workspace):
    """--seed used to rebuild IRMetadata, dropping project / version_tag / ui."""
    from app.cli.main import _run_with_seed
    from app.core.ir.loader import load_ir
    from app.core.sdk import Pipeline

    graph = load_ir(_graph(project="proj-cli", version_tag="v9"))
    pipe = Pipeline._from_ir(graph)
    seen = {}

    def fake_run(self, logger=None, **kwargs):
        seen["meta"] = self.to_ir().metadata
        seen["actor"] = getattr(self, "_audit_actor", None)

    with patch.object(Pipeline, "run", fake_run):
        _run_with_seed(pipe, 777, None)
    meta = seen["meta"]
    assert meta.seed == 777
    assert meta.project == "proj-cli"
    assert meta.version_tag == "v9"
    assert meta.name == "iface-demo"
    assert seen["actor"] == "cli"


def test_mcp_execute_pending_rewired_and_audited(iface_node, tmp_workspace):
    import app.mcp.handlers.execution as ex

    captured = {}

    def sync_submit(fn, *args, **kwargs):
        captured["graph"] = args[0]
        captured["run_manager"] = kwargs.get("run_manager")
        return None

    with patch.object(ex._PIPELINE_EXECUTOR, "submit", sync_submit):
        out = ex.execute_pipeline_handler({"graph": _graph(), "project": "proj-mcp"})
    assert out["status"] == "pending" and out["accepted"] is True
    cfg = dict(captured["graph"].nodes[0].config)
    assert cfg["output_dir"].startswith("workspace/artifacts/iface-demo/")
    meta = json.loads((tmp_workspace / "runs" / out["run_id"] / "meta.json").read_text())
    assert meta["project"] == "proj-mcp"
    assert meta["status"] == "pending"
    starts = [e for e in _audit_events(tmp_workspace) if e.get("action") == "run.start"]
    assert starts and starts[-1]["actor"] == "mcp"


def test_mcp_execute_refuses_invalid(tmp_workspace):
    import app.mcp.handlers.execution as ex

    out = ex.execute_pipeline_handler({"graph": _graph(node_type="_nope_")})
    assert out["error"] is True and out["valid"] is False
    assert out["error_type"] == "ir_validation_error"


# ── Item 3: shared run lister ────────────────────────────────────────────────


def _mk_run(root: Path, run_id: str, created_at: str, **extra) -> Path:
    d = root / run_id
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"run_id": run_id, "created_at": created_at, "status": "completed", **extra}))
    return d


def test_list_runs_orders_by_created_at_not_mtime(tmp_path):
    from app.core.runs.run_listing import clear_run_listing_cache, list_runs

    clear_run_listing_cache()
    old = _mk_run(tmp_path, "aaa", "2026-01-01T00:00:00+00:00")
    _mk_run(tmp_path, "bbb", "2026-01-02T00:00:00+00:00")
    _mk_run(tmp_path, "ccc", "2026-01-02T00:00:00+00:00")  # tie → run_id desc
    # Touch the oldest (atomic meta rename bumps dir mtime) — must not reorder.
    time.sleep(0.01)
    tmp = old / "meta.json.tmp"
    tmp.write_text(json.dumps({"run_id": "aaa", "created_at": "2026-01-01T00:00:00+00:00", "status": "failed"}))
    os.replace(tmp, old / "meta.json")
    ids = [m["run_id"] for _p, m in list_runs(tmp_path, limit=None).rows]
    assert ids == ["ccc", "bbb", "aaa"]
    page1 = [m["run_id"] for _p, m in list_runs(tmp_path, limit=2, offset=0).rows]
    page2 = [m["run_id"] for _p, m in list_runs(tmp_path, limit=2, offset=2).rows]
    assert page1 + page2 == ids
    assert list_runs(tmp_path, limit=1).total_matched == 3


def test_list_runs_entry_vanishing_skips_only_that_entry(tmp_path):
    from app.core.runs.run_listing import clear_run_listing_cache, list_runs

    clear_run_listing_cache()
    _mk_run(tmp_path, "keep1", "2026-01-01T00:00:00+00:00")
    gone = _mk_run(tmp_path, "gone", "2026-01-03T00:00:00+00:00")
    _mk_run(tmp_path, "keep2", "2026-01-02T00:00:00+00:00")
    real_stat = Path.stat

    def flaky_stat(self, *a, **k):
        if self == gone / "meta.json":
            raise FileNotFoundError(str(self))
        return real_stat(self, *a, **k)

    with patch.object(Path, "stat", flaky_stat):
        ids = [m["run_id"] for _p, m in list_runs(tmp_path, limit=None).rows]
    assert ids == ["keep2", "keep1"]


def test_list_runs_project_and_status_filters(tmp_path):
    from app.core.runs.run_listing import clear_run_listing_cache, list_runs

    clear_run_listing_cache()
    _mk_run(tmp_path, "r1", "2026-01-01T00:00:00+00:00", project="alpha")
    _mk_run(tmp_path, "r2", "2026-01-02T00:00:00+00:00", project="beta")
    d3 = _mk_run(tmp_path, "r3", "2026-01-03T00:00:00+00:00", status="failed")
    (d3 / "graph.json").write_text(json.dumps({"metadata": {"project": "alpha"}, "nodes": []}))
    page = list_runs(tmp_path, project="alpha", limit=None)
    assert [m["run_id"] for _p, m in page.rows] == ["r3", "r1"]
    page = list_runs(tmp_path, project="alpha", status="failed", limit=None)
    assert [m["run_id"] for _p, m in page.rows] == ["r3"]


def test_mcp_list_runs_honours_store_guard(tmp_workspace):
    from app.mcp.handlers.journey import list_runs_handler

    with patch("app.core.persist.store_integrity.readiness_store_corrupt", return_value=True):
        out = list_runs_handler({})
    assert out["error"] is True and out["error_type"] == "store_corrupt"


def test_mcp_list_runs_project_infers_from_graph(tmp_workspace):
    """MCP used to call project_matches without run_path (no graph inference)."""
    from app.core.config import runs_dir
    from app.core.runs.run_listing import clear_run_listing_cache
    from app.mcp.handlers.journey import list_runs_handler

    clear_run_listing_cache()
    d = _mk_run(runs_dir(), "g1", "2026-03-01T00:00:00+00:00")
    (d / "graph.json").write_text(json.dumps({"metadata": {"project": "infer-me"}, "nodes": []}))
    out = list_runs_handler({"project": "infer-me"})
    assert [r["run_id"] for r in out["runs"]] == ["g1"]


# ── Item 4: GET paths never write meta.json ──────────────────────────────────


def test_project_backfill_is_read_only(tmp_path):
    from app.core.runs.run_project import backfill_project_meta, project_matches

    d = tmp_path / "run1"
    d.mkdir()
    meta = {"run_id": "run1", "status": "running"}
    (d / "meta.json").write_text(json.dumps(meta))
    (d / "graph.json").write_text(json.dumps({"metadata": {"project": "pz"}, "nodes": []}))
    before = (d / "meta.json").read_bytes()
    assert backfill_project_meta(d) == {"project": "pz"}
    assert project_matches(meta, "pz", d) is True
    assert (d / "meta.json").read_bytes() == before


# ── Item 6: readiness cache + bounded globs ──────────────────────────────────


def test_readiness_snapshot_cached_and_fresh(tmp_workspace, monkeypatch):
    import app.core.host.readiness as rd

    rd.clear_readiness_cache()
    monkeypatch.setenv("GRAPHYN_READINESS_CACHE_S", "30")
    calls = {"n": 0}
    real = rd._compute_snapshot

    def counting():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(rd, "_compute_snapshot", counting)
    rd.readiness_snapshot()
    rd.readiness_snapshot()
    assert calls["n"] == 1
    rd.readiness_snapshot(max_age_s=0)
    assert calls["n"] == 2
    monkeypatch.setenv("GRAPHYN_READINESS_CACHE_S", "0")
    rd.readiness_snapshot()
    rd.readiness_snapshot()
    assert calls["n"] == 4
    rd.clear_readiness_cache()


def test_readiness_store_corrupt_known_paths_only(tmp_workspace):
    import app.core.host.readiness as rd

    rd.clear_readiness_cache()
    assert rd.readiness_snapshot(max_age_s=0)["checks"]["store_corrupt"] is False
    deep = tmp_workspace / "artifacts" / "slug" / "runs" / "r1" / "data"
    deep.mkdir(parents=True)
    (deep / "big.json.corrupt").write_text("x")  # deep artifact tree: not an index
    assert rd.readiness_snapshot(max_age_s=0)["checks"]["store_corrupt"] is False
    (tmp_workspace / "artifacts" / "by_run").mkdir(parents=True, exist_ok=True)
    (tmp_workspace / "artifacts" / "by_run" / "r1.json.corrupt").write_text("x")
    assert rd.readiness_snapshot(max_age_s=0)["checks"]["store_corrupt"] is True
    rd.clear_readiness_cache()


def test_readiness_does_not_recursive_glob(tmp_workspace, monkeypatch):
    import app.core.host.readiness as rd

    seen: list[str] = []
    real_glob = Path.glob

    def spy(self, pattern, *a, **k):
        seen.append(pattern)
        return real_glob(self, pattern, *a, **k)

    (tmp_workspace / "artifacts" / "by_run").mkdir(parents=True, exist_ok=True)
    (tmp_workspace / "plugins").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "glob", spy)
    rd.readiness_snapshot(max_age_s=0)
    assert seen and not any("**" in p for p in seen)
    rd.clear_readiness_cache()
