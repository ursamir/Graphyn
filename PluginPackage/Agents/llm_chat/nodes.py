"""LlmChatNode — multi-turn chat via stub / openai_compat / ollama."""
from __future__ import annotations

import json

import importlib
import logging
import time
from typing import Any, ClassVar, Literal

from pydantic import Field, model_validator

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

def _echo_text(raw: Any) -> str:
    """provider='echo': the user's last message, verbatim (no model involved)."""
    msgs = _normalize_messages(raw)
    users = [m["content"] for m in msgs if m.get("role") == "user"]
    return users[-1] if users else (msgs[-1]["content"] if msgs else "")


def _normalize_messages(raw: Any) -> list[dict[str, str]]:
    from app.core.nodes.payload import wrapper_field, unwrap_payload

    # F19 (F-06): a CodeResult / MappedPayload / … carries the real payload.
    if wrapper_field(raw) is not None:
        raw = unwrap_payload(raw)
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


_LEGACY_PROVIDER = {"local": "auto", "stub": "echo", "local_stub": "echo"}


class LlmChatNode(Node):
    """Multi-turn chat completion against a real LLM provider (or explicit echo)."""

    node_type: ClassVar[str] = "llm_chat"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="llm_chat",
        label="LLM Chat",
        description=(
            "Multi-turn chat with a real model. provider=auto (default) uses the configured "
            "provider: a credential connection / workspace default, a local Ollama "
            "(OLLAMA_BASE_URL), or an OpenAI-compatible / Anthropic / Gemini key — and fails "
            "with a clear needs-credentials error when none is configured. provider=echo returns "
            "the input unchanged for tests and is labelled as not an LLM."
        ),
        category="Processing",
        version="0.3.0",
        tags=["agents", "llm", "openai", "ollama"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        # Remote model sampling is not reproducible (even at temperature 0).
        deterministic=False,
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
            default=False,
            title="Stub mode",
            description="Deprecated: same as provider=echo. Returns a labelled placeholder, never a model answer.",
        )
        provider: Literal["auto", "openai_compat", "ollama", "anthropic", "gemini", "echo"] = Field(
            default="auto",
            title="Provider",
            description=(
                "auto (default): the configured LLM — connection / workspace default, local Ollama "
                "(OLLAMA_BASE_URL), or an API key; fails clearly if none is set. openai_compat | "
                "ollama | anthropic | gemini: that provider. echo: returns your input unchanged "
                "(for tests; not an LLM)."
            ),
        )
        model: str = Field(default="gpt-4o-mini", title="Model", description="Chat model id. Ollama uses OLLAMA_MODEL / the connection default when left as gpt-*.")
        temperature: float = Field(default=0.2, ge=0, title="Temperature", description="Sampling temperature (0 allowed).")
        api_secret_name: str = Field(
            default="OPENAI_API_KEY",
            title="API secret name",
            description="Secret/env name for openai_compat. Unused for echo/ollama.",
        )
        base_url: str = Field(
            default="",
            title="Base URL",
            description="OpenAI-compatible base URL override (must pass the egress policy).",
        )
        system_prompt: str = Field(
            default="",
            title="System prompt",
            description="Optional system message prepended when not already present.",
        )
        timeout_s: float = Field(default=60.0, gt=0, title="Timeout (s)", description="HTTP timeout.")
        connection_id: str = Field(
            default="",
            title="Credential connection id",
            description="Graphyn credential store connection id (kind matches provider). Empty → workspace default → env.",
        )

        @model_validator(mode="before")
        @classmethod
        def _legacy_provider(cls, data: Any) -> Any:
            """``local`` (was an extractive echo) → ``auto``; ``stub`` → ``echo``."""
            if isinstance(data, dict):
                prov = str(data.get("provider") or "").strip().lower()
                if prov in _LEGACY_PROVIDER:
                    data = dict(data)
                    data["provider"] = _LEGACY_PROVIDER[prov]
                    log.warning(
                        "llm_chat: provider=%r is deprecated; using %r", prov, data["provider"]
                    )
            return data

    def process(self, inputs=None, **kwargs):
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        raw = inputs.get("messages")
        if raw is None:
            raw = inputs.get("input")
        provider = (getattr(self.config, "provider", None) or "auto").strip().lower()
        if bool(getattr(self.config, "stub", False)) or provider == "echo":
            return {
                "output": ChatMessage(
                    role="assistant",
                    content=_echo_text(raw),
                    metadata={"provider": "echo", "is_llm": False,
                              "note": "echo provider: input returned unchanged, no model was called"},
                )
            }

        conn_id = (getattr(self.config, "connection_id", "") or "") or None
        from app.core.ml.llm_client import NeedsCredentialsError, chat_completion, resolve_auto_provider

        reason = "explicit"
        if provider == "auto":
            try:
                provider, reason = resolve_auto_provider(conn_id)
            except NeedsCredentialsError as exc:
                raise NeedsCredentialsError(f"llm_chat: {exc}") from exc

        messages = _normalize_messages(raw)
        system = (getattr(self.config, "system_prompt", "") or "").strip()
        if system and not any(m.get("role") == "system" for m in messages):
            messages = [{"role": "system", "content": system}, *messages]
        if not messages:
            messages = [{"role": "user", "content": ""}]

        model = getattr(self.config, "model", None) or "gpt-4o-mini"
        req_hash = self.body_sha256({"model": model, "messages": messages,
                                     "temperature": float(self.config.temperature)})
        t0 = time.monotonic()
        try:
            result = chat_completion(
                messages=messages,
                provider=provider,
                model=model,
                temperature=float(self.config.temperature),
                base_url=(getattr(self.config, "base_url", "") or "") or None,
                api_secret_name=getattr(self.config, "api_secret_name", None) or "OPENAI_API_KEY",
                connection_id=conn_id,
                timeout_s=float(self.config.timeout_s),
            )
        except NeedsCredentialsError:
            raise
        except Exception as exc:
            self.record_external_call(
                "llm", "POST", (getattr(self.config, "base_url", "") or f"llm://{provider}"), None,
                request_sha256=req_hash, duration_ms=(time.monotonic() - t0) * 1000.0,
                connection_id=conn_id, error=type(exc).__name__,
            )
            raise RuntimeError(f"llm_chat: provider={provider!r} failed: {exc}") from exc

        self.record_external_call(
            "llm", "POST", str(result.get("base_url") or f"llm://{provider}"), 200,
            request_sha256=req_hash, response_sha256=str(result.get("content") or ""),
            duration_ms=(time.monotonic() - t0) * 1000.0, connection_id=conn_id,
        )
        return {
            "output": ChatMessage(
                role="assistant",
                content=str(result.get("content") or ""),
                metadata={
                    "provider": str(result.get("provider") or provider),
                    "model": str(result.get("model") or model),
                    "is_llm": True,
                    "provider_selected_by": reason,
                },
            )
        }
