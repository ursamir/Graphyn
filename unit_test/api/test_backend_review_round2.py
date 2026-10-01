"""Regression tests for the second backend review round (2026-10).

1. template titles fall back to the repo source when the synced copy lacks one
2. run outputs use natural (numeric-aware) ordering before truncation
3. disabled / orphaned schedules report next_run_at: null; API keys stable
4. isolated plugin stubs take category/label/description from NodeMetadata
5. node failure is reported once (terminal error tagged already_reported)
6. GET /runs/{id} exposes node_order (incl. nodes that never ran)
7. proposals accept optional kind + context
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


# ── 1. Template titles ───────────────────────────────────────────────────────


def test_template_title_falls_back_to_repo_source(api_client, tmp_workspace: Path):
    src = json.loads((REPO / "examples" / "templates" / "captions.graph.json").read_text())
    expected = src["metadata"]["title"]
    stale = json.loads(json.dumps(src))
    stale["metadata"].pop("title", None)
    stale["metadata"]["source_example"] = "templates/captions.graph.json"
    tdir = tmp_workspace / "configs" / "templates"
    tdir.mkdir(parents=True)
    (tdir / "captions.graph.json").write_text(json.dumps(stale), encoding="utf-8")
    # A stale copy without source_example still resolves by name.
    stale2 = json.loads((REPO / "examples" / "templates" / "edge-deploy.graph.json").read_text())
    title2 = stale2["metadata"].pop("title")
    (tdir / "edge-deploy.graph.json").write_text(json.dumps(stale2), encoding="utf-8")

    resp = api_client.get("/api/v1/pipelines/templates")
    assert resp.status_code == 200
    by_name = {t["name"]: t["title"] for t in resp.json()}
    assert by_name["captions"] == expected
    assert by_name["edge-deploy"] == title2


def test_resolve_template_title_rules():
    from app.core.templates.example_templates import resolve_template_title

    assert resolve_template_title("captions", {"title": "Mine"}) == "Mine"
    assert resolve_template_title("no-such-template-xyz") == "No such template xyz"
    assert resolve_template_title("../etc", {"source_example": "../../x"}) == "../etc"


# ── 2. Natural ordering of outputs ───────────────────────────────────────────


def test_natural_sort_key_orders_digits_numerically():
    from app.core.runs.run_outputs import natural_sort_key

    names = ["10.wav", "100.wav", "2.wav", "0.wav", "1.wav", "b.json", "A.csv"]
    assert sorted(names, key=natural_sort_key) == [
        "0.wav", "1.wav", "2.wav", "10.wav", "100.wav", "A.csv", "b.json"
    ]


def _numbered_run(ws: Path, n: int) -> tuple[str, Path]:
    out = ws / "artifacts" / "numbered" / "clips"
    out.mkdir(parents=True)
    for i in range(n):
        (out / f"{i}.wav").write_bytes(b"RIFF")
    run_id = "run-natural-1"
    run_dir = ws / "runs" / run_id
    run_dir.mkdir(parents=True)
    graph = {
        "schema_version": "1.2",
        "metadata": {"name": "numbered"},
        "nodes": [{"id": "writer_0", "node_type": "audio_exporter", "config": {"output_dir": str(out)}}],
        "edges": [],
    }
    (run_dir / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
    (run_dir / "meta.json").write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
    return run_id, run_dir


def test_outputs_truncate_in_natural_order(tmp_workspace: Path, monkeypatch):
    monkeypatch.chdir(tmp_workspace.parent)
    import app.core.runs.run_outputs as ro

    run_id, run_dir = _numbered_run(tmp_workspace, 120)
    monkeypatch.setattr(ro, "_MAX_LISTED_FILES", 5)
    detail = ro.list_run_output_files_detail(run_id, run_dir)
    wavs = [e["name"] for e in detail["items"] if e["name"].endswith(".wav")]
    assert wavs and wavs == [f"{i}.wav" for i in range(len(wavs))]
    page = ro.list_node_output_files(run_id, run_dir, "writer_0", limit=12, offset=0)
    names = [e["name"] for e in page["items"]]
    assert names == [f"{i}.wav" for i in range(12)]
    page2 = ro.list_node_output_files(run_id, run_dir, "writer_0", limit=5, offset=98)
    assert [e["name"] for e in page2["items"]] == [f"{i}.wav" for i in range(98, 103)]


# ── 3. Schedules ─────────────────────────────────────────────────────────────


def test_disabled_schedule_has_no_next_run(tmp_workspace: Path):
    from app.core.pipelines.schedules import (
        create_schedule,
        disable_schedules_for_project,
        list_schedules,
        set_schedule_enabled,
    )

    off = create_schedule(name="off", project="p1", pipeline="main", enabled=False, base_dir=tmp_workspace)
    assert off["next_run_at"] is None
    on = create_schedule(name="on", project="p2", pipeline="main", base_dir=tmp_workspace)
    assert on["next_run_at"]

    disabled = set_schedule_enabled(on["id"], False, base_dir=tmp_workspace)
    assert disabled["next_run_at"] is None
    enabled = set_schedule_enabled(on["id"], True, base_dir=tmp_workspace)
    nxt = datetime.fromisoformat(enabled["next_run_at"])
    assert nxt > datetime.now(timezone.utc) + timedelta(minutes=50)

    disable_schedules_for_project("p2", base_dir=tmp_workspace)
    items = {i["name"]: i for i in list_schedules(base_dir=tmp_workspace)}
    assert items["on"]["orphaned"] is True and items["on"]["next_run_at"] is None


def test_legacy_disabled_row_reports_null_next_run(tmp_workspace: Path):
    from app.core.pipelines.schedules import create_schedule, list_schedules

    create_schedule(name="legacy", project="p", pipeline="main", base_dir=tmp_workspace)
    path = tmp_workspace / "schedules.json"
    data = json.loads(path.read_text())
    data[0]["enabled"] = False  # old writer left next_run_at in place
    path.write_text(json.dumps(data))
    assert list_schedules(base_dir=tmp_workspace)[0]["next_run_at"] is None


def test_permanent_error_clears_next_run_and_sets_orphaned_at(tmp_workspace: Path):
    from app.core.pipelines.schedules import create_schedule, list_schedules, tick_due_schedules

    create_schedule(name="ghost", project="nope-project", pipeline="main", base_dir=tmp_workspace)
    path = tmp_workspace / "schedules.json"
    data = json.loads(path.read_text())
    data[0]["next_run_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    path.write_text(json.dumps(data))
    tick_due_schedules(base_dir=tmp_workspace)
    item = list_schedules(base_dir=tmp_workspace)[0]
    assert item["enabled"] is False and item["next_run_at"] is None
    assert item["orphaned"] is True and item["orphaned_at"]


def test_get_schedules_api_has_stable_orphan_keys(api_client, tmp_workspace: Path):
    from app.core.pipelines.schedules import create_schedule, disable_schedules_for_project

    create_schedule(name="live", project="alive", pipeline="main")
    create_schedule(name="dead", project="gone", pipeline="main")
    disable_schedules_for_project("gone")
    body = api_client.get("/api/v1/system/schedules").json()["schedules"]
    by = {s["name"]: s for s in body}
    for item in body:
        for key in ("orphaned", "disabled_reason", "orphaned_at", "next_run_at"):
            assert key in item
    assert by["live"]["orphaned"] is False and by["live"]["disabled_reason"] is None
    assert by["live"]["next_run_at"]
    assert by["dead"]["orphaned"] is True and by["dead"]["orphaned_at"]
    assert by["dead"]["next_run_at"] is None

    resp = api_client.post(f"/api/v1/system/schedules/{by['dead']['id']}/enable", json={"enabled": True})
    assert resp.status_code == 200
    again = resp.json()
    assert again["orphaned"] is False and again["disabled_reason"] is None
    assert again["next_run_at"]


# ── 4. Isolated plugin metadata ──────────────────────────────────────────────

_ISOLATED_SRC = '''
from typing import ClassVar
from app.core.nodes.base import Node
from app.core.nodes.metadata import NodeMetadata


class Trainy(Node):
    node_type = "trainy"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="trainy",
        label="Trainy McTrain",
        description=(
            "Trains "
            "things."
        ),
        category="ML",
        tags=["ml", "training"],
        requires_gpu=True,
        memory_requirements="high",
    )
'''


def _manifest(**kw):
    from app.core.plugins.manifest import PluginManifest

    base = dict(
        name="trainy-pack",
        version="2.0.0",
        description="Trainy pack.",
        author="t",
        platform_version=">=0.0",
        entry_points=["nodes.py"],
        runtime="isolated",
        node_types=["trainy", "other_node"],
        tags=["pack"],
    )
    base.update(kw)
    return PluginManifest(**base)


def test_isolated_spec_extracts_metadata_literals():
    from app.core.plugins.isolated_schema import specs_from_source

    spec = specs_from_source(_ISOLATED_SRC)["trainy"]
    assert spec.metadata_kwargs["category"] == "ML"
    assert spec.metadata_kwargs["label"] == "Trainy McTrain"
    assert spec.metadata_kwargs["description"] == "Trains things."
    assert spec.metadata_kwargs["requires_gpu"] is True


def test_isolated_stub_registers_with_declared_category(tmp_path: Path):
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.loader import PluginLoader

    plugin_dir = tmp_path / "trainy"
    plugin_dir.mkdir()
    (plugin_dir / "nodes.py").write_text(_ISOLATED_SRC, encoding="utf-8")
    registry = NodeRegistry()
    loader = PluginLoader(registry)
    loader._register_isolated_nodes(plugin_dir, _manifest())  # type: ignore[attr-defined]
    meta = registry.get_metadata("trainy")
    assert meta.category == "ML"
    assert meta.label == "Trainy McTrain"
    assert meta.description == "Trains things."
    assert meta.tags == ["ml", "training"]
    assert meta.requires_gpu is True
    # A node with no NodeMetadata literal falls back to manifest + generic.
    other = registry.get_metadata("other_node")
    assert other.category == "plugin"
    assert other.description == "Trainy pack."
    assert other.tags == ["pack"]
    assert other.version == "2.0.0"


@pytest.mark.parametrize(
    "plugin, node_type, category",
    [
        ("trainer", "trainer", "ML"),
        ("trainer", "model_builder", "ML"),
        ("evaluator", "evaluator", "ML"),
        ("dataset_builder", "dataset_builder", "ML"),
        ("edge_optimizer", "edge_optimizer", "Export"),
        ("realtime_inference", "realtime_inference", "Inference"),
    ],
)
def test_bundled_isolated_plugins_declare_real_category(plugin, node_type, category):
    from app.core.plugins.isolated_schema import specs_from_source

    src = REPO / "PluginPackage" / "Common" / plugin / "nodes.py"
    if not src.is_file():
        pytest.skip(f"{plugin} not present in PluginPackage")
    spec = specs_from_source(src.read_text(encoding="utf-8")).get(node_type)
    assert spec is not None
    assert spec.metadata_kwargs.get("category") == category


# ── 5. Single error report ───────────────────────────────────────────────────


def test_logger_node_error_has_error_field():
    from app.core.logger import PipelineLogger

    events: list[dict] = []

    class _Q:
        def put_nowait(self, item):
            events.append(item)

    log = PipelineLogger(queue=_Q())
    log.node_error("audio_conditioner", 1, ValueError("Sample rate should be over 0"), node_id="ac_1")
    ev = [e for e in events if isinstance(e, dict) and e.get("type") == "node_error"][0]
    assert ev["error"] == "Sample rate should be over 0"
    assert ev["error_message"] == ev["error"]


def test_terminal_error_marks_already_reported_node_failure():
    from app.api.routers.pipelines import _RunEventChannel, _terminal_error_event

    ch = _RunEventChannel()
    ch.put_nowait({"type": "node_error", "node_id": "ac_1", "node_type": "audio_conditioner",
                   "error": "Sample rate should be over 0"})
    ev = _terminal_error_event("r1", ValueError("Sample rate should be over 0"), ch.last_node_error)
    assert ev["type"] == "error" and ev["error"] == ev["message"]
    assert ev["already_reported"] is True and ev["node_id"] == "ac_1"

    other = _terminal_error_event("r1", RuntimeError("backend down"), ch.last_node_error)
    assert "already_reported" not in other and other["error"] == "backend down"
    assert "already_reported" not in _terminal_error_event("r1", RuntimeError("x"), None)


# ── 6. node_order on run detail ──────────────────────────────────────────────


def test_graph_node_order_is_execution_order():
    from app.core.runs.run_nodes import graph_node_order

    graph = {
        "nodes": [
            {"id": "c", "node_type": "t"},
            {"id": "a", "node_type": "t"},
            {"id": "b", "node_type": "t"},
            {"id": "d", "node_type": "t"},
        ],
        "edges": [
            {"src_id": "a", "dst_id": "b"},
            {"src_id": "b", "dst_id": "c"},
            {"src_id": "a", "dst_id": "d"},
        ],
    }
    order = graph_node_order(graph)
    assert [n["node_id"] for n in order] == ["a", "b", "d", "c"]
    assert [n["wave"] for n in order] == [0, 1, 1, 2]
    assert [n["index"] for n in order] == [0, 1, 2, 3]


def test_get_run_exposes_node_order_and_error_field(api_client, tmp_workspace: Path):
    run_id = "noderun1"
    run_dir = tmp_workspace / "runs" / run_id
    run_dir.mkdir(parents=True)
    graph = {
        "schema_version": "1.2",
        "metadata": {"name": "order"},
        "nodes": [
            {"id": "ingest_0", "node_type": "dataset_ingest", "config": {}},
            {"id": "cond_1", "node_type": "audio_conditioner", "config": {}},
            {"id": "seg_2", "node_type": "segmenter", "config": {}},
        ],
        "edges": [
            {"src_id": "ingest_0", "src_port": "output", "dst_id": "cond_1", "dst_port": "input"},
            {"src_id": "cond_1", "src_port": "output", "dst_id": "seg_2", "dst_port": "input"},
        ],
    }
    (run_dir / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
    meta = {
        "run_id": run_id,
        "status": "failed",
        "node_stats": [
            {"node_id": "ingest_0", "status": "completed"},
            {"node_id": "cond_1", "status": "failed"},
        ],
    }
    (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    logs = [{"type": "node_error", "node_id": "cond_1", "error_message": "boom"}]
    (run_dir / "logs.json").write_text(json.dumps(logs), encoding="utf-8")

    body = api_client.get(f"/api/v1/runs/{run_id}").json()
    order = body["node_order"]
    assert [n["node_id"] for n in order] == ["ingest_0", "cond_1", "seg_2"]
    assert [n["status"] for n in order] == ["completed", "failed", "not_run"]
    assert body["logs"][0]["error"] == "boom"


# ── 7. Proposals kind/context ────────────────────────────────────────────────


def _tiny_graph() -> dict:
    return {"schema_version": "1.2", "metadata": {"name": "p"}, "nodes": [], "edges": []}


def test_proposal_kind_and_context_roundtrip(api_client, tmp_workspace: Path):
    ctx = {"run_id": "r1", "node_id": "cond_1", "error": "Sample rate should be over 0"}
    resp = api_client.post(
        "/api/v1/proposals",
        json={"summary": "Explain failure", "graph": _tiny_graph(), "kind": "explain_failure", "context": ctx},
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["kind"] == "explain_failure" and created["context"] == ctx
    got = api_client.get(f"/api/v1/proposals/{created['id']}").json()
    assert got["kind"] == "explain_failure" and got["context"] == ctx
    listed = api_client.get("/api/v1/proposals").json()["proposals"]
    assert any(p["id"] == created["id"] and p["kind"] == "explain_failure" for p in listed)


def test_proposal_without_kind_is_unchanged(api_client, tmp_workspace: Path):
    resp = api_client.post("/api/v1/proposals", json={"summary": "plain", "graph": _tiny_graph()})
    assert resp.status_code == 200
    assert resp.json()["kind"] is None and resp.json()["context"] is None


def test_proposal_rejects_bad_kind(api_client, tmp_workspace: Path):
    resp = api_client.post(
        "/api/v1/proposals", json={"summary": "x", "graph": _tiny_graph(), "kind": "Bad Kind!"}
    )
    assert resp.status_code in (400, 422)


# ── 8. plugin.toml bounds + ui table reach config_schema ─────────────────────

_TOML_FIELDS = {
    "rate": {
        "type": "number", "title": "Rate", "default": 0.5,
        "exclusiveMinimum": 0, "exclusiveMaximum": 1, "multipleOf": 0.05,
    },
    "name": {"type": "string", "default": "a", "minLength": 1, "maxLength": 32, "pattern": "^[a-z]+$"},
    "mode": {"type": "string", "default": "x", "enum": ["x", "y"]},
    "extra": {
        "type": "integer", "default": 1, "minimum": 0, "maximum": 9,
        "ui": {"group": "Advanced", "widget": "slider", "visible_if": {"mode": "y"}, "depends_on": ["mode"]},
    },
}


def test_toml_bounds_and_ui_table_pass_through():
    from app.core.nodes.plugin_ui import json_schema_from_toml_fields

    props = json_schema_from_toml_fields(_TOML_FIELDS)["properties"]
    assert props["rate"]["exclusiveMinimum"] == 0 and props["rate"]["exclusiveMaximum"] == 1
    assert props["rate"]["multipleOf"] == 0.05
    assert props["name"]["minLength"] == 1 and props["name"]["maxLength"] == 32
    assert props["name"]["pattern"] == "^[a-z]+$"
    assert props["mode"]["enum"] == ["x", "y"]
    extra = props["extra"]
    assert extra["minimum"] == 0 and extra["maximum"] == 9
    assert extra["group"] == "Advanced" and extra["widget"] == "slider"
    assert extra["ui"]["visible_if"] == {"mode": "y"}
    assert extra["ui"]["depends_on"] == ["mode"]
    # Copied, not aliased.
    extra["ui"]["visible_if"]["mode"] = "z"
    assert _TOML_FIELDS["extra"]["ui"]["visible_if"] == {"mode": "y"}


def test_registry_config_schema_overlays_bounds_and_ui():
    from pydantic import Field

    from app.core.nodes.base import Node
    from app.core.nodes.config import NodeConfig
    from app.core.nodes.metadata import NodeMetadata
    from app.core.nodes.registry import NodeRegistry

    class _Cfg(NodeConfig):
        rate: float = Field(0.5, description="pydantic desc")
        extra: int = 1

    class _N(Node):
        node_type = "bounded_node"
        Config = _Cfg
        input_ports: dict = {}
        output_ports: dict = {}

        def process(self, inputs):  # pragma: no cover
            return {}

    reg = NodeRegistry()
    reg.register(
        "bounded_node",
        _N,
        NodeMetadata(node_type="bounded_node", label="B", description="b", category="Test"),
    )
    reg.set_plugin_ui_schema("bounded_node", {k: _TOML_FIELDS[k] for k in ("rate", "extra")})
    schema = reg.get_config_schema("bounded_node")
    rate = schema["properties"]["rate"]
    assert rate["exclusiveMinimum"] == 0 and rate["multipleOf"] == 0.05
    assert rate["description"] == "pydantic desc"  # Pydantic-only keys kept
    assert schema["properties"]["extra"]["ui"]["visible_if"] == {"mode": "y"}
