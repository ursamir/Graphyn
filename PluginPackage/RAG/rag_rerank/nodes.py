"""RagRerankNode — Cross-encoder/LLM rerank

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
from typing import ClassVar, Any, Literal
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

def _hybrid_like_rerank(config, inputs, types):
    hits = _docs_from_corpus(inputs.get("hits"))
    query = _text(inputs.get("query"))
    top_n = int(_cfg(config, "top_n", _cfg(config, "max_chars", 5)) or 5)
    scores = _bm25(query, [h["text"] for h in hits]) if hits else []
    order = sorted(range(len(hits)), key=lambda i: scores[i], reverse=True)[:top_n]
    return [_hit(types, hits[i], scores[i]) for i in order]



def _cross_encoder_rerank(config, inputs, types):
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
    except ImportError as exc:
        raise ImportError("sentence-transformers>=2.2 (CrossEncoder) required for backend=cross_encoder") from exc
    hits = _docs_from_corpus(inputs.get("hits"))
    query = _text(inputs.get("query"))
    top_n = int(_cfg(config, "top_n", 5) or 5)
    if not hits:
        return []
    model = CrossEncoder(str(_cfg(config, "model_name_or_path", "cross-encoder/ms-marco-MiniLM-L-6-v2")))
    scores = [float(s) for s in model.predict([(query, h["text"]) for h in hits])]
    order = sorted(range(len(hits)), key=lambda i: scores[i], reverse=True)[:top_n]
    return [_hit(types, hits[i], scores[i]) for i in order]


class RagRerankNode(Node):
    """Cross-encoder/LLM rerank"""

    node_type: ClassVar[str] = "rag_rerank"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="rag_rerank",
        label="Rag Rerank",
        description="Cross-encoder/LLM rerank",
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
        "hits": InputPort(name="hits", data_type=object, required=True, description="list[RetrievalHit] NEW"),
        "query": InputPort(name="query", data_type=object, required=True, description="str"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[RetrievalHit] NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        backend: Literal["bm25", "cross_encoder"] = Field(default="bm25", title="Backend", description="bm25 lexical rerank (no deps) or cross_encoder (sentence-transformers CrossEncoder).")
        model_name_or_path: str = Field(default='cross-encoder/ms-marco-MiniLM-L-6-v2', title="Model name or path", description="Model name or path.")
        top_n: int = Field(default=5, title="Top n", description="Top n.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'rag' / 'rag_rerank'
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
            raise ImportError(f"rag_rerank: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        backend = str(getattr(self.config, "backend", "bm25") or "bm25")
        if backend == "cross_encoder":
            return {"output": _cross_encoder_rerank(self.config, inputs, _types)}
        if backend != "bm25":
            raise ValueError(f"rag_rerank: unsupported backend {backend!r}")
        return {"output": _hybrid_like_rerank(self.config, inputs, _types)}
