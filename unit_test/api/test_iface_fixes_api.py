"""Interface-layer fixes: REST prepare/audit parity, NDJSON stream channel,
cross-interface run order, MCP isError, CLI remote node paging, POST
/projects 409, promote 404 (items 1, 2, 3, 5, 7, 8 + promote)."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest

from app.core.ir.loader import CURRENT_IR_VERSION

NODE_TYPE = "_iface_api_node"


@pytest.fixture
def iface_node():
    from app.core.nodes import registry
    from app.core.nodes.base import Node
    from app.core.nodes.config import NodeConfig
    from app.core.nodes.metadata import NodeMetadata
    from app.core.nodes.ports import InputPort, OutputPort

    class _Node(Node):
        node_type: ClassVar[str] = NODE_TYPE
        input_ports: ClassVar[dict] = {
            "input": InputPort(name="input", data_type=list | None, required=False)
        }
        output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}
        metadata: ClassVar[NodeMetadata] = NodeMetadata(
            node_type=NODE_TYPE, label="IfaceApi", description="iface api node", category="Test"
        )

        class Config(NodeConfig):
            output_dir: str = ""

        def process(self, data):
            return data

    registry.register(NODE_TYPE, _Node, _Node.metadata)
    try:
        yield _Node
    finally:
        registry.unregister(NODE_TYPE)


def _graph() -> dict:
    return {
        "schema_version": CURRENT_IR_VERSION,
        "metadata": {"name": "iface-api", "seed": 0},
        "nodes": [{"id": "n0", "node_type": NODE_TYPE, "config": {"output_dir": "examples/01_wake_word/output/x"}}],
        "edges": [],
    }


def _audit(ws: Path) -> list[dict]:
    path = ws / "audit" / "events.jsonl"
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


# ── Item 1: REST audit actor + shared prepare ────────────────────────────────


def test_run_async_audit_uses_resolved_actor(iface_node, tmp_workspace, api_client):
    with patch("app.core.execution.runtime_backend.get_backend") as gb:
        gb.return_value = MagicMock()
        resp = api_client.post(
            "/api/v1/pipelines/run-async", json=_graph(), headers={"X-Actor": "alice"}
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending"
    starts = [e for e in _audit(tmp_workspace) if e.get("action") == "run.start"]
    assert starts and starts[-1]["actor"] == "alice"


def test_run_async_refuses_invalid_with_val_codes(tmp_workspace, api_client):
    g = _graph()
    g["nodes"][0]["node_type"] = "_nope_unregistered_"
    resp = api_client.post("/api/v1/pipelines/run-async", json=g)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "validation_failed"
    assert any(e["code"] == "VAL-UNK-TYPE" for e in detail["errors"])


# ── Item 2: NDJSON stream channel ────────────────────────────────────────────


def test_channel_drops_oldest_non_terminal_and_keeps_terminal():
    from app.api.routers.pipelines import _RunEventChannel

    ch = _RunEventChannel(maxsize=3)
    for i in range(10):
        ch.put_nowait({"type": "log", "i": i})
    ch.put_nowait({"type": "done", "run_id": "r"})
    ch.put_nowait({"type": "log", "i": 99})  # full: evicts oldest log, not done
    ch.finish(None)
    out = []
    while True:
        has, item = ch.poll()
        assert has
        if item is None:
            break
        out.append(item)
    assert len(out) == 3
    assert {"type": "done", "run_id": "r"} in out
    assert out[-1] == {"type": "log", "i": 99}
    assert ch.dropped >= 8


def test_channel_never_blocks_after_consumer_close():
    from app.api.routers.pipelines import _RunEventChannel

    ch = _RunEventChannel(maxsize=2)
    ch.close()
    t0 = time.monotonic()
    for i in range(10_000):
        ch.put({"type": "log", "i": i})  # blocking-style put must not block
    ch.finish({"type": "error", "message": "x"})
    assert time.monotonic() - t0 < 2.0
    assert ch.poll() == (True, None)


def test_channel_finish_always_delivers_terminal_when_full():
    from app.api.routers.pipelines import _RunEventChannel

    ch = _RunEventChannel(maxsize=2)
    ch.put_nowait({"type": "log"})
    ch.put_nowait({"type": "log"})
    ch.finish({"type": "error", "message": "boom"})
    items = []
    while True:
        _has, item = ch.poll()
        if item is None:
            break
        items.append(item)
    assert items[-1]["type"] == "error"


def test_stream_emits_terminal_error_on_backend_failure(iface_node, tmp_workspace, api_client):
    backend = MagicMock()
    backend.execute.side_effect = RuntimeError("kaboom")
    with patch("app.core.execution.runtime_backend.get_backend", return_value=backend):
        resp = api_client.post("/api/v1/pipelines/run", json=_graph())
    assert resp.status_code == 200
    lines = [json.loads(ln) for ln in resp.text.splitlines() if ln.strip()]
    assert lines[0]["type"] == "run_started"
    assert lines[-1]["type"] == "error"
    assert lines[-1]["message"] == "kaboom"
    assert lines[-1]["run_id"] == resp.headers["X-Run-Id"]


def test_stream_synthesizes_done_when_backend_silent(iface_node, tmp_workspace, api_client):
    backend = MagicMock()
    backend.execute.return_value = {}
    with patch("app.core.execution.runtime_backend.get_backend", return_value=backend):
        resp = api_client.post("/api/v1/pipelines/run", json=_graph())
    lines = [json.loads(ln) for ln in resp.text.splitlines() if ln.strip()]
    assert lines[-1]["type"] == "done"


def test_stream_flood_does_not_block_producer(iface_node, tmp_workspace, api_client):
    """> queue size of events with a terminal event: stream ends, terminal delivered."""
    finished = threading.Event()

    def flood(graph, logger=None, run_manager=None, **kwargs):
        for i in range(5000):
            logger.info(f"event {i}")
        logger.pipeline_done(run_manager.run_id, 0.1)
        finished.set()
        return {}

    backend = MagicMock()
    backend.execute.side_effect = flood
    with patch("app.core.execution.runtime_backend.get_backend", return_value=backend):
        resp = api_client.post("/api/v1/pipelines/run", json=_graph())
    assert finished.wait(10)
    lines = [json.loads(ln) for ln in resp.text.splitlines() if ln.strip()]
    assert lines[-1]["type"] == "done"


# ── Item 3: all interfaces share one run order ───────────────────────────────


def _mk_run(root: Path, run_id: str, created_at: str, **extra) -> None:
    d = root / run_id
    d.mkdir(parents=True)
    (d / "meta.json").write_text(
        json.dumps({"run_id": run_id, "created_at": created_at, "status": "completed", **extra})
    )


def test_rest_mcp_cli_share_run_order(tmp_workspace, api_client):
    from app.cli.main import _list_runs
    from app.core.config import runs_dir
    from app.core.host.readiness import clear_readiness_cache
    from app.core.runs.run_listing import clear_run_listing_cache
    from app.mcp.handlers.journey import list_runs_handler

    clear_run_listing_cache()
    clear_readiness_cache()
    root = runs_dir()
    for i, rid in enumerate(["x1", "x2", "x3"]):
        _mk_run(root, rid, f"2026-02-0{i + 1}T00:00:00+00:00", project="pp")
    (root / "no-meta-dir").mkdir()
    expected = ["x3", "x2", "x1"]
    rest = [r["run_id"] for r in api_client.get("/api/v1/runs?limit=10").json()]
    rest_proj = [r["run_id"] for r in api_client.get("/api/v1/runs?limit=10&project=pp").json()]
    mcp = [r["run_id"] for r in list_runs_handler({"limit": 10, "project": "pp"})["runs"]]
    cli = [r["run_id"] for r in _list_runs(limit=10)]
    assert rest == expected and rest_proj == expected and mcp == expected and cli == expected
    page2 = [r["run_id"] for r in api_client.get("/api/v1/runs?limit=2&offset=2").json()]
    assert page2 == ["x1"]


# ── Item 5: MCP isError ──────────────────────────────────────────────────────


def _call(server, name, args):
    return asyncio.run(server.handle_call_tool(name, args))


def test_mcp_call_tool_is_error_flags(monkeypatch):
    import app.mcp.server as server

    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    tools = {
        "ok": {"description": "", "inputSchema": {}, "handler": lambda a: {"fine": 1}},
        "soft": {"description": "", "inputSchema": {}, "handler": lambda a: {"error": True, "error_type": "nope", "message": "m"}},
        "boom": {"description": "", "inputSchema": {}, "handler": lambda a: (_ for _ in ()).throw(RuntimeError("kaput"))},
    }
    monkeypatch.setattr(server, "_TOOLS", tools)
    ok = _call(server, "ok", {})
    assert ok.isError is False and json.loads(ok.content[0].text) == {"fine": 1}
    soft = _call(server, "soft", {})
    assert soft.isError is True and json.loads(soft.content[0].text)["error_type"] == "nope"
    boom = _call(server, "boom", {})
    assert boom.isError is True
    assert json.loads(boom.content[0].text) == {"error": True, "error_type": "RuntimeError", "message": "kaput"}
    unknown = _call(server, "missing", {})
    assert unknown.isError is True


# ── Item 7: CLI remote nodes pages through everything ────────────────────────


def test_cli_remote_nodes_pages_all(monkeypatch):
    import app.cli.main as cli

    catalog = [{"node_type": f"n{i:03d}"} for i in range(1234)]
    seen_paths = []

    def fake_get(path, *, api_url, token):
        seen_paths.append(path)
        from urllib.parse import parse_qs, urlsplit

        q = parse_qs(urlsplit(path).query)
        limit = int(q["limit"][0])
        offset = int(q.get("offset", ["0"])[0])
        page = catalog[offset: offset + limit]
        nxt = offset + len(page) if offset + len(page) < len(catalog) else None
        return 200, {"items": page, "total": len(catalog), "limit": limit, "offset": offset, "next_offset": nxt}

    monkeypatch.setattr(cli, "_remote_get", fake_get)
    status, body = cli._remote_list_all_nodes(api_url="http://x", token=None)
    assert status == 200
    assert [n["node_type"] for n in body["items"]] == [n["node_type"] for n in catalog]
    assert body["total"] == 1234
    assert len(seen_paths) == 3


def test_cli_remote_nodes_propagates_error(monkeypatch):
    import app.cli.main as cli

    monkeypatch.setattr(cli, "_remote_get", lambda path, **k: (401, {"detail": "no"}))
    assert cli._remote_list_all_nodes(api_url="http://x", token=None)[0] == 401


# ── Item 8: duplicate project → 409 ──────────────────────────────────────────


def test_create_duplicate_project_409_real_manager(api_client, tmp_workspace):
    from app.domain.project_manager import ProjectManager

    pm = ProjectManager()  # BASE resolves under the isolated GRAPHYN_PROJECT_DIR
    with patch("app.api.routers.projects._pm", pm):
        first = api_client.post("/api/v1/projects", json={"name": "dupe-proj"})
        assert first.status_code == 200, first.text
        second = api_client.post("/api/v1/projects", json={"name": "dupe-proj"})
    assert second.status_code == 409
    assert "already exists" in second.text


# ── Promote: publish_alias FileNotFoundError → 404 ───────────────────────────


def test_promote_publish_alias_missing_dir_404(api_client, tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    runs_dir = tmp_path / "runs"
    run_id = "prom-404"
    (runs_dir / run_id).mkdir(parents=True)
    art = tmp_path / "artifacts" / "speech-commands" / "runs" / run_id
    art.mkdir(parents=True)
    (art / "metrics.json").write_text("{}", encoding="utf-8")
    (runs_dir / run_id / "meta.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "completed",
        "graph_name": "speech_commands_e2e_train_ml",
        "artifacts_dir": f"workspace/artifacts/speech-commands/runs/{run_id}",
    }))
    with (
        patch("app.api.routers.runs._get_runs_root", return_value=runs_dir),
        patch("app.core.paths.workspace_paths.publish_alias", side_effect=FileNotFoundError("run dir missing")),
    ):
        resp = api_client.post(f"/api/v1/runs/{run_id}/promote")
    assert resp.status_code == 404
