"""Runtime fixes: logical graph hash, checkpoints, partial runs, run lifecycle, cancel."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.nodes.errors import ResumeError
from app.core.execution.orchestrator import run_pipeline_ir
from app.core.runs.run_control import get_active_run
from app.core.runs.run_journal import RunManager, write_cancel_marker

from unit_test.core._runtime_fixes_nodes import (  # noqa: F401 — rt_env is a fixture
    CALLS,
    HOOKS,
    SEEDS,
    TEARDOWNS,
    chain_graph,
    make_graph,
    read_meta,
    rt_env,
)

OUT = "workspace/artifacts/rtfix/out"


# ── #3 logical graph hash / seeds / cache keys ────────────────────────────────

def test_graph_hash_and_seeds_stable_across_runs_with_scoped_paths(rt_env):
    g = chain_graph(output_dir=OUT)
    r1, r2 = RunManager(), RunManager()
    run_pipeline_ir(g, run_manager=r1, use_cache=False)
    run_pipeline_ir(g, run_manager=r2, use_cache=False)
    m1, m2 = read_meta(r1), read_meta(r2)
    # Materialized graphs differ (run_id embedded in scoped output_dir) …
    g1 = json.loads((Path(r1.base_path) / "graph.json").read_text())
    assert r1.run_id in json.dumps(g1)
    assert m1["materialized_graph_hash"] != m2["materialized_graph_hash"]
    # … but the logical hash and node seeds are identical.
    assert m1["graph_hash"] == m2["graph_hash"]
    assert SEEDS["rtfix_source"][0] == SEEDS["rtfix_source"][1]


def test_cache_hits_across_runs_despite_run_scoped_paths(rt_env):
    g = chain_graph(output_dir=OUT)
    run_pipeline_ir(g, run_manager=RunManager(), use_cache=True)
    run_pipeline_ir(g, run_manager=RunManager(), use_cache=True)
    assert CALLS["rtfix_source"] == 1  # second run: cache hit
    assert CALLS["rtfix_add"] == 1
    assert CALLS["rtfix_sink"] == 2  # cacheable=False in plugin metadata


def test_resume_accepts_same_logical_graph(rt_env):
    g = chain_graph(output_dir=OUT)

    def boom(_node, _inputs):
        raise RuntimeError("fail once")

    HOOKS["rtfix_add"] = boom
    r1 = RunManager()
    with pytest.raises(RuntimeError, match="fail once"):
        run_pipeline_ir(g, run_manager=r1, use_cache=False, checkpoint=True)
    assert read_meta(r1)["status"] == "failed"

    HOOKS.clear()
    r2 = RunManager()
    out = run_pipeline_ir(
        g, run_manager=r2, use_cache=False, checkpoint=True, resume_run_id=r1.run_id
    )
    assert out == {"output": [{"rt": True, "v": 11}]}
    assert CALLS["rtfix_source"] == 1  # resumed from checkpoint, not re-run
    meta = read_meta(r2)
    assert meta["status"] == "succeeded"
    assert meta["skipped_nodes"] == ["a"]


# ── #4 checkpoint lookup filtered by graph hash ───────────────────────────────

def test_find_latest_checkpoint_ignores_other_graphs(rt_env):
    from app.core.runs.checkpoint import _find_latest_checkpoint

    g1 = chain_graph(name="proj-one")
    g2 = make_graph([("a", "rtfix_source", {"value": 99})], name="proj-two")
    r1, r2 = RunManager(), RunManager()
    run_pipeline_ir(g1, run_manager=r1, use_cache=False, checkpoint=True)
    run_pipeline_ir(g2, run_manager=r2, use_cache=False, checkpoint=True)

    h1 = read_meta(r1)["graph_hash"]
    assert _find_latest_checkpoint("a", graph_hash=h1) == {"output": [{"rt": True, "v": 1}]}
    assert _find_latest_checkpoint("a", graph_hash="0" * 64) is None
    assert _find_latest_checkpoint("a", graph_hash=None) is None
    # Slow path (index removed) still filters by hash.
    import shutil

    from app.core.config import runs_dir

    shutil.rmtree(runs_dir() / "checkpoints")
    assert _find_latest_checkpoint("a", graph_hash=h1) == {"output": [{"rt": True, "v": 1}]}
    assert _find_latest_checkpoint("a", graph_hash="f" * 64) is None
    assert _find_latest_checkpoint("a", graph_hash=h1, source_run_id=r2.run_id) is None


# ── #5 partial execution ──────────────────────────────────────────────────────

def test_include_node_fed_by_excluded_node_uses_input_override(rt_env):
    g = chain_graph()
    run = RunManager()
    out = run_pipeline_ir(
        g,
        run_manager=run,
        use_cache=False,
        include_nodes=["c"],
        input_overrides={"c": {"input": [{"rt": True, "v": 42}]}},
    )
    assert out == {"output": [{"rt": True, "v": 42}]}
    assert CALLS["rtfix_sink"] == 1
    assert CALLS["rtfix_source"] == 0


def test_excluded_siso_node_passes_its_input_through_to_output_port(rt_env):
    g = chain_graph()
    out = run_pipeline_ir(g, run_manager=RunManager(), use_cache=False, exclude_nodes=["b"])
    assert CALLS["rtfix_add"] == 0
    assert CALLS["rtfix_sink"] == 1
    assert out == {"output": [{"rt": True, "v": 1}]}


def test_included_node_reads_excluded_upstream_from_checkpoint(rt_env):
    g = chain_graph()
    run_pipeline_ir(g, run_manager=RunManager(), use_cache=False, checkpoint=True)
    CALLS.clear()
    out = run_pipeline_ir(g, run_manager=RunManager(), use_cache=False, include_nodes=["b", "c"])
    assert CALLS["rtfix_source"] == 0
    assert CALLS["rtfix_add"] == 1
    assert out == {"output": [{"rt": True, "v": 11}]}


# ── #6 lifecycle: terminal statuses, cleanup on every error path ──────────────

def test_cancel_during_last_node_ends_cancelled_not_succeeded(rt_env):
    run = RunManager()
    HOOKS["rtfix_sink"] = lambda _n, _i: run.cancel()
    run_pipeline_ir(chain_graph(), run_manager=run, use_cache=False)
    assert read_meta(run)["status"] == "cancelled"
    assert get_active_run(run.run_id) is None


def test_unknown_include_id_marks_failed_and_not_active(rt_env):
    run = RunManager()
    with pytest.raises(ValueError, match="Unknown node ID"):
        run_pipeline_ir(chain_graph(), run_manager=run, include_nodes=["nope"])
    assert read_meta(run)["status"] == "failed"
    assert get_active_run(run.run_id) is None


def test_unknown_node_type_marks_failed(rt_env):
    run = RunManager()
    g = make_graph([("x", "rtfix_does_not_exist", {})])
    with pytest.raises(Exception):
        run_pipeline_ir(g, run_manager=run)
    assert read_meta(run)["status"] == "failed"
    assert get_active_run(run.run_id) is None


def test_setup_failure_marks_failed_and_tears_down_earlier_executors(rt_env):
    run = RunManager()
    g = make_graph(
        [("a", "rtfix_source", {}), ("z", "rtfix_badsetup", {})],
        [("a", "output", "z", "input")],
    )
    with pytest.raises(RuntimeError, match="setup exploded"):
        run_pipeline_ir(g, run_manager=run)
    assert read_meta(run)["status"] == "failed"
    assert TEARDOWNS["rtfix_source"] == 1
    assert get_active_run(run.run_id) is None


def test_resume_error_marks_failed_and_tears_down(rt_env):
    run = RunManager()
    with pytest.raises(ResumeError):
        run_pipeline_ir(chain_graph(), run_manager=run, resume_run_id="doesnotexist")
    assert read_meta(run)["status"] == "failed"
    assert TEARDOWNS["rtfix_source"] == 1 and TEARDOWNS["rtfix_add"] == 1
    assert get_active_run(run.run_id) is None


def test_node_failure_status_not_overwritten_by_later_writes(rt_env):
    run = RunManager()
    HOOKS["rtfix_add"] = lambda _n, _i: (_ for _ in ()).throw(RuntimeError("bad"))
    with pytest.raises(RuntimeError):
        run_pipeline_ir(chain_graph(), run_manager=run, use_cache=False)
    assert read_meta(run)["status"] == "failed"
    assert run.mark_cancelled() is False
    assert run.save_metadata({"x": 1}) is False
    assert run.pause() is False
    meta = read_meta(run)
    assert meta["status"] == "failed" and meta["error"] == "bad"


def test_run_journal_compare_and_set(rt_env):
    run = RunManager()
    assert run.mark_running() is True
    assert run.mark_cancelled() is True
    # Terminal cancelled is never overwritten by succeed/fail/start/pause/resume.
    assert run.save_metadata({"num_nodes": 1}) is False
    assert run.mark_failed("late") is False
    assert run.mark_running() is False
    assert run.pause() is False
    assert run.resume() is False
    meta = read_meta(run)
    assert meta["status"] == "cancelled"
    assert meta["num_nodes"] == 1  # metadata still merged
    assert run.mark_cancelled() is True  # idempotent ack


# ── #7 queued / cross-process cancel ──────────────────────────────────────────

def test_run_cancelled_while_queued_never_starts(rt_env):
    run = RunManager()
    # Simulate the API offline-cancel branch (another process writes meta).
    meta_path = Path(run.base_path) / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["status"] = "cancelled"
    meta_path.write_text(json.dumps(meta))
    out = run_pipeline_ir(chain_graph(), run_manager=run, use_cache=False)
    assert out == {}
    assert sum(CALLS.values()) == 0
    assert read_meta(run)["status"] == "cancelled"


def test_cross_process_cancel_marker_stops_between_nodes(rt_env):
    run = RunManager()
    HOOKS["rtfix_source"] = lambda _n, _i: write_cancel_marker(run.base_path)
    run_pipeline_ir(chain_graph(), run_manager=run, use_cache=False)
    assert CALLS["rtfix_source"] == 1
    assert CALLS["rtfix_add"] == 0
    assert read_meta(run)["status"] == "cancelled"


def test_api_offline_cancel_writes_marker_and_respects_terminal(rt_env):
    from unittest.mock import MagicMock

    from app.api.routers import run_control as rc

    run = RunManager()  # pending, not registered as active in this process
    body = rc.cancel_run(run.run_id, MagicMock())
    assert body["status"] == "cancelled"
    assert (Path(run.base_path) / "cancel_requested").exists()
    out = run_pipeline_ir(chain_graph(), run_manager=run, use_cache=False)
    assert out == {} and sum(CALLS.values()) == 0
    assert read_meta(run)["status"] == "cancelled"

    done = RunManager()
    done.save_metadata({})
    with pytest.raises(Exception):  # 409 invalid_transition — terminal kept
        rc.cancel_run(done.run_id, MagicMock())
    assert read_meta(done)["status"] == "succeeded"


# ── #9 cancel wired into NodeExecutor in Mode A ───────────────────────────────

def test_local_cancel_interrupts_retry_backoff(rt_env):
    import time

    run = RunManager()
    HOOKS["rtfix_flaky"] = lambda _n, _i: run.cancel()
    g = make_graph(
        [("a", "rtfix_source", {}), ("f", "rtfix_flaky", {})],
        [("a", "output", "f", "input")],
    )
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="cancelled by control plane"):
        run_pipeline_ir(g, run_manager=run, use_cache=False)
    assert time.monotonic() - t0 < 10  # did not sit in the 30 s back-off
    assert CALLS["rtfix_flaky"] == 1
    assert read_meta(run)["status"] == "cancelled"
