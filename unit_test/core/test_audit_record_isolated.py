"""Isolated plugin workers: real failure reason + node_progress end-to-end.

* ``IsolatedNodeError`` carries the worker's real exception (from the worker
  ``error.json``, or a noise-filtered stderr traceback as fallback) instead of
  leading TensorFlow/absl stderr noise.
* ``emit_node_progress`` inside an isolated worker reaches the host sink, the
  ``PipelineLogger`` journal/queue, ``meta.json["node_progress"]`` and
  ``logs.json`` (including through the real ``NodeExecutor`` path).
"""
from __future__ import annotations

import json
import sys
import textwrap
import threading
from pathlib import Path
from queue import Queue
from typing import ClassVar

import pytest

from app.core.nodes import progress as prog
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import OutputPort
from app.core.nodes.progress import PROGRESS_ENV_MARKER, ProgressThrottle, progress_context
from app.core.plugins import isolated_executor as iso
from app.core.plugins.isolated_executor import (
    IsolatedNodeError,
    parse_worker_stderr,
    run_isolated_node,
)
from app.core.plugins.runtime_registry import IsolatedPluginSpec, get_runtime_registry

# Captured at import (collection) time — before conftest's autouse
# ``patch_threads`` turns Thread.start into a no-op for each test. The
# isolated streaming path needs real stderr/stdout reader threads.
_REAL_THREAD_START = threading.Thread.start

PROGRESS_TYPE = "audit_iso_progress"
FAIL_TYPE = "audit_iso_fail"
PLUGIN_NAME = "audit-iso-plugin"

_ABSL_NOISE = (
    "WARNING: All log messages before absl::InitializeLog() is called are written to STDERR\n"
    "I0000 00:00:1700000000.123456   4242 cuda_executor.cc:1015] successful NUMA node read\n"
    "E0000 00:00:1700000000.2   4242 cuda_dnn.cc:8310] Unable to register cuDNN factory\n"
    "2026-10-04 10:00:00.000000: I tensorflow/core/util/port.cc:113] oneDNN custom "
    "operations are on.\n"
)

_NODES_PY = textwrap.dedent(
    f'''
    import sys
    from typing import ClassVar

    from app.core.nodes.base import Node
    from app.core.nodes.config import NodeConfig
    from app.core.nodes.metadata import NodeMetadata
    from app.core.nodes.ports import OutputPort
    from app.core.nodes.progress import emit_node_progress


    class AuditIsoProgressNode(Node):
        node_type: ClassVar[str] = "{PROGRESS_TYPE}"
        metadata: ClassVar[NodeMetadata] = NodeMetadata(
            node_type="{PROGRESS_TYPE}", label="Audit iso progress",
            description="test", category="Test",
        )
        input_ports: ClassVar[dict] = {{}}
        output_ports: ClassVar[dict] = {{"output": OutputPort(name="output", data_type=dict)}}

        class Config(NodeConfig):
            epochs: int = 2

        def process(self, inputs):
            n = int(self.config.epochs)
            for epoch in range(1, n + 1):
                emit_node_progress({{"phase": "train", "epoch": epoch, "epochs": n,
                                     "loss": 1.0 / epoch, "final": True}})
            return {{"output": {{"value": 42, "epochs": n}}}}


    class AuditIsoFailNode(Node):
        node_type: ClassVar[str] = "{FAIL_TYPE}"
        metadata: ClassVar[NodeMetadata] = NodeMetadata(
            node_type="{FAIL_TYPE}", label="Audit iso fail",
            description="test", category="Test",
        )
        input_ports: ClassVar[dict] = {{}}
        output_ports: ClassVar[dict] = {{"output": OutputPort(name="output", data_type=dict)}}

        def process(self, inputs):
            sys.stderr.write({_ABSL_NOISE!r})
            sys.stderr.flush()
            raise ValueError("bad shape 42")
    '''
)

_PLUGIN_TOML = textwrap.dedent(
    f'''
    [plugin]
    name             = "{PLUGIN_NAME}"
    version          = "1.0.0"
    description      = "Audit test isolated plugin."
    author           = "Graphyn Tests"
    platform_version = ">=0.0"
    entry_points     = ["nodes.py"]
    license          = "MIT"
    dependencies     = []
    runtime          = "isolated"
    node_types       = ["{PROGRESS_TYPE}", "{FAIL_TYPE}"]
    '''
)


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setattr(threading.Thread, "start", _REAL_THREAD_START)
    monkeypatch.setattr(prog, "_THROTTLE", ProgressThrottle())
    monkeypatch.setattr(prog, "_WORKER_THROTTLE", ProgressThrottle())
    monkeypatch.delenv(PROGRESS_ENV_MARKER, raising=False)
    monkeypatch.delenv(prog.PROGRESS_ENV_FD, raising=False)
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(ws))


