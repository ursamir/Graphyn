"""ErrorCatchNode — pass input through; emit errors on the error port.

When config.on_error is continue_error_output, NodeExecutor routes process()
failures to on_error_port instead of failing the DAG.
"""
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
        _types = importlib.import_module("error_catch.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

ErrorPayload = _types.ErrorPayload
log = logging.getLogger(__name__)


class ErrorCatchNode(Node):
    node_type: ClassVar[str] = "error_catch"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="error_catch",
        label="Error Catch",
        description="Passthrough with error port. Pair with on_error=continue_error_output.",
        category="Logic",
        version="1.0.0",
        tags=["error", "catch", "workflow", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )
    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object | None, required=False, description="Happy-path payload"),
        "error": InputPort(name="error", data_type=object | None, required=False, description="Upstream error artifact"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="Passthrough input"),
        "error": OutputPort(name="error", data_type=object, description="Error payload if present or on failure"),
    }

    class Config(NodeConfig):
        on_error: str = "continue_error_output"
        on_error_port: str = "error"
        fail_on_error_input: bool = False

    def process(self, inputs):
        payload = inputs.get("input") if isinstance(inputs, dict) else inputs
        err_in = inputs.get("error") if isinstance(inputs, dict) else None
        if err_in is not None:
            if self.config.fail_on_error_input:
                raise RuntimeError(f"ErrorCatchNode: upstream error: {err_in}")
            wrapped = err_in
            if not isinstance(err_in, dict):
                wrapped = {"ok": False, "message": str(err_in), "payload": err_in}
            return {"output": None, "error": wrapped}
        if self.config.fail_on_error_input is False and payload is None and err_in is None:
            return {
                "output": None,
                "error": ErrorPayload(ok=True, message="", payload=None, metadata={"empty": True}),
            }
        return {
            "output": payload,
            "error": None,
        }
