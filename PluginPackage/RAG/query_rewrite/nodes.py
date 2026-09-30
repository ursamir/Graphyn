"""QueryRewriteNode — Rewrite/HyDE/multi-query

Auto-scaffolded from docs/PLUGIN_NODE_PLATFORM_CATALOG.json.
Default config.stub=False runs the real implementation.
"""
from __future__ import annotations

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
        _types = importlib.import_module("query_rewrite.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

log = logging.getLogger(__name__)

def _cfg(config: Any, name: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)

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

def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())

def _query_rewrite(config, inputs, types):
    query = _text(inputs.get("query") or inputs.get("input"))
    n = max(1, int(_cfg(config, "n_queries", 3) or 3))
    strategy = str(_cfg(config, "strategy", "paraphrase") or "paraphrase")
    variants = [query]
    tokens = _tokens(query)
    if strategy == "keyword" and tokens:
        variants.append(" ".join(tokens))
    if len(tokens) > 2:
        variants.append(" ".join(tokens[: max(1, len(tokens) // 2)]))
        variants.append(" ".join(reversed(tokens)))
    # Deduplicate while preserving order.
    seen = []
    for item in variants:
        if item and item not in seen:
            seen.append(item)
    return seen[:n]



class QueryRewriteNode(Node):
    """Rewrite/HyDE/multi-query"""

    node_type: ClassVar[str] = "query_rewrite"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="query_rewrite",
        label="Query Rewrite",
        description="Rewrite/HyDE/multi-query",
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
        "query": InputPort(name="query", data_type=object, required=True, description="str"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="list[str]"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=False, title="Stub mode", description="Opt-in placeholder. Default runs the real implementation.")
        strategy: str = Field(default='rewrite', title="Strategy", description="Strategy.")
        n_queries: int = Field(default=3, title="N queries", description="N queries.")
        model: str = Field(default='gpt-4o-mini', title="Model", description="Model.")
        api_secret_name: str = Field(default='OPENAI_API_KEY', title="Api secret name", description="Api secret name.")

    def process(self, inputs=None, **kwargs):
        """Stub-capable process — real backends optional."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, 'stub', False))
        out_dir = Path('workspace/artifacts') / 'rag' / 'query_rewrite'
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
            raise ImportError(f"query_rewrite: optional dependency missing ({exc}). Install plugin optional_dependencies or set config.stub=True.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return {"output": _query_rewrite(self.config, inputs, _types)}
