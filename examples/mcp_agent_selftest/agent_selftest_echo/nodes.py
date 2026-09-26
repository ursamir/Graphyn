"""AgentSelftestEchoNode — stamp + echo payload for MCP install self-test."""
from __future__ import annotations

import importlib
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
        _types = importlib.import_module("agent_selftest_echo.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

EchoReceipt = _types.EchoReceipt


class AgentSelftestEchoNode(Node):
    node_type: ClassVar[str] = "agent_selftest_echo"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="agent_selftest_echo",
        label="Agent Selftest Echo",
        description="Echo input with a stamped message (MCP self-test plugin).",
        category="Utility",
        version="0.1.0",
        tags=["selftest", "echo", "mcp", "utility"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
    )
    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=object | None,
            required=False,
            description="Arbitrary payload to echo",
        ),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="Echoed payload dict"),
        "receipt": OutputPort(name="receipt", data_type=object, description="EchoReceipt"),
    }

    class Config(NodeConfig):
        message: str = Field(
            default="agent-selftest-echo",
            title="Message",
            description="Stamp prefixed onto echoed payload.",
        )

    def process(self, inputs):
        payload = inputs.get("input") if isinstance(inputs, dict) else inputs
        if isinstance(payload, dict):
            keys = sorted(str(k) for k in payload.keys())
            body: dict[str, Any] = dict(payload)
        else:
            keys = []
            body = {"value": payload}
        msg = str(self.config.message or "agent-selftest-echo")
        body = {"message": msg, **body}
        receipt = EchoReceipt(message=msg, input_keys=keys, metadata={"plugin": "agent-selftest-echo"})
        return {"output": body, "receipt": receipt}
