"""RagGenerateNode — Generate answer (wrap structured_llm pattern)

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
        _types = importlib.import_module("rag_generate.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

AssembledPrompt = _types.AssembledPrompt
RagAnswer = _types.RagAnswer

log = logging.getLogger(__name__)


class RagGenerateNode(Node):
    """Generate answer (wrap structured_llm pattern)"""

    node_type: ClassVar[str] = "rag_generate"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="rag_generate",
        label="Rag Generate",
        description="Generate answer (wrap structured_llm pattern)",
        category="Processing",
        version="0.1.0",
        tags=["rag", "stub"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "prompt": InputPort(name="prompt", data_type=object, required=True, description="AssembledPrompt NEW"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="RagAnswer NEW"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return typed minimal outputs without heavy ML deps.")
        provider: str = Field(default='openai_compat', title="Provider", description="Provider.")
        model: str = Field(default='gpt-4o-mini', title="Model", description="Model.")
        temperature: float = Field(default=0.0, title="Temperature", description="Temperature.")
        api_secret_name: str = Field(default='OPENAI_API_KEY', title="Api secret name", description="Api secret name.")


    def process(self, inputs=None, **kwargs):
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}
        stub = bool(getattr(self.config, "stub", True))
        prompt = inputs.get("prompt") or inputs.get("input")
        if stub:
            return {
                "output": RagAnswer(
                    answer="[stub] RAG answer — set stub=False and configure provider/secret to call an LLM.",
                    citations=[],
                    metadata={"stub": True, "provider": str(getattr(self.config, "provider", ""))},
                )
            }
        raise ImportError(
            "rag_generate: real LLM call requires httpx + API secret. "
            "Set config.stub=True for offline use."
        )

