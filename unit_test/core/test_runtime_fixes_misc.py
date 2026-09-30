"""Runtime fixes: capability merge, condition DoS guard, validation, provenance."""
from __future__ import annotations

import json
import os
import threading
from unittest.mock import MagicMock

import pytest

from app.core.execution.conditions import (
    ConditionEvaluationError,
    evaluate_condition,
    validate_condition_syntax,
)
from app.core.ir.models import IRCapabilityMetadata, IRNode
from app.core.nodes.metadata import NodeMetadata
from app.core.host.registry_runtime import resolve_capability

from unit_test.core._runtime_fixes_nodes import make_graph, rt_env  # noqa: F401


# ── #11 capability merge ──────────────────────────────────────────────────────

def _registry_with(meta: NodeMetadata):
    reg = MagicMock()
    reg.get_metadata.return_value = meta
    return reg


def _meta(**kw) -> NodeMetadata:
    return NodeMetadata(node_type="side", label="s", description="d", category="c", **kw)


def test_ir_capability_hint_does_not_reset_plugin_cacheable():
    reg = _registry_with(_meta(cacheable=False, requires_gpu=False))
    node = IRNode(id="n", node_type="side", capability_metadata=IRCapabilityMetadata(requires_gpu=True))
    cap = resolve_capability(node, reg)
    assert cap.requires_gpu is True
    assert cap.cacheable is False


def test_roundtripped_default_values_do_not_override_plugin():
    from app.core.ir.loader import dump_ir, load_ir

    g = make_graph([("n", "side", {})])
    data = dump_ir(g)
    data["nodes"][0]["capability_metadata"] = IRCapabilityMetadata().model_dump(mode="json")
    node = load_ir(data).nodes[0]
    cap = resolve_capability(node, _registry_with(_meta(cacheable=False)))
    assert cap.cacheable is False


def test_explicit_non_default_ir_value_overrides_plugin():
    node = IRNode(id="n", node_type="side", capability_metadata=IRCapabilityMetadata(deterministic=False))
    cap = resolve_capability(node, _registry_with(_meta(deterministic=True)))
    assert cap.deterministic is False


# ── #12 condition DoS guard ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    "expr",
    [
        "'a' * 9999999999",
        "output['s'] * 9999999999",
        "[1] * 999999999",
        "'%999999999d' % 1",
        "2 ** 99999999",
    ],
)
def test_condition_rejects_repetition_and_formatting(expr):
    with pytest.raises(ConditionEvaluationError):
        evaluate_condition(expr, {"s": "abc"})


def test_condition_numeric_mult_mod_still_work():
    assert evaluate_condition("output['n'] * 2 > 5", {"n": 3}) is True
    assert evaluate_condition("output['n'] % 2 == 1", {"n": 3}) is True
    with pytest.raises(ConditionEvaluationError):
        evaluate_condition("(10 ** 1) * 1", {})  # Pow disallowed
    with pytest.raises(ConditionEvaluationError, match="maximum integer size"):
        evaluate_condition("output['n'] * output['n'] > 0", {"n": 10 ** 2000})


def test_validate_condition_syntax():
    validate_condition_syntax("len(output['x']) > 0")
    with pytest.raises(ConditionEvaluationError):
        validate_condition_syntax("len(output['x']) >")
    with pytest.raises(ConditionEvaluationError):
        validate_condition_syntax("__import__('os')")


# ── #13 validation ────────────────────────────────────────────────────────────

def _validate(graph):
    from app.core.nodes import registry
    from app.core.execution.validation import validate_graph_ir_result

    return validate_graph_ir_result(graph, registry)


def test_validation_flags_fan_in_into_single_port(rt_env):
    g = make_graph(
        [("a", "rtfix_source", {}), ("b", "rtfix_source", {}), ("c", "rtfix_sink", {})],
        [("a", "output", "c", "input"), ("b", "output", "c", "input")],
    )
    res = _validate(g)
    assert any(e["code"] == "VAL-CARDINALITY" for e in res["errors"])
    assert res["valid"] is False


def test_validation_warns_required_port_without_edge(rt_env):
    g = make_graph([("c", "rtfix_sink", {})])
    res = _validate(g)
    assert res["valid"] is True  # overrides may supply it at run time
    assert any(w["code"] == "VAL-UNCONNECTED-INPUT" for w in res["warnings"])


def test_validation_checks_condition_syntax(rt_env):
    from app.core.ir.models import GraphIR, IREdge

    g = make_graph([("a", "rtfix_source", {}), ("c", "rtfix_sink", {})])
    g = GraphIR(
        schema_version=g.schema_version,
        metadata=g.metadata,
        nodes=g.nodes,
        edges=[IREdge(src_id="a", src_port="output", dst_id="c", dst_port="input",
                      condition="len(output['output']) >")],
    )
    res = _validate(g)
    assert any(e["code"] == "VAL-COND" for e in res["errors"])


def test_validation_clean_chain_has_no_errors(rt_env):
    from unit_test.core._runtime_fixes_nodes import chain_graph

    res = _validate(chain_graph())
    assert res["errors"] == []


# ── #14 provenance concurrency ────────────────────────────────────────────────

def test_provenance_concurrent_stores_do_not_lose_index_entries(tmp_path):
    # conftest patches Thread.start to a no-op; restore it for this test only.
    # A scoped patch (not monkeypatch) so teardown can't re-install the no-op
    # after conftest's own patch has exited.
    from unittest.mock import patch as _patch

    with _patch.object(threading.Thread, "start", _REAL_THREAD_START):
        _run_provenance_concurrency(tmp_path)


def _run_provenance_concurrency(tmp_path) -> None:
    from app.core.artifacts.provenance import ProvenanceStore

    stores = [ProvenanceStore(base_dir=str(tmp_path)) for _ in range(4)]
    errors: list[BaseException] = []

    def work(i: int) -> None:
        try:
            for j in range(25):
                stores[i].record(
                    artifact_id=f"a{i}_{j}", run_id="shared", node_id="n",
                    node_type="t", graph_hash="g" * 64, input_artifact_ids=[],
                )
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors
    by_run = json.loads((tmp_path / "provenance" / "by_run" / "shared.json").read_text())
    assert len(by_run) == 100
    by_hash = json.loads((tmp_path / "provenance" / "by_graph_hash" / f"{'g' * 64}.json").read_text())
    assert len(by_hash) == 100
    leftovers = [p for p in os.listdir(tmp_path / "provenance" / "by_run") if p.endswith(".tmp")]
    assert leftovers == []


_REAL_THREAD_START = threading.Thread.start
