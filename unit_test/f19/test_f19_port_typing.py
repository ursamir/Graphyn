# unit_test/f19/test_f19_port_typing.py
"""F19 / F-22 — plugin manifests declare a runtime; port types survive the catalog.

Before: 8 plugin.toml files had no ``runtime`` key; ``list[AudioSample]`` was
published as ``builtins.list`` and Common producers declared ``object``, so the
builder's wire-time check (``/nodes/compatible``) could not resolve the type
and silently accepted every connection.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _threads(real_threads):
    yield


@pytest.fixture(scope="module")
def full_registry(tmp_path_factory):
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.manager import PluginManager
    from app.core.plugins.venv_manager import PluginVenvManager

    tmp = tmp_path_factory.mktemp("f19_ports")
    reg = NodeRegistry()
    mgr = PluginManager(registry=reg, base_dir=str(tmp))
    mgr._plugins_dir = str(tmp)
    with patch.object(PluginVenvManager, "ensure", return_value=Path("/tmp/fake-venv/bin/python")):
        for toml in sorted((REPO / "PluginPackage").rglob("plugin.toml")):
            try:
                mgr.install(str(toml.parent) + "/")
            except Exception:
                continue
    return reg


def test_every_bundled_manifest_declares_runtime():
    missing, bad = [], []
    for toml in sorted((REPO / "PluginPackage").rglob("plugin.toml")):
        data = tomllib.loads(toml.read_text(encoding="utf-8"))
        rt = data.get("runtime", (data.get("plugin") or {}).get("runtime"))
        if rt is None:
            missing.append(str(toml.relative_to(REPO)))
        elif rt not in {"inprocess", "isolated"}:
            bad.append((str(toml.relative_to(REPO)), rt))
    assert not missing, missing
    assert not bad, bad


def test_type_label_keeps_generics_and_round_trips():
    from app.models.audio_sample import AudioSample
    from app.core.nodes.type_names import parse_type_label, type_label

    for t in (list[AudioSample], object | None, dict[str, list[int]], AudioSample | None, list):
        label = type_label(t)
        assert parse_type_label(label) == t, label
    assert type_label(list[AudioSample]) == "builtins.list[app.models.audio_sample.AudioSample]"
    assert type_label(None) is None
    with pytest.raises(LookupError):
        parse_type_label("nowhere.Unknown")
    with pytest.raises(ValueError):
        parse_type_label("builtins.list[")


def test_catalog_publishes_element_types(full_registry):
    meta = full_registry.get_metadata("segmenter")
    assert meta.input_ports["input"]["data_type"] == "builtins.list[app.models.audio_sample.AudioSample]"
    http = full_registry.get_metadata("http_request")
    assert http.output_ports["output"]["data_type"].endswith(".HttpResponse")


def test_compatible_endpoint_resolves_generic_labels(api_client, full_registry, monkeypatch):
    import app.api.routers.nodes as nodes_router

    monkeypatch.setattr(nodes_router, "get_registry", lambda: full_registry)
    r = api_client.get(
        "/api/v1/nodes/compatible",
        params={"output_type": "builtins.list[app.models.audio_sample.AudioSample]", "direction": "input"},
    )
    assert r.status_code == 200, r.text
    names = {n["node_type"] for n in r.json()}
    assert "segmenter" in names and "audio_conditioner" in names
    assert "trainer" not in names  # DatasetArtifact input does not take raw clips


def test_check_connection_refuses_mismatch_and_allows_match(api_client, full_registry, monkeypatch):
    import app.api.routers.nodes as nodes_router

    monkeypatch.setattr(nodes_router, "get_registry", lambda: full_registry)
    q = lambda **kw: api_client.get("/api/v1/nodes/check-connection", params=kw)  # noqa: E731

    ok = q(src_node_type="dataset_ingest", dst_node_type="audio_conditioner")
    assert ok.status_code == 200 and ok.json()["compatible"] is True, ok.text

    bad = q(src_node_type="http_request", dst_node_type="trainer", dst_port="dataset")
    body = bad.json()
    assert bad.status_code == 200 and body["compatible"] is False, bad.text
    assert "HttpResponse" in body["reason"] and "DatasetArtifact" in body["reason"]

    # Generic transforms still accept typed producers (object is a universal sink).
    assert q(src_node_type="http_request", dst_node_type="set_map").json()["compatible"] is True

    clips_to_dataset = q(src_node_type="segmenter", dst_node_type="trainer", dst_port="dataset").json()
    assert clips_to_dataset["compatible"] is False

    missing = q(src_node_type="segmenter", dst_node_type="trainer", dst_port="nope").json()
    assert missing["compatible"] is False and "no input named" in missing["reason"]
    assert q(src_node_type="nope_x", dst_node_type="trainer").status_code == 404


def test_check_connection_matches_graph_validator(full_registry):
    """The endpoint and VAL-TYPE use the same rule."""
    from app.core.ir.loader import load_ir
    from app.core.execution.validation import validate_graph_ir_result

    ir = load_ir({
        "schema_version": "1.2",
        "metadata": {"seed": 1, "name": "f19-type"},
        "nodes": [
            {"id": "h", "node_type": "http_request", "config": {"url": "https://example.com"}},
            {"id": "t", "node_type": "trainer", "config": {}},
        ],
        "edges": [{"src_id": "h", "src_port": "output", "dst_id": "t", "dst_port": "dataset"}],
    })
    res = validate_graph_ir_result(ir, full_registry)
    assert any(e.get("code") == "VAL-TYPE" for e in res.get("errors") or []), res
