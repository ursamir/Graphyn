"""G3 run inputs / graph parameters, cron schedules, webhook payload injection."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.execution.run_inputs import RunInputsError, prepare_parameters, prepare_run_inputs
from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode, IRParameter
from app.core.ir.parameters import ParameterError, apply_parameters
from app.core.pipelines.cron import CronError, next_fire, parse_cron

from unit_test.core._runtime_fixes_nodes import CALLS, HOOKS, rt_env  # noqa: F401


def _g(params: dict | None = None, cfg: dict | None = None) -> GraphIR:
    return GraphIR(
        schema_version="1.3",
        metadata=IRMetadata(name="p", seed=0),
        nodes=[
            IRNode(id="a", node_type="rtfix_source", config=cfg or {"value": 1}),
            IRNode(id="b", node_type="rtfix_add", config={"inc": 1}),
        ],
        edges=[IREdge(src_id="a", src_port="output", dst_id="b", dst_port="input")],
        parameters=params or {},
    )


# ── parameters ────────────────────────────────────────────────────────────────

def test_parameters_substitute_typed_and_embedded():
    g = _g(
        {"n": IRParameter(type="int", default=3), "tag": IRParameter(type="str", default="x")},
        {"value": "${params.n}", "output_dir": "out/${params.tag}/run"},
    )
    out = apply_parameters(g, {"n": 7})
    cfg = dict(out.nodes[0].config)
    assert cfg["value"] == 7
    assert cfg["output_dir"] == "out/x/run"


def test_parameters_errors():
    g = _g({"n": IRParameter(type="int", default=3)})
    with pytest.raises(ParameterError):
        apply_parameters(g, {"nope": 1})
    with pytest.raises(ParameterError):
        apply_parameters(g, {"n": "seven"})
    with pytest.raises(ParameterError):
        apply_parameters(_g(), {"n": 1})
    assert apply_parameters(_g(), None) is not None


def test_prepare_parameters_meta():
    g = _g({"n": IRParameter(type="int", default=3)}, {"value": "${params.n}"})
    g2, meta = prepare_parameters(g, {"n": 5})
    assert dict(g2.nodes[0].config)["value"] == 5
    assert meta["parameter_names"] == ["n"]
    assert len(meta["parameters_sha256"]) == 64
    same, empty = prepare_parameters(_g(), None)
    assert empty == {}


# ── run inputs ────────────────────────────────────────────────────────────────

def test_prepare_run_inputs_validates_and_fingerprints(rt_env):
    g = _g()
    overrides, meta = prepare_run_inputs(g, {"b": {"input": [{"rt": True, "v": 41}]}})
    assert overrides == {"b": {"input": [{"rt": True, "v": 41}]}}
    assert meta["input_keys"] == ["b.input"]
    assert len(meta["inputs_sha256"]) == 64
    with pytest.raises(RunInputsError):
        prepare_run_inputs(g, {"zzz": {"input": 1}})
    with pytest.raises(RunInputsError):
        prepare_run_inputs(g, {"b": {"nope": 1}})
    with pytest.raises(RunInputsError) as exc:
        prepare_run_inputs(g, {"b": {"input": "x" * 100}}, max_bytes=50)
    assert exc.value.status_code == 413
    assert prepare_run_inputs(g, None) == (None, {})


def test_webhook_payload_injected_into_trigger_node(rt_env):
    """input_overrides reach a webhook_trigger node and flow downstream."""
    from app.core.execution.orchestrator import run_pipeline_ir
    from app.core.nodes import registry as global_registry
    from app.core.runs.run_journal import RunManager

    path = Path(__file__).resolve().parents[2] / "PluginPackage/Common/webhook_trigger/nodes.py"
    spec = importlib.util.spec_from_file_location("graphyn_test_webhook_nodes_core", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    cls = mod.WebhookTriggerNode
    already = "webhook_trigger" in global_registry
    if not already:
        global_registry.register("webhook_trigger", cls, cls.metadata)
    try:
        seen: dict = {}
        HOOKS["rtfix_sink"] = lambda node, inputs: seen.update(inputs)
        g = GraphIR(
            schema_version="1.3",
            metadata=IRMetadata(name="wh", seed=0),
            nodes=[
                IRNode(id="hook", node_type="webhook_trigger", config={}),
                IRNode(id="sink", node_type="rtfix_sink", config={}),
            ],
            edges=[IREdge(src_id="hook", src_port="body", dst_id="sink", dst_port="input")],
        )
        body = [{"rt": True, "v": 9}]
        run_pipeline_ir(g, run_manager=RunManager(), use_cache=False,
                        input_overrides={"hook": {"body": body, "headers": {}, "query": {}}})
        assert seen["input"] == body
    finally:
        if not already:
            global_registry.unregister("webhook_trigger")


# ── cron ──────────────────────────────────────────────────────────────────────

T0 = datetime(2026, 10, 5, 10, 7, tzinfo=timezone.utc)  # Monday


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("*/15 * * * *", datetime(2026, 10, 5, 10, 15, tzinfo=timezone.utc)),
        ("0 2 * * 1-5", datetime(2026, 10, 6, 2, 0, tzinfo=timezone.utc)),
        ("30 9 1 * *", datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc)),
        ("@weekly", datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)),
        ("0 12 * * sun", datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)),
        ("0 0 29 feb *", datetime(2028, 2, 29, 0, 0, tzinfo=timezone.utc)),
        ("7 10 * * *", datetime(2026, 10, 6, 10, 7, tzinfo=timezone.utc)),
        ("0 0 1 * 1", datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)),  # dom OR dow
    ],
)
def test_next_fire(expr, expected):
    assert next_fire(expr, T0) == expected


@pytest.mark.parametrize("bad", ["", "* * * *", "61 * * * *", "* * * * 9", "5-1 * * * *", "*/0 * * * *", "x * * * *"])
def test_parse_cron_rejects(bad):
    with pytest.raises(CronError):
        parse_cron(bad)


def test_schedule_with_cron(tmp_path):
    from app.core.pipelines.schedules import create_schedule, list_schedules, normalize_schedule

    item = create_schedule(name="nightly", project="p", pipeline="q", cron="0 2 * * *",
                           base_dir=tmp_path)
    assert item["cron"] == "0 2 * * *"
    nxt = datetime.fromisoformat(item["next_run_at"])
    assert nxt.hour == 2 and nxt.minute == 0
    assert normalize_schedule(list_schedules(base_dir=tmp_path)[0])["cron"] == "0 2 * * *"
    with pytest.raises(ValueError):
        create_schedule(name="bad", project="p", pipeline="q", cron="nope", base_dir=tmp_path)
    plain = create_schedule(name="hourly", project="p", pipeline="q", interval_minutes=60, base_dir=tmp_path)
    assert normalize_schedule(plain)["cron"] is None


def test_tick_advances_cron_schedule(tmp_path, monkeypatch):
    from app.core.pipelines import schedules as sched

    item = sched.create_schedule(name="c", project="p", pipeline="q", cron="*/5 * * * *", base_dir=tmp_path)
    # Make it due now.
    def _due(items):
        for it in items:
            it["next_run_at"] = "2000-01-01T00:00:00+00:00"
        return items, None

    sched._mutate(sched.schedules_path(tmp_path), _due)
    monkeypatch.setattr(sched, "_execute_pipeline", lambda project, pipeline, env="prod": "run-x")
    fired = sched.tick_due_schedules(tmp_path)
    assert fired and fired[0]["last_run_id"] == "run-x"
    nxt = datetime.fromisoformat(fired[0]["next_run_at"])
    assert nxt.minute % 5 == 0 and nxt > datetime.now(timezone.utc)
    assert item["id"] == fired[0]["id"]
