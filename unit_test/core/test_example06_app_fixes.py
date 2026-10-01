"""App fixes found while verifying the Example 06 (speech commands E2E) template.

1. Pipeline-cache hits never leak another run's run-scoped output paths, and
   non-cacheable nodes never hit (even with a stale cache entry).
2. ``latest`` only moves to runs that produced artifacts; no empty run dirs.
3. /runs/{id}/outputs: run + key files first, per-node fair cap, source-node
   input files are not listed as outputs.
5. node_end.output_count counts the primary ``output`` port only.
(4 — ingest fallback / project stamp — lives in test_workspace_paths.py and
graphyn-ui/src/lib/projectStamp.test.ts; the graph_prepare check is here.)
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import threading
import time
from pathlib import Path
from typing import ClassVar

import pytest

from app.core.execution.orchestrator import run_pipeline_ir
from app.core.nodes import registry as global_registry
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.core.runs.run_journal import RunManager

from unit_test.core._runtime_fixes_nodes import (  # noqa: F401 — rt_env is a fixture
    CALLS,
    make_graph,
    rt_env,
)


# conftest stubs Thread.start / pool submit; parallel mode needs the real ones.
_REAL_SUBMIT = concurrent.futures.ThreadPoolExecutor.submit
_REAL_START = threading.Thread.start


@pytest.fixture
def real_threads(monkeypatch):
    monkeypatch.setattr(concurrent.futures.ThreadPoolExecutor, "submit", _REAL_SUBMIT)
    monkeypatch.setattr(threading.Thread, "start", _REAL_START)


class RtWriter(Node):
    """Writes ``model.bin`` into its (run-scoped) output_dir and returns the path."""

    node_type: ClassVar[str] = "rtfix_writer"
    input_ports: ClassVar[dict] = {}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}

    class Config(NodeConfig):
        output_dir: str = ""

    def process(self, inputs):
        from app.core.paths.workspace_paths import artifact_fs_path

        CALLS[self.node_type] += 1
        out = artifact_fs_path(self.config.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "model.bin").write_text(f"call-{CALLS[self.node_type]}", encoding="utf-8")
        return {"output": [{"rt": True, "v": 1, "path": f"{self.config.output_dir}/model.bin"}]}


class RtGate(Node):
    node_type: ClassVar[str] = "rtfix_gate"
    input_ports: ClassVar[dict] = {}
    output_ports: ClassVar[dict] = {
        "output": OutputPort(name="output", data_type=list),
        "rejected": OutputPort(name="rejected", data_type=list),
    }

    class Config(NodeConfig):
        passed: int = 3
        rejected: int = 2

    def process(self, inputs):
        CALLS[self.node_type] += 1
        return {
            "output": [{"rt": True, "v": i} for i in range(self.config.passed)],
            "rejected": [{"rt": True, "v": -i} for i in range(self.config.rejected)],
        }


def _register(cls, *, cacheable: bool = True) -> None:
    global_registry.register(
        cls.node_type,
        cls,
        NodeMetadata(
            node_type=cls.node_type,
            label=cls.node_type,
            description="example-06 fix test node",
            category="Test",
            cacheable=cacheable,
        ),
    )


@pytest.fixture
def ex6_env(rt_env):
    _register(RtWriter)
    _register(RtGate)
    yield rt_env
    global_registry.unregister(RtWriter.node_type)
    global_registry.unregister(RtGate.node_type)


OUT = "workspace/artifacts/rtfix/models"


def _writer_graph(**kw):
    return make_graph([("w", "rtfix_writer", {"output_dir": OUT})], name="rtfix", **kw)


def _fs(posix: str) -> Path:
    from app.core.paths.workspace_paths import artifact_fs_path

    return artifact_fs_path(posix)


# ── 1. cache hits are re-homed into the current run ───────────────────────────


@pytest.mark.parametrize("parallel", [False, True])
def test_cache_hit_rescopes_run_scoped_paths(ex6_env, real_threads, parallel):
    r1, r2 = RunManager(), RunManager()
    out1 = run_pipeline_ir(_writer_graph(), run_manager=r1, use_cache=True, parallel=parallel)
    out2 = run_pipeline_ir(_writer_graph(), run_manager=r2, use_cache=True, parallel=parallel)
    assert CALLS["rtfix_writer"] == 1  # second run: cache hit
    p1 = out1["output"][0]["path"]
    p2 = out2["output"][0]["path"]
    assert f"/runs/{r1.run_id}/" in p1
    assert f"/runs/{r2.run_id}/" in p2 and r1.run_id not in p2
    # The file was copied into run 2's own artifact dir.
    assert _fs(p2).read_text(encoding="utf-8") == "call-1"


def test_cache_hit_discarded_when_source_artifacts_are_gone(ex6_env):
    import shutil

    r1, r2 = RunManager(), RunManager()
    out1 = run_pipeline_ir(_writer_graph(), run_manager=r1, use_cache=True)
    shutil.rmtree(_fs(out1["output"][0]["path"]).parent.parent)  # delete runs/<r1>
    out2 = run_pipeline_ir(_writer_graph(), run_manager=r2, use_cache=True)
    assert CALLS["rtfix_writer"] == 2  # re-executed instead of returning a dead path
    assert _fs(out2["output"][0]["path"]).is_file()


def test_non_cacheable_node_ignores_stale_cache_entry(ex6_env, real_threads):
    run_pipeline_ir(_writer_graph(), run_manager=RunManager(), use_cache=True)
    assert CALLS["rtfix_writer"] == 1
    # Plugin metadata now says cacheable=False (e.g. isolated stub metadata fixed).
    _register(RtWriter, cacheable=False)
    for parallel in (False, True):
        run_pipeline_ir(_writer_graph(), run_manager=RunManager(), use_cache=True, parallel=parallel)
    assert CALLS["rtfix_writer"] == 3


def test_rescope_unit_cases(ex6_env):
    from app.core.execution.cache_rescope import rescope_cached_outputs

    same = {"output": [{"path": "workspace/artifacts/s/runs/abc/x.bin"}]}
    assert rescope_cached_outputs(same, "abc") is same  # own run: untouched
    plain = {"output": [1, 2, "hello"]}
    assert rescope_cached_outputs(plain, "new") is plain
    # Free text mentioning another run cannot be re-homed → miss.
    text = {"output": "saved to workspace/artifacts/s/runs/old/x.bin ok"}
    assert rescope_cached_outputs(text, "new") is None
    # Missing source file → miss.
    missing = {"output": "workspace/artifacts/s/runs/old/none.bin"}
    assert rescope_cached_outputs(missing, "new") is None


def test_distributed_cache_load_respects_cacheable(ex6_env):
    from app.core.distributed.backend import _cache_load

    _register(RtWriter, cacheable=False)
    key, cached = _cache_load(
        use_cache=True, node_type="rtfix_writer", config={}, inputs={}, seed=0, run_id="r"
    )
    assert key is None and cached is None


# ── 2. latest only moves to runs that produced artifacts ──────────────────────


def test_latest_not_moved_by_run_without_artifacts(ex6_env):
    from app.core.paths.workspace_paths import artifact_layout, latest_run_id

    r1 = RunManager()
    run_pipeline_ir(_writer_graph(), run_manager=r1, use_cache=False)
    assert latest_run_id("rtfix") == r1.run_id

    # Same slug, writes nothing under artifacts/rtfix/runs/<id>/ (like a
    # preprocess graph exporting to the stable dataset/ tree).
    r2 = RunManager()
    g = make_graph([("a", "rtfix_source", {"value": 1})], name="rtfix")
    run_pipeline_ir(g, run_manager=r2, use_cache=False)
    assert latest_run_id("rtfix") == r1.run_id
    assert not _fs(artifact_layout("rtfix", r2.run_id)["run_dir"]).exists()
    assert (_fs(artifact_layout("rtfix", "_")["latest_dir"]) / "models" / "model.bin").is_file()


def test_publish_latest_if_produced_prunes_empty_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    from app.core.paths.workspace_paths import (
        artifact_fs_path,
        artifact_layout,
        latest_run_id,
        publish_latest_if_produced,
    )

    empty = artifact_fs_path(artifact_layout("demo", "e1")["run_dir"])
    (empty / "models").mkdir(parents=True)
    assert publish_latest_if_produced("demo", "e1") is None
    assert not empty.exists()
    assert latest_run_id("demo") is None

    full = artifact_fs_path(artifact_layout("demo", "f1")["run_dir"])
    full.mkdir(parents=True)
    (full / "metrics.json").write_text("{}", encoding="utf-8")
    assert publish_latest_if_produced("demo", "f1") == artifact_layout("demo", "f1")["latest_dir"]
    assert latest_run_id("demo") == "f1"


# ── 3. outputs listing priority / fairness / inputs ───────────────────────────


def _ex6_like_run(ws: Path) -> tuple[str, Path]:
    run_id = "run-ex6-outputs"
    run_dir = ws / "runs" / run_id
    run_dir.mkdir(parents=True)
    created = time.time()
    # Pre-existing Phase-1 dataset (ingest *input*): 60 wavs + labels.csv.
    ds = ws / "artifacts" / "sc" / "dataset" / "speech_commands" / "v1"
    for split in ("train", "val"):
        d = ds / split / "yes"
        d.mkdir(parents=True)
        for i in range(30):
            (d / f"{i}.wav").write_bytes(b"RIFF")
    (ds / "labels.csv").write_text("path,label\n", encoding="utf-8")
    old = created - 3600
    for p in ds.rglob("*"):
        os.utime(p, (old, old))
    run_art = ws / "artifacts" / "sc" / "runs" / run_id
    (run_art / "tflite").mkdir(parents=True)
    (run_art / "tflite" / "model.tflite").write_bytes(b"TFL3")
    (run_art / "tflite" / "labels.txt").write_text("yes\n", encoding="utf-8")
    (run_art / "metrics.json").write_text('{"accuracy": 0.9}', encoding="utf-8")
    clips = run_art / "clips"
    clips.mkdir()
    for i in range(40):
        (clips / f"{i}.wav").write_bytes(b"RIFF")
    rel = f"workspace/artifacts/sc/runs/{run_id}"
    graph = {
        "schema_version": "1.2",
        "metadata": {"name": "sc"},
        "nodes": [
            {"id": "dataset_ingest_0", "node_type": "dataset_ingest",
             "config": {"path": "workspace/artifacts/sc/dataset/speech_commands/v1"}},
            {"id": "writer_0", "node_type": "audio_exporter", "config": {"output_dir": f"{rel}/clips"}},
            {"id": "evaluator_0", "node_type": "evaluator", "config": {"output_path": rel}},
            {"id": "edge_optimizer_0", "node_type": "edge_optimizer",
             "config": {"output_path": f"{rel}/tflite"}},
        ],
        "edges": [
            {"src_id": "dataset_ingest_0", "src_port": "output", "dst_id": "writer_0", "dst_port": "input"},
            {"src_id": "writer_0", "src_port": "output", "dst_id": "evaluator_0", "dst_port": "input"},
            {"src_id": "evaluator_0", "src_port": "output", "dst_id": "edge_optimizer_0",
             "dst_port": "input"},
        ],
    }
    (run_dir / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
    from datetime import datetime, timezone

    (run_dir / "meta.json").write_text(
        json.dumps({
            "run_id": run_id,
            "created_at": datetime.fromtimestamp(created, tz=timezone.utc).isoformat(),
            "artifacts_dir": rel,
            "graph_name": "sc",
        }),
        encoding="utf-8",
    )

    # Register platform file_tree artifacts (listing no longer walks graph paths).
    from app.core.artifacts.artifact_store import ArtifactStore
    from app.core.artifacts.file_tree import file_tree_payload, register_file_tree_serializer

    register_file_tree_serializer()
    store = ArtifactStore()
    clip_files = [{"path": f"{i}.wav"} for i in range(40)]
    store.register(
        run_id=run_id,
        node_id="writer_0",
        node_type="audio_exporter",
        artifact_type="file_tree",
        data=file_tree_payload(
            {"root": f"{rel}/clips", "files": clip_files, "total": 40}
        ),
    )
    store.register(
        run_id=run_id,
        node_id="evaluator_0",
        node_type="evaluator",
        artifact_type="file_tree",
        data=file_tree_payload(
            {
                "root": rel,
                "files": [{"path": "metrics.json"}],
                "total": 1,
            }
        ),
    )
    store.register(
        run_id=run_id,
        node_id="edge_optimizer_0",
        node_type="edge_optimizer",
        artifact_type="file_tree",
        data=file_tree_payload(
            {
                "root": f"{rel}/tflite",
                "files": [{"path": "model.tflite"}, {"path": "labels.txt"}],
                "total": 2,
            }
        ),
    )
    return run_id, run_dir


def test_outputs_prioritise_key_files_and_skip_ingest_inputs(tmp_workspace: Path, monkeypatch):
    monkeypatch.chdir(tmp_workspace.parent)
    import app.core.runs.run_outputs as ro

    run_id, run_dir = _ex6_like_run(tmp_workspace)
    monkeypatch.setattr(ro, "_MAX_LISTED_FILES", 12)
    detail = ro.list_run_output_files_detail(run_id, run_dir)
    items = detail["items"]
    names = [i["name"] for i in items]
    assert len(items) == 12 and detail["truncated"] is True
    # Run journal files first, then key files.
    assert names[:2] == ["graph.json", "meta.json"]
    for key in ("model.tflite", "metrics.json", "labels.txt"):
        assert key in names, names
    assert names.index("model.tflite") < names.index("0.wav")
    # Ingest pre-existing inputs are never listed nor attributed.
    assert not any("/dataset/" in i["path"] for i in items)
    assert not any(i.get("node_id") == "dataset_ingest_0" for i in items)
    # Bulk node still gets slots and reports its truncation consistently.
    shown = sum(1 for i in items if i.get("node_id") == "writer_0")
    assert shown >= 1
    assert detail["truncated_by_node"]["writer_0"] == {"shown": shown, "total": 40}
    page = ro.list_node_output_files(run_id, run_dir, "writer_0", limit=50)
    assert page["total"] == 40 and len(page["items"]) == 40
    assert ro.list_node_output_files(run_id, run_dir, "dataset_ingest_0")["total"] == 0


def test_outputs_keep_files_ingest_wrote_during_run(tmp_workspace: Path, monkeypatch):
    monkeypatch.chdir(tmp_workspace.parent)
    import app.core.runs.run_outputs as ro

    run_id, run_dir = _ex6_like_run(tmp_workspace)
    fresh = tmp_workspace / "artifacts" / "sc" / "dataset" / "speech_commands" / "v1" / "ingest_report.json"
    fresh.write_text("{}", encoding="utf-8")  # mtime = now (after run start)
    from app.core.runs.run_outputs import _InputFilter, _load_run_graph

    flt = _InputFilter(_load_run_graph(run_dir), run_dir)
    assert flt.input_owner(fresh.resolve()) is None
    old = next((tmp_workspace / "artifacts" / "sc" / "dataset").rglob("*.wav")).resolve()
    assert flt.input_owner(old) == "dataset_ingest_0"


# ── 4. backend prepare keeps hand-off paths (consistent with the UI stamp) ────


def test_prepare_graph_project_does_not_rewrite_handoff_paths():
    from app.core.execution.graph_prepare import prepare_graph
    from app.core.ir.loader import dump_ir

    ds = "workspace/artifacts/speech-commands/dataset/speech_commands"
    g = {
        "schema_version": "1.2",
        "metadata": {"name": "speech_commands_e2e_preprocess", "seed": 0},
        "nodes": [
            {"id": "ing", "node_type": "dataset_ingest", "config": {"path": f"{ds}/v1"}},
            {"id": "exp", "node_type": "audio_exporter", "config": {"output_dir": ds, "version_tag": "v1"}},
        ],
        "edges": [],
    }
    prepared = prepare_graph(g, payload={"project": "e06-verify-1"}, validate=False)
    out = dump_ir(prepared.graph)
    cfg = {n["id"]: n["config"] for n in out["nodes"]}
    assert cfg["exp"]["output_dir"] == ds and "project" not in cfg["exp"]
    assert cfg["ing"]["path"] == f"{ds}/v1"
    assert prepared.project_fields.get("project") == "e06-verify-1"


# ── 5. node_end.output_count = primary output port ────────────────────────────


def test_logger_output_count_uses_primary_port():
    from app.core.logger import PipelineLogger, port_item_counts, primary_output_count

    counts = port_item_counts({"output": [1] * 206, "rejected": [1] * 13, "meta": None})
    assert counts == {"output": 206, "rejected": 13, "meta": 0}
    assert primary_output_count(counts) == 206
    assert primary_output_count({"a": 2, "b": 1}) == 3  # no output port: sum

    lg = PipelineLogger()
    lg.node_end("audio_quality_gate", 3, 0.1, node_id="g", output_counts=counts)
    ev = [e for e in lg.logs if isinstance(e, dict) and e.get("type") == "node_end"][-1]
    assert ev["output_count"] == 206
    assert ev["rejected_count"] == 13
    assert ev["output_counts"]["rejected"] == 13


@pytest.mark.parametrize("parallel", [False, True])
def test_node_end_event_counts_output_port_only(ex6_env, real_threads, parallel):
    r = RunManager()
    g = make_graph([("g", "rtfix_gate", {"passed": 3, "rejected": 2})], name="rtfix-gate")
    run_pipeline_ir(g, run_manager=r, use_cache=False, parallel=parallel)
    logs = json.loads((Path(r.base_path) / "logs.json").read_text(encoding="utf-8"))
    events = logs if isinstance(logs, list) else logs.get("logs", [])
    end = [e for e in events if isinstance(e, dict) and e.get("type") == "node_end"]
    assert end and end[-1]["output_count"] == 3
    assert end[-1]["rejected_count"] == 2
