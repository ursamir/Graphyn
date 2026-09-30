"""CitationAttachNode — Attach citations to RagAnswer

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
        _types = importlib.import_module("citation_attach.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

RagAnswer = _types.RagAnswer
RetrievalHit = _types.RetrievalHit

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

def _citation_attach(config, inputs, types):
    answer = _text(inputs.get("answer"))
    hits = _docs_from_corpus(inputs.get("hits"))
    style = str(_cfg(config, "style", "bracket") or "bracket")
    min_overlap = int(_num_or(_cfg(config, "min_overlap", 1), 1))
    answer_toks = set(_tokens(answer))
    citations = []
    for doc in hits:
        overlap = len(answer_toks & set(_tokens(doc["text"])))
        if overlap >= min_overlap:
            mark = f"[{doc['chunk_id']}]" if style == "bracket" else doc["chunk_id"]
            citations.append({"chunk_id": doc["chunk_id"], "mark": mark, "overlap": overlap})
    cited = answer
    if citations and style == "bracket":
        cited = answer + " " + " ".join(c["mark"] for c in citations)
    return _T(types, "RagAnswer", answer=cited, citations=citations, metadata={"style": style})



class CitationAttachNode(Node):
    """Attach citations to RagAnswer"""

    node_type: ClassVar[str] = "citation_attach"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="citation_attach",
        label="Citation Attach",
        description="Attach citations to RagAnswer",
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
        "answer": InputPort(name="answer", data_type=object, required=True, description="RagAnswer NEW"),
        "hits": InputPort(name="hits", data_type=object, required=True, description="list[RetrievalHit] NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="RagAnswer NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        style: str = Field(default='numeric', title="Style", description="Style.")
        min_overlap: float = Field(default=0.2, title="Min overlap", description="Min overlap.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'rag' / 'citation_attach'
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
            result = RagAnswer()
            return {"output": result}
        # Non-stub: attempt real backend; fall back with install hint
        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"citation_attach: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _citation_attach(self.config, inputs, _types)}
