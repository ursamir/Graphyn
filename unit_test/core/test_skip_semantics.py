"""G1 skip semantics + G6 external-call audit, sequential and parallel paths.

Rule 1 (unchanged): skip when a required input's edges are all unproduced.
Rule 2 (new):       skip when the node has ≥1 incoming edge and EVERY incoming
                    edge is unproduced (optional ports included).
"""
from __future__ import annotations

import concurrent.futures
import json
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any, ClassVar

import pytest

from app.core.execution.orchestrator import run_pipeline_ir
from app.core.execution.skip_logic import should_skip_for_unproduced
from app.core.ir.models import GraphIR, IREdge, IRMetadata, IRNode
from app.core.nodes import registry as global_registry
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort
from app.core.runs.run_journal import RunManager

CALLS: dict[str, list[Any]] = defaultdict(list)
# Captured at import, before conftest's autouse no-op thread patch (parallel path).
_REAL_SUBMIT = concurrent.futures.ThreadPoolExecutor.submit
_REAL_START = threading.Thread.start


class SkSource(Node):
    node_type: ClassVar[str] = "sktest_source"
    input_ports: ClassVar[dict] = {}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=object)}

    class Config(NodeConfig):
        value: int = 1

    def process(self, inputs):
        CALLS[self.node_type].append(self.config.value)
        return {"output": {"v": self.config.value}}


class SkBranch(Node):
    """if_switch-style: emits ONLY the taken branch port."""

    node_type: ClassVar[str] = "sktest_branch"
    input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=object | None, required=False)}
    output_ports: ClassVar[dict] = {
        "true": OutputPort(name="true", data_type=object),
        "false": OutputPort(name="false", data_type=object),
    }

    class Config(NodeConfig):
        take: bool = True

    def process(self, inputs):
        return {"true" if self.config.take else "false": inputs.get("input")}


class SkOptional(Node):
    """Single OPTIONAL input — previously ran with None on the untaken branch."""

    node_type: ClassVar[str] = "sktest_optional"
    input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=object | None, required=False)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=object)}

    class Config(NodeConfig):
        tag: str = ""

    def process(self, inputs):
        CALLS[f"optional:{self.config.tag}"].append(inputs.get("input"))
        return {"output": inputs.get("input")}


class SkMerge(Node):
    node_type: ClassVar[str] = "sktest_merge"
    input_ports: ClassVar[dict] = {
        "a": InputPort(name="a", data_type=object | None, required=False),
        "b": InputPort(name="b", data_type=object | None, required=False),
    }
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=object)}

    class Config(NodeConfig):
        pass

    def process(self, inputs):
        CALLS["merge"].append((inputs.get("a"), inputs.get("b")))
        return {"output": [inputs.get("a"), inputs.get("b")]}


class SkFanIn(Node):
    """Required multi-input consumer (Example-06 trainer/evaluator shape)."""

    node_type: ClassVar[str] = "sktest_fanin"
    input_ports: ClassVar[dict] = {
        "a": InputPort(name="a", data_type=object, required=True),
        "b": InputPort(name="b", data_type=object | None, required=False),
    }
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=object)}

    class Config(NodeConfig):
        tag: str = ""

    def process(self, inputs):
        CALLS[f"fanin:{self.config.tag}"].append(1)
        return {"output": {"tag": self.config.tag}}


class SkEgress(Node):
    node_type: ClassVar[str] = "sktest_egress"
    input_ports: ClassVar[dict] = {"input": InputPort(name="input", data_type=object | None, required=False)}
    output_ports: ClassVar[dict] = {"output": OutputPort(name="output", data_type=object)}

    class Config(NodeConfig):
        fail: bool = False

    def process(self, inputs):
        self.record_external_call(
            "http", "post", "https://user:pw@api.example.com:8443/v1/x?token=SECRET#frag", 200,
            request_sha256=b'{"a":1}', response_sha256="sha256:" + "0" * 64,
            duration_ms=12.345, connection_id="conn-1",
        )
        if self.config.fail:
            raise RuntimeError("boom after egress")
        return {"output": 1}


_CLASSES = [SkSource, SkBranch, SkOptional, SkMerge, SkFanIn, SkEgress]


