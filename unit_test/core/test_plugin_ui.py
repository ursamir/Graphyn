"""plugin.toml config_schema overlays Pydantic as the Builder UI contract."""
from __future__ import annotations

from app.core.nodes.plugin_ui import json_schema_from_toml_fields, overlay_plugin_ui
from app.core.nodes.registry import NodeRegistry
from app.core.nodes.errors import NodeNotFoundError
from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from pydantic import Field
from typing import Literal


def test_toml_enum_and_widget():
    schema = json_schema_from_toml_fields(
        {
            "backend": {
                "type": "string",
                "title": "Backend",
                "enum": ["keras", "pytorch", "auto"],
                "default": "auto",
            },
            "token": {"type": "string", "widget": "secret", "title": "Token"},
        }
    )
    props = schema["properties"]
    assert props["backend"]["enum"] == ["keras", "pytorch", "auto"]
    assert props["backend"]["title"] == "Backend"
    assert props["token"]["widget"] == "secret"


def test_plugin_toml_wins_over_pydantic():
    base = {
        "type": "object",
        "properties": {
            "backend": {"type": "string", "title": "Engine"},
            "epochs": {"type": "integer", "default": 3},
        },
    }
    out = overlay_plugin_ui(
        base,
        {
            "backend": {
                "type": "string",
                "title": "Backend",
                "enum": ["keras", "auto"],
            }
        },
    )
    assert out["properties"]["backend"]["title"] == "Backend"
    assert out["properties"]["backend"]["enum"] == ["keras", "auto"]
    assert out["properties"]["epochs"]["default"] == 3


class _Dummy(Node):
    node_type = "dummy_ui"
    metadata = NodeMetadata(node_type="dummy_ui", label="Dummy", description="d", category="test")

    class Config(NodeConfig):
        backend: Literal["x"] = Field(default="x", title="FromCode")


def test_registry_overlays_plugin_ui():
    reg = NodeRegistry()
    reg.register("dummy_ui", _Dummy, _Dummy.metadata)
    raw = reg.get_config_schema("dummy_ui")
    assert raw["properties"]["backend"]["title"] == "FromCode"
    reg.set_plugin_ui_schema(
        "dummy_ui",
        {"backend": {"type": "string", "title": "FromPlugin", "enum": ["keras", "auto"]}},
    )
    over = reg.get_config_schema("dummy_ui")
    assert over["properties"]["backend"]["title"] == "FromPlugin"
    assert over["properties"]["backend"]["enum"] == ["keras", "auto"]


def test_missing_config_raises():
    reg = NodeRegistry()
    try:
        reg.get_class("nope")
        raise AssertionError("expected missing")
    except NodeNotFoundError:
        pass