@pytest.fixture
def iso_spec(tmp_path) -> IsolatedPluginSpec:
    plugin_dir = tmp_path / "audit_iso_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.toml").write_text(_PLUGIN_TOML, encoding="utf-8")
    (plugin_dir / "nodes.py").write_text(_NODES_PY, encoding="utf-8")
    return IsolatedPluginSpec(
        plugin_name=PLUGIN_NAME,
        install_path=str(plugin_dir),
        venv_python=sys.executable,
        node_types=(PROGRESS_TYPE, FAIL_TYPE),
    )


# ── Task A: real failure reason ──────────────────────────────────────────────


def test_parse_worker_stderr_skips_tf_noise_and_takes_last_traceback():
    stderr = (
        _ABSL_NOISE
        + "Traceback (most recent call last):\n"
        '  File "old.py", line 1, in <module>\n'
        "KeyError: 'first'\n"
        "\nDuring handling of the above exception, another exception occurred:\n\n"
        "Traceback (most recent call last):\n"
        '  File "nodes.py", line 9, in process\n'
        "    raise ShapeError('bad shape 42')\n"
        "W0000 00:00:1700000000.3   4242 gpu_device.cc:2344] Cannot dlopen some GPU libraries.\n"
        "pkg.mod.ShapeError: bad shape 42\n"
    )
    parsed = parse_worker_stderr(stderr)
    assert parsed["error_type"] == "ShapeError"
    assert parsed["message"] == "bad shape 42"
    assert parsed["traceback"].startswith("Traceback (most recent call last):")
    assert "nodes.py" in parsed["traceback"] and "old.py" not in parsed["traceback"]
    assert "gpu_device.cc" not in parsed["traceback"]


def test_parse_worker_stderr_keeps_cuda_exception_and_no_traceback_fallback():
    parsed = parse_worker_stderr(
        "Traceback (most recent call last):\n  File \"x\"\nRuntimeError: CUDA out of memory\n"
    )
    assert (parsed["error_type"], parsed["message"]) == ("RuntimeError", "CUDA out of memory")

    parsed = parse_worker_stderr(_ABSL_NOISE + "Segmentation fault in libfoo\n" + _ABSL_NOISE)
    assert parsed == {"error_type": "WorkerError", "message": "Segmentation fault in libfoo", "traceback": ""}
    assert parse_worker_stderr(_ABSL_NOISE)["message"] == ""


def test_isolated_node_error_str_and_pickle():
    import pickle

    exc = IsolatedNodeError(
        "ValueError", "bad", traceback_text="tb", node_type="n", plugin_name="p",
        exit_code=1, stderr_tail="tail",
    )
    assert isinstance(exc, RuntimeError)
    assert str(exc) == "ValueError: bad"
    assert str(IsolatedNodeError("KeyError", "")) == "KeyError"
    back = pickle.loads(pickle.dumps(exc))
    assert (back.error_type, back.error_message, back.node_type, back.exit_code) == (
        "ValueError", "bad", "n", 1,
    )


def _assert_real_failure(exc: IsolatedNodeError) -> None:
    assert exc.error_type == "ValueError"
    assert exc.error_message == "bad shape 42"
    assert str(exc) == "ValueError: bad shape 42"
    assert not str(exc).startswith("WARNING")
    assert "ValueError" in exc.traceback_text
    assert exc.node_type == FAIL_TYPE and exc.plugin_name == PLUGIN_NAME
    assert exc.exit_code == 1
    assert "absl::InitializeLog" not in exc.stderr_tail
    assert "bad shape 42" in exc.stderr_tail


def test_isolated_failure_uses_worker_error_file(iso_spec):
    with pytest.raises(IsolatedNodeError) as info:
        run_isolated_node(iso_spec, node_type=FAIL_TYPE, config={}, seed=1, inputs={})
    _assert_real_failure(info.value)


def test_isolated_failure_stderr_fallback_without_error_file(iso_spec, monkeypatch):
    monkeypatch.setattr(iso, "_read_worker_error_file", lambda _path: None)
    with pytest.raises(IsolatedNodeError) as info:
        run_isolated_node(iso_spec, node_type=FAIL_TYPE, config={}, seed=1, inputs={})
    _assert_real_failure(info.value)


