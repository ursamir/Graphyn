"""HitlApproveNode — Human-in-the-loop approval gate before promote/ship/destructive ops

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

log = logging.getLogger(__name__)


class HitlApproveNode(Node):
    """Human-in-the-loop approval gate before promote/ship/destructive ops"""

    node_type: ClassVar[str] = "hitl_approve"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="hitl_approve",
        label="Hitl Approve",
        description="Human-in-the-loop approval gate before promote/ship/destructive ops",
        category="Control",
        version="0.1.0",
        tags=["agents", "stub"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="Any"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "approved": OutputPort(name="approved", data_type=object, description="Any"),
        "rejected": OutputPort(name="rejected", data_type=object, description="Any"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        timeout_s: int = Field(default=3600, title="Timeout s", description="Timeout s.")
        approver_roles: list = Field(default_factory=list)
        reason_required: bool = Field(default=True, title="Reason required", description="Reason required.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        out_dir = Path('workspace/artifacts') / 'agents' / 'hitl_approve'
        if stub:
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            result = {
                "approved": None,
                "rejected": None,
            }
            return result
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"hitl_approve: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc

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
            out_dir = Path('workspace/artifacts') / 'agents' / 'hitl_approve'
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            return {
                "approved": None,
                "rejected": None,
            }
        finally:
            try:
                self.config.stub = prev  # type: ignore[misc]
            except Exception:
                pass
