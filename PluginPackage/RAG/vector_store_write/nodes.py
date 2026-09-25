"""VectorStoreWriteNode — Write to faiss/chroma/pgvector

Default config.stub=True returns typed minimal outputs without heavy deps.
When stub=False, uses chromadb or faiss-cpu from the Wave-1 RAG venv.
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
        _types = importlib.import_module("vector_store_write.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

Chunk = _types.Chunk
EmbeddingVector = _types.EmbeddingVector
VectorStoreRef = _types.VectorStoreRef

log = logging.getLogger(__name__)


def _as_list(val: Any) -> list:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val]


def _vec(item: Any) -> list[float]:
    emb = getattr(item, "embedding", None)
    if emb is None and isinstance(item, dict):
        emb = item.get("embedding")
    if emb is None:
        return []
    if hasattr(emb, "tolist"):
        emb = emb.tolist()
    return [float(x) for x in list(emb)]


class VectorStoreWriteNode(Node):
    """Write to faiss/chroma/pgvector"""

    node_type: ClassVar[str] = "vector_store_write"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="vector_store_write",
        label="Vector Store Write",
        description="Write to faiss/chroma/pgvector",
        category="Output",
        version="0.2.0",
        tags=["rag", "wave1"],
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
        backend: str = Field(default="chromadb", title="Backend", description="Backend: chromadb|faiss|pgvector.")
        persist_path: str = Field(default="workspace/artifacts/vectorstores/default", title="Persist path", description="Persist path.")
        collection: str = Field(default="default", title="Collection", description="Collection.")
        pg_dsn_secret: str = Field(default="PGVECTOR_DSN", title="Pg dsn secret", description="Pg dsn secret.")

    def process(self, inputs=None, **kwargs):
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}
        persist = Path(getattr(self.config, "persist_path", None) or "workspace/artifacts/vectorstores/default")
        persist.mkdir(parents=True, exist_ok=True)
        backend = str(getattr(self.config, "backend", "chromadb") or "chromadb").lower()
        collection = str(getattr(self.config, "collection", "default") or "default")
        stub = bool(getattr(self.config, "stub", True))
        embeddings = _as_list(inputs.get("embeddings"))
        chunks = _as_list(inputs.get("chunks"))

        if stub:
            meta = {
                "backend": backend,
                "collection": collection,
                "stub": True,
                "n_embeddings": len(embeddings),
            }
            (persist / "index_meta.json").write_text(json.dumps(meta), encoding="utf-8")
            return {"output": VectorStoreRef(backend=backend, path=str(persist), collection=collection, metadata=meta)}

        if backend in ("chroma", "chromadb"):
            return {"output": self._write_chromadb(persist, collection, embeddings, chunks)}
        if backend == "faiss":
            return {"output": self._write_faiss(persist, collection, embeddings, chunks)}
        if backend in ("pgvector", "pg"):
            from app.core.plugins.wave1_runtime import install_hint

            raise RuntimeError(
                "vector_store_write: pgvector backend needs-api (DSN wiring). "
                + install_hint("rag", ["psycopg", "pgvector"])
            )
        raise RuntimeError(f"vector_store_write: unknown backend {backend!r}")

    def _write_chromadb(self, persist: Path, collection: str, embeddings: list, chunks: list):
        try:
            import chromadb  # type: ignore
        except ImportError as exc:
            from app.core.plugins.wave1_runtime import install_hint

            raise ImportError(install_hint("rag", ["chromadb>=0.4"])) from exc

        client = chromadb.PersistentClient(path=str(persist / "chroma"))
        coll = client.get_or_create_collection(name=collection)
        ids, docs, embs, metas = [], [], [], []
        for i, item in enumerate(embeddings):
            vec = _vec(item)
            if not vec:
                continue
            meta = getattr(item, "metadata", None)
            cid = meta.get("chunk_id") if isinstance(meta, dict) else None
            if not cid:
                cid = f"emb-{i}"
            text = ""
            if i < len(chunks):
                text = getattr(chunks[i], "text", None) or ""
                if not cid or str(cid).startswith("emb-"):
                    cid = getattr(chunks[i], "chunk_id", None) or cid
            ids.append(str(cid))
            docs.append(text or f"doc-{i}")
            embs.append(vec)
            metas.append({"i": i, "source": str(getattr(item, "source_path", "") or "")})
        if ids:
            coll.upsert(ids=ids, embeddings=embs, documents=docs, metadatas=metas)
        meta = {
            "backend": "chromadb",
            "collection": collection,
            "stub": False,
            "n_embeddings": len(ids),
            "dim": len(embs[0]) if embs else 0,
        }
        (persist / "index_meta.json").write_text(json.dumps(meta), encoding="utf-8")
        log.info("vector_store_write chromadb wrote %d vectors → %s", len(ids), persist)
        return VectorStoreRef(backend="chromadb", path=str(persist), collection=collection, metadata=meta)

    def _write_faiss(self, persist: Path, collection: str, embeddings: list, chunks: list):
        try:
            import faiss  # type: ignore
            import numpy as np  # type: ignore
        except ImportError as exc:
            from app.core.plugins.wave1_runtime import install_hint

            raise ImportError(install_hint("rag", ["faiss-cpu>=1.7", "numpy"])) from exc

        rows = [_vec(item) for item in embeddings]
        rows = [r for r in rows if r]
        if not rows:
            meta = {"backend": "faiss", "collection": collection, "stub": False, "n_embeddings": 0}
            (persist / "index_meta.json").write_text(json.dumps(meta), encoding="utf-8")
            return VectorStoreRef(backend="faiss", path=str(persist), collection=collection, metadata=meta)
        mat = np.asarray(rows, dtype="float32")
        index = faiss.IndexFlatIP(mat.shape[1])
        # L2-normalize for cosine-ish IP
        faiss.normalize_L2(mat)
        index.add(mat)
        faiss.write_index(index, str(persist / "index.faiss"))
        texts = []
        for i, _ in enumerate(rows):
            if i < len(chunks):
                texts.append(getattr(chunks[i], "text", None) or "")
            else:
                texts.append("")
        (persist / "texts.json").write_text(json.dumps(texts), encoding="utf-8")
        meta = {
            "backend": "faiss",
            "collection": collection,
            "stub": False,
            "n_embeddings": int(mat.shape[0]),
            "dim": int(mat.shape[1]),
        }
        (persist / "index_meta.json").write_text(json.dumps(meta), encoding="utf-8")
        log.info("vector_store_write faiss wrote %d vectors → %s", mat.shape[0], persist)
        return VectorStoreRef(backend="faiss", path=str(persist), collection=collection, metadata=meta)
