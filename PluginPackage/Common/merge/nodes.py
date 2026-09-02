"""MergeNode — append or combine_by_key for two list/dict inputs."""
from __future__ import annotations

import importlib
import logging
from typing import Any, ClassVar

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("merge.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

MergedPayload = _types.MergedPayload
log = logging.getLogger(__name__)


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _key_of(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


class MergeNode(Node):
    node_type: ClassVar[str] = "merge"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="merge",
        label="Merge",
        description="Merge two list/dict inputs by append or combine_by_key.",
        category="Transform",
        version="1.0.0",
        tags=["merge", "workflow", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
    )
    input_ports: ClassVar[dict[str, InputPort]] = {
        "a": InputPort(name="a", data_type=object | None, required=False, description="First input"),
        "b": InputPort(name="b", data_type=object | None, required=False, description="Second input"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="MergedPayload"),
    }

    class Config(NodeConfig):
        mode: str = "append"  # append | combine_by_key
        key: str = "id"

    def process(self, inputs):
        a = inputs.get("a") if isinstance(inputs, dict) else None
        b = inputs.get("b") if isinstance(inputs, dict) else None
        mode = (self.config.mode or "append").strip().lower()
        if mode == "combine_by_key":
            key = self.config.key or "id"
            merged: dict[Any, Any] = {}
            order: list[Any] = []
            for item in _as_list(a) + _as_list(b):
                k = _key_of(item, key)
                if k is None:
                    k = id(item)
                if k not in merged:
                    order.append(k)
                    merged[k] = item
                else:
                    if isinstance(merged[k], dict) and isinstance(item, dict):
                        merged[k] = {**merged[k], **item}
                    else:
                        merged[k] = item
            data = [merged[k] for k in order]
        else:
            if isinstance(a, dict) and isinstance(b, dict):
                data = {**a, **b}
            else:
                data = _as_list(a) + _as_list(b)
        return {"output": MergedPayload(data=data, mode=mode, metadata={})}