@pytest.fixture
def sk_env(tmp_path, monkeypatch, patch_threads):
    monkeypatch.setattr(concurrent.futures.ThreadPoolExecutor, "submit", _REAL_SUBMIT)
    monkeypatch.setattr(threading.Thread, "start", _REAL_START)
    ws = tmp_path / "workspace"
    ws.mkdir()
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(ws))
    CALLS.clear()
    for cls in _CLASSES:
        global_registry.register(
            cls.node_type, cls,
            NodeMetadata(node_type=cls.node_type, label=cls.node_type, description="skip test",
                         category="Test", cacheable=False),
        )
    yield ws
    for cls in _CLASSES:
        global_registry.unregister(cls.node_type)


def _graph(nodes, edges) -> GraphIR:
    return GraphIR(
        schema_version="1.2",
        metadata=IRMetadata(name="sktest", seed=0),
        nodes=[IRNode(id=n, node_type=t, config=c) for n, t, c in nodes],
        edges=[IREdge(src_id=a, src_port=ap, dst_id=b, dst_port=bp) for a, ap, b, bp in edges],
    )


def _run(g: GraphIR, parallel: bool) -> RunManager:
    run = RunManager()
    run_pipeline_ir(g, run_manager=run, use_cache=False, parallel=parallel)
    return run


def _meta(run: RunManager) -> dict:
    return json.loads((Path(run.base_path) / "meta.json").read_text(encoding="utf-8"))


MODES = pytest.mark.parametrize("parallel", [False, True], ids=["sequential", "parallel"])


# ── pure function ─────────────────────────────────────────────────────────────

def _node(**ports):
    return type("N", (), {"input_ports": {k: InputPort(name=k, data_type=object if v else object | None, required=v)
                                          for k, v in ports.items()}})()


def test_rule2_all_edges_unproduced_skips_optional_node():
    skip, why = should_skip_for_unproduced(
        node_id="n", node=_node(input=False), incoming={"n": [("br", "true", "input")]},
        node_outputs={"br": {"false": 1}}, skipped=set(), edge_conditions={},
    )
    assert skip and why == "all_inputs_unproduced"


def test_rule2_partial_inputs_still_run():
    skip, _ = should_skip_for_unproduced(
        node_id="m", node=_node(a=False, b=False),
        incoming={"m": [("x", "true", "a"), ("y", "output", "b")]},
        node_outputs={"x": {"false": 1}, "y": {"output": 2}}, skipped=set(), edge_conditions={},
    )
    assert skip is False


def test_rule2_condition_false_reason_and_provided_ports():
    kw = dict(node_id="n", node=_node(input=False), incoming={"n": [("s", "output", "input")]},
              node_outputs={"s": {"output": 1}}, skipped=set(),
              edge_conditions={("s", "output", "n", "input"): "False"},
              condition_results={("s", "output", "input"): False})
    assert should_skip_for_unproduced(**kw) == (True, "condition_false")
    # An override / passthrough value counts as a produced input.
    assert should_skip_for_unproduced(**kw, provided_ports={"input"}) == (False, None)


def test_source_nodes_never_skipped():
    assert should_skip_for_unproduced(node_id="s", node=_node(), incoming={}, node_outputs={},
                                      skipped=set(), edge_conditions={}) == (False, None)


def test_rule1_required_still_applies_with_other_inputs_produced():
    skip, why = should_skip_for_unproduced(
        node_id="f", node=_node(a=True, b=False),
        incoming={"f": [("x", "true", "a"), ("y", "output", "b")]},
        node_outputs={"x": {"false": 1}, "y": {"output": 2}}, skipped=set(), edge_conditions={},
    )
    assert skip and why == "upstream_skipped"


# ── end to end (sequential + parallel) ────────────────────────────────────────

@MODES
def test_if_switch_untaken_optional_branch_is_skipped(sk_env, parallel):
    g = _graph(
        [("src", "sktest_source", {"value": 7}), ("br", "sktest_branch", {"take": True}),
         ("yes", "sktest_optional", {"tag": "yes"}), ("no", "sktest_optional", {"tag": "no"})],
        [("src", "output", "br", "input"), ("br", "true", "yes", "input"), ("br", "false", "no", "input")],
    )
    _run(g, parallel)
    assert CALLS["optional:yes"] == [{"v": 7}]
    assert CALLS["optional:no"] == []  # previously ran with input=None


