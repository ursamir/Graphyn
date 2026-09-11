"""StructuredLlmNode — JSON-schema extract via OpenAI-compatible HTTP or local heuristic."""
from __future__ import annotations

import importlib
import json
import logging
import os
import re
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


def _resolve_key(env_key: str) -> str:
    try:
        from app.core.secrets import resolve_secret
        return resolve_secret(env_key)
    except Exception:
        return os.environ.get(env_key, "").strip()


def _base_looks_like_groq(base: str) -> bool:
    return "groq.com" in (base or "").strip().lower()


def _resolve_openai_compat_key(base_url: str) -> str:
    key = _resolve_key("OPENAI_API_KEY")
    if key:
        return key
    base = (base_url or os.environ.get("OPENAI_BASE_URL") or "").strip()
    if _base_looks_like_groq(base):
        return _resolve_key("GROQ_API_KEY")
    return ""


def _schema_default(prop_schema: dict) -> Any:
    t = (prop_schema or {}).get("type") or "string"
    if t == "array":
        return []
    if t == "object":
        return {}
    if t == "integer":
        return 0
    if t == "number":
        return 0.0
    if t == "boolean":
        return False
    return ""


def _heuristic_extract(text: str, schema: dict) -> dict:
    """Deterministic keyword / sentence extract for E2E when no LLM key is available.

    Not a substitute for a real LLM — fills schema properties from transcript text
    using simple rules so call-analytics / meeting-crm graphs can complete locally.
    """
    props = (schema or {}).get("properties") or {}
    required = list((schema or {}).get("required") or [])
    raw = (text or "").strip()
    lowered = raw.lower()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw) if s.strip()]
    first = sentences[0] if sentences else (raw[:240] if raw else "no transcript")
    words = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", raw)

    out: dict[str, Any] = {}
    for name, prop in props.items():
        if not isinstance(prop, dict):
            prop = {}
        key = str(name).lower()
        ptype = prop.get("type") or "string"

        if key in {"summary", "pain", "next_step", "owner", "customer_id"}:
            if key == "summary":
                out[name] = first
            elif key == "pain":
                hit = next((s for s in sentences if any(w in s.lower() for w in ("pain", "issue", "problem", "blocked", "frustrat"))), first)
                out[name] = hit
            elif key == "next_step":
                hit = next((s for s in sentences if any(w in s.lower() for w in ("next", "follow", "schedule", "action", "will"))), first)
                out[name] = hit
            elif key == "owner":
                m = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", raw)
                out[name] = m.group(1) if m else "owner"
            elif key == "customer_id":
                m = re.search(r"\b(?:cust(?:omer)?[_-]?id|id)[:\s#]*([A-Za-z0-9\-]+)\b", raw, re.I)
                out[name] = m.group(1) if m else "unknown"
            continue

        if key == "sentiment":
            if any(w in lowered for w in ("angry", "upset", "terrible", "frustrated", "cancel")):
                out[name] = "negative"
            elif any(w in lowered for w in ("great", "thanks", "happy", "love", "excellent")):
                out[name] = "positive"
            else:
                out[name] = "neutral"
            continue

        if key in {"topics", "action_items", "objections"} and ptype == "array":
            if key == "topics":
                # top unique content words
                stop = {"the", "and", "for", "that", "this", "with", "from", "have", "will", "your", "our"}
                topics = []
                for w in words:
                    wl = w.lower()
                    if wl in stop or wl in topics:
                        continue
                    topics.append(wl)
                    if len(topics) >= 5:
                        break
                out[name] = topics or ["general"]
            elif key == "action_items":
                items = [s for s in sentences if any(w in s.lower() for w in ("will", "should", "need", "action", "follow", "schedule"))]
                out[name] = items[:5] or ([first] if first else [])
            else:  # objections
                items = [s for s in sentences if any(w in s.lower() for w in ("but", "however", "concern", "object", "expensive", "risk"))]
                out[name] = items[:5]
            continue

        # generic fill
        if ptype == "array":
            out[name] = [first] if first else []
        elif ptype == "integer":
            m = re.search(r"\b(\d+)\b", raw)
            out[name] = int(m.group(1)) if m else 0
        elif ptype == "number":
            m = re.search(r"\b(\d+(?:\.\d+)?)\b", raw)
            out[name] = float(m.group(1)) if m else 0.0
        elif ptype == "boolean":
            out[name] = any(w in lowered for w in ("yes", "true", "confirm"))
        elif ptype == "object":
            out[name] = {"text": first}
        else:
            out[name] = first

    for req in required:
        if req not in out:
            out[req] = _schema_default((props.get(req) or {}))
    return out


