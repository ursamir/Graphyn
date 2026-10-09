"""MergeNode — append or combine_by_key for two list/dict inputs."""
from __future__ import annotations

import importlib
import logging
from typing import Any, ClassVar, Literal
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
        description="Append inputs into a list, combine list items by key, or merge two objects with explicit conflict handling (never silently overwrites).",
        category="Transform",
        version="1.1.0",
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
        mode: Literal["append", "combine_by_key", "merge_dicts"] = Field(default='append', title="Mode", description="append: concatenate a and b into one list (two objects become a two-item list — nothing is overwritten). combine_by_key: correlate list items on the merge key. merge_dicts: shallow-merge two objects; key conflicts follow on_conflict.")
        key: str = Field(default='id', title="Merge key", description="Field used to correlate items in combine_by_key mode.")
        on_conflict: Literal["error", "prefer_a", "prefer_b"] = Field(default='error', title="On key conflict", description="merge_dicts only: what to do when both objects set the same key to different values. error (default) fails the node; prefer_a / prefer_b keep that side. Conflicts are always listed in the output metadata.")

    def process(self, inputs):
        from app.core.nodes.payload import unwrap_payload

        # F19 (F-06): operate on payloads, not on upstream wrappers.
        a = unwrap_payload(inputs.get("a")) if isinstance(inputs, dict) else None
        b = unwrap_payload(inputs.get("b")) if isinstance(inputs, dict) else None
        mode = (self.config.mode or "append").strip().lower()
        meta: dict[str, Any] = {}
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
        elif mode == "merge_dicts":
            if a is None:
                a = {}
            if b is None:
                b = {}
            if not isinstance(a, dict) or not isinstance(b, dict):
                raise ValueError(
                    "merge: merge_dicts needs two objects; got "
                    f"{type(a).__name__} and {type(b).__name__}. Use append for lists."
                )
            conflicts = sorted(str(k) for k in a.keys() & b.keys() if a[k] != b[k])
            policy = (self.config.on_conflict or "error").strip().lower()
            if conflicts and policy == "error":
                raise ValueError(
                    f"merge: both inputs set different values for {conflicts}. "
                    "Set on_conflict to prefer_a or prefer_b, or rename the fields first."
                )
            data = {**b, **a} if policy == "prefer_a" else {**a, **b}
            meta = {"conflicts": conflicts, "on_conflict": policy}
        else:
            # F19 (F-25): append never overwrites — two objects become two items.
            data = _as_list(a) + _as_list(b)
        return {"output": MergedPayload(data=data, mode=mode, metadata=meta)}
