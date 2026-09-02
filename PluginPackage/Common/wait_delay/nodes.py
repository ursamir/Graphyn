"""WaitDelayNode — sleep seconds (capped)."""
from __future__ import annotations

import importlib
import logging
import time
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
        _types = importlib.import_module("wait_delay.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

DelayReceipt = _types.DelayReceipt
log = logging.getLogger(__name__)


class WaitDelayNode(Node):
    node_type: ClassVar[str] = "wait_delay"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="wait_delay",
        label="Wait / Delay",
        description="Sleep for N seconds, capped by max_seconds (default 300).",
        category="Logic",
        version="1.0.0",
        tags=["wait", "delay", "workflow", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )
    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object | None, required=False, description="Passthrough payload"),
    }
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="Passthrough input"),
        "receipt": OutputPort(name="receipt", data_type=object, description="DelayReceipt"),
    }

    class Config(NodeConfig):
        seconds: float = 0.0
        max_seconds: float = 300.0

    def process(self, inputs):
        payload = inputs.get("input") if isinstance(inputs, dict) else inputs
        requested = float(self.config.seconds or 0.0)
        cap = float(self.config.max_seconds if self.config.max_seconds is not None else 300.0)
        if cap < 0:
            cap = 0.0
        slept = min(max(requested, 0.0), cap)
        if slept > 0:
            time.sleep(slept)
        receipt = DelayReceipt(
            slept_s=slept,
            requested_s=requested,
            capped=requested > cap,
            metadata={"max_seconds": cap},
        )
        return {"output": payload, "receipt": receipt}
