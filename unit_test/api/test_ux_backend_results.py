"""UX backend #1–#6, #9–#11 — run summary, display names, run models, registry, ship.

Builds a synthetic run shaped like Example 06's forked train graph:
ingest → features → dataset → {model_builder → trainer → evaluator → edge_optimizer} × 2.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

RUN = "run-ux-1"
PREV = "run-ux-0"
LABELS = ["down", "go", "no", "stop", "up", "yes"]


def _node(nid, ntype, cfg=None):
    return {"id": nid, "node_type": ntype, "config": cfg or {}}


def _graph(run_id: str, name: str = "speech_commands_e2e_train_ml", ingest_path: str | None = None):
    base = f"workspace/artifacts/speech-commands/runs/{run_id}"
    nodes = [
        _node("dataset_ingest_0", "dataset_ingest", {"path": ingest_path or "workspace/datasets/input/speech-commands"}),
        _node("feature_frontend_0", "feature_frontend"),
        _node("dataset_builder_0", "dataset_builder"),
        _node("model_builder_0", "model_builder", {"architecture": "ds_cnn", "filters": 64, "output_path": f"{base}/models"}),
        _node("trainer_0", "trainer", {"epochs": 50, "batch_size": 32, "output_path": f"{base}/trainer_0"}),
        _node("evaluator_0", "evaluator", {"output_path": f"{base}/evaluator_0"}),
        _node("edge_optimizer_0", "edge_optimizer", {"output_path": f"{base}/tflite"}),
        _node("model_builder_b", "model_builder", {"architecture": "simple_cnn", "filters": 64, "output_path": f"{base}/model_builder_b"}),
        _node("trainer_b", "trainer", {"epochs": 30, "batch_size": 32, "output_path": f"{base}/trainer_b"}),
        _node("evaluator_b", "evaluator", {"output_path": f"{base}/evaluator_b"}),
        _node("edge_optimizer_b", "edge_optimizer", {"output_path": f"{base}/tflite_b"}),
    ]
    e = [
        ("dataset_ingest_0", "feature_frontend_0"),
        ("feature_frontend_0", "dataset_builder_0"),
        ("dataset_builder_0", "model_builder_0"),
        ("dataset_builder_0", "trainer_0"),
        ("model_builder_0", "trainer_0"),
        ("trainer_0", "evaluator_0"),
        ("evaluator_0", "edge_optimizer_0"),
        ("dataset_builder_0", "model_builder_b"),
        ("model_builder_b", "trainer_b"),
        ("dataset_builder_0", "trainer_b"),
        ("trainer_b", "evaluator_b"),
        ("evaluator_b", "edge_optimizer_b"),
    ]
    return {
        "schema_version": 2,
        "metadata": {"name": name, "project": "demo"},
        "nodes": nodes,
        "edges": [{"src_id": a, "src_port": "output", "dst_id": b, "dst_port": "input"} for a, b in e],
    }


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (bytes, bytearray)):
        path.write_bytes(data)
    elif isinstance(data, str):
        path.write_text(data)
    else:
        path.write_text(json.dumps(data))


def make_run(ws: Path, run_id: str, acc_a: float, acc_b: float, created: str, **graph_kw) -> Path:
    rdir = ws / "runs" / run_id
    graph = _graph(run_id, **graph_kw)
    _write(rdir / "graph.json", graph)
    _write(
        rdir / "meta.json",
        {
            "run_id": run_id,
            "status": "succeeded",
            "project": "demo",
            "graph_name": graph["metadata"]["name"],
            "created_at": created,
            "artifacts_dir": f"workspace/artifacts/speech-commands/runs/{run_id}",
        },
    )
    _write(
        rdir / "logs.json",
        [
            {"type": "node_end", "node_id": "dataset_ingest_0", "node_type": "dataset_ingest", "output_count": 1200},
        ],
    )
    art = ws / "artifacts" / "speech-commands" / "runs" / run_id
    _write(art / "models" / "compiled_abc.keras", b"k" * 10)
    _write(art / "trainer_0" / "model.keras", b"k" * 20)
    _write(art / "trainer_0" / "saved_model" / "saved_model.pb", b"p" * 5)
    _write(art / "trainer_0" / "checkpoints" / "best.keras", b"c")
    _write(art / "evaluator_0" / "metrics.json", {"test_accuracy": acc_a, "per_class": {}, "roc_auc": 0.8})
    _write(art / "tflite" / "model.tflite", b"t" * 7)
    _write(art / "tflite" / "labels.txt", "\n".join(LABELS) + "\n")
    _write(art / "model_builder_b" / "compiled_def.keras", b"k")
    _write(art / "trainer_b" / "model.keras", b"k" * 3)
    _write(art / "evaluator_b" / "metrics.json", {"test_accuracy": acc_b})
    _write(art / "tflite_b" / "model.tflite", b"t")
    _write(art / "tflite_b" / "labels.txt", "\n".join(LABELS) + "\n")
    # outputs_index → artifact data.json with labels (trainer outputs)
    rows = []
    for nid in ("trainer_0", "trainer_b"):
        aid = f"{run_id}-{nid}"
        _write(ws / "artifacts" / aid / "data" / "data.json", {
            "model_path": f"workspace/artifacts/speech-commands/runs/{run_id}/{nid}/saved_model",
            "labels": LABELS,
            "history": {"val_accuracy": [0.4, 0.6]},
            "metrics": {},
        })
        rows.append({"artifact_id": aid, "node_id": nid, "node_type": "trainer", "data_path": f"artifacts/{aid}/data", "port": "output"})
    _write(rdir / "outputs_index.json", {"schema_version": 2, "artifacts": rows})
    return rdir


@pytest.fixture
def ux_ws(tmp_workspace: Path):
    from app.core.runs.run_summary import clear_cache

    clear_cache()
    make_run(tmp_workspace, PREV, 0.40, 0.30, "2026-10-01T00:00:00+00:00")
    make_run(tmp_workspace, RUN, 0.56, 0.50, "2026-10-02T00:00:00+00:00")
    yield tmp_workspace
    clear_cache()


# ── 1–3: summary / display name / labels ──────────────────────────────────────


def test_run_detail_summary(api_client, ux_ws):
    body = api_client.get(f"/api/v1/runs/{RUN}").json()
    assert body["display_name"] == "Speech commands E2E · train"
    assert body["meta"]["graph_name"] == "speech_commands_e2e_train_ml"
    s = body["summary"]
    assert s["primary_metric"] == {"name": "test_accuracy", "value": 0.56}
    assert s["best_path_id"] == "path-a"
    labels = {p["path_id"]: p["label"] for p in s["paths"]}
    assert labels == {"path-a": "DS-CNN · 50 epochs", "path-b": "CNN-small · 30 epochs"}
    pa = next(p for p in s["paths"] if p["path_id"] == "path-a")
    assert pa["node_ids"] == ["model_builder_0", "trainer_0", "evaluator_0", "edge_optimizer_0"]
    assert pa["metrics"]["test_accuracy"] == 0.56 and pa["metrics"]["final_val_accuracy"] == 0.6
    assert s["dataset"]["source_path"] == "workspace/datasets/input/speech-commands"
    assert s["dataset"]["clip_count"] == 1200
    assert s["dataset"]["from_ingest_node"] == "dataset_ingest_0"
    reg = body["regression"]
    assert reg["best_previous_run_id"] == PREV
    assert reg["best_previous_value"] == 0.40
    assert reg["delta"] == pytest.approx(0.16)
    assert body["meta"]["summary"] == s


def test_run_list_rows_carry_summary(api_client, ux_ws):
    rows = api_client.get("/api/v1/runs").json()
    row = next(r for r in rows if r["run_id"] == RUN)
    assert row["display_name"] == "Speech commands E2E · train"
    assert row["summary"]["best_path_id"] == "path-a"
    # List skips sibling regression scans (detail GET attaches it).
    assert row.get("regression") is None
    prev = next(r for r in rows if r["run_id"] == PREV)
    assert prev["regression"] is None


def test_paths_single_sink_and_fallback_labels():
    from app.core.runs.run_summary import compute_paths, path_labels

    g = {"nodes": [{"id": "a", "node_type": "x"}, {"id": "b", "node_type": "trainer", "config": {"epochs": 5}}],
         "edges": [{"src_id": "a", "dst_id": "b"}]}
    paths = compute_paths(g)
    assert paths == [{"path_id": "path-a", "node_ids": ["a", "b"]}]
    assert path_labels(g, paths) == {"path-a": "5 epochs"}
    g2 = {
        "nodes": [{"id": "s", "node_type": "src"}, {"id": "t1", "node_type": "trainer", "config": {"epochs": 5}},
                  {"id": "t2", "node_type": "trainer", "config": {"epochs": 5}}],
        "edges": [{"src_id": "s", "dst_id": "t1"}, {"src_id": "s", "dst_id": "t2"}],
    }
    p2 = compute_paths(g2)
    assert [p["node_ids"] for p in p2] == [["t1"], ["t2"]]
    assert path_labels(g2, p2) == {"path-a": "Path A", "path-b": "Path B"}


@pytest.mark.parametrize(
    ("name", "ingest", "meta_extra", "expected"),
    [
        ("speech_commands_e2e_preprocess", "workspace/datasets/input/speech-commands/yes", {}, "Speech commands E2E · preprocess · yes"),
        ("speech_commands_e2e_preprocess_down", "workspace/datasets/input/speech-commands/down", {}, "Speech commands E2E · preprocess · down"),
        ("pipeline", "workspace/datasets/output/p/v1/test/down", {"source_example": "06_speech_commands_e2e/pipeline_infer.graph.json"}, "Speech commands E2E · infer · down"),
        ("anything", "workspace/datasets/input/x", {"title": "My KWS"}, "My KWS"),
    ],
)
def test_display_names(name, ingest, meta_extra, expected):
    from app.core.runs.run_display import run_display_name

    g = {"metadata": {"name": name, **meta_extra},
         "nodes": [{"id": "i", "node_type": "dataset_ingest", "config": {"path": ingest}}], "edges": []}
    assert run_display_name(g, name) == expected


# ── 4: run models ─────────────────────────────────────────────────────────────


def test_run_models_endpoint(api_client, ux_ws):
    body = api_client.get(f"/api/v1/runs/{RUN}/models").json()
    assert body["best_path_id"] == "path-a"
    rows = body["models"]
    by_name = {(r["node_id"], r["format"]): r for r in rows}
    builder = by_name[("model_builder_0", "keras")]
    assert builder["kind"] == "compiled_untrained"
    trained = by_name[("trainer_0", "keras")]
    assert trained["kind"] == "trained"
    assert trained["path"] == f"workspace/artifacts/speech-commands/runs/{RUN}/trainer_0/model.keras"
    assert trained["size_bytes"] == 20 and trained["created_at"]
    assert trained["labels"] == LABELS and trained["path_label"] == "DS-CNN · 50 epochs"
    assert trained["metrics"]["test_accuracy"] == 0.56
    assert trained["suggested_name"] == "speech-commands-dscnn"
    assert by_name[("trainer_0", "saved_model")]["kind"] == "trained"
    opt = by_name[("edge_optimizer_0", "tflite")]
    assert opt["kind"] == "optimized" and opt["labels_source"] == "labels.txt"
    assert by_name[("trainer_b", "keras")]["suggested_name"] == "speech-commands-cnnsmall"
    # checkpoints/ are not listed
    assert not any("checkpoints" in r["path"] for r in rows)


# ── 4b/5: registry ────────────────────────────────────────────────────────────


def test_register_rejects_untrained_and_resolves_real_path(api_client, ux_ws):
    r = api_client.post("/api/v1/models", json={"name": "bad", "run_id": RUN, "node_id": "model_builder_0"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "compiled_untrained"
    r = api_client.post(
        "/api/v1/models",
        json={"name": "bad", "run_id": RUN, "node_id": "model_builder_0", "allow_untrained": True},
    )
    assert r.status_code == 200
    model_path = f"workspace/artifacts/speech-commands/runs/{RUN}/trainer_0/model.keras"
    r = api_client.post("/api/v1/models", json={"name": "speech-commands-dscnn", "run_id": RUN, "model_path": model_path})
    assert r.status_code == 200, r.text
    st = r.json()["stages"]["staging"]
    assert st["path"] == model_path and st["artifact_kind"] == "trained"
    assert st["alias_path"].endswith("speech-commands/staging")
    got = api_client.get("/api/v1/models/speech-commands-dscnn").json()["stages"]["staging"]
    assert got["kind"] == "model_stage" and got["exists"] is True
    assert got["format"] == "keras" and got["labels"] == LABELS
    assert got["metrics"]["test_accuracy"] == 0.56 and got["source_run_id"] == RUN
    r = api_client.post("/api/v1/models", json={"name": "x", "run_id": RUN, "model_path": "workspace/nope.keras"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "model_not_in_run"


def test_legacy_registry_entry_resolved_at_read(api_client, ux_ws):
    reg = ux_ws / "artifacts" / "_registry" / "models.json"
    _write(reg, {"models": {"edge_optimizer_0": {"slug": "speech-commands", "stages": {"staging": {
        "run_id": RUN, "slug": "speech-commands", "path": "workspace/artifacts/speech-commands/staging"}}}}})
    body = api_client.get("/api/v1/models/edge_optimizer_0").json()
    st = body["stages"]["staging"]
    assert st["path"].endswith("/tflite/model.tflite") and st["format"] == "tflite"
    assert st["alias_path"] == "workspace/artifacts/speech-commands/staging"
    assert st["exists"] is True
    listed = api_client.get("/api/v1/models").json()["models"]
    assert listed[0]["stages"]["staging"]["kind"] == "model_stage"


def test_request_approve_prod_carries_artifact(ux_ws):
    from app.core.mlops.model_registry import approve_prod, register_model, request_prod

    register_model("kws", run_id=RUN, slug="", stage="staging", node_id="trainer_0")
    request_prod("kws")
    done = approve_prod("kws")
    assert done["stages"]["prod"]["artifact_path"].endswith("trainer_0/model.keras")


# ── 6: ship ───────────────────────────────────────────────────────────────────


@pytest.fixture
def ship_proj(ux_ws):
    from app.domain.project_manager import ProjectManager

    ProjectManager().create("ux-ship")
    from app.api import idempotency as idem

    idem._MEMORY.clear()
    return "ux-ship"


def test_ship_with_run_model_path_and_labels(api_client, ship_proj):
    path = f"workspace/artifacts/speech-commands/runs/{RUN}/tflite/model.tflite"
    r = api_client.post(
        f"/api/v1/projects/{ship_proj}/ship/packages",
        headers={"Idempotency-Key": "ux-ship-1"},
        json={"model_path": path, "run_id": RUN, "labels": LABELS, "target": {"runtime": "tflite"}},
    )
    assert r.status_code == 201, r.text
    man = r.json()["manifest"]
    assert man["model_ref"]["model_path"] == path and man["labels"] == LABELS
    roles = {f["path"]: f["role"] for f in man["files"]}
    assert roles["model/model.tflite"] == "model" and roles["model/labels.txt"] == "labels"


def test_ship_labels_mismatch(api_client, ship_proj):
    path = f"workspace/artifacts/speech-commands/runs/{RUN}/tflite/model.tflite"
    r = api_client.post(
        f"/api/v1/projects/{ship_proj}/ship/packages",
        headers={"Idempotency-Key": "ux-ship-2"},
        json={"model_path": path, "labels": list(reversed(LABELS)), "target": {"runtime": "tflite"}},
    )
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "labels_mismatch"
    assert body["detail"]["expected"] == LABELS


def test_ship_requires_model(api_client, ship_proj):
    r = api_client.post(
        f"/api/v1/projects/{ship_proj}/ship/packages",
        headers={"Idempotency-Key": "ux-ship-3"},
        json={"target": {"runtime": "tflite"}},
    )
    assert r.status_code == 422


# ── 9 / 10 / 11 ───────────────────────────────────────────────────────────────


def test_data_output_files_rows(api_client, tmp_workspace):
    d = tmp_workspace / "datasets" / "output" / "proj" / "v1" / "train" / "yes"
    d.mkdir(parents=True)
    (d / "a.wav").write_bytes(b"RIFF")
    body = api_client.get("/api/v1/data/outputs/proj/v1").json()
    assert isinstance(body, dict) and isinstance(body["files"], list)
    row = next(f for f in body["files"] if f["path"].endswith("a.wav"))
    assert row["name"] == "a.wav" and row["size"] == 4
    assert body["file_count"] == len(body["files"])


def test_pipeline_env_kind(tmp_path):
    from app.core.pipelines.pipeline_environments import enrich_pipeline_summary, get_environments

    assert get_environments(tmp_path, "p")["kind"] == "pipeline_env"
    assert enrich_pipeline_summary(tmp_path, {"name": "p"})["environments"]["kind"] == "pipeline_env"


def test_templates_runnable_and_group(api_client, tmp_workspace):
    tdir = tmp_workspace / "configs" / "templates"
    tdir.mkdir(parents=True)
    graph = {
        "schema_version": 2,
        "metadata": {"name": "t", "group": "speech-commands-e2e", "phase": 1, "step_title": "Prepare data"},
        "nodes": [{"id": "a", "node_type": "definitely_not_registered_xyz", "config": {}}],
        "edges": [],
    }
    (tdir / "t1.graph.json").write_text(json.dumps(graph))
    rows = api_client.get("/api/v1/pipelines/templates").json()
    row = next(r for r in rows if r["name"] == "t1")
    assert row["runnable"] is False
    assert row["missing_node_types"] == ["definitely_not_registered_xyz"]
    assert row["group"] == "speech-commands-e2e" and row["phase"] == 1
    assert row["step_title"] == "Prepare data"
