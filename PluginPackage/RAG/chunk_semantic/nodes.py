"""ChunkSemanticNode — Semantic breakpoint chunker

Default config.stub=True returns empty chunks.
When stub=False, embeds sentences with sentence-transformers (Wave-1 RAG venv)
and splits on cosine-distance breakpoints.
"""
from __future__ import annotations

import importlib
import logging
import re
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
        _types = importlib.import_module("chunk_semantic.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

Chunk = _types.Chunk
RawDocument = _types.RawDocument

log = logging.getLogger(__name__)

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _as_list(val: Any) -> list:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val]


def _doc_text(item: Any) -> tuple[str, str]:
    if isinstance(item, str):
        return item, ""
    text = getattr(item, "text", None)
    source = getattr(item, "source", None) or getattr(item, "path", None) or ""
    if text is None and isinstance(item, dict):
        text = item.get("text") or item.get("content") or ""
        source = item.get("source") or item.get("path") or source
    return str(text or ""), str(source or "")


class ChunkSemanticNode(Node):
    """Semantic breakpoint chunker"""

    node_type: ClassVar[str] = "chunk_semantic"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="chunk_semantic",
        label="Chunk Semantic",
        description="Semantic breakpoint chunker",
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
        "input": InputPort(name="input", data_type=object, required=True, description="list[RawDocument] NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[Chunk]"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        embedding_model: str = Field(default='sentence-transformers/all-MiniLM-L6-v2', title="Embedding model", description="Embedding model.")
        breakpoint_percentile: float = Field(default=95.0, title="Breakpoint percentile", description="Breakpoint percentile.")

    def process(self, inputs=None, **kwargs):
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', True))
        if stub:
            return {"output": []}
        return self._process_real(inputs)

    def _process_real(self, inputs: dict):
        try:
            from app.core.plugins.wave1_runtime import force_cpu_torch_env

            force_cpu_torch_env()
            from sentence_transformers import SentenceTransformer  # type: ignore
            import numpy as np  # type: ignore
        except ImportError as exc:
            from app.core.plugins.wave1_runtime import install_hint

            raise ImportError(install_hint("rag", ["sentence-transformers>=2.2", "numpy"])) from exc

        docs = _as_list(inputs.get("input") or inputs.get("documents"))
        model_name = str(getattr(self.config, "embedding_model", None) or "sentence-transformers/all-MiniLM-L6-v2")
        pct = float(getattr(self.config, "breakpoint_percentile", 95.0) or 95.0)
        model = SentenceTransformer(model_name)
        out: list = []
        chunk_i = 0
        for doc in docs:
            text, source = _doc_text(doc)
            sents = [s.strip() for s in _SENT_SPLIT.split(text) if s and s.strip()]
            if not sents:
                if text.strip():
                    sents = [text.strip()]
                else:
                    continue
            if len(sents) == 1:
                out.append(Chunk(text=sents[0], source=source, chunk_id=f"sem-{chunk_i}", metadata={"backend": "semantic"}))
                chunk_i += 1
                continue
            embs = model.encode(sents, normalize_embeddings=True)
            embs = np.asarray(embs, dtype="float32")
            # cosine distance between consecutive sentences
            dists = []
            for i in range(len(embs) - 1):
                dist = float(1.0 - float(np.dot(embs[i], embs[i + 1])))
                dists.append(dist)
            threshold = float(np.percentile(np.asarray(dists, dtype="float32"), pct)) if dists else 0.0
            buf: list[str] = [sents[0]]
            for i, sent in enumerate(sents[1:], start=0):
                if dists[i] >= threshold and buf:
                    out.append(Chunk(text=" ".join(buf), source=source, chunk_id=f"sem-{chunk_i}", metadata={"backend": "semantic", "breakpoint": dists[i]}))
                    chunk_i += 1
                    buf = [sent]
                else:
                    buf.append(sent)
            if buf:
                out.append(Chunk(text=" ".join(buf), source=source, chunk_id=f"sem-{chunk_i}", metadata={"backend": "semantic"}))
                chunk_i += 1
        log.info("chunk_semantic produced %d chunks from %d docs", len(out), len(docs))
        return {"output": out}
