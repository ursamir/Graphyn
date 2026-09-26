"""RagGenerateNode — generate answer via stub / openai_compat / ollama."""
from __future__ import annotations

import importlib
import logging
from typing import Any, ClassVar, Literal

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


def _prompt_to_messages(prompt: Any) -> list[dict[str, str]]:
    if prompt is None:
        return [{"role": "user", "content": ""}]
    if isinstance(prompt, str):
        return [{"role": "user", "content": prompt}]
    if isinstance(prompt, dict):
        msgs = prompt.get("messages")
        if isinstance(msgs, list) and msgs:
            out = []
            for m in msgs:
                if isinstance(m, dict):
                    out.append({"role": str(m.get("role") or "user"), "content": str(m.get("content") or "")})
                else:
                    out.append({"role": "user", "content": str(m)})
            return out
        system = str(prompt.get("system") or "")
        user = str(prompt.get("user") or prompt.get("text") or prompt.get("prompt") or "")
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        return messages
    system = str(getattr(prompt, "system", "") or "")
    user = str(getattr(prompt, "user", "") or "")
    msgs = getattr(prompt, "messages", None)
    if isinstance(msgs, list) and msgs:
        out = []
        for m in msgs:
            if isinstance(m, dict):
                out.append({"role": str(m.get("role") or "user"), "content": str(m.get("content") or "")})
            else:
                out.append({"role": "user", "content": str(m)})
        return out
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user or str(prompt)})
    return messages


class RagGenerateNode(Node):
    """Generate RAG answer (stub | openai_compat | ollama)."""

    node_type: ClassVar[str] = "rag_generate"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="rag_generate",
        label="RAG Generate",
        description=(
            "Generate answer from an assembled prompt. "
            "Providers: stub, openai_compat, ollama."
        ),
        category="Processing",
        version="0.2.0",
        tags=["rag", "llm", "openai", "ollama"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "prompt": InputPort(name="prompt", data_type=object, required=True, description="AssembledPrompt or text"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="RagAnswer"),
    }

    class Config(NodeConfig):
        stub: bool = Field(default=True, title="Stub mode", description="When true, return stub RagAnswer (no network).")
        provider: Literal["stub", "openai_compat", "ollama"] = Field(
            default="stub",
            title="Provider",
            description="stub | openai_compat | ollama",
        )
        model: str = Field(default="gpt-4o-mini", title="Model", description="Chat model id.")
        temperature: float = Field(default=0.0, title="Temperature", description="Sampling temperature.")
        api_secret_name: str = Field(default="OPENAI_API_KEY", title="API secret name", description="Secret/env for openai_compat.")
        base_url: str = Field(default="", title="Base URL", description="OpenAI-compatible base URL override.")
        timeout_s: float = Field(default=60.0, title="Timeout (s)", description="HTTP timeout.")

    def process(self, inputs=None, **kwargs):
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}
        stub = bool(getattr(self.config, "stub", True))
        provider = (getattr(self.config, "provider", None) or "stub").strip().lower()
        prompt = inputs.get("prompt") or inputs.get("input")
        if stub or provider == "stub":
            return {
                "output": RagAnswer(
                    answer="[stub] RAG answer — set stub=False and provider=openai_compat|ollama to call an LLM.",
                    citations=[],
                    metadata={"stub": True, "provider": provider},
                )
            }

        messages = _prompt_to_messages(prompt)
        from app.core.llm_client import NeedsCredentialsError, chat_completion

        try:
            result = chat_completion(
                messages=messages,
                provider=provider,
                model=getattr(self.config, "model", None) or "gpt-4o-mini",
                temperature=float(getattr(self.config, "temperature", 0.0) or 0.0),
                base_url=(getattr(self.config, "base_url", "") or "") or None,
                api_secret_name=getattr(self.config, "api_secret_name", None) or "OPENAI_API_KEY",
                timeout_s=float(getattr(self.config, "timeout_s", 60.0) or 60.0),
            )
        except NeedsCredentialsError:
            raise
        except Exception as exc:
            raise RuntimeError(f"rag_generate: provider={provider!r} failed: {exc}") from exc

        return {
            "output": RagAnswer(
                answer=str(result.get("content") or ""),
                citations=[],
                metadata={
                    "stub": False,
                    "provider": result.get("provider"),
                    "model": result.get("model"),
                    "base_url": result.get("base_url"),
                },
            )
        }
