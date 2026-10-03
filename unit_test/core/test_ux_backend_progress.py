"""UX backend #7/#8 — node_progress contract, isolated marker forwarding, ingest dataset info."""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

from app.core.execution.orchestrator import run_pipeline_ir
from app.core.logger import PipelineLogger
from app.core.nodes import progress as prog
from app.core.nodes.progress import (
    PROGRESS_ENV_MARKER,
    PROGRESS_MARKER,
    ProgressThrottle,
    build_progress_event,
    emit_node_progress,
    format_progress_message,
    parse_progress_line,
    progress_context,
)
from app.core.runs.run_journal import RunManager
from unit_test.core._runtime_fixes_nodes import (  # noqa: F401 — rt_env is a fixture
    HOOKS,
    chain_graph,
    read_meta,
    rt_env,
)


# Captured at import (collection) time — before conftest's autouse
# ``patch_threads`` turns Thread.start into a no-op for each test.
_REAL_THREAD_START = threading.Thread.start


@pytest.fixture(autouse=True)
def _fresh_throttle(monkeypatch):
    monkeypatch.setattr(prog, "_THROTTLE", ProgressThrottle())
    monkeypatch.setattr(prog, "_WORKER_THROTTLE", ProgressThrottle())
    monkeypatch.delenv(PROGRESS_ENV_MARKER, raising=False)
    monkeypatch.delenv(prog.PROGRESS_ENV_FD, raising=False)


def test_emit_outside_run_is_noop(capsys):
    emit_node_progress({"epoch": 1})
    emit_node_progress("not a dict")  # type: ignore[arg-type]
    assert capsys.readouterr().err == ""


def test_message_format():
    msg = format_progress_message(
        "trainer", {"epoch": 3, "epochs": 30, "loss": 0.41, "val_accuracy": 0.78}
    )
    assert msg == "Trainer · epoch 3/30 · loss 0.41 · val_acc 0.78"
    assert format_progress_message("dataset_ingest", {"phase": "scan", "pct": 50}) == (
        "Dataset ingest · scan · 50%"
    )


def test_event_shape_and_reserved_keys():
    ev = build_progress_event("trainer_0", "trainer", {"epoch": 1, "type": "x", "node_id": "evil"})
    assert ev["type"] == "node_progress"
    assert ev["node_id"] == "trainer_0" and ev["node_type"] == "trainer"
    assert ev["ts"] and ev["timestamp"] == ev["ts"]
    assert ev["epoch"] == 1 and ev["message"].startswith("Trainer · epoch 1")


def test_context_delivery_and_throttle():
    got: list[dict] = []
    with progress_context("n1", "trainer", got.append):
        emit_node_progress({"epoch": 1, "epochs": 3})
        emit_node_progress({"epoch": 2, "epochs": 3})  # throttled (< 0.5 s)
        emit_node_progress({"epoch": 3, "epochs": 3, "pct": 100})  # bypass
    emit_node_progress({"epoch": 4})  # outside context → no-op
    assert [e["epoch"] for e in got] == [1, 3]
    assert all(e["node_id"] == "n1" for e in got)


def test_marker_mode_writes_stderr_line(monkeypatch, capsys):
    monkeypatch.setenv(PROGRESS_ENV_MARKER, "1")
    emit_node_progress({"phase": "train", "epoch": 1})
    err = capsys.readouterr().err.strip()
    assert err.startswith(PROGRESS_MARKER)
    assert parse_progress_line(err) == {"phase": "train", "epoch": 1}
    assert parse_progress_line("plain stderr") is None
    assert parse_progress_line(f"{PROGRESS_MARKER} not-json") is None


def test_logger_node_progress_queue_and_journal():
    from queue import Queue

    q: Queue = Queue()
    lg = PipelineLogger(queue=q)
    lg.node_progress(build_progress_event("t", "trainer", {"epoch": 1}))
    assert q.get_nowait()["type"] == "node_progress"
    assert list(lg.logs)[-1]["type"] == "node_progress"