@MODES
def test_merge_runs_with_one_side(sk_env, parallel):
    g = _graph(
        [("src", "sktest_source", {"value": 3}), ("br", "sktest_branch", {"take": False}),
         ("yes", "sktest_optional", {"tag": "yes"}), ("no", "sktest_optional", {"tag": "no"}),
         ("m", "sktest_merge", {})],
        [("src", "output", "br", "input"), ("br", "true", "yes", "input"), ("br", "false", "no", "input"),
         ("yes", "output", "m", "a"), ("no", "output", "m", "b")],
    )
    _run(g, parallel)
    assert CALLS["optional:yes"] == []
    assert CALLS["merge"] == [(None, {"v": 3})]


@MODES
def test_skip_chain_propagates(sk_env, parallel):
    g = _graph(
        [("src", "sktest_source", {}), ("br", "sktest_branch", {"take": True}),
         ("n1", "sktest_optional", {"tag": "n1"}), ("n2", "sktest_optional", {"tag": "n2"}),
         ("n3", "sktest_optional", {"tag": "n3"})],
        [("src", "output", "br", "input"), ("br", "false", "n1", "input"),
         ("n1", "output", "n2", "input"), ("n2", "output", "n3", "input")],
    )
    _run(g, parallel)
    assert CALLS["optional:n1"] == CALLS["optional:n2"] == CALLS["optional:n3"] == []


@MODES
def test_example06_style_fanout_unaffected(sk_env, parallel):
    """dataset_builder → {model_builder, trainer, evaluator} fan-out/fan-in (pipeline_train_ml)."""
    g = _graph(
        [("ds", "sktest_source", {}), ("mb", "sktest_fanin", {"tag": "mb"}),
         ("tr", "sktest_fanin", {"tag": "tr"}), ("ev", "sktest_fanin", {"tag": "ev"}),
         ("opt", "sktest_optional", {"tag": "opt"})],
        [("ds", "output", "mb", "a"), ("ds", "output", "tr", "a"), ("mb", "output", "tr", "b"),
         ("ds", "output", "ev", "a"), ("tr", "output", "ev", "b"), ("ev", "output", "opt", "input")],
    )
    _run(g, parallel)
    assert CALLS["fanin:mb"] == CALLS["fanin:tr"] == CALLS["fanin:ev"] == [1]
    assert CALLS["optional:opt"] == [{"tag": "ev"}]


# ── G6 external call audit ────────────────────────────────────────────────────

@MODES
def test_external_calls_land_in_meta_and_sealed_record(sk_env, parallel):
    g = _graph([("src", "sktest_source", {}), ("eg", "sktest_egress", {})],
               [("src", "output", "eg", "input")])
    run = _run(g, parallel)
    rows = _meta(run)["external_calls"]
    assert len(rows) == 1
    row = rows[0]
    assert row["url"] == "https://api.example.com:8443/v1/x"  # no userinfo / query / fragment
    assert "SECRET" not in json.dumps(rows) and "pw" not in row["url"]
    assert row["method"] == "POST" and row["status"] == 200 and row["kind"] == "http"
    assert row["node_id"] == "eg" and row["node_type"] == "sktest_egress"
    assert row["request_sha256"].startswith("sha256:") and row["connection_id"] == "conn-1"
    rec = json.loads((Path(run.base_path) / "prove.json").read_text(encoding="utf-8"))
    assert rec["external_calls"][0]["url"] == row["url"]


def test_external_calls_recorded_even_when_node_fails(sk_env):
    g = _graph([("src", "sktest_source", {}), ("eg", "sktest_egress", {"fail": True})],
               [("src", "output", "eg", "input")])
    run = RunManager()
    with pytest.raises(Exception):
        run_pipeline_ir(g, run_manager=run, use_cache=False)
    rows = _meta(run).get("external_calls") or []
    assert [r["node_id"] for r in rows] == ["eg"]


def test_audit_record_external_call_rows_redact_defensively():
    from app.core.runs.audit_record import _external_call_rows

    rows = _external_call_rows({"external_calls": [
        {"url": "https://u:p@h.example/x?k=v", "method": "GET", "secret_header": "nope"}, "junk"]})
    assert rows == [{"url": "https://h.example/x", "method": "GET"}]
