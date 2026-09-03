"""IfSwitchNode — route payload to true/false (and optional named cases)."""
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
        _types = importlib.import_module("if_switch.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

BranchResult = _types.BranchResult

log = logging.getLogger(__name__)


def _as_dict(payload: Any) -> dict:
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return payload
    if hasattr(payload, "model_dump"):
        try:
            dumped = payload.model_dump()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass
    return {"value": payload}


def _jsonpath(payload: Any, path: str) -> Any:
    path = (path or "").strip()
    if not path:
        return payload
    if path.startswith("$"):
        path = path[1:]
    if path.startswith("."):
        path = path[1:]
    cur = payload
    if not path:
        return cur
    import re
    tokens = re.findall(r"[^.\[\]]+|\[\d+\]", path)
    for tok in tokens:
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
                cur = getattr(cur, tok, None)
            if cur is None:
                return None
    return cur


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, (str, list, dict, tuple, set)):
        return bool(value)
    return True


class IfSwitchNode(Node):
    """Evaluate expression/JSONPath and emit on true or false (plus cases)."""

    node_type: ClassVar[str] = "if_switch"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="if_switch",
        label="IF Switch",
        description="Branch on a condition expression or JSONPath of the payload.",
        category="Logic",
        version="1.0.0",
        tags=["logic", "branch", "workflow", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=object | None,
            cardinality="single",
            required=False,
            description="Any payload",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "true": OutputPort(name="true", data_type=object, description="Payload when condition is true"),
        "false": OutputPort(name="false", data_type=object, description="Payload when condition is false"),
        "cases": OutputPort(name="cases", data_type=object, description="Named case matches dict"),
        "output": OutputPort(name="output", data_type=object, description="BranchResult summary"),
    }

    class Config(NodeConfig):
        expression: str = Field(default='', title="Expression", description="Expression.")
        jsonpath: str = Field(default='', title="Jsonpath", description="Jsonpath.")
        cases: list = Field(default=[], title="Cases", description="Cases.")

    def process(self, inputs):
        payload = inputs.get("input") if isinstance(inputs, dict) else inputs
        as_dict = _as_dict(payload)
        matched = False
        expr = (self.config.expression or "").strip()
        path = (self.config.jsonpath or "").strip()
        if expr:
            from app.core.conditions import evaluate_condition
            matched = bool(evaluate_condition(expr, as_dict))
        elif path:
            matched = _truthy(_jsonpath(payload if payload is not None else as_dict, path))
        else:
            matched = _truthy(payload)

        case_hits: dict[str, Any] = {}
        for raw in list(self.config.cases or []):
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            cexpr = str(raw.get("expression") or "").strip()
            if not name:
                continue
            hit = False
            if cexpr:
                from app.core.conditions import evaluate_condition
                hit = bool(evaluate_condition(cexpr, as_dict))
            if hit:
                case_hits[name] = payload

        result = BranchResult(
            matched=matched,
            branch="true" if matched else "false",
            payload=payload,
            metadata={"cases": sorted(case_hits.keys())},
        )
        return {
            "true": payload if matched else None,
            "false": None if matched else payload,
            "cases": case_hits,
            "output": result,
        }
