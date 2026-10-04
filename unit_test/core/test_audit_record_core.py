"""Run audit record (prove.json v2): completeness, chain, verify, replay, archive.

Covers the audit/traceability items: plugin/node implementations, external
input hashes + dataset version, environment, actor/trigger, cache provenance,
record hash chain + verify, per-node output folders on a 2-branch graph,
node labels in records/events, real failure reasons, saved-pipeline ref +
drift, replay graph de-scoping, archive / short-id resolution.
"""
from __future__ import annotations

import concurrent.futures
import json
import threading
from pathlib import Path
from typing import ClassVar, Optional

import pytest

from app.core.execution.orchestrator import run_pipeline_ir
from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode
from app.core.nodes import registry as global_registry
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.core.runs.run_journal import RunManager

_REAL_SUBMIT = concurrent.futures.ThreadPoolExecutor.submit
_REAL_START = threading.Thread.start
CALLS: dict[str, int] = {}


class AudReader(Node):
    node_type: ClassVar[str] = "aud_reader"
    input_ports: ClassVar[dict] = {}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}

    class Config(NodeConfig):
        path: str = ""

    def process(self, inputs):
        from app.core.runs.audit_record import resolve_path

        CALLS[self.node_type] = CALLS.get(self.node_type, 0) + 1
        root = resolve_path(self.config.path)
        names = sorted(p.name for p in root.iterdir()) if root.is_dir() else []
        return {"output": [{"name": n} for n in names]}


class AudWriter(Node):
    """Trainer-like: writes model.bin + labels.txt into its output_path."""

    node_type: ClassVar[str] = "aud_trainer"
    input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=Optional[list], required=False)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}

    class Config(NodeConfig):
        output_path: str = "workspace/artifacts/audtest"
        architecture: str = "ds_cnn"
        epochs: int = 1

    def process(self, inputs):
        from app.core.paths.workspace_paths import artifact_fs_path

        out = artifact_fs_path(self.config.output_path)
        out.mkdir(parents=True, exist_ok=True)
        (out / "model.bin").write_text(self.config.architecture, encoding="utf-8")
        (out / "labels.txt").write_text("yes\nno\n", encoding="utf-8")
        return {"output": [{"model": f"{self.config.output_path}/model.bin"}]}


class AudFail(Node):
    node_type: ClassVar[str] = "aud_fail"
    input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=Optional[list], required=False)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=list)}

    class Config(NodeConfig):
        pass

    def process(self, inputs):
        raise ValueError("bad shape 42")


_CLASSES = (AudReader, AudWriter, AudFail)


@pytest.fixture
def aud_env(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(ws))
    CALLS.clear()
    from app.core.runs.audit_hashing import clear_hash_caches

    clear_hash_caches()
    for cls in _CLASSES:
        global_registry.register(
            cls.node_type, cls,
            NodeMetadata(node_type=cls.node_type, label=cls.node_type, description="audit test",
                         category="Test", cacheable=cls is AudReader),
        )
    data = ws / "datasets" / "output" / "proj" / "v1" / "train"
    data.mkdir(parents=True)
    for i in range(3):
        (data / f"{i}.wav").write_bytes(b"RIFF" + bytes([i]) * 16)
    yield ws
    for cls in _CLASSES:
        global_registry.unregister(cls.node_type)


DATA = "workspace/datasets/output/proj/v1/train"


def two_branch_graph(project: str | None = None, name: str = "audtest") -> GraphIR:
    return GraphIR(
        schema_version="1.2",
        metadata=IRMetadata(name=name, seed=7, project=project),
        nodes=[
            IRNode(id="reader", node_type="aud_reader", config={"path": DATA}),
            IRNode(id="trainer_a", node_type="aud_trainer",
                   config={"output_path": "workspace/artifacts/audtest", "architecture": "ds_cnn"}),
            IRNode(id="trainer_b", node_type="aud_trainer",
                   config={"output_path": "workspace/artifacts/audtest", "architecture": "mobilenet"}),
        ],
        edges=[
            IREdge(src_id="reader", src_port="output", dst_id="trainer_a", dst_port="input"),
            IREdge(src_id="reader", src_port="output", dst_id="trainer_b", dst_port="input"),
        ],
    )


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _run(graph=None, **kw) -> RunManager:
    rm = RunManager()
    rm._write_meta_field("actor", "alice")
    rm._write_meta_field("trigger", "ui")
    run_pipeline_ir(graph or two_branch_graph(), run_manager=rm, use_cache=kw.pop("use_cache", False), **kw)
    return rm


# ── 1 + 4 + 6: record completeness, per-node folders, labels ──────────────────


