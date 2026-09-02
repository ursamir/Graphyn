"""StructuredLlmNode — JSON-schema extract via mock or OpenAI-compatible HTTP."""
from __future__ import annotations

import importlib
import json
import logging
import os
from typing import Any, ClassVar

from app.core.nodes.base import Node
from app.core.nodes.config import NodeConfig
from app.core.nodes.metadata import NodeMetadata
from app.core.nodes.ports import InputPort, OutputPort

try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("structured_llm.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

StructuredDocument = _types.StructuredDocument

log = logging.getLogger(__name__)


def _text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "text" in value:
            return str(value.get("text") or "")
        if "data" in value and isinstance(value["data"], dict):
            return json.dumps(value["data"])
        return json.dumps(value)
    text = getattr(value, "text", None)
    if text is not None:
        return str(text)
    data = getattr(value, "data", None)
    if isinstance(data, dict):
        return json.dumps(data)
    return str(value)


def _fill_schema(schema: Any, key: str = "value") -> Any:
    if not isinstance(schema, dict):
        return f"mock_{key}"
    t = schema.get("type")
    if t is None and "properties" in schema:
        t = "object"
    if t == "object" or (t is None and "properties" in schema):
        props = schema.get("properties") or {}
        out = {}
        for k, sub in props.items():
            out[k] = _fill_schema(sub if isinstance(sub, dict) else {"type": "string"}, k)
        return out
    if t == "array":
        items = schema.get("items") or {"type": "string"}
        return [_fill_schema(items, key)]
    if t == "integer":
        return 0
    if t == "number":
        return 0.0
    if t == "boolean":
        return False
    if t == "null":
        return None
    # string / default
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]
    return f"mock_{key}"


class StructuredLlmNode(Node):
    """Extract a JSON object matching json_schema from transcript/text."""

    node_type: ClassVar[str] = "structured_llm"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="structured_llm",
        label="Structured LLM",
        description=(
            "Extract JSON matching a schema from text. "
            "Mock fills deterministic placeholders; openai_compat uses chat completions."
        ),
        category="Processing",
        version="1.0.0",
        tags=["llm", "json", "extract", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=True,
        streaming_support=False,
        realtime_support=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(
            name="input",
            data_type=object,
            cardinality="single",
            required=True,
            description="Transcript, text, or any object with .text",
        )
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(
            name="output",
            data_type=object,
            description="StructuredDocument with extracted JSON",
        )
    }

    class Config(NodeConfig):
        provider: str = "mock"  # mock | openai_compat
        json_schema: dict = {}
        schema_name: str = "extracted"
        model: str = "gpt-4o-mini"
        base_url: str = ""
        timeout_s: float = 30.0
        system_prompt: str = "Extract JSON matching the provided schema. Reply with JSON only."

    def process(self, value):
        schema = self.config.json_schema or {"type": "object", "properties": {}}
        provider = (self.config.provider or "mock").strip().lower()
        text = _text_of(value)
        if provider == "mock":
            data = _fill_schema(schema)
            return StructuredDocument(
                data=data if isinstance(data, dict) else {"value": data},
                schema_name=self.config.schema_name,
                provider="mock",
                raw_text=text,
                metadata={"empty_input": not bool(text)},
            )
        if provider != "openai_compat":
            raise RuntimeError(
                f"StructuredLlmNode: unknown provider {provider!r}. Use mock or openai_compat."
            )
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "StructuredLlmNode: provider='openai_compat' requires environment "
                "variable OPENAI_API_KEY. Set the key or use provider='mock'."
            )
        data = self._openai_extract(api_key, text, schema)
        return StructuredDocument(
            data=data,
            schema_name=self.config.schema_name,
            provider="openai_compat",
            raw_text=text,
            metadata={},
        )

    def _openai_extract(self, api_key: str, text: str, schema: dict) -> dict:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "StructuredLlmNode: openai_compat requires the 'httpx' package."
            ) from exc
        base = (self.config.base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        url = f"{base}/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.config.system_prompt},
                {"role": "user", "content": text or ""},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": self.config.schema_name or "extracted",
                    "schema": schema,
                    "strict": False,
                },
            },
        }
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=self.config.timeout_s,
        )
        resp.raise_for_status()
        body = resp.json()
        content = (((body.get("choices") or [{}])[0].get("message") or {}).get("content")) or "{}"
        parsed = json.loads(content) if isinstance(content, str) else content
        if not isinstance(parsed, dict):
            return {"value": parsed}
        return parsed
