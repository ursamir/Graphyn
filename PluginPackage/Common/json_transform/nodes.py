"""JsonTransformNode — dotted-path / simple JSONPath extract (no exec)."""
from __future__ import annotations

import importlib
import logging
import re
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
        _types = importlib.import_module("json_transform.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

JsonDocument = _types.JsonDocument
log = logging.getLogger(__name__)

_TOKEN = re.compile(r"[^.\[\]]+|\[\d+\]")


def _get_path(obj: Any, path: str) -> Any:
    path = (path or "").strip()
    if not path or path == "$":
        return obj
    if path.startswith("$"):
        path = path[1:]
    if path.startswith("."):
        path = path[1:]
    cur = obj
    for tok in _TOKEN.findall(path):
        if tok.startswith("[") and tok.endswith("]"):
            idx = int(tok[1:-1])
            if isinstance(cur, (list, tuple)) and 0 <= idx < len(cur):
                cur = cur[idx]
            else:
                return None
        else:
            if isinstance(cur, dict):
                cur = cur.get(tok)
            else:
                return None
    return cur


def _set_path(root: dict, path: str, value: Any) -> None:
    path = path[1:] if path.startswith("$") else path
    path = path[1:] if path.startswith(".") else path
    parts = [p for p in path.split(".") if p and not p.startswith("[")]
    if not parts:
        return
    cur: Any = root
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


class JsonTransformNode(Node):
    node_type: ClassVar[str] = "json_transform"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="json_transform",
        label="JSON Transform",
        description="Extract and remap fields using dotted paths or simple JSONPath. No exec.",
        category="Transform",
        version="1.0.0",
        tags=["json", "transform", "workflow", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
    )
    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object | None, required=False, description="JSON-like payload"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="JsonDocument"),
    }

    class Config(NodeConfig):
        mappings: list = Field(default=[], title="Mappings", description="Mappings.")
        pick: list = Field(default=[], title="Pick", description="Pick.")
        path: str = Field(default='', title="Path", description="Path under workspace/datasets/input (or another workspace path).")

    def process(self, inputs):
        payload = inputs.get("input") if isinstance(inputs, dict) else inputs
        mappings = list(self.config.mappings or [])
        pick = list(self.config.pick or [])
        single = (self.config.path or "").strip()
        if single and not mappings and not pick:
            return {"output": JsonDocument(data=_get_path(payload, single), metadata={"path": single})}
        out: dict[str, Any] = {}
        for m in mappings:
            if not isinstance(m, dict):
                continue
            src = str(m.get("from") or m.get("src") or "")
            dst = str(m.get("to") or m.get("dst") or src)
            if not src or not dst:
                continue
            _set_path(out, dst, _get_path(payload, src))
        for p in pick:
            key = str(p)
            out[key.split(".")[-1]] = _get_path(payload, key)
        if not mappings and not pick:
            out = payload if isinstance(payload, dict) else {"value": payload}
        return {"output": JsonDocument(data=out, metadata={})}
