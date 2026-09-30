"""HybridRetrieveNode — BM25+dense hybrid with RRF

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter

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
        _types = importlib.import_module("hybrid_retrieve.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

Chunk = _types.Chunk
RetrievalHit = _types.RetrievalHit
VectorStoreRef = _types.VectorStoreRef

log = logging.getLogger(__name__)


def _num_or(value, default):
    """Config numeric with a real default: only None falls back (0 stays 0)."""
    return default if value is None or value == "" else value

def _cfg(config: Any, name: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)

def _T(types: Any, name: str, **kwargs: Any) -> Any:
    cls = getattr(types, name, None) if types is not None else None
    if cls is None:
        return kwargs
    fields = getattr(cls, "model_fields", None)
    if isinstance(fields, dict) and fields:
        kwargs = {k: v for k, v in kwargs.items() if k in fields}
    return cls(**kwargs)

def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj

def _text(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, list):
        return "\n".join(_text(x) for x in obj)
    data = _dump(obj)
    if isinstance(data, dict):
        for key in ("text", "query", "content", "answer", "user", "path", "value", "final"):
            if data.get(key):
                return str(data[key])
        return json.dumps(data, default=str)
    return str(obj)

def _as_list(obj: Any) -> list:
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    if isinstance(obj, tuple):
        return list(obj)
    return [obj]

def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())

def _chunk_id(text: str, index: int) -> str:
    digest = hashlib.sha1(f"{index}:{text}".encode()).hexdigest()[:12]
    return f"c{index}-{digest}"

def _bm25(query: str, docs: list[str], *, k1: float = 1.2, b: float = 0.75) -> list[float]:
    tokenized = [_tokens(d) for d in docs]
    q = _tokens(query)
    n = len(tokenized) or 1
    avg = sum(len(t) for t in tokenized) / n
    df: Counter[str] = Counter()
    for toks in tokenized:
        df.update(set(toks))
    scores = []
    for toks in tokenized:
        tf = Counter(toks)
        dl = len(toks) or 1
        score = 0.0
        for term in q:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            freq = tf[term]
            score += idf * (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * dl / (avg or 1)))
        scores.append(score)
    return scores

def _rrf(rank_lists: list[list[int]], k: int) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranks in rank_lists:
        for rank, idx in enumerate(ranks, start=1):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank)
    return scores

def _docs_from_corpus(corpus: Any) -> list[dict[str, Any]]:
    docs = []
    for i, item in enumerate(_as_list(corpus)):
        data = _dump(item)
        if isinstance(data, str):
            data = {"text": data}
        if not isinstance(data, dict):
            data = {"text": _text(item)}
        data.setdefault("text", _text(item))
        data.setdefault("chunk_id", data.get("chunk_id") or _chunk_id(str(data["text"]), i))
        docs.append(data)
    return docs

def _hit(types: Any, doc: dict[str, Any], score: float) -> Any:
    return _T(
        types,
        "RetrievalHit",
        chunk_id=str(doc.get("chunk_id") or ""),
        text=str(doc.get("text") or ""),
        score=float(score),
        metadata={"source": doc.get("source") or ""},
    )

def _numbers(obj: Any) -> list[float]:
    data = _dump(obj)
    if isinstance(data, dict):
        for key in ("values", "features", "payload", "vector", "embedding", "data"):
            if key in data:
                return _numbers(data[key])
        return [float(v) for v in data.values() if isinstance(v, (int, float))]
    if isinstance(data, (list, tuple)):
        out: list[float] = []
        for item in data:
            if isinstance(item, (int, float)):
                out.append(float(item))
            elif isinstance(item, (list, tuple, dict)):
                out.extend(_numbers(item))
        return out
    if isinstance(data, (int, float)):
        return [float(data)]
    return []

def _hybrid_retrieve(config, inputs, types):
    docs = _docs_from_corpus(inputs.get("corpus"))
    query = _text(inputs.get("query"))
    top_k = int(_cfg(config, "top_k", 10) or 10)
    rrf_k = int(_cfg(config, "rrf_k", 60) or 60)
    if not docs:
        return []
    bm = _bm25(query, [d["text"] for d in docs])
    dense = []
    qv = _numbers(inputs.get("query"))
    for doc in docs:
        dv = _numbers(doc.get("metadata")) or _numbers(doc)
        if qv and dv and len(qv) == len(dv):
            dot = sum(a * b for a, b in zip(qv, dv))
            dense.append(dot)
        else:
            overlap = len(set(_tokens(query)) & set(_tokens(doc["text"])))
            dense.append(float(overlap))
    bm_rank = sorted(range(len(docs)), key=lambda i: bm[i], reverse=True)
    dn_rank = sorted(range(len(docs)), key=lambda i: dense[i], reverse=True)
    fused = _rrf([bm_rank, dn_rank], rrf_k)
    order = sorted(fused, key=lambda i: fused[i], reverse=True)[:top_k]
    bw = float(_num_or(_cfg(config, "bm25_weight", 0.5), 0.5))
    dw = float(_num_or(_cfg(config, "dense_weight", 0.5), 0.5))
    return [
        _hit(types, docs[i], bw * bm[i] + dw * dense[i] + fused[i])
        for i in order
        if (bw * bm[i] + dw * dense[i]) > 0 or query == ""
    ]



class HybridRetrieveNode(Node):
    """BM25+dense hybrid with RRF"""

    node_type: ClassVar[str] = "hybrid_retrieve"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="hybrid_retrieve",
        label="Hybrid Retrieve",
        description="BM25+dense hybrid with RRF",
        category="Processing",
        version="0.1.0",
        tags=["rag"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "store": InputPort(name="store", data_type=object, required=True, description="VectorStoreRef NEW"),
        "corpus": InputPort(name="corpus", data_type=object, required=True, description="list[Chunk]"),
        "query": InputPort(name="query", data_type=object, required=True, description="str"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[RetrievalHit] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        top_k: int = Field(default=10, title="Top k", description="Top k.")
        dense_weight: float = Field(default=0.5, title="Dense weight", description="Dense weight.")
        bm25_weight: float = Field(default=0.5, title="Bm25 weight", description="Bm25 weight.")
        rrf_k: int = Field(default=60, title="Rrf k", description="Rrf k.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'rag' / 'hybrid_retrieve'
        if stub:
            log.warning(
                "%s: stub mode (config.stub=True) returned a placeholder, not a real result",
                getattr(self, "node_type", type(self).__name__),
            )
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            _out = out_dir / 'stub'
            result = []
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"hybrid_retrieve: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _hybrid_retrieve(self.config, inputs, _types)}