def test_isolated_streaming_forwards_markers(tmp_path, monkeypatch):
    from app.core.plugins.isolated_executor import _run_isolated_subprocess

    monkeypatch.setattr(threading.Thread, "start", _REAL_THREAD_START)

    script = (
        "import sys, json\n"
        f"sys.stderr.write('{PROGRESS_MARKER} ' + json.dumps({{'epoch': 1, 'epochs': 2}}) + '\\n')\n"
        "sys.stderr.write('regular warning\\n')\n"
        f"sys.stderr.write('{PROGRESS_MARKER} ' + json.dumps({{'epoch': 2, 'epochs': 2}}) + '\\n')\n"
        "print('out')\n"
    )
    got: list[dict] = []
    res = _run_isolated_subprocess(
        [sys.executable, "-c", script], env={}, timeout=30, on_progress=got.append
    )
    assert res.returncode == 0
    assert [p["epoch"] for p in got] == [1, 2]
    assert "regular warning" in res.stderr and PROGRESS_MARKER not in res.stderr
    assert "out" in res.stdout


def test_run_isolated_node_sets_marker_env_and_forwards(monkeypatch):
    """run_isolated_node: marker env only when a sink is bound; lines reach the sink."""
    from app.core.plugins import isolated_executor as iso

    seen_env: dict = {}

    def fake_run(cmd, *, env, timeout, cancel_check=None, on_progress=None):
        seen_env.update(env)
        if on_progress is not None:
            on_progress({"epoch": 7, "epochs": 9})
        raise RuntimeError("stop-here")

    monkeypatch.setattr(iso, "_run_isolated_subprocess", fake_run)

    class Spec:
        plugin_name = "p"
        install_path = "/nonexistent"
        venv_python = sys.executable
        node_types = ("trainer",)

    got: list[dict] = []
    with progress_context("trainer_0", "trainer", got.append):
        with pytest.raises(RuntimeError, match="stop-here"):
            iso.run_isolated_node(Spec(), node_type="trainer", config={}, seed=1, inputs={})
    assert seen_env.get(PROGRESS_ENV_MARKER) == "1"
    assert got and got[0]["node_id"] == "trainer_0" and got[0]["epoch"] == 7


def test_orchestrator_journals_progress(rt_env):
    def hook(node, _inputs):
        emit_node_progress({"phase": "train", "epoch": 1, "epochs": 2, "loss": 0.5})
        emit_node_progress({"phase": "train", "epoch": 2, "epochs": 2, "final": True})

    HOOKS["rtfix_source"] = hook
    run = RunManager()
    run_pipeline_ir(chain_graph(), run_manager=run, use_cache=False)
    logs = json.loads((Path(run.base_path) / "logs.json").read_text())
    events = [e for e in logs if e.get("type") == "node_progress"]
    assert [e["epoch"] for e in events] == [1, 2]
    assert events[0]["node_id"] == "a" and events[0]["node_type"] == "rtfix_source"
    assert "epoch 1/2" in events[0]["message"]
    meta = read_meta(run)
    assert meta["node_progress"]["a"]["epoch"] == 2


# ── #8 ingest dataset info ────────────────────────────────────────────────────


def test_ingest_dataset_info_direct_and_fallback(tmp_path, monkeypatch):
    from app.core.runs.run_dataset import ingest_dataset_info, ingest_node_end_extra

    ws = tmp_path / "workspace"
    d = ws / "datasets" / "input" / "kws" / "yes"
    d.mkdir(parents=True)
    (d / "a.wav").write_bytes(b"RIFF")
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(ws))
    monkeypatch.chdir(tmp_path)
    info = ingest_dataset_info({"path": "workspace/datasets/input/kws/yes"}, 12)
    assert info["source_path"] == "workspace/datasets/input/kws/yes"
    assert info["clip_count"] == 12
    assert info["fallback_used"] is False
    assert info["resolved_path"].endswith("datasets/input/kws/yes")

    class N:
        config = {"path": "workspace/datasets/input/kws/yes"}

    extra = ingest_node_end_extra(N(), "dataset_ingest", {"output": 3})
    assert extra["dataset"]["clip_count"] == 3
    assert ingest_node_end_extra(N(), "trainer", {"output": 3}) is None


def test_logger_node_end_extra_merges_without_override():
    lg = PipelineLogger()
    lg.node_end("dataset_ingest", 0, 1.0, output_counts={"output": 5}, node_id="i",
                extra={"dataset": {"clip_count": 5}, "type": "evil"})
    ev = list(lg.logs)[-1]
    assert ev["type"] == "node_end" and ev["dataset"]["clip_count"] == 5
