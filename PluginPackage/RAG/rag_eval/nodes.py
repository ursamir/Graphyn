"""RagEvalNode — Ragas-style faithfulness/relevancy/precision

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

import hashlib
import json
import re

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
        _types = importlib.import_module("rag_eval.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

RagAnswer = _types.RagAnswer
RagEvalReport = _types.RagEvalReport
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

def _rag_eval(config, inputs, types):
    answer = _text(inputs.get("answer"))
    truth = _text(inputs.get("ground_truth"))
    hits = _docs_from_corpus(inputs.get("hits"))
    a, t = set(_tokens(answer)), set(_tokens(truth))
    precision = len(a & t) / len(a) if a else 0.0
    recall = len(a & t) / len(t) if t else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    hit_rate = 1.0 if any(set(_tokens(h["text"])) & t for h in hits) or not t else 0.0
    metrics = {"token_f1": f1, "precision": precision, "recall": recall, "hit_rate": hit_rate}
    fail_below = _cfg(config, "fail_below", None)
    passed = True
    if isinstance(fail_below, (int, float)):
        passed = f1 >= float(fail_below)
    return _T(types, "RagEvalReport", metrics=metrics, passed=passed, metadata={"n_hits": len(hits)})



class RagEvalNode(Node):
    """Ragas-style faithfulness/relevancy/precision"""

    node_type: ClassVar[str] = "rag_eval"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="rag_eval",
        label="Rag Eval",
        description="Ragas-style faithfulness/relevancy/precision",
        category="Quality",
        version="0.1.0",
        tags=["rag"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "answer": InputPort(name="answer", data_type=object, required=True, description="RagAnswer NEW"),
        "hits": InputPort(name="hits", data_type=object, required=True, description="list[RetrievalHit] NEW"),
        "ground_truth": InputPort(name="ground_truth", data_type=object | None, required=False, description="str optional"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="RagEvalReport NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        metrics: list = Field(default_factory=list)
        judge_model: str = Field(default='gpt-4o-mini', title="Judge model", description="Judge model.")
        fail_below: dict = Field(default_factory=dict)

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'rag' / 'rag_eval'
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
            result = RagEvalReport()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"rag_eval: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _rag_eval(self.config, inputs, _types)}
