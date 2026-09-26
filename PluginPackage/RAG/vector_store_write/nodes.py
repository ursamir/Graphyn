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
            return {"output": self._write_pgvector(persist, collection, embeddings, chunks)}
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

    def _resolve_pg_dsn(self) -> str:
        """Resolve PGVECTOR DSN from named secret or env — never invent one."""
        import os

        secret_name = str(getattr(self.config, "pg_dsn_secret", None) or "PGVECTOR_DSN").strip() or "PGVECTOR_DSN"
        try:
            from app.core.secrets import resolve_secret

            dsn = (resolve_secret(secret_name) or "").strip()
        except Exception:
            dsn = ""
        if not dsn:
            dsn = (os.environ.get(secret_name) or os.environ.get("PGVECTOR_DSN") or "").strip()
        return dsn

    def _write_pgvector(self, persist: Path, collection: str, embeddings: list, chunks: list):
        """Opt-in pgvector backend. Fail-closed with needs-api when DSN/deps/extension missing.

        Default Wave-1 path remains chromadb|faiss. Do not point PGVECTOR_DSN at
        production sentinel Postgres unless it already has the vector extension and
        is intentionally dedicated for Graphyn embeddings.
        """
        from app.core.plugins.wave1_runtime import install_hint

        dsn = self._resolve_pg_dsn()
        secret_name = str(getattr(self.config, "pg_dsn_secret", None) or "PGVECTOR_DSN")
        hint = install_hint("rag", ["psycopg[binary]>=3.1"])
        if not dsn:
            raise RuntimeError(
                "vector_store_write: pgvector needs-api — set secret/env "
                f"{secret_name} to a dedicated Postgres DSN that already has the "
                "vector extension. Do not enable against production sentinel DBs. "
                "Default backends remain chromadb|faiss. " + hint
            )
        try:
            import psycopg  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "vector_store_write: pgvector client missing (psycopg). " + hint
            ) from exc

        rows = []
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
            rows.append((str(cid), text or f"doc-{i}", vec))

        if not rows:
            meta = {"backend": "pgvector", "collection": collection, "stub": False, "n_embeddings": 0}
            (persist / "index_meta.json").write_text(json.dumps(meta), encoding="utf-8")
            return VectorStoreRef(backend="pgvector", path=str(persist), collection=collection, metadata=meta)

        dim = int(len(rows[0][2]))
        table = "graphyn_embeddings"
        try:
            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM pg_available_extensions WHERE name = %s",
                        ("vector",),
                    )
                    if cur.fetchone() is None:
                        raise RuntimeError(
                            "vector extension not available on this Postgres "
                            "(needs pgvector image / package). " + hint
                        )
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                    cur.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {table} (
                            collection TEXT NOT NULL,
                            chunk_id TEXT NOT NULL,
                            document TEXT,
                            embedding vector({dim}),
                            PRIMARY KEY (collection, chunk_id)
                        )
                        """
                    )
                    for cid, doc, vec in rows:
                        lit = "[" + ",".join(str(float(x)) for x in vec) + "]"
                        cur.execute(
                            f"""
                            INSERT INTO {table} (collection, chunk_id, document, embedding)
                            VALUES (%s, %s, %s, %s::vector)
                            ON CONFLICT (collection, chunk_id) DO UPDATE
                              SET document = EXCLUDED.document,
                                  embedding = EXCLUDED.embedding
                            """,
                            (collection, cid, doc, lit),
                        )
                conn.commit()
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                "vector_store_write: pgvector needs-api — write failed "
                f"({type(exc).__name__}: {exc}). Keep backend=chromadb|faiss for "
                "Wave-1 defaults; use a dedicated vector-enabled DSN when ready. "
                + hint
            ) from exc

        meta = {
            "backend": "pgvector",
            "collection": collection,
            "stub": False,
            "n_embeddings": len(rows),
            "dim": dim,
            "table": table,
            "dsn_secret": secret_name,
        }
        (persist / "index_meta.json").write_text(json.dumps(meta), encoding="utf-8")
        log.info("vector_store_write pgvector wrote %d vectors collection=%s", len(rows), collection)
        return VectorStoreRef(backend="pgvector", path=str(persist), collection=collection, metadata=meta)
