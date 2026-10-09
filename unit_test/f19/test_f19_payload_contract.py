"""F19 (F-06 / F-11 / F-19 / F-24 / F-25): canonical inter-node payload contract.

Every test feeds a REAL upstream wrapper (python_code's CodeResult, csv_table's
CsvTableResult, set_map's MappedPayload …) produced by the real plugin into
the downstream node, exactly as the executor does.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.nodes.payload import payload_paths, unwrap_payload, wrapper_field
from app.core.plugins.manager import PluginManager
from unit_test.plugins._helpers import materialize_isolated_class

_PACKS = {
    "python_code": "PluginPackage/Common/python_code/",
    "set_map": "PluginPackage/Common/set_map/",
    "json_transform": "PluginPackage/Common/json_transform/",
    "merge": "PluginPackage/Common/merge/",
    "if_switch": "PluginPackage/Common/if_switch/",
    "csv_table": "PluginPackage/Common/csv_table/",
    "object_store": "PluginPackage/Common/object_store/",
    "eval_gate": "PluginPackage/Common/eval_gate/",
    "prompt_template": "PluginPackage/Agents/prompt_template/",
    "output_schema_validate": "PluginPackage/Agents/output_schema_validate/",
}


@pytest.fixture(scope="module")
def cls(tmp_path_factory):
    from app.core.nodes.registry import NodeRegistry

    tmp = tmp_path_factory.mktemp("f19_payload_plugins")
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp))
    mgr._plugins_dir = str(tmp)
    for src in _PACKS.values():
        mgr.install(src)
    return lambda nt: materialize_isolated_class(reg.get_class(nt))


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_PROJECT_DIR", str(tmp_path))
    return tmp_path


def _code(cls, source: str, value=None):
    return cls("python_code")(config={"source": source}, seed=0).process({"input": value})["output"]


# ── the contract itself ─────────────────────────────────────────────────


def test_unwrap_payload_rules(cls):
    cr = _code(cls, "output = {'a': 1, 'b': [1, 2]}")
    assert type(cr).__name__ == "CodeResult" and wrapper_field(cr) == "data"
    assert unwrap_payload(cr) == {"a": 1, "b": [1, 2]}
    # serialised wrapper (Mode B / JSON round-trip) is recognised by its exact field set
    assert unwrap_payload(json.loads(cr.model_dump_json())) == {"a": 1, "b": [1, 2]}
    # plain dicts that merely contain "data" are NOT unwrapped
    assert unwrap_payload({"data": 1, "other": 2}) == {"data": 1, "other": 2}
    assert unwrap_payload([cr, cr]) == [{"a": 1, "b": [1, 2]}] * 2
    assert unwrap_payload("text") == "text" and unwrap_payload(None) is None


def test_payload_paths_rules(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")

    class HasPath:
        path = str(f)

    assert payload_paths(str(f)) == [str(f)]
    assert payload_paths({"path": str(f)}) == [str(f)]
    assert payload_paths({"files": [str(f), {"path": str(f)}]}) == [str(f), str(f)]
    assert payload_paths(HasPath()) == [str(f)]
    assert payload_paths("https://example.com/x") == []
    assert payload_paths("multi\nline text") == []


# ── downstream nodes operate on the payload ─────────────────────────────


def test_set_map_on_code_result(cls):
    cr = _code(cls, "output = {'name': 'ada', 'tmp': 1}")
    out = cls("set_map")(config={"rename": {"name": "who"}, "drop": ["tmp"], "set": {"k": 2}}, seed=0).process({"input": cr})["output"]
    assert out.data == {"who": "ada", "k": 2}


def test_json_transform_on_code_result_and_legacy_wrapper_path(cls):
    cr = _code(cls, "output = {'user': {'name': 'ada'}}")
    node = cls("json_transform")
    assert node(config={"jsonpath": "$.user.name"}, seed=0).process({"input": cr})["output"].data == "ada"
    # paths written against the wrapper keep working
    assert node(config={"jsonpath": "$.data.user.name"}, seed=0).process({"input": cr})["output"].data == "ada"


def test_merge_on_code_results_and_append_never_overwrites(cls):
    a = _code(cls, "output = {'x': 1}")
    b = _code(cls, "output = {'y': 2}")
    m = cls("merge")
    assert m(config={"mode": "merge_dicts"}, seed=0).process({"a": a, "b": b})["output"].data == {"x": 1, "y": 2}
    # F-25: append of two dicts is a 2-item list (previously b overwrote a)
    assert m(config={"mode": "append"}, seed=0).process({"a": a, "b": b})["output"].data == [{"x": 1}, {"y": 2}]
    c = _code(cls, "output = {'x': 9}")
    with pytest.raises(Exception, match="conflict"):
        m(config={"mode": "merge_dicts"}, seed=0).process({"a": a, "b": c})
    assert m(config={"mode": "merge_dicts", "on_conflict": "prefer_b"}, seed=0).process({"a": a, "b": c})["output"].data == {"x": 9}


def test_if_switch_bare_names_on_code_result(cls):
    cr = _code(cls, "output = {'score': 0.9, 'label': 'yes'}")
    node = cls("if_switch")(config={"expression": "score > 0.5 and label == 'yes'"}, seed=0)
    out = node.process({"input": cr})
    assert "true" in out and "false" not in out
    # branch forwards the original upstream value unchanged
    assert unwrap_payload(out["true"]) == {"score": 0.9, "label": "yes"}
    low = _code(cls, "output = {'score': 0.1, 'label': 'yes'}")
    out2 = cls("if_switch")(config={"expression": "output['score'] > 0.5"}, seed=0).process({"input": low})
    assert "false" in out2 and "true" not in out2


def test_prompt_template_and_output_schema_validate_on_code_result(cls):
    cr = _code(cls, "output = {'name': 'ada', 'n': 3}")
    pt = cls("prompt_template")(config={"template": "Hi {name} x{n}"}, seed=0).process({"input": cr})
    rendered = pt["output"]
    text = getattr(rendered, "text", None) or getattr(rendered, "content", None) or str(rendered)
    assert "Hi ada x3" in text
    osv = cls("output_schema_validate")(
        config={"json_schema": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}},
        seed=0,
    ).process({"input": cr})
    assert osv  # validates the payload, not {data, metadata}


def test_eval_gate_required_keys_on_code_result(cls):
    cr = _code(cls, "output = {'pain': 'x'}")
    with pytest.raises(RuntimeError, match="owner"):
        cls("eval_gate")(config={"check_empty_transcript": False, "required_keys": ["pain", "owner"]}, seed=0).process({"input": cr})
    rows = _code(cls, "output = []")
    with pytest.raises(RuntimeError, match="empty list"):
        cls("eval_gate")(config={}, seed=0).process({"input": rows})


# ── F-11 object_store put is never a silent no-op ───────────────────────


def test_object_store_put_dict_code_result_rows_and_path_objects(cls, ws):
    put = lambda v, **cfg: cls("object_store")(config={"operation": "put", "root": "store", **cfg}, seed=0).process({"input": v})["output"]
    ref = put({"a": 1})
    assert json.loads(Path(ref.uri).read_text()) == {"a": 1} and ref.metadata["source"] == "inline"
    ref = put(_code(cls, "output = {'b': 2}"), key="code.json")
    assert Path(ref.uri).name == "code.json" and json.loads(Path(ref.uri).read_text()) == {"b": 2}
    # CsvTableResult → copies the CSV file it points at (.path attribute)
    (ws / "t.csv").write_text("a,b\n1,2\n")
    table = cls("csv_table")(config={"path": "t.csv"}, seed=0).process({"input": None})["output"]
    ref = put(table)
    assert Path(ref.uri).read_text() == "a,b\n1,2\n" and ref.metadata["source"] == "file"
    # rows without a file → CSV
    ref = put(_code(cls, "output = [{'a': 1}, {'a': 2}]"))
    assert Path(ref.uri).suffix == ".csv" and Path(ref.uri).read_text().splitlines() == ["a", "1", "2"]


def test_object_store_put_nothing_fails_loudly(cls, ws):
    node = cls("object_store")(config={"operation": "put", "root": "store"}, seed=0)
    for empty in (None, {}, [], _code(cls, "output = None")):
        with pytest.raises(RuntimeError, match="nothing to store"):
            node.process({"input": empty})


# ── F-19 csv_table reads workspace symlinks into the bundled examples tree ──


def test_csv_table_reads_symlinked_dataset(cls, ws, monkeypatch, tmp_path_factory):
    seed = tmp_path_factory.mktemp("examples") / "13_csv" / "data"
    seed.mkdir(parents=True)
    (seed / "sales.csv").write_text("region,total\nnorth,3\n")
    monkeypatch.setenv("GRAPHYN_EXAMPLES_DIR", str(seed.parent.parent))
    (ws / "datasets" / "input").mkdir(parents=True)
    (ws / "datasets" / "input" / "csv-data").symlink_to(seed)
    node = cls("csv_table")
    for p in ("datasets/input/csv-data/sales.csv", "workspace/datasets/input/csv-data/sales.csv"):
        out = node(config={"path": p}, seed=0).process({"input": None})["output"]
        assert out.rows == [{"region": "north", "total": "3"}]
        assert "workspace/workspace" not in out.path


def test_csv_table_symlink_outside_trusted_roots_rejected(cls, ws, tmp_path_factory):
    secret = tmp_path_factory.mktemp("elsewhere") / "s.csv"
    secret.write_text("a\n1\n")
    (ws / "leak.csv").symlink_to(secret)
    with pytest.raises(RuntimeError, match="outside"):
        cls("csv_table")(config={"path": "leak.csv"}, seed=0).process({"input": None})
    # writes never follow links into examples/
    with pytest.raises(RuntimeError, match="outside"):
        cls("csv_table")(config={"path": "leak.csv", "operation": "write"}, seed=0).process({"input": [{"a": 1}]})


# ── F-24 python_code standard exceptions ────────────────────────────────


def test_python_code_standard_exceptions(cls):
    src = (
        "class BadInput(ValueError):\n    pass\n"
        "def process(inputs, config):\n"
        "    try:\n"
        "        n = inputs['input']['n']\n"
        "        if n < 0:\n            raise BadInput('negative')\n"
        "        return 1 / n\n"
        "    except ZeroDivisionError:\n        return 'zero'\n"
        "    except KeyError as exc:\n        return 'missing ' + str(exc)\n"
    )
    run = lambda v: cls("python_code")(config={"source": src}, seed=0).process({"input": v})["output"].data
    assert run({"n": 2}) == 0.5 and run({"n": 0}) == "zero" and run({}) == "missing 'n'"
    with pytest.raises(ValueError, match="negative"):
        run({"n": -1})