def test_two_branch_run_record_and_node_folders(aud_env):
    rm = _run()
    run_dir = Path(rm.base_path)
    rid = rm.run_id
    # 4. each branch writer has its own node folder (not the run root)
    root = aud_env / "artifacts" / "audtest" / "runs" / rid
    assert (root / "trainer_a" / "model.bin").read_text() == "ds_cnn"
    assert (root / "trainer_b" / "model.bin").read_text() == "mobilenet"
    assert not (root / "model.bin").exists()
    graph = _read(run_dir / "graph.json")
    paths = {n["id"]: n["config"].get("output_path") for n in graph["nodes"]}
    assert paths["trainer_a"].endswith(f"/runs/{rid}/trainer_a")
    assert (run_dir / "graph.logical.json").is_file()

    rec = _read(run_dir / "prove.json")
    assert rec["schema_version"] == "2.0" and rec["status"] == "succeeded"
    from app.core.runs.audit_record import record_hash

    assert rec["record_hash"] == record_hash(rec)
    assert rec["previous_record_hash"] is None and rec["chain"]["seq"] == 1
    impl = rec["node_implementation_versions"]["aud_trainer"]
    assert impl["version"] and impl["plugin_code_hash"].startswith("sha256:")
    assert impl["runtime"] == "builtin"
    # external input with content hash + dataset version
    ext = [e for e in rec["external_inputs"] if e["node_id"] == "reader"]
    assert ext and ext[0]["content_hash"].startswith("sha256:") and ext[0]["file_count"] == 3
    assert ext[0]["dataset"] == {"project": "proj", "version": "v1"}
    assert rec["dataset_versions"][0]["version"] == "v1"
    env = rec["environment"]
    assert env["python"] and "numpy" in env["libraries"] and env["graphyn_version"]
    assert rec["actor"] == "alice" and rec["trigger"] == "ui"
    assert rec["pipeline_source"] == "adhoc" and rec["pipeline_version"] is None
    assert {o["node_id"] for o in rec["outputs"]} == {"trainer_a", "trainer_b"}
    # 6. labels in meta / record / events
    labels = rec["node_labels"]
    assert labels["trainer_a"].startswith("Aud trainer · Path A")
    assert "Path B" in labels["trainer_b"] and "MobileNet" in labels["trainer_b"]
    meta = _read(run_dir / "meta.json")
    assert meta["node_labels"] == labels
    logs = _read(run_dir / "logs.json")
    starts = [e for e in logs if e.get("type") == "node_start" and e.get("node_id") == "trainer_b"]
    assert starts and starts[0]["node_label"] == labels["trainer_b"]
    assert any(s.get("node_label") for s in meta["node_stats"])
    # chain file + platform audit run.finish with the same actor
    from app.core.runs.audit_record import read_chain
    from app.core.trust.audit import list_audit

    chain = read_chain(None)
    assert chain[-1]["run_id"] == rid and chain[-1]["record_hash"] == rec["record_hash"]
    fin = [e for e in list_audit(100) if e["action"] == "run.finish" and e["resource_id"] == rid]
    assert fin and fin[0]["actor"] == "alice" and fin[0]["meta"]["record_hash"] == rec["record_hash"]


def test_chain_links_consecutive_runs(aud_env):
    r1 = _run()
    r2 = _run()
    a = _read(Path(r1.base_path) / "prove.json")
    b = _read(Path(r2.base_path) / "prove.json")
    assert b["previous_record_hash"] == a["record_hash"]
    assert b["chain"]["seq"] == a["chain"]["seq"] + 1


# ── 1b: verify ────────────────────────────────────────────────────────────────


def test_verify_pass_changed_fail(aud_env):
    from app.core.runs.audit_record import verify_run

    rm = _run()
    run_dir = Path(rm.base_path)
    res = verify_run(run_dir)
    assert res["status"] == "pass", res
    kinds = {c["check"] for c in res["checks"]}
    assert {"record_hash", "chain", "graph_snapshot", "logical_graph", "external_input", "output"} <= kinds

    # changed input
    (aud_env / "datasets" / "output" / "proj" / "v1" / "train" / "0.wav").write_bytes(b"other")
    res = verify_run(run_dir)
    assert res["status"] == "changed"
    assert any(c["check"] == "external_input" and c["status"] == "changed" for c in res["checks"])

    # changed output — with file-level details
    out = aud_env / "artifacts" / "audtest" / "runs" / rm.run_id / "trainer_a" / "model.bin"
    out.write_text("tampered")
    res = verify_run(run_dir)
    row = next(c for c in res["checks"] if c["check"] == "output" and c["node_id"] == "trainer_a")
    assert row["status"] == "changed" and row["details"]["modified"] == ["model.bin"]

    # tampered record → fail
    rec = _read(run_dir / "prove.json")
    rec["actor"] = "mallory"
    (run_dir / "prove.json").write_text(json.dumps(rec))
    res = verify_run(run_dir)
    assert res["status"] == "fail"
    assert next(c for c in res["checks"] if c["check"] == "record_hash")["status"] == "fail"


