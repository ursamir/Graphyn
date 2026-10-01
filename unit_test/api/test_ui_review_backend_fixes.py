"""Regression tests for backend issues found in the live UI review (2026-10).

1. orphan schedules (project delete / permanent start errors / ?project=)
2. run outputs never attribute ProjectManager metadata to a node
3. outputs truncation metadata (?with_meta=1, ?node_id= paging)
4. pipeline_cancelled notification
5. credentials secret_fields_set
6. POST /pipelines/run never writes a project pipeline
7. distinct template display titles
8. readiness catalog section (non-blocking)
9. draining 503 carries Retry-After + retryable
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── 1. Orphan schedules ──────────────────────────────────────────────────────


def _make_due(base: Path) -> None:
    path = base / "schedules.json"
    data = json.loads(path.read_text())
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    for item in data:
        item["next_run_at"] = past
    path.write_text(json.dumps(data))


def test_project_delete_orphans_its_schedules(tmp_workspace: Path):
    from app.core.pipelines.schedules import create_schedule, list_schedules
    from app.domain.project_manager import ProjectManager

    pm = ProjectManager()
    pm.create("doomed")
    create_schedule(name="hourly", project="doomed", pipeline="main", base_dir=tmp_workspace)
    keep = create_schedule(name="other", project="keeper", pipeline="main", base_dir=tmp_workspace)

    pm.delete("doomed", "doomed")

    items = {i["project"]: i for i in list_schedules(base_dir=tmp_workspace)}
    orphan = items["doomed"]
    assert orphan["enabled"] is False
    assert orphan["orphaned"] is True
    assert "Project deleted" in orphan["disabled_reason"]
    assert items["keeper"]["enabled"] is True
    assert "orphaned" not in items["keeper"]
    assert keep["id"] == items["keeper"]["id"]


def test_project_delete_without_schedules_file_creates_nothing(tmp_workspace: Path):
    from app.domain.project_manager import ProjectManager

    pm = ProjectManager()
    pm.create("solo")
    pm.delete("solo", "solo")
    assert not (tmp_workspace / "schedules.json").exists()


def test_tick_auto_disables_on_project_not_found(tmp_workspace: Path):
    from app.core.pipelines.schedules import create_schedule, list_schedules, tick_due_schedules

    create_schedule(name="ghost", project="samir-test", pipeline="main", base_dir=tmp_workspace)
    _make_due(tmp_workspace)
    fired = tick_due_schedules(base_dir=tmp_workspace)
    assert fired and fired[0]["last_error"].startswith("Project not found")
    item = list_schedules(base_dir=tmp_workspace)[0]
    assert item["enabled"] is False
    assert item["orphaned"] is True
    assert "auto-disabled" in item["disabled_reason"]
    assert item["last_error_at"]
    # A second tick does not retry a disabled schedule.
    _make_due(tmp_workspace)
    assert tick_due_schedules(base_dir=tmp_workspace) == []


def test_tick_auto_disables_on_pipeline_not_found(tmp_workspace: Path):
    from app.core.pipelines.schedules import create_schedule, list_schedules, tick_due_schedules
    from app.domain.project_manager import ProjectManager

    ProjectManager().create("realproj")
    create_schedule(
        name="nopipe", project="realproj", pipeline="missing", env="draft", base_dir=tmp_workspace
    )
    _make_due(tmp_workspace)
    tick_due_schedules(base_dir=tmp_workspace)
    item = list_schedules(base_dir=tmp_workspace)[0]
    assert item["enabled"] is False
    assert "not found" in item["last_error"]
    assert not item.get("orphaned")


def test_transient_error_keeps_schedule_enabled(tmp_workspace: Path, monkeypatch):
    from app.core.pipelines import schedules as sched

    sched.create_schedule(name="flaky", project="p", pipeline="main", base_dir=tmp_workspace)
    _make_due(tmp_workspace)

    def _boom(*_a, **_k):
        raise RuntimeError("backend busy")

    monkeypatch.setattr(sched, "_execute_pipeline", _boom)
    sched.tick_due_schedules(base_dir=tmp_workspace)
    item = sched.list_schedules(base_dir=tmp_workspace)[0]
    assert item["enabled"] is True
    assert item["last_error"] == "backend busy"


def test_reenable_clears_orphan_flags(tmp_workspace: Path):
    from app.core.pipelines.schedules import (
        create_schedule,
        disable_schedules_for_project,
        set_schedule_enabled,
    )

    item = create_schedule(name="s", project="gone", pipeline="main", base_dir=tmp_workspace)
    disable_schedules_for_project("gone", base_dir=tmp_workspace)
    again = set_schedule_enabled(item["id"], True, base_dir=tmp_workspace)
    assert again["enabled"] is True
    assert "orphaned" not in again and "disabled_reason" not in again


def test_get_schedules_project_filter(api_client, tmp_workspace: Path):
    from app.core.pipelines.schedules import create_schedule

    create_schedule(name="a", project="alpha", pipeline="main")
    create_schedule(name="b", project="beta", pipeline="main")
    resp = api_client.get("/api/v1/system/schedules", params={"project": "alpha"})
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()["schedules"]]
    assert names == ["a"]
    assert len(api_client.get("/api/v1/system/schedules").json()["schedules"]) == 2


# ── 2 / 3. Run outputs attribution + truncation ──────────────────────────────


def _make_project_run(ws: Path, *, n_wavs: int = 3) -> tuple[str, Path, Path]:
    """Project dir with PM metadata + an exporter v1/ dir, and a run whose graph points there."""
    project = ws / "datasets" / "output" / "proj"
    (project / "pipelines").mkdir(parents=True)
    (project / "snapshots").mkdir()
    for name in ("project.json", "taxonomy.json", "contract.json", "links.json"):
        (project / name).write_text("{}", encoding="utf-8")
    (project / "spec.md").write_text("# spec", encoding="utf-8")
    (project / "pipelines" / "main.graph.json").write_text("{}", encoding="utf-8")
    (project / "snapshots" / "s1.json").write_text("{}", encoding="utf-8")
    (project / "annotations.jsonl").write_text("", encoding="utf-8")
    v1 = project / "v1" / "train" / "yes"
    v1.mkdir(parents=True)
    label_rows = ["id,path,label,split"]
    published: list[dict] = [{"path": "labels.csv"}]
    for i in range(n_wavs):
        (v1 / f"s{i}.wav").write_bytes(b"RIFF")
        rel = f"train/yes/s{i}.wav"
        label_rows.append(f"{i},{rel},yes,train")
        published.append({"path": rel})
    (project / "v1" / "labels.csv").write_text("\n".join(label_rows) + "\n", encoding="utf-8")
    (project / "v0").mkdir()
    (project / "v0" / "labels.csv").write_text("old\n", encoding="utf-8")

    run_id = "run-ui-review-1"
    run_dir = ws / "runs" / run_id
    run_dir.mkdir(parents=True)
    graph = {
        "schema_version": "1.2",
        "metadata": {"name": "ui-review", "seed": 1},
        "nodes": [
            {
                "id": "audio_exporter_3",
                "node_type": "audio_exporter",
                "config": {
                    "output_dir": "workspace/datasets/output/audio_export",
                    "project": "proj",
                    "version_tag": "v1",
                },
            }
        ],
        "edges": [],
    }
    (run_dir / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
    (run_dir / "meta.json").write_text(json.dumps({"run_id": run_id}), encoding="utf-8")

    # Listing comes from ArtifactStore file_tree (not graph path rediscovery).
    from app.core.artifacts.artifact_store import ArtifactStore
    from app.core.artifacts.file_tree import file_tree_payload, register_file_tree_serializer

    register_file_tree_serializer()
    ArtifactStore().register(
        run_id=run_id,
        node_id="audio_exporter_3",
        node_type="audio_exporter",
        artifact_type="file_tree",
        data=file_tree_payload(
            {
                "root": "workspace/datasets/output/proj/v1",
                "files": published,
                "total": len(published),
            }
        ),
    )
    return run_id, run_dir, project


def test_is_project_metadata_path(tmp_workspace: Path):
    from app.core.runs.run_outputs import is_project_metadata_path

    _run_id, _run_dir, project = _make_project_run(tmp_workspace)
    assert is_project_metadata_path(project / "project.json")
    assert is_project_metadata_path(project / "pipelines" / "main.graph.json")
    assert is_project_metadata_path(project / "annotations.jsonl")
    assert is_project_metadata_path(project)
    assert not is_project_metadata_path(project / "v1" / "labels.csv")
    assert not is_project_metadata_path(tmp_workspace / "runs")


def test_outputs_exclude_project_metadata(tmp_workspace: Path, monkeypatch):
    monkeypatch.chdir(tmp_workspace.parent)
    from app.core.runs.run_outputs import list_run_output_files

    run_id, run_dir, _project = _make_project_run(tmp_workspace)
    entries = list_run_output_files(run_id, run_dir)
    names = {e["name"] for e in entries}
    paths = [e["path"] for e in entries]
    for meta in ("project.json", "spec.md", "taxonomy.json", "contract.json", "links.json", "main.graph.json"):
        assert meta not in names, meta
    assert not any("/pipelines/" in p or "/snapshots/" in p for p in paths)
    # v0 belongs to an older export, not this run.
    assert not any("/v0/" in p for p in paths)
    exporter = [e for e in entries if e.get("node_id") == "audio_exporter_3"]
    assert exporter and all("/v1" in e["path"] for e in exporter)


def test_outputs_with_meta_and_node_paging(api_client, tmp_workspace: Path, monkeypatch):
    monkeypatch.chdir(tmp_workspace.parent)
    import app.core.runs.run_outputs as ro

    run_id, _run_dir, _project = _make_project_run(tmp_workspace, n_wavs=12)
    # Force truncation of the node listing so the meta has something to report.
    monkeypatch.setattr(ro, "_MAX_LISTED_FILES", 5)

    bare = api_client.get(f"/api/v1/runs/{run_id}/outputs")
    assert bare.status_code == 200
    assert isinstance(bare.json(), list)
    assert bare.headers.get("X-Graphyn-Outputs-Truncated") == "true"

    meta = api_client.get(f"/api/v1/runs/{run_id}/outputs", params={"with_meta": 1})
    assert meta.status_code == 200
    body = meta.json()
    assert set(body) >= {"items", "truncated", "max_items", "truncated_by_node"}
    assert body["truncated"] is True
    node = body["truncated_by_node"]["audio_exporter_3"]
    assert node["total"] == 13  # 12 wavs + labels.csv
    assert node["shown"] < node["total"]

    page1 = api_client.get(
        f"/api/v1/runs/{run_id}/outputs",
        params={"node_id": "audio_exporter_3", "limit": 10, "offset": 0},
    ).json()
    page2 = api_client.get(
        f"/api/v1/runs/{run_id}/outputs",
        params={"node_id": "audio_exporter_3", "limit": 10, "offset": 10},
    ).json()
    assert page1["total"] == 13 and page1["has_more"] is True
    assert len(page1["items"]) == 10 and len(page2["items"]) == 3
    assert page2["has_more"] is False
    all_names = {i["name"] for i in page1["items"] + page2["items"]}
    assert "project.json" not in all_names


def test_artifact_data_dir_summary_reports_total(tmp_path: Path):
    from app.core.runs import run_outputs as ro

    data = tmp_path / "data"
    data.mkdir()
    for i in range(20):
        (data / f"a{i}.wav").write_bytes(b"x")
    (data / "data.json").write_text("{}", encoding="utf-8")
    stats: dict[str, int] = {}
    with patch.object(ro, "is_under_jail", return_value=True):
        picked = ro._collect_artifact_data_dir(data, limit=100, stats=stats)
    assert len(picked) == ro._MAX_AUDIO_SAMPLES_LISTED + 1
    assert stats["total"] == 21


def test_oversized_artifact_data_json_is_not_parsed(tmp_path: Path, monkeypatch):
    """Tensor dumps in ArtifactStore data.json must not block outputs listing."""
    from app.core.runs import run_outputs as ro

    data = tmp_path / "data"
    data.mkdir()
    huge = data / "data.json"
    # Size gate only — do not write hundreds of MB in the test.
    huge.write_text('{"X_train": []}', encoding="utf-8")
    monkeypatch.setattr(ro, "_MAX_DATA_JSON_PARSE_BYTES", 1)
    monkeypatch.setattr(ro, "_MAX_DATA_JSON_LIST_BYTES", 1)
    assert ro._load_data_json_paths(data) == []
    with patch.object(ro, "is_under_jail", return_value=True):
        assert ro._allowed_file(huge) is False
    small = data / "metrics.json"
    small.write_text('{"acc": 1}', encoding="utf-8")
    with patch.object(ro, "is_under_jail", return_value=True):
        assert ro._allowed_file(small) is True


# ── 4. Cancel notification ───────────────────────────────────────────────────


def test_cancelled_maps_to_pipeline_cancelled(monkeypatch):
    from app.core.runs.run_notify import notify_run_terminal

    calls = []

    class Fake:
        def notify(self, event, payload):
            calls.append((event, payload))

    monkeypatch.setattr("app.core.notify.webhook.WebhookService", Fake)
    in_app = []
    monkeypatch.setattr(
        "app.core.notify.in_app_notify.notify_from_run_event",
        lambda event, payload: in_app.append(event),
    )
    notify_run_terminal("cancelled", "r9", graph_name="g", project="p")
    assert calls == [
        ("pipeline_cancelled", {"run_id": "r9", "status": "cancelled", "graph_name": "g", "project": "p"})
    ]
    assert in_app == ["pipeline_cancelled"]


def test_mark_cancelled_notifies_once(tmp_workspace: Path, monkeypatch):
    from app.core.runs.run_journal import RunManager

    events = []
    monkeypatch.setattr(
        "app.core.runs.run_notify.notify_run_terminal",
        lambda status, run_id, **kw: events.append((status, run_id, kw.get("project"))),
    )
    run = RunManager()
    run._write_meta_field("project", "proj")
    assert run.mark_cancelled() is True
    run.mark_cancelled()  # idempotent re-stamp (orchestrator + cancel route) → no second event
    assert events == [("cancelled", run.run_id, "proj")]


def test_in_app_cancelled_level_is_warning(tmp_workspace: Path, monkeypatch):
    from app.core.notify import in_app_notify

    captured = {}
    monkeypatch.setattr(
        in_app_notify, "append_notification", lambda **kw: captured.update(kw) or kw
    )
    in_app_notify.notify_from_run_event("pipeline_cancelled", {"run_id": "r", "status": "cancelled"})
    assert captured["level"] == "warning"
    assert captured["event"] == "pipeline_cancelled"


# ── 5. Credentials secret_fields_set ─────────────────────────────────────────


def test_credentials_secret_fields_set(api_client, tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    monkeypatch.delenv("GRAPHYN_AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("GRAPHYN_API_TOKEN", raising=False)
    monkeypatch.delenv("GRAPHYN_CREDENTIALS_KEY", raising=False)

    unset = api_client.post(
        "/api/v1/credentials",
        json={"name": "local-ollama", "kind": "ollama", "payload": {}},
    ).json()
    assert unset["fields"].get("api_key", "") == ""
    assert unset["secret_fields_set"] == {"api_key": False}

    setv = api_client.post(
        "/api/v1/credentials",
        json={"name": "oa", "kind": "openai_compat", "payload": {"api_key": "sk-hidden"}},
    )
    assert "sk-hidden" not in setv.text
    body = setv.json()
    assert body["fields"]["api_key"] == "***"
    assert body["secret_fields_set"] == {"api_key": True}

    listed = api_client.get("/api/v1/credentials").json()["items"]
    by_name = {i["name"]: i for i in listed}
    assert by_name["local-ollama"]["secret_fields_set"]["api_key"] is False
    assert by_name["oa"]["secret_fields_set"]["api_key"] is True
    got = api_client.get(f"/api/v1/credentials/{body['id']}").json()
    assert got["secret_fields_set"] == {"api_key": True}


# ── 6. Runs never save project pipelines ─────────────────────────────────────


def test_run_does_not_create_project_pipeline(api_client, tmp_workspace: Path):
    from app.domain.project_manager import ProjectManager

    ProjectManager().create("ui-review")
    pipelines = tmp_workspace / "datasets" / "output" / "ui-review" / "pipelines"
    before = sorted(p.name for p in pipelines.glob("*")) if pipelines.is_dir() else []

    ir = {
        "schema_version": "1.2",
        "metadata": {"name": "basic-wakeword", "seed": 42, "project": "ui-review"},
        "nodes": [],
        "edges": [],
    }

    def _fake_execute(graph, logger=None, run_manager=None, **kwargs):
        if logger is not None:
            logger.pipeline_done(getattr(run_manager, "run_id", "x"), 0.01)
        return {}

    with (
        patch("app.api.routers.pipelines._refuse_invalid_graph", return_value=None),
        patch("app.core.execution.runtime_backend.get_backend") as gb,
    ):
        backend = MagicMock()
        backend.execute.side_effect = _fake_execute
        gb.return_value = backend
        resp = api_client.post("/api/v1/pipelines/run", json={"graph": ir, "project": "ui-review"})
        _ = resp.text
    assert resp.status_code == 200, resp.text
    after = sorted(p.name for p in pipelines.glob("*")) if pipelines.is_dir() else []
    assert after == before
    assert "basic-wakeword.graph.json" not in after


def test_audio_exporter_never_writes_pipelines_dir(tmp_path: Path, monkeypatch):
    pytest.importorskip("soundfile")
    import importlib.util

    repo = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "_ui_review_audio_exporter", repo / "PluginPackage" / "Audio" / "audio_exporter" / "nodes.py"
    )
    import sys

    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)
    monkeypatch.chdir(tmp_path)
    node = mod.AudioExporterNode(config={"project": "ui-review", "version_tag": "v1"})
    node.process({"input": []})
    project = tmp_path / "workspace" / "datasets" / "output" / "ui-review"
    assert (project / "v1" / "labels.csv").is_file()
    assert not (project / "pipelines").exists()


# ── 7. Template titles ───────────────────────────────────────────────────────


def test_template_display_titles_are_unique():
    from app.core.templates.example_templates import discover_example_graphs

    titles = [t["title"].strip().lower() for t in discover_example_graphs()]
    dupes = sorted({t for t in titles if titles.count(t) > 1})
    assert not dupes, dupes


def test_template_display_title_rules():
    from app.core.templates.example_templates import template_display_title

    assert template_display_title("ex-22-call-analytics") == "Call analytics (example 22)"
    assert template_display_title("call-analytics", {"title": "Call analytics (local)"}) == "Call analytics (local)"
    assert template_display_title("meeting-crm") == "Meeting CRM"


def test_starter_templates_still_load_with_title():
    from app.core.ir.loader import load_ir

    repo = Path(__file__).resolve().parents[2]
    for name in ("call-analytics", "captions", "edge-deploy"):
        data = json.loads((repo / "examples" / "templates" / f"{name}.graph.json").read_text())
        assert data["metadata"]["title"]
        load_ir(data)


# ── 8. Readiness catalog ─────────────────────────────────────────────────────


def test_readiness_catalog_section_is_informational(tmp_path: Path, monkeypatch):
    from app.core.host import readiness

    pkg = tmp_path / "pkg"
    for name in ("a", "b"):
        d = pkg / "Pack" / name
        d.mkdir(parents=True)
        (d / "plugin.toml").write_text(
            f'[plugin]\nname = "{name}"\nversion = "1.0.0"\nnode_types = ["{name}_node"]\n',
            encoding="utf-8",
        )
    monkeypatch.setenv("GRAPHYN_PLUGIN_PACKAGE_DIR", str(pkg))
    monkeypatch.delenv("GRAPHYN_BUNDLED_PLUGIN_ALLOWLIST", raising=False)
    readiness.clear_readiness_cache()
    try:
        cat = readiness.catalog_summary(registered_node_types=1)
        assert cat["bundled_plugins"] == 2
        assert cat["bundled_node_types"] == 2
        assert cat["partial_catalog"] is True
        assert cat["warnings"]
        snap = readiness.readiness_snapshot(max_age_s=0)
        assert "catalog" in snap
        assert "partial_catalog" in snap["catalog"]
        # ready semantics are unchanged by the catalog section
        expected_ready = (
            bool(snap["registry_ready"])
            and not snap["checks"]["store_corrupt"]
            and not snap["checks"]["disk_full"]
            and snap["checks"]["project_dir_writable"]
        )
        assert snap["ready"] is expected_ready
    finally:
        readiness.clear_readiness_cache()


# ── 9. Draining 503 ──────────────────────────────────────────────────────────


def test_run_draining_503_is_retryable_with_retry_after(api_client):
    with patch("app.core.host.shutdown.is_draining", return_value=True):
        resp = api_client.post("/api/v1/pipelines/run", json={"ir": {}})
    assert resp.status_code == 503
    assert resp.headers.get("Retry-After") == "30"
    err = resp.json()["error"]
    assert err["code"] == "draining"
    assert err["retryable"] is True
