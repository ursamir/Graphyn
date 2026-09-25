"""KgLightExtractNode — Light entity/relation extract

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
        _types = importlib.import_module("kg_light_extract.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

Chunk = _types.Chunk
KnowledgeGraphFragment = _types.KnowledgeGraphFragment
RagAnswer = _types.RagAnswer

log = logging.getLogger(__name__)


class KgLightExtractNode(Node):
    """Light entity/relation extract"""

    node_type: ClassVar[str] = "kg_light_extract"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="kg_light_extract",
        label="Kg Light Extract",
        description="Light entity/relation extract",
        category="Processing",
        version="0.1.0",
        tags=["rag", "stub"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="list[Chunk]|RagAnswer NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="KnowledgeGraphFragment NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        backend: str = Field(default='llm', title="Backend", description="Backend.")
        schema: dict = Field(default_factory=dict)
        api_secret_name: str = Field(default='OPENAI_API_KEY', title="Api secret name", description="Api secret name.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        out_dir = Path('workspace/artifacts') / 'rag' / 'kg_light_extract'
        if stub:
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            result = KnowledgeGraphFragment()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"kg_light_extract: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc

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
            out_dir = Path('workspace/artifacts') / 'rag' / 'kg_light_extract'
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            return {"output": KnowledgeGraphFragment()}
        finally:
            try:
                self.config.stub = prev  # type: ignore[misc]
            except Exception:
                pass