def test_verify_unsealed_and_legacy(aud_env):
    from app.core.runs.audit_record import verify_run

    rm = RunManager()
    assert verify_run(Path(rm.base_path))["status"] == "unsealed"


# ── 5: real failure reason; failed runs are sealed too ────────────────────────


def test_failed_run_records_real_exception(aud_env):
    g = GraphIR(
        schema_version="1.2",
        metadata=IRMetadata(name="audfail", seed=1),
        nodes=[IRNode(id="boom", node_type="aud_fail", config={})],
        edges=[],
    )
    rm = RunManager()
    with pytest.raises(ValueError):
        run_pipeline_ir(g, run_manager=rm, use_cache=False)
    run_dir = Path(rm.base_path)
    meta = _read(run_dir / "meta.json")
    assert meta["status"] == "failed"
    assert meta["error_type"] == "ValueError" and "bad shape 42" in meta["error"]
    assert "Traceback" in meta["error_traceback"] and meta["failed_node_id"] == "boom"
    err = [e for e in _read(run_dir / "logs.json") if e.get("type") == "node_error"][0]
    assert err["error_type"] == "ValueError" and "ValueError: bad shape 42" in err["traceback"]
    assert err["node_label"]
    rec = _read(run_dir / "prove.json")
    assert rec["status"] == "failed" and rec["error_type"] == "ValueError"
    from app.core.trust.audit import list_audit

    assert any(e["action"] == "run.fail" and e["resource_id"] == rm.run_id for e in list_audit(50))


def test_isolated_node_error_attrs_flow_into_event():
    from app.core.logger import PipelineLogger
    from app.core.plugins.isolated_executor import IsolatedNodeError

    lg = PipelineLogger()
    lg.set_node_labels({"t": "Trainer · Path C (MobileNet · lr 0.002)"})
    exc = IsolatedNodeError("ValueError", "bad", traceback_text="Traceback ...\nValueError: bad",
                            node_type="trainer", plugin_name="trainer")
    lg.node_error("trainer", 3, exc, node_id="t")
    ev = lg.logs[-1]
    assert ev["error"] == "ValueError: bad" and ev["error_type"] == "ValueError"
    assert ev["traceback"].endswith("ValueError: bad") and ev["plugin"] == "trainer"
    assert ev["node_label"].startswith("Trainer · Path C")


# ── cache provenance ─────────────────────────────────────────────────────────


def test_cache_hit_records_source_run(aud_env):
    r1 = _run(use_cache=True)
    r2 = _run(use_cache=True)
    assert CALLS["aud_reader"] == 1
    stats = {s["node_id"]: s for s in _read(Path(r2.base_path) / "meta.json")["node_stats"]}
    assert stats["reader"]["cache_hit"] is True
    assert stats["reader"]["cache_source_run_id"] == r1.run_id
    assert stats["reader"]["cache_key"]
    rec = _read(Path(r2.base_path) / "prove.json")
    assert rec["cache"] == [{"node_id": "reader", "node_type": "aud_reader",
                             "cache_key": stats["reader"]["cache_key"], "source_run_id": r1.run_id}]


# ── pipeline ref + drift ─────────────────────────────────────────────────────


def _save_pipeline(ws: Path, graph: GraphIR, name: str = "audtest") -> Path:
    from app.core.ir.loader import dump_ir

    pdir = ws / "datasets" / "output" / "proj" / "pipelines"
    pdir.mkdir(parents=True, exist_ok=True)
    path = pdir / f"{name}.graph.json"
    path.write_text(json.dumps(dump_ir(graph)), encoding="utf-8")
    return path


def test_pipeline_ref_and_drift(aud_env):
    from app.core.runs.audit_record import _semantic_hash, logical_graph_for_run, pipeline_drift

    graph = two_branch_graph(project="proj")
    saved = _save_pipeline(aud_env, graph)
    rm = _run(graph)
    rec = _read(Path(rm.base_path) / "prove.json")
    assert rec["pipeline_source"] == "saved"
    ref = rec["pipeline_version"]
    assert ref["name"] == "audtest" and ref["env"] == "draft" and ref["match"] == "content_hash"
    assert ref["revision_hash"] == rec["graph_hash"]
    sem = _semantic_hash(logical_graph_for_run(rm.base_path))
    drift = pipeline_drift(ref, rec["graph_hash"], sem)
    assert drift["drifted"] is False
    # Edit the saved draft → drift
    data = json.loads(saved.read_text())
    data["nodes"][1]["config"]["architecture"] = "crnn"
    saved.write_text(json.dumps(data))
    drift = pipeline_drift(ref, rec["graph_hash"], sem)
    assert drift["drifted"] is True and drift["layout_only"] is False
    # Layout-only change
    data["nodes"][1]["config"]["architecture"] = "ds_cnn"
    data["ui"] = {"positions": {"reader": {"x": 10.0, "y": 20.0}}}
    saved.write_text(json.dumps(data))
    drift = pipeline_drift(ref, rec["graph_hash"], sem)
    assert drift["drifted"] is True and drift["layout_only"] is True


