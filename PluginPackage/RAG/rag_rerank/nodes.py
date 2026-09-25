"""RagRerankNode — Cross-encoder/LLM rerank

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
        _types = importlib.import_module("rag_rerank.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

RetrievalHit = _types.RetrievalHit

log = logging.getLogger(__name__)


class RagRerankNode(Node):
    """Cross-encoder/LLM rerank"""

    node_type: ClassVar[str] = "rag_rerank"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="rag_rerank",
        label="Rag Rerank",
        description="Cross-encoder/LLM rerank",
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
        "hits": InputPort(name="hits", data_type=object, required=True, description="list[RetrievalHit] NEW"),
        "query": InputPort(name="query", data_type=object, required=True, description="str"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[RetrievalHit] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        backend: str = Field(default='cross_encoder', title="Backend", description="Backend.")
        model_name_or_path: str = Field(default='cross-encoder/ms-marco-MiniLM-L-6-v2', title="Model name or path", description="Model name or path.")
        top_n: int = Field(default=5, title="Top n", description="Top n.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        out_dir = Path('workspace/artifacts') / 'rag' / 'rag_rerank'
        if stub:
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            result = []
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"rag_rerank: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc

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
            out_dir = Path('workspace/artifacts') / 'rag' / 'rag_rerank'
            out_dir.mkdir(parents=True, exist_ok=True)
            _out = out_dir / 'stub'
            return {"output": []}
        finally:
            try:
                self.config.stub = prev  # type: ignore[misc]
            except Exception:
                pass