class StructuredLlmNode(Node):
    """Extract a JSON object matching json_schema from transcript/text."""

    node_type: ClassVar[str] = "structured_llm"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="structured_llm",
        label="Structured LLM",
        description=(
            "Extract JSON matching a schema from text. "
            "Providers: openai_compat (OPENAI_API_KEY / Groq), local_heuristic (free E2E)."
        ),
        category="Processing",
        version="1.1.0",
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
        provider: Literal["openai_compat", "local_heuristic"] = Field(
            default="openai_compat",
            title="Provider",
            description="LLM backend: openai_compat (HTTP) or local_heuristic (deterministic, free).",
        )
        json_schema: dict = Field(default={}, title="JSON Schema", description="JSON Schema object the model must satisfy.")
        schema_name: str = Field(default="extracted", title="Schema name", description="Name attached to the structured-output schema for the provider.")
        model: str = Field(default="gpt-4o-mini", title="Model", description="Chat model id (default gpt-4o-mini). Requires OPENAI_API_KEY or Groq.")
        base_url: str = Field(default="", title="Base URL", description="OpenAI-compatible base URL override. Groq: https://api.groq.com/openai/v1")
        timeout_s: float = Field(default=30.0, title="Timeout (s)", description="Request/operation timeout in seconds.")
        system_prompt: str = Field(
            default="Extract JSON matching the provided schema. Reply with JSON only.",
            title="System prompt",
            description="System instruction for extraction; keep output JSON-only.",
        )

    def process(self, value):
        schema = self.config.json_schema or {"type": "object", "properties": {}}
        provider = (self.config.provider or "openai_compat").strip().lower()
        text = _text_of(value)
        if provider == "local_heuristic":
            data = _heuristic_extract(text, schema)
            return StructuredDocument(
                data=data,
                schema_name=self.config.schema_name,
                provider="local_heuristic",
                raw_text=text,
                metadata={"mode": "heuristic"},
            )
        if provider != "openai_compat":
            raise RuntimeError(
                f"StructuredLlmNode: unknown provider {provider!r}. "
                "Use openai_compat or local_heuristic."
            )
        api_key = _resolve_openai_compat_key(self.config.base_url or "")
        if not api_key:
            raise RuntimeError(
                "StructuredLlmNode: provider='openai_compat' requires secret/env "
                "OPENAI_API_KEY (or GROQ_API_KEY when base_url is Groq). "
                "For a free local path use provider='local_heuristic'."
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
                "StructuredLlmNode: openai_compat requires the 'httpx' package. "
                "Install httpx (e.g. pip install httpx)."
            ) from exc
        base = (
            self.config.base_url
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        url = f"{base}/chat/completions"
        model = self.config.model
        if _base_looks_like_groq(base) and (not model or model.startswith("gpt-")):
            model = "llama-3.1-8b-instant"
        payload = {
            "model": model,
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
        # Groq may not support json_schema response_format on all models — fall back to json_object
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=self.config.timeout_s,
        )
        status_code = int(getattr(resp, "status_code", 200) or 200)
        if status_code >= 400 and _base_looks_like_groq(base):
            payload["response_format"] = {"type": "json_object"}
            payload["messages"][0]["content"] = (
                self.config.system_prompt
                + " Schema: "
                + json.dumps(schema)
            )
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
