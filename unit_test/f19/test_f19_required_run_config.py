# unit_test/f19/test_f19_required_run_config.py
"""F19 / F-25 — graphs missing run-critical config are refused before a run starts.

Before: marketplace seeds such as an email alert (send_email ``to`` empty) or a
completion webhook (http_webhook ``url`` empty) validated clean and then failed
at run time. Now validation reports ``VAL-REQ-CONFIG`` warnings and the execute
path (API / SDK / CLI / MCP share check_graph_executable) refuses with 422.
"""
from __future__ import annotations

import pytest

from app.core.execution.graph_prepare import GraphPrepareError, check_graph_executable
from app.core.execution.validation import validate_graph_ir_result
from app.core.ir.models import GraphIR

@pytest.fixture(scope="module")
def reg(tmp_path_factory):
    from app.core.nodes.registry import NodeRegistry
    from app.core.plugins.manager import PluginManager

    r = NodeRegistry()
    tmp = tmp_path_factory.mktemp("f19_req_plugins")
    mgr = PluginManager(registry=r, base_dir=str(tmp))
    mgr._plugins_dir = str(tmp)
    for p in ("send_email", "http_webhook", "http_request", "csv_table"):
        mgr.install(f"PluginPackage/Common/{p}/")
    return r


def _graph(node_type, config):
    return GraphIR.model_validate(
        {"schema_version": "1.2", "metadata": {"name": "t", "seed": 0}, "nodes": [{"id": "n0", "node_type": node_type, "config": config}], "edges": []}
    )


@pytest.mark.parametrize(
    "node_type,config,field",
    [
        ("send_email", {"dry_run": True}, "to"),
        ("http_webhook", {}, "url"),
        ("http_request", {}, "url"),
        ("csv_table", {}, "path"),
    ],
)
def test_missing_run_config_warns_then_refuses(reg, node_type, config, field):
    res = validate_graph_ir_result(_graph(node_type, config), reg)
    assert res["valid"] is True  # schema-optional: templates/drafts still load
    req = [w for w in res["warnings"] if w["code"] == "VAL-REQ-CONFIG"]
    assert req and req[0]["field"] == field
    with pytest.raises(GraphPrepareError) as ei:
        check_graph_executable(_graph(node_type, config), registry=reg)
    assert ei.value.to_dict()["errors"][0]["code"] == "VAL-REQ-CONFIG"


@pytest.mark.parametrize(
    "node_type,config",
    [
        ("send_email", {"to": "ops@example.com", "dry_run": True}),
        ("send_email", {"allow_payload_recipients": True, "dry_run": True}),
        ("http_webhook", {"connection_id": "hook-1"}),
        ("http_webhook", {"url": "https://example.com/hook"}),
        ("http_request", {"url": "https://example.com"}),
        ("csv_table", {"path": "datasets/x.csv"}),
    ],
)
def test_configured_nodes_pass(reg, node_type, config):
    res = check_graph_executable(_graph(node_type, config), registry=reg)
    assert not [w for w in res["warnings"] if w["code"] == "VAL-REQ-CONFIG"]
