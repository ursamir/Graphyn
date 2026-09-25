"""VectorStoreQueryNode — Dense vector similarity query

Default config.stub=True returns typed empty hits.
When stub=False, queries chromadb or faiss stores written by vector_store_write.
"""
from __future__ import annotations

import importlib
import json
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


def _query_vec(query: Any) -> list[float] | None:
    if query is None:
        return None
    if isinstance(query, str):
        return None  # needs embedder upstream
    emb = getattr(query, "embedding", None)
    if emb is None and isinstance(query, dict):
        emb = query.get("embedding")
    if emb is None and isinstance(query, (list, tuple)):
        emb = query
    if emb is None:
        return None
    if hasattr(emb, "tolist"):
        emb = emb.tolist()
    return [float(x) for x in list(emb)]


class VectorStoreQueryNode(Node):
    """Dense vector similarity query"""

    node_type: ClassVar[str] = "vector_store_query"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="vector_store_query",
        label="Vector Store Query",
        description="Dense vector similarity query",
        category="Processing",
        version="0.2.0",
        tags=["rag", "wave1"],
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
        backend: str = Field(default="chromadb", title="Backend", description="Backend.")
        persist_path: str = Field(default="workspace/artifacts/vectorstores/default", title="Persist path", description="Persist path.")

    def process(self, inputs=None, **kwargs):
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}
        k = int(getattr(self.config, "top_k", 5) or 5)
        stub = bool(getattr(self.config, "stub", True))
        if stub:
            return {"output": []}

        store = inputs.get("store")
        path = getattr(store, "path", None) or str(getattr(self.config, "persist_path", "") or "")
        backend = (getattr(store, "backend", None) or getattr(self.config, "backend", "chromadb") or "chromadb").lower()
        collection = getattr(store, "collection", None) or "default"
        qvec = _query_vec(inputs.get("query"))
        if qvec is None:
            raise RuntimeError(
                "vector_store_query: query must be EmbeddingVector (or list[float]); "
                "string queries need text_embed upstream when stub=False"
            )
        persist = Path(path)
        if backend in ("chroma", "chromadb"):
            hits = self._query_chromadb(persist, collection, qvec, k)
        elif backend == "faiss":
            hits = self._query_faiss(persist, qvec, k)
        else:
            raise RuntimeError(f"vector_store_query: unsupported backend {backend!r}")
        return {"output": hits}

    def _query_chromadb(self, persist: Path, collection: str, qvec: list[float], k: int):
        try:
            import chromadb  # type: ignore
        except ImportError as exc:
            from app.core.plugins.wave1_runtime import install_hint

            raise ImportError(install_hint("rag", ["chromadb>=0.4"])) from exc
        client = chromadb.PersistentClient(path=str(persist / "chroma"))
        coll = client.get_or_create_collection(name=collection)
        res = coll.query(query_embeddings=[qvec], n_results=max(1, k))
        hits = []
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        for i, cid in enumerate(ids):
            dist = float(dists[i]) if i < len(dists) else 0.0
            score = 1.0 / (1.0 + dist)
            hits.append(
                RetrievalHit(
                    chunk_id=str(cid),
                    text=str(docs[i]) if i < len(docs) else "",
                    score=score,
                    metadata=dict(metas[i]) if i < len(metas) and metas[i] else {"backend": "chromadb"},
                )
            )
        return hits

    def _query_faiss(self, persist: Path, qvec: list[float], k: int):
        try:
            import faiss  # type: ignore
            import numpy as np  # type: ignore
        except ImportError as exc:
            from app.core.plugins.wave1_runtime import install_hint

            raise ImportError(install_hint("rag", ["faiss-cpu>=1.7"])) from exc
        index_path = persist / "index.faiss"
        if not index_path.is_file():
            return []
        index = faiss.read_index(str(index_path))
        q = np.asarray([qvec], dtype="float32")
        faiss.normalize_L2(q)
        scores, idxs = index.search(q, max(1, k))
        texts = []
        tp = persist / "texts.json"
        if tp.is_file():
            texts = json.loads(tp.read_text(encoding="utf-8"))
        hits = []
        for score, idx in zip(scores[0].tolist(), idxs[0].tolist()):
            if idx < 0:
                continue
            hits.append(
                RetrievalHit(
                    chunk_id=f"faiss-{idx}",
                    text=str(texts[idx]) if idx < len(texts) else "",
                    score=float(score),
                    metadata={"backend": "faiss", "i": idx},
                )
            )
        return hits
