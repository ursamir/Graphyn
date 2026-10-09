"""WaitDelayNode — sleep seconds (capped)."""
from __future__ import annotations

import importlib
import logging
import time
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
        _types = importlib.import_module("wait_delay.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

DelayReceipt = _types.DelayReceipt
log = logging.getLogger(__name__)

_STEP_S = 0.25  # cancel-check granularity


class WaitDelayNode(Node):
    node_type: ClassVar[str] = "wait_delay"
    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="wait_delay",
        label="Wait / Delay",
        description="Sleep for N seconds, capped by max_seconds (default 300). Stops early when the run is cancelled.",
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
        "receipt": OutputPort(name="receipt", data_type=DelayReceipt, description="DelayReceipt"),
    }

    class Config(NodeConfig):
        seconds: float = Field(default=0.0, title="Seconds", description="How long to wait before forwarding the payload.")
        max_seconds: float = Field(default=300.0, title="Max seconds", description="Hard cap on delay (safety).")

    def process(self, inputs):
        payload = inputs.get("input") if isinstance(inputs, dict) else inputs
        requested = float(self.config.seconds or 0.0)
        cap = float(self.config.max_seconds if self.config.max_seconds is not None else 300.0)
        if cap < 0:
            cap = 0.0
        target = min(max(requested, 0.0), cap)
        slept = self._sleep_cancellable(target)
        receipt = DelayReceipt(
            slept_s=slept,
            requested_s=requested,
            capped=requested > cap,
            metadata={"max_seconds": cap, "target_s": target},
        )
        return {"output": payload, "receipt": receipt}

    def _run_cancelled(self) -> bool:
        """True when the owning run (``self._run_id``) was cancelled (in-process or durable marker)."""
        run_id = str(getattr(self, "_run_id", "") or "")
        if not run_id:
            return False
        try:
            from app.core.runs.run_control import get_active_run

            run = get_active_run(run_id)
            return bool(run is not None and run.is_cancelled)
        except Exception:
            return False

    def _sleep_cancellable(self, seconds: float) -> float:
        """Sleep in <=0.25 s increments, stopping early if the run is cancelled.

        Raises ``RuntimeError`` on cancellation so downstream nodes do not run
        with a delay that never completed (the orchestrator then records the
        run as cancelled).
        """
        if seconds <= 0:
            return 0.0
        start = time.monotonic()
        deadline = start + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return seconds
            if self._run_cancelled():
                raise RuntimeError(
                    f"wait_delay: run cancelled after {time.monotonic() - start:.2f}s of {seconds:.2f}s"
                )
            time.sleep(min(_STEP_S, remaining))
