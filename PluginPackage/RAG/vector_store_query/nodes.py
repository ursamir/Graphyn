"""VectorStoreQueryNode — Dense vector similarity query

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
        _types = importlib.import_module("vector_store_query.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

EmbeddingVector = _types.EmbeddingVector
RetrievalHit = _types.RetrievalHit
VectorStoreRef = _types.VectorStoreRef

log = logging.getLogger(__name__)


class VectorStoreQueryNode(Node):
    """Dense vector similarity query"""

    node_type: ClassVar[str] = "vector_store_query"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="vector_store_query",
        label="Vector Store Query",
        description="Dense vector similarity query",
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
        "store": InputPort(name="store", data_type=object, required=True, description="VectorStoreRef NEW"),
        "query": InputPort(name="query", data_type=object, required=True, description="str|EmbeddingVector"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[RetrievalHit] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        top_k: int = Field(default=5, title="Top k", description="Top k.")
        backend: str = Field(default='faiss', title="Backend", description="Backend.")
        persist_path: str = Field(default='workspace/artifacts/vectorstores/default', title="Persist path", description="Persist path.")


    def process(self, inputs=None, **kwargs):
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}
        k = int(getattr(self.config, "top_k", 5) or 5)
        # Honesty stub: empty retrieval hits with typed objects
        hits = [RetrievalHit(chunk_id=f"stub-{i}", text="", score=0.0, metadata={"stub": True}) for i in range(0)]
        return {"output": hits[:k]}

