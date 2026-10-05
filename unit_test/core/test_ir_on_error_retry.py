"""IR 1.3 per-node on_error (route / continue / fail) and retry policies."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.execution.orchestrator import run_pipeline_ir
from app.core.ir.loader import dump_ir, load_ir
from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode, IROnError, IRRetry
from app.core.runs.run_journal import RunManager

from unit_test.core._runtime_fixes_nodes import CALLS, HOOKS, rt_env  # noqa: F401


def _graph(flaky_kwargs: dict, extra_edges: list[tuple[str, str, str, str]] | None = None) -> GraphIR:
    nodes = [
        IRNode(id="a", node_type="rtfix_source", config={"value": 1}),
        IRNode(id="f", node_type="rtfix_flaky", config={}, **flaky_kwargs),
        IRNode(id="ok", node_type="rtfix_sink", config={}),
    ]
    edges = [("a", "output", "f", "input"), ("f", "output", "ok", "input")]
    edges += extra_edges or []
    if any(d == "handler" for _, _, d, _ in edges):
        nodes.append(IRNode(id="handler", node_type="rtfix_sink", config={}))
    return GraphIR(
        schema_version="1.3",
        metadata=IRMetadata(name="onerr", seed=0),
        nodes=nodes,
        edges=[IREdge(src_id=s, src_port=sp, dst_id=d, dst_port=dp) for s, sp, d, dp in edges],
    )


def _logs(run: RunManager) -> list[dict]:
    path = Path(run.base_path) / "logs.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def test_old_graph_dump_unchanged_and_new_fields_round_trip():
    g = GraphIR(
        schema_version="1.2",
        metadata=IRMetadata(name="x", seed=0),
        nodes=[IRNode(id="a", node_type="t")],
    )
    dumped = dump_ir(g)
    assert "on_error" not in dumped["nodes"][0]
    assert "retry" not in dumped["nodes"][0]

    g2 = GraphIR(
        schema_version="1.3",
        metadata=IRMetadata(name="x", seed=0),
        nodes=[
            IRNode(
                id="a",
                node_type="t",
                on_error=IROnError(mode="route"),
                retry=IRRetry(max_attempts=3, backoff_s=0.5, on=["timeout"]),
            )
        ],
    )
    d2 = dump_ir(g2)
    assert d2["nodes"][0]["on_error"] == {"mode": "route", "port": "error"}
    assert d2["nodes"][0]["retry"]["max_attempts"] == 3
    again = load_ir(d2)
    assert again.nodes[0].retry.on == ("timeout",)


def test_error_port_edge_requires_route_mode():
    with pytest.raises(ValueError, match="route"):
        GraphIR(
            schema_version="1.3",
            metadata=IRMetadata(name="x", seed=0),
            nodes=[
                IRNode(id="a", node_type="t", on_error=IROnError(mode="continue")),
                IRNode(id="b", node_type="t"),
            ],
            edges=[IREdge(src_id="a", src_port="error", dst_id="b", dst_port="input")],
        )


def test_retry_validation_bounds():
    with pytest.raises(ValueError):
        IRRetry(max_attempts=0)
    with pytest.raises(ValueError):
        IRRetry(backoff_s=-1)


def test_route_mode_runs_error_branch_and_skips_success(rt_env):
    seen: dict = {}
    HOOKS["rtfix_sink"] = lambda node, inputs: seen.setdefault("inputs", []).append(inputs)
    g = _graph(
        {"on_error": IROnError(mode="route"), "retry": IRRetry(max_attempts=2, backoff_s=0)},
        [("f", "error", "handler", "input")],
    )
    run = RunManager()
    run_pipeline_ir(g, run_manager=run, use_cache=False)
    # Flaky retried per IR (2 attempts), not the class policy (5 × 30 s).
    assert CALLS["rtfix_flaky"] == 2
    # Only the handler sink ran, with the routed error payload.
    assert CALLS["rtfix_sink"] == 1
    payload = seen["inputs"][0]["input"]
    assert payload["ok"] is False
    assert payload["error_type"] == "RuntimeError"
    assert payload["message"] == "transient"
    assert payload["node_id"] == "f"
    assert payload["attempt"] == 2
    meta = json.loads((Path(run.base_path) / "meta.json").read_text())
    assert meta["status"] in ("succeeded", "completed")
    types = [e.get("type") for e in _logs(run)]
    assert "node_retry" in types
    assert "node_error_routed" in types


def test_continue_mode_skips_dependants_and_succeeds(rt_env):
    g = _graph({"on_error": IROnError(mode="continue"), "retry": IRRetry(max_attempts=1)})
    run = RunManager()
    run_pipeline_ir(g, run_manager=run, use_cache=False)
    assert CALLS["rtfix_flaky"] == 1
    assert CALLS["rtfix_sink"] == 0  # 'ok' depends on f.output → skipped
    meta = json.loads((Path(run.base_path) / "meta.json").read_text())
    assert meta["status"] in ("succeeded", "completed")
    assert "node_failed_continued" in [e.get("type") for e in _logs(run)]


def test_fail_mode_and_retry_on_timeout_only(rt_env):
    # RuntimeError is not a timeout → no retry; on_error=fail → run fails.
    g = _graph({"on_error": IROnError(mode="fail"), "retry": IRRetry(max_attempts=3, on=["timeout"])})
    run = RunManager()
    with pytest.raises(RuntimeError, match="transient"):
        run_pipeline_ir(g, run_manager=run, use_cache=False)
    assert CALLS["rtfix_flaky"] == 1


def test_retry_on_timeout_retries_timeouts(rt_env):
    def _boom(node, inputs):
        raise TimeoutError("slow upstream")

    HOOKS["rtfix_flaky"] = _boom
    g = _graph(
        {"on_error": IROnError(mode="continue"), "retry": IRRetry(max_attempts=3, on=["timeout"])}
    )
    run_pipeline_ir(g, run_manager=RunManager(), use_cache=False)
    assert CALLS["rtfix_flaky"] == 3


def test_validator_accepts_error_port_edge(rt_env):
    from app.core.execution.validation import validate_graph_ir_result
    from app.core.host.registry_runtime import get_registry

    g = _graph({"on_error": IROnError(mode="route")}, [("f", "error", "handler", "input")])
    result = validate_graph_ir_result(g, get_registry())
    assert result["valid"], result["errors"]
