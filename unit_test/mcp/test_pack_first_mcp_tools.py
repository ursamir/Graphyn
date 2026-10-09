"""MCP pack-first tools."""
from __future__ import annotations

from app.mcp.handlers.journey import (
    describe_pack_handler,
    get_node_spec_handler,
    list_packs_handler,
    materialize_template_handler,
)
from app.mcp.tool_registry import register_all_tools


def test_tools_registered():
    names: list[str] = []
    register_all_tools(lambda n, *a, **k: names.append(n))
    for required in (
        "materialize_template",
        "get_node_spec",
        "list_packs",
        "describe_pack",
        "search_templates",
    ):
        assert required in names


def test_list_packs():
    out = list_packs_handler({})
    assert out["ok"] is True
    assert out["count"] == 9


def test_get_node_spec_shipped_and_removed():
    # F19 (F-07): Vision / TinyML packs are not shipped on this branch.
    trainer = get_node_spec_handler({"node_type": "trainer"})
    assert trainer["ok"] is True
    assert trainer["status"] == "Shipped"
    gone = get_node_spec_handler({"node_type": "yolo_train"})
    assert gone.get("ok") is not True


def test_materialize_template():
    out = materialize_template_handler({"template_id": "tpl-audio-kws-train-smart-home"})
    assert out["ok"] is True
    graph = out["graph"]
    assert graph["schema_version"] == "1.1"
    assert len(graph["nodes"]) >= 2
    assert len(graph["edges"]) >= 1


def test_describe_pack_audio():
    # F19 (F-07): Vision was removed; describe a shipped pack instead.
    out = describe_pack_handler({"pack": "Audio", "template_limit": 5})
    assert out["ok"] is True
    assert out["node_count"] >= 10
    assert out["template_sample_count"] >= 1
