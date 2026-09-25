"""AgentLoopNode — Multi-step plan→tool→observe loop

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=True returns typed minimal outputs without heavy deps.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import ClassVar, Any
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
        _types = importlib.import_module("agent_loop.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

AgentResult = _types.AgentResult

log = logging.getLogger(__name__)


class AgentLoopNode(Node):
    """Multi-step plan→tool→observe loop"""

    node_type: ClassVar[str] = "agent_loop"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="agent_loop",
        label="Agent Loop",
        description="Multi-step plan→tool→observe loop",
        category="Agents",
        version="0.1.0",
        tags=["agents", "stub"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "goal": InputPort(name="goal", data_type=object, required=True, description="str"),
        "context": InputPort(name="context", data_type=object | None, required=False, description="Any optional"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="AgentResult NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        max_steps: int = Field(default=8, title="Max steps", description="Max steps.")
        model: str = Field(default='gpt-4o-mini', title="Model", description="Model.")
        api_secret_name: str = Field(default='OPENAI_API_KEY', title="Api secret name", description="Api secret name.")
        tool_allowlist: list = Field(default_factory=lambda: [])

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        out_dir = Path('workspace/artifacts') / 'agents' / 'agent_loop'
        if stub:
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            result = AgentResult()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"agent_loop: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc

    def _process_real(self, inputs: dict):
        """Override point for richer backends; default = stub path."""
        # Keep default identical to stub so unit tests stay offline.
        prev = self.config.stub
        object.__setattr__(self.config, 'stub', True) if hasattr(self.config, 'model_copy') else None
        try:
            self.config.stub = True  # type: ignore[misc]
        except Exception:
            pass
        try:
            # Re-enter stub branch
            out_dir = Path('workspace/artifacts') / 'agents' / 'agent_loop'
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            return {"output": AgentResult()}
        finally:
            try:
                self.config.stub = prev  # type: ignore[misc]
            except Exception:
                pass
