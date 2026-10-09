"""Regression tests for the Claude Code tech-review fixes (P0 #5–7 and related P1s)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


def test_file_lock_fails_closed_without_primitive():
    import app.core.persist.file_lock as fl

    assert fl.acquire  # imported
    orig_fcntl, orig_msvcrt = fl._fcntl, fl._msvcrt
    fl._fcntl = lambda: None
    fl._msvcrt = lambda: None
    try:
        with pytest.raises(fl.LockUnavailable):
            fl.acquire(open("/dev/null", "rb"), exclusive=True)
    finally:
        fl._fcntl = orig_fcntl
        fl._msvcrt = orig_msvcrt


def test_windows_lock_refuses_readonly_empty_file(tmp_path):
    """Empty read-only handles cannot be padded; must fail closed, not raise IOError."""
    import app.core.persist.file_lock as fl

    class _FakeMsvcrt:
        LK_NBLCK = 1
        LK_LOCK = 2
        LK_UNLCK = 0

        @staticmethod
        def locking(*_a, **_k):
            raise AssertionError("must not lock a handle that cannot be padded")

    path = tmp_path / "empty.json"
    path.write_bytes(b"")
    orig_fcntl, orig_msvcrt = fl._fcntl, fl._msvcrt
    fl._fcntl = lambda: None
    fl._msvcrt = lambda: _FakeMsvcrt
    try:
        with path.open("rb") as fh:
            with pytest.raises(fl.LockUnavailable):
                fl.acquire(fh, exclusive=False)
    finally:
        fl._fcntl = orig_fcntl
        fl._msvcrt = orig_msvcrt


def test_ticker_skips_when_lock_unavailable(tmp_path, monkeypatch):
    import app.core.pipelines.schedules as schedules
    from app.core.persist.file_lock import LockUnavailable

    def _boom(*_a, **_k):
        raise LockUnavailable("no lock")

    monkeypatch.setattr("app.core.persist.file_lock.acquire", _boom)
    called = {"n": 0}

    def _tick(_base=None):
        called["n"] += 1
        return [{"fired": True}]

    monkeypatch.setattr(schedules, "tick_due_schedules", _tick)
    assert schedules.try_tick_due_schedules(tmp_path) == []
    assert called["n"] == 0


def test_paused_run_is_not_claimed():
    from app.core.distributed.models import NodeJob, WorkerInfo
    from app.core.distributed.queue import JobQueue
    from app.core.distributed.store import MemoryStateStore

    q = JobQueue(store=MemoryStateStore(), load_persisted=False)
    q.enqueue(NodeJob(job_id="j1", run_id="run-a", node_id="n", node_type="x"))
    worker = WorkerInfo(worker_id="w", plugins=["x"])
    q.set_run_paused("run-a", True)
    assert q.is_run_paused("run-a")
    assert q.claim(worker) is None
    q.set_run_paused("run-a", False)
    claimed = q.claim(worker)
    assert claimed is not None
    assert claimed.job_id == "j1"


def test_stale_complete_tombstones_job_scoped_blob(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path / "workspace"))
    from app.core.distributed.models import JobResult, NodeJob, WorkerInfo
    from app.core.distributed.queue import JobQueue
    from app.core.distributed.store import MemoryStateStore
    from app.core.distributed.transfer import get_blob, job_output_key, put_blob

    q = JobQueue(store=MemoryStateStore(), load_persisted=False, lease_ttl_s=60)
    q.enqueue(NodeJob(job_id="job1", run_id="r", node_id="n", node_type="x"))
    worker = WorkerInfo(worker_id="w", plugins=["x"])
    claimed = q.claim(worker)
    assert claimed is not None
    key = job_output_key(claimed.job_id, int(claimed.lease_generation or 0), "output")
    uri = put_blob(b"zombie-output", key=key)
    assert get_blob(uri) == b"zombie-output"
    with pytest.raises(ValueError, match="lease_generation"):
        q.complete(
            JobResult(
                job_id=claimed.job_id,
                status="succeeded",
                output_refs={"output": uri},
                worker_id="w",
                lease_generation=int(claimed.lease_generation or 0) + 9,
            )
        )
    with pytest.raises(FileNotFoundError):
        get_blob(uri)
    record = tmp_path / "workspace" / "artifacts" / "distributed_blob_tombstones.jsonl"
    assert record.is_file()
    assert uri in record.read_text()


def test_conditional_edge_is_evaluated():
    from app.core.distributed.backend import _assemble_inputs

    incoming = {"dst": [("src", "output", "in", "output['output']['ok']")]}
    blocked = _assemble_inputs(
        "dst",
        incoming=incoming,
        node_outputs={"src": {"output": {"ok": False}}},
        input_overrides=None,
    )
    assert "in" not in blocked
    passed = _assemble_inputs(
        "dst",
        incoming=incoming,
        node_outputs={"src": {"output": {"ok": True, "value": 3}}},
        input_overrides=None,
    )
    # condition reads output['ok']; the wired value is the source port.
    assert passed["in"] == {"ok": True, "value": 3}


def test_python_code_blocks_format_and_restricted_network(monkeypatch):
    import sys

    root = str(Path("PluginPackage/Common").resolve())
    sys.path.insert(0, root)
    try:
        import python_code.nodes as mod
    finally:
        sys.path.remove(root)
    tree = ast.parse('x = "{0.__class__}".format(1)\n')
    with pytest.raises(mod.RestrictedCodeError, match="format"):
        mod._validate_source(tree, allow_network=False, allowed_paths=[])

    monkeypatch.setenv("GRAPHYN_HTTP_EGRESS_MODE", "restricted")
    node = mod.PythonCodeNode(config={"source": "output = 1\n", "allow_network": True})
    with pytest.raises(mod.RestrictedCodeError, match="restricted"):
        node.process({})


def test_secret_value_shape_caught_under_renamed_key():
    from app.core.ir.secret_policy import find_inline_secrets

    hits = find_inline_secrets(
        {
            "nodes": [
                {
                    "id": "n",
                    "node_type": "x",
                    "config": {"note": "sk-abcdefghijklmnopqrstuvwxyz"},
                }
            ]
        }
    )
    assert any("note" in h for h in hits)


def test_dependency_url_denied_when_auth_required(monkeypatch):
    from app.core.plugins.dependencies import DependencyChecker
    from app.core.plugins.errors import PluginDependencyError

    monkeypatch.setenv("GRAPHYN_AUTH_REQUIRED", "1")
    monkeypatch.delenv("GRAPHYN_PLUGIN_ALLOWED_SOURCES", raising=False)
    with pytest.raises(PluginDependencyError):
        DependencyChecker._check_requirement_urls(
            ["evil @ https://example.invalid/pkg.whl"]
        )


def test_reject_tree_symlinks(tmp_path):
    from app.core.plugins.errors import PluginInstallError
    from app.core.plugins.installer import reject_tree_symlinks

    root = tmp_path / "plug"
    root.mkdir()
    (root / "plugin.toml").write_text("name='x'\n")
    outside = tmp_path / "secret.txt"
    outside.write_text("nope")
    (root / "link").symlink_to(outside)
    with pytest.raises(PluginInstallError, match="symlink"):
        reject_tree_symlinks(root)


# F20: test_hybrid_retrieve_real_returns_hits removed — the RAG pack (hybrid_retrieve)
# is not shipped (F8 3cc62d7: "RAG/Vision/TinyML/MLOps stay out").
