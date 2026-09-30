"""Runtime fixes: event-driven mode (#8) and parallel resume state (#10)."""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
from pathlib import Path

import pytest

import app.core.execution.events as events_mod
from app.core.execution.events import EventSource
from app.core.execution.orchestrator import run_pipeline_ir, run_pipeline_ir_async
from app.core.runs.run_control import get_active_run
from app.core.runs.run_journal import RunManager

from unit_test.core._runtime_fixes_nodes import (  # noqa: F401
    CALLS,
    HOOKS,
    chain_graph,
    make_graph,
    read_meta,
    rt_env,
)

_REAL_SUBMIT = concurrent.futures.ThreadPoolExecutor.submit
_REAL_START = threading.Thread.start

_TRIGGER = {"source_type": "timer", "source_config": {"interval_s": 3600}}


class _ScriptedSource(EventSource):
    """Yields scripted payloads, then either ends or idles *ignoring close()*."""

    def __init__(self, payloads, idle: bool) -> None:
        self.payloads = list(payloads)
        self.idle = idle
        self.closed = False

    async def watch(self):
        for p in self.payloads:
            await asyncio.sleep(0)
            yield p
        if self.idle:
            await asyncio.sleep(3600)  # only task cancellation can end this

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def scripted(monkeypatch):
    """Map trigger node id → _ScriptedSource; run to_thread inline (threads are patched)."""
    plan: dict[str, _ScriptedSource] = {}
    order: list[str] = []

    def factory(source_type, source_config):
        return plan[order.pop(0)]

    async def inline_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(events_mod, "create_event_source", factory)
    monkeypatch.setattr(asyncio, "to_thread", inline_to_thread)

    def add(node_id: str, source: _ScriptedSource) -> _ScriptedSource:
        plan[node_id] = source
        order.append(node_id)
        return source

    return add


def _run_async(graph, run, timeout=15.0):
    async def _go():
        return await asyncio.wait_for(
            run_pipeline_ir_async(graph, run_manager=run, use_cache=False, event_driven=True),
            timeout=timeout,
        )

    return asyncio.run(_go())


def test_event_runs_only_nodes_reachable_from_trigger(rt_env, scripted):
    g = make_graph(
        [
            ("t1", "rtfix_source", {"value": 1}),
            ("x", "rtfix_add", {"inc": 1}),
            ("t2", "rtfix_source", {"value": 5}),
            ("y", "rtfix_sink", {}),
        ],
        [("t1", "output", "x", "input"), ("t2", "output", "y", "input")],
        triggers={"t1": _TRIGGER, "t2": _TRIGGER},
    )
    scripted("t1", _ScriptedSource([{"e": 1}], idle=False))
    scripted("t2", _ScriptedSource([], idle=False))
    run = RunManager()
    _run_async(g, run)
    assert CALLS["rtfix_source"] == 1  # t1 only; t2 never fired
    assert CALLS["rtfix_add"] == 1
    assert CALLS["rtfix_sink"] == 0  # y is not downstream of t1
    meta = read_meta(run)
    assert meta["status"] == "succeeded" and meta["trigger_count"] == 1


def test_event_failure_stops_all_sources_and_stays_failed(rt_env, scripted):
    g = make_graph(
        [
            ("t1", "rtfix_source", {}),
            ("x", "rtfix_add", {}),
            ("t2", "rtfix_source", {}),
        ],
        [("t1", "output", "x", "input")],
        triggers={"t1": _TRIGGER, "t2": _TRIGGER},
    )

    def boom(_n, _i):
        raise RuntimeError("event node failed")

    HOOKS["rtfix_add"] = boom
    s1 = scripted("t1", _ScriptedSource([{"e": 1}, {"e": 2}, {"e": 3}], idle=False))
    s2 = scripted("t2", _ScriptedSource([], idle=True))  # idle forever
    run = RunManager()
    _run_async(g, run)
    assert CALLS["rtfix_add"] == 1  # no further events after the failure
    meta = read_meta(run)
    assert meta["status"] == "failed"
    assert "event node failed" in meta["error"]
    assert s1.closed and s2.closed
    run.mark_cancelled()
    assert read_meta(run)["status"] == "failed"
    assert get_active_run(run.run_id) is None


def test_event_cancel_does_not_hang_on_idle_source(rt_env, scripted):
    g = make_graph(
        [("t1", "rtfix_source", {}), ("t2", "rtfix_source", {})],
        triggers={"t1": _TRIGGER, "t2": _TRIGGER},
    )
    run = RunManager()
    HOOKS["rtfix_source"] = lambda _n, _i: run.cancel()
    scripted("t1", _ScriptedSource([{"e": 1}], idle=True))
    s2 = scripted("t2", _ScriptedSource([], idle=True))
    _run_async(g, run, timeout=10.0)
    assert read_meta(run)["status"] == "cancelled"
    assert s2.closed
    assert get_active_run(run.run_id) is None


def test_parallel_mode_records_resume_state(rt_env, monkeypatch):
    monkeypatch.setattr(concurrent.futures.ThreadPoolExecutor, "submit", _REAL_SUBMIT)
    monkeypatch.setattr(threading.Thread, "start", _REAL_START)
    g = chain_graph()
    r1 = RunManager()
    run_pipeline_ir(g, run_manager=r1, use_cache=False, checkpoint=True, parallel=True)
    state = json.loads((Path(r1.base_path) / "resume_state.json").read_text())
    assert sorted(state["completed_nodes"]) == ["a", "b", "c"]
    assert state["graph_hash"] == read_meta(r1)["graph_hash"]

    CALLS.clear()
    r2 = RunManager()
    run_pipeline_ir(g, run_manager=r2, use_cache=False, resume_run_id=r1.run_id)
    assert sum(CALLS.values()) == 0
    assert sorted(read_meta(r2)["skipped_nodes"]) == ["a", "b", "c"]
