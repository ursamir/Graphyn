"""VectorStoreWriteNode — Write to faiss/chroma/pgvector

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
        _types = importlib.import_module("vector_store_write.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

Chunk = _types.Chunk
EmbeddingVector = _types.EmbeddingVector
VectorStoreRef = _types.VectorStoreRef

log = logging.getLogger(__name__)


class VectorStoreWriteNode(Node):
    """Write to faiss/chroma/pgvector"""

    node_type: ClassVar[str] = "vector_store_write"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="vector_store_write",
        label="Vector Store Write",
        description="Write to faiss/chroma/pgvector",
        category="Output",
        version="0.1.0",
        tags=["rag", "stub"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "embeddings": InputPort(name="embeddings", data_type=object, required=True, description="list[EmbeddingVector]"),
        "chunks": InputPort(name="chunks", data_type=object | None, required=False, description="list[Chunk] optional"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="VectorStoreRef NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        backend: str = Field(default='faiss', title="Backend", description="Backend.")
        persist_path: str = Field(default='workspace/artifacts/vectorstores/default', title="Persist path", description="Persist path.")
        collection: str = Field(default='default', title="Collection", description="Collection.")
        pg_dsn_secret: str = Field(default='PGVECTOR_DSN', title="Pg dsn secret", description="Pg dsn secret.")


    def process(self, inputs=None, **kwargs):
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}
        persist = Path(getattr(self.config, "persist_path", None) or "workspace/artifacts/vectorstores/default")
        persist.mkdir(parents=True, exist_ok=True)
        backend = str(getattr(self.config, "backend", "faiss") or "faiss")
        collection = str(getattr(self.config, "collection", "default") or "default")
        meta = {
            "backend": backend,
            "collection": collection,
            "stub": bool(getattr(self.config, "stub", True)),
            "n_embeddings": len(inputs.get("embeddings") or []) if isinstance(inputs.get("embeddings"), list) else 0,
        }
        (persist / "index_meta.json").write_text(__import__("json").dumps(meta), encoding="utf-8")
        return {"output": VectorStoreRef(backend=backend, path=str(persist), collection=collection, metadata=meta)}

