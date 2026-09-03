"""SetMapNode — copy/rename/drop fields on dict or list-of-dicts."""
from __future__ import annotations

import importlib
import logging
from typing import Any, ClassVar
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("set_map.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

MappedPayload = _types.MappedPayload
log = logging.getLogger(__name__)


def _apply_one(item: Any, copy_map: dict, rename: dict, drop: list, set_fields: dict) -> Any:
    if not isinstance(item, dict):
        if set_fields:
            return {"value": item, **set_fields}
        return item
    out = dict(item)
    for src, dst in dict(copy_map or {}).items():
        if src in out:
            out[str(dst)] = out[src]
    for src, dst in dict(rename or {}).items():
        if src in out:
            out[str(dst)] = out.pop(src)
    for key in list(drop or []):
        out.pop(str(key), None)
    for k, v in dict(set_fields or {}).items():
        out[str(k)] = v
    return out


class SetMapNode(Node):
    node_type: ClassVar[str] = "set_map"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="set_map",
        label="Set / Map",
        description="Copy, rename, drop, or set fields on a dict or list of dicts.",
        category="Transform",
        version="1.0.0",
        tags=["transform", "map", "workflow", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
    )
    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object | None, required=False, description="dict or list"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="Mapped payload"),
    }

    class Config(NodeConfig):
        copy_fields: dict = Field(default={}, title="Copy Fields", description="Copy Fields.")
        rename: dict = Field(default={}, title="Rename", description="Rename.")
        drop: list = Field(default=[], title="Drop", description="Drop.")
        set: dict = Field(default={}, title="Set", description="Set.")

    def process(self, inputs):
        payload = inputs.get("input") if isinstance(inputs, dict) else inputs
        copy_map = dict(self.config.copy_fields or {})
        rename = dict(self.config.rename or {})
        drop = list(self.config.drop or [])
        set_fields = dict(getattr(self.config, "set") or {})
        if isinstance(payload, list):
            data = [_apply_one(x, copy_map, rename, drop, set_fields) for x in payload]
        else:
            data = _apply_one(payload, copy_map, rename, drop, set_fields)
        return {"output": MappedPayload(data=data, metadata={"dropped": drop})}
