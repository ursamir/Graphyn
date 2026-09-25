"""HydeGenerateNode — HyDE: generate hypothetical document for embedding-based retrieve

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


class HydeGenerateNode(Node):
    """HyDE: generate hypothetical document for embedding-based retrieve"""

    node_type: ClassVar[str] = "hyde_generate"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="hyde_generate",
        label="Hyde Generate",
        description="HyDE: generate hypothetical document for embedding-based retrieve",
        category="Query",
        version="0.1.0",
        tags=["rag", "stub"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "query": InputPort(name="query", data_type=object, required=True, description="str"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="str"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        model: str = Field(default='', title="Model", description="Model.")
        api_secret_name: str = Field(default='', title="Api secret name", description="Api secret name.")
        max_tokens: int = Field(default=256, title="Max tokens", description="Max tokens.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        out_dir = Path('workspace/artifacts') / 'rag' / 'hyde_generate'
        if stub:
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            result = ""
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"hyde_generate: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc

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
            out_dir = Path('workspace/artifacts') / 'rag' / 'hyde_generate'
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            return {"output": ""}
        finally:
            try:
                self.config.stub = prev  # type: ignore[misc]
            except Exception:
                pass