# ── replay graph ─────────────────────────────────────────────────────────────


def test_replay_graph_is_logical_and_rescoped(aud_env):
    from app.core.runs.run_replay import load_replay_graph

    rm = _run()
    g = load_replay_graph(rm.base_path)
    paths = [n.config.get("output_path") for n in g.nodes if n.config.get("output_path")]
    assert paths and all("/runs/" not in p for p in paths)
    # legacy run without graph.logical.json: run scoping is undone
    (Path(rm.base_path) / "graph.logical.json").unlink()
    g2 = load_replay_graph(rm.base_path)
    assert all(rm.run_id not in json.dumps(dict(n.config)) for n in g2.nodes)


def test_start_replay_links_and_checks_inputs(aud_env):
    from app.core.runs.run_replay import InputsChanged, start_replay

    rm = _run()
    calls = []
    res = start_replay(rm.base_path, actor="bob", submit=lambda fn: calls.append(fn))
    assert res["replay_of"] == rm.run_id and res["run_id"] != rm.run_id and calls
    calls[0]()  # execute synchronously
    new_dir = Path(rm.base_path).parent / res["run_id"]
    meta = _read(new_dir / "meta.json")
    assert meta["replay_of"] == rm.run_id and meta["trigger"] == "replay" and meta["actor"] == "bob"
    assert meta["status"] == "succeeded" and meta["graph_hash"] == _read(Path(rm.base_path) / "meta.json")["graph_hash"]
    assert _read(new_dir / "prove.json")["replay_of"] == rm.run_id
    # inputs changed → refused unless force
    (aud_env / "datasets" / "output" / "proj" / "v1" / "train" / "9.wav").write_bytes(b"new")
    with pytest.raises(InputsChanged) as ei:
        start_replay(rm.base_path, check_inputs=True, submit=lambda fn: None)
    assert ei.value.changes[0]["status"] == "changed"
    assert start_replay(rm.base_path, check_inputs=True, force=True, submit=lambda fn: None)["run_id"]


# ── misc units ───────────────────────────────────────────────────────────────


def test_hash_path_manifest_mode_for_huge_trees(tmp_path):
    from app.core.runs.audit_hashing import hash_path

    for i in range(5):
        (tmp_path / f"f{i}.bin").write_bytes(bytes([i]) * 10)
    content = hash_path(tmp_path)
    manifest = hash_path(tmp_path, max_files=2)
    assert content["hash_mode"] == "content" and manifest["hash_mode"] == "manifest"
    assert content["file_count"] == manifest["file_count"] == 5
    assert content["content_hash"] != manifest["content_hash"]
    assert hash_path(tmp_path) == content  # cached, stable
    (tmp_path / "f0.bin").write_bytes(b"changed!!!")
    assert hash_path(tmp_path)["content_hash"] != content["content_hash"]


def test_resolve_run_id_prefix(tmp_path):
    from app.core.runs.run_resolve import RunIdAmbiguous, RunIdNotFound, resolve_run_id

    (tmp_path / "abcdef1234aa").mkdir()
    (tmp_path / "abcdef1299bb").mkdir()
    assert resolve_run_id(tmp_path, "abcdef1234aa") == "abcdef1234aa"
    assert resolve_run_id(tmp_path, "abcdef1234") == "abcdef1234aa"
    with pytest.raises(RunIdAmbiguous):
        resolve_run_id(tmp_path, "abcdef12")
    with pytest.raises(RunIdNotFound):
        resolve_run_id(tmp_path, "abcdef1")  # < 8 chars: exact only


def test_scope_moves_run_root_sinks_only():
    from app.core.paths.workspace_paths import scope_outputs_to_run

    g = {"nodes": [
        {"id": "ev", "node_type": "evaluator", "config": {"output_path": "workspace/artifacts/evaluation"}},
        {"id": "opt", "node_type": "edge_optimizer", "config": {"output_path": "workspace/artifacts/sc/tflite"}},
        {"id": "pk", "node_type": "packager", "config": {"model_path": "workspace/artifacts/evaluation/model.keras"}},
    ]}
    out = scope_outputs_to_run(g, "r1")
    cfg = {n["id"]: n["config"] for n in out["nodes"]}
    assert cfg["ev"]["output_path"] == "workspace/artifacts/evaluation/runs/r1/ev"
    assert cfg["opt"]["output_path"] == "workspace/artifacts/sc/runs/r1/tflite"
    assert cfg["pk"]["model_path"] == "workspace/artifacts/evaluation/runs/r1/ev/model.keras"
