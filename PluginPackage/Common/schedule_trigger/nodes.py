"""ScheduleTriggerNode — source node; emits a tick so graphs run manually too."""
from __future__ import annotations

import importlib
import logging
import time
from typing import Any, ClassVar
from pydantic import Field

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import OutputPort

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("schedule_trigger.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

TickEvent = _types.TickEvent
log = logging.getLogger(__name__)


class ScheduleTriggerNode(Node):
    node_type: ClassVar[str] = "schedule_trigger"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="schedule_trigger",
        label="Schedule Trigger",
        description="Source node for cron/interval schedules. process() emits a tick payload for manual runs.",
        category="Input",
        version="1.0.0",
        tags=["schedule", "trigger", "workflow", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
        streaming_support=False,
        realtime_support=False,
    )
    input_ports: ClassVar[dict] = {}
    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="TickEvent"),
    }

    class Config(NodeConfig):
        cron: str = Field(default='', title="Cron", description="Cron.")
        interval_s: float = Field(default=0.0, title="Interval S", description="Interval S.")

    def process(self, inputs):
        return {"output": TickEvent(
            tick=True,
            cron=self.config.cron or "",
            interval_s=float(self.config.interval_s or 0.0),
            metadata={"ts": time.time(), "source_type": "timer"},
        )}
