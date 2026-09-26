"""LlmChatNode — multi-turn chat via stub / openai_compat / ollama."""
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
        _types = importlib.import_module("llm_chat.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

ChatMessage = _types.ChatMessage

log = logging.getLogger(__name__)


def _normalize_messages(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        if "messages" in raw:
            raw = raw["messages"]
        elif "content" in raw or "role" in raw:
            raw = [raw]
        elif "text" in raw or "input" in raw or "prompt" in raw:
            text = raw.get("text") or raw.get("input") or raw.get("prompt") or ""
            return [{"role": "user", "content": str(text)}]
        else:
            return [{"role": "user", "content": str(raw)}]
    if isinstance(raw, str):
        return [{"role": "user", "content": raw}]
    if hasattr(raw, "content") and hasattr(raw, "role"):
        return [{"role": str(getattr(raw, "role", "user")), "content": str(getattr(raw, "content", ""))}]
    if not isinstance(raw, (list, tuple)):
        return [{"role": "user", "content": str(raw)}]
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append({
                "role": str(item.get("role") or "user"),
                "content": str(item.get("content") or item.get("text") or ""),
            })
        elif hasattr(item, "content"):
            out.append({
                "role": str(getattr(item, "role", "user")),
                "content": str(getattr(item, "content", "")),
            })
        else:
            out.append({"role": "user", "content": str(item)})
    return out


class LlmChatNode(Node):
    """Multi-turn chat completion (stub | openai_compat | ollama)."""

    node_type: ClassVar[str] = "llm_chat"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="llm_chat",
        label="LLM Chat",
        description=(
            "Multi-turn chat. Providers: stub, openai_compat, ollama, "
            "anthropic (ANTHROPIC_API_KEY), gemini (GEMINI_API_KEY)."
        ),
        category="Processing",
        version="0.2.0",
        tags=["agents", "llm", "openai", "ollama"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "messages": InputPort(
            name="messages",
            data_type=object | None,
            required=False,
            description="list[dict] chat messages, or string/prompt object",
        ),
        "input": InputPort(
            name="input",
            data_type=object | None,
            required=False,
            description="Alternate input (linear chains); coerced to user message",
        ),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="ChatMessage"),
    }

    class Config(NodeConfig):
        stub: bool = Field(
            default=True,
            title="Stub mode",
            description="When true, return a deterministic stub ChatMessage (no network).",
        )
        provider: Literal["stub", "openai_compat", "ollama", "anthropic", "gemini"] = Field(
            default="stub",
            title="Provider",
            description="stub | openai_compat | ollama | anthropic | gemini",
        )
        model: str = Field(default="gpt-4o-mini", title="Model", description="Chat model id.")
        temperature: float = Field(default=0.2, title="Temperature", description="Sampling temperature.")
        api_secret_name: str = Field(
            default="OPENAI_API_KEY",
            title="API secret name",
            description="Secret/env name for openai_compat. Unused for stub/ollama.",
        )
        base_url: str = Field(
            default="",
            title="Base URL",
            description="OpenAI-compatible base URL override. Ollama default: http://127.0.0.1:11434/v1",
        )
        system_prompt: str = Field(
            default="",
            title="System prompt",
            description="Optional system message prepended when not already present.",
        )
        timeout_s: float = Field(default=60.0, title="Timeout (s)", description="HTTP timeout.")

    def process(self, inputs=None, **kwargs):
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        stub = bool(getattr(self.config, "stub", True))
        provider = (getattr(self.config, "provider", None) or "stub").strip().lower()
        if stub or provider == "stub":
            return {
                "output": ChatMessage(
                    role="assistant",
                    content="[stub] llm_chat — set stub=False and provider=openai_compat|ollama|anthropic|gemini to call a model.",
                )
            }

        raw = inputs.get("messages")
        if raw is None:
            raw = inputs.get("input")
        messages = _normalize_messages(raw)
        system = (getattr(self.config, "system_prompt", "") or "").strip()
        if system and not any(m.get("role") == "system" for m in messages):
            messages = [{"role": "system", "content": system}, *messages]
        if not messages:
            messages = [{"role": "user", "content": ""}]

        from app.core.llm_client import NeedsCredentialsError, chat_completion

        try:
            result = chat_completion(
                messages=messages,
                provider=provider,
                model=getattr(self.config, "model", None) or "gpt-4o-mini",
                temperature=float(getattr(self.config, "temperature", 0.2) or 0.0),
                base_url=(getattr(self.config, "base_url", "") or "") or None,
                api_secret_name=getattr(self.config, "api_secret_name", None) or "OPENAI_API_KEY",
                timeout_s=float(getattr(self.config, "timeout_s", 60.0) or 60.0),
            )
        except NeedsCredentialsError:
            raise
        except Exception as exc:
            raise RuntimeError(f"llm_chat: provider={provider!r} failed: {exc}") from exc

        return {
            "output": ChatMessage(
                role="assistant",
                content=str(result.get("content") or ""),
            )
        }