def test_isolated_failure_with_progress_sink_streaming_path(iso_spec):
    got: list[dict] = []
    with progress_context("f1", FAIL_TYPE, got.append):
        with pytest.raises(IsolatedNodeError) as info:
            run_isolated_node(iso_spec, node_type=FAIL_TYPE, config={}, seed=1, inputs={})
    _assert_real_failure(info.value)


# ── Task B: node_progress from isolated workers ──────────────────────────────


def test_isolated_worker_progress_reaches_sink(iso_spec):
    got: list[dict] = []
    with progress_context("train_0", PROGRESS_TYPE, got.append):
        result = run_isolated_node(
            iso_spec, node_type=PROGRESS_TYPE, config={"epochs": 2}, seed=1, inputs={}
        )
    assert result.outputs == {"output": {"value": 42, "epochs": 2}}
    assert [e["epoch"] for e in got] == [1, 2]
    for ev in got:
        assert ev["type"] == "node_progress"
        assert ev["node_id"] == "train_0" and ev["node_type"] == PROGRESS_TYPE
        assert ev["phase"] == "train" and ev["epochs"] == 2 and ev["final"] is True
        assert "epoch" in ev["message"]


def _make_logger_and_run():
    from app.core.logger import PipelineLogger
    from app.core.runs.run_journal import RunManager

    q: Queue = Queue()
    return PipelineLogger(queue=q), q, RunManager()


def _drain(q: Queue) -> list[dict]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _assert_host_chain(logger, q, run, node_id: str, epochs: list[int]) -> None:
    journal = [e for e in logger.logs if e.get("type") == "node_progress"]
    assert [e["epoch"] for e in journal] == epochs
    streamed = [e for e in _drain(q) if isinstance(e, dict) and e.get("type") == "node_progress"]
    assert [e["epoch"] for e in streamed] == epochs
    meta = json.loads((Path(run.base_path) / "meta.json").read_text(encoding="utf-8"))
    assert meta["node_progress"][node_id]["epoch"] == epochs[-1]
    run.save_logs(logger.logs)
    saved = json.loads((Path(run.base_path) / "logs.json").read_text(encoding="utf-8"))
    saved_progress = [e for e in saved if e.get("type") == "node_progress"]
    assert [e["epoch"] for e in saved_progress] == epochs
    assert all(e["node_id"] == node_id for e in saved_progress)


def test_host_chain_sink_logger_meta_logs(iso_spec):
    from app.core.execution.orchestrator import _progress_sink_for

    logger, q, run = _make_logger_and_run()
    sink = _progress_sink_for(logger, run)
    with progress_context("train_0", PROGRESS_TYPE, sink):
        run_isolated_node(iso_spec, node_type=PROGRESS_TYPE, config={"epochs": 3}, seed=1, inputs={})
    _assert_host_chain(logger, q, run, "train_0", [1, 2, 3])


class _HostStub(Node):
    """Host-side stand-in for the isolated node (like the plugin loader's stub)."""

    node_type: ClassVar[str] = PROGRESS_TYPE
    _graphyn_isolated: ClassVar[bool] = True
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type=PROGRESS_TYPE, label="stub", description="stub", category="Test"
    )
    input_ports: ClassVar[dict] = {}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=dict)}

    class Config(NodeConfig):
        epochs: int = 2

    def process(self, inputs):  # pragma: no cover - must run in the worker
        raise AssertionError("isolated node ran in-process")


def test_node_executor_isolated_progress_end_to_end(iso_spec):
    from app.core.execution.node_executor import NodeExecutor
    from app.core.execution.orchestrator import _progress_sink_for

    registry = get_runtime_registry()
    registry.register(iso_spec)
    try:
        logger, q, run = _make_logger_and_run()
        node = _HostStub(config={"epochs": 2}, seed=3)
        exe = NodeExecutor(node, run_id=run.run_id)
        exe.set_progress_sink("trainer_0", _progress_sink_for(logger, run))
        exe.setup()
        try:
            outputs = exe.execute({})
        finally:
            exe.teardown()
        assert outputs["output"] == {"value": 42, "epochs": 2}
        _assert_host_chain(logger, q, run, "trainer_0", [1, 2])
    finally:
        registry.unregister_plugin(PLUGIN_NAME)
