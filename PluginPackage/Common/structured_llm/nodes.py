"""StructuredLlmNode — JSON-schema extract via OpenAI-compatible HTTP or local heuristic."""
from __future__ import annotations

import importlib
import json
import logging
import re
import time
from typing import Any, ClassVar, Literal
from pydantic import Field, model_validator

from app.core.trust.egress import validate_http_egress_url
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
    from app.core.nodes.payload import wrapper_field, unwrap_payload

    # F19 (F-06): read the payload, not the upstream wrapper.
    if wrapper_field(value) is not None:
        value = unwrap_payload(value)
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


def _base_looks_like_groq(base: str) -> bool:
    return "groq.com" in (base or "").strip().lower()


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


_NEG = ("angry", "upset", "terrible", "frustrated", "cancel", "unhappy", "disappointed")
_POS = ("great", "thanks", "happy", "love", "excellent", "pleased")


def _rule_based_extract(text: str, schema: dict) -> tuple[dict, list[str]]:
    """Deterministic, explicitly *non-LLM* field extraction (F19 / F-23).

    Only fills a field when a concrete rule matches the text; every other field
    is ``None`` and reported in ``unfilled``. It never copies the whole input
    into fields to look complete.
    """
    props = (schema or {}).get("properties") or {}
    raw = (text or "").strip()
    lowered = raw.lower()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw) if s.strip()]

    def _sentences_with(words: tuple[str, ...]) -> list[str]:
        return [s for s in sentences if any(w in s.lower() for w in words)]

    out: dict[str, Any] = {}
    for name, prop in props.items():
        prop = prop if isinstance(prop, dict) else {}
        key = str(name).lower()
        ptype = prop.get("type") or "string"
        enum = prop.get("enum") if isinstance(prop.get("enum"), list) else None
        val: Any = None
        if enum:
            hits = [e for e in enum if isinstance(e, str) and re.search(rf"\b{re.escape(e.lower())}\b", lowered)]
            val = hits[0] if len(hits) == 1 else None
        elif key == "sentiment":
            neg = any(w in lowered for w in _NEG)
            pos = any(w in lowered for w in _POS)
            val = "negative" if neg and not pos else "positive" if pos and not neg else None
        elif key == "summary" and ptype == "string" and sentences:
            val = sentences[0]  # extractive: the first sentence, labelled rule_based
        elif key in ("pain", "issue", "problem"):
            hits = _sentences_with(("pain", "issue", "problem", "blocked", "frustrat"))
            val = (hits if ptype == "array" else hits[0]) if hits else None
        elif key in ("next_step", "action_items"):
            hits = _sentences_with(("next step", "follow up", "follow-up", "schedule", "action item", " will "))
            val = (hits[:5] if ptype == "array" else hits[0]) if hits else None
        elif key == "objections":
            hits = _sentences_with(("however", "concern", "too expensive", "expensive", "risk", " but "))
            val = hits[:5] if hits else None
        elif key in ("email", "contact_email"):
            m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", raw)
            val = m.group(0) if m else None
        elif key in ("customer_id", "id", "ticket_id", "order_id"):
            m = re.search(r"\b(?:cust(?:omer)?[_ -]?id|ticket|order|id)[:\s#]*([A-Za-z0-9\-]{3,})\b", raw, re.I)
            val = m.group(1) if m else None
        elif ptype in ("integer", "number"):
            m = re.search(rf"\b{re.escape(key)}\b\D{{0,12}}(\d+(?:\.\d+)?)", lowered)
            if m:
                val = int(float(m.group(1))) if ptype == "integer" else float(m.group(1))
        elif ptype == "boolean":
            m = re.search(rf"\b{re.escape(key)}\b\W{{0,6}}(yes|no|true|false)\b", lowered)
            if m:
                val = m.group(1) in ("yes", "true")
        out[name] = val
    unfilled = [n for n, v in out.items() if v is None]
    return out, unfilled


_FENCE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?```\s*$", re.S | re.I)


def _parse_json_object(content: Any) -> dict:
    """Parse a model reply into a JSON object (code fences tolerated)."""
    if isinstance(content, dict):
        return content
    text = str(content or "").strip()
    m = _FENCE.match(text)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        data = None
        if 0 <= start < end:
            try:
                data = json.loads(text[start : end + 1])
            except Exception:
                data = None
        if data is None:
            return {"raw": content}
    return data if isinstance(data, dict) else {"value": data}


class StructuredLlmNode(Node):
    """Extract a JSON object matching json_schema from transcript/text."""

    node_type: ClassVar[str] = "structured_llm"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="structured_llm",
        label="Structured LLM",
        description=(
            "Extract JSON matching a schema from text with a real LLM. provider=auto (default) "
            "uses the configured provider (connection / workspace default, local Ollama, or an "
            "API key) and fails clearly when none is configured. rule_based is an explicit "
            "non-LLM keyword extractor: unmatched fields stay null and are listed as unfilled."
        ),
        category="Processing",
        version="1.1.0",
        tags=["llm", "json", "extract", "common"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        # Remote LLM output is not reproducible and each run is real egress:
        # never cache, never claim determinism.
        deterministic=False,
        cacheable=False,
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
            data_type=StructuredDocument,
            description="StructuredDocument with extracted JSON",
        )
    }

    class Config(NodeConfig):
        provider: Literal["auto", "openai_compat", "ollama", "anthropic", "gemini", "rule_based"] = Field(
            default="auto",
            title="Provider",
            description=(
                "auto (default): the configured LLM (connection / workspace default, local Ollama "
                "via OLLAMA_BASE_URL, or an API key); fails clearly if none. openai_compat | ollama | "
                "anthropic | gemini: that provider. rule_based: deterministic keyword rules, NOT an "
                "LLM — unmatched fields are left empty and listed as unfilled in the result."
            ),
        )

        @model_validator(mode="before")
        @classmethod
        def _legacy_provider(cls, data: Any) -> Any:
            if isinstance(data, dict) and str(data.get("provider") or "").strip().lower() == "local_heuristic":
                data = dict(data)
                data["provider"] = "rule_based"
                log.warning("structured_llm: provider 'local_heuristic' is now 'rule_based' (not an LLM)")
            return data
        json_schema: dict = Field(default={}, title="JSON Schema", description="JSON Schema object the model must satisfy.")
        schema_name: str = Field(default="extracted", title="Schema name", description="Name attached to the structured-output schema for the provider.")
        model: str = Field(default="gpt-4o-mini", title="Model", description="Chat model id. Ollama uses OLLAMA_MODEL / the connection default when left as gpt-*.")
        base_url: str = Field(default="", title="Base URL", description="OpenAI-compatible base URL override. Groq: https://api.groq.com/openai/v1")
        timeout_s: float = Field(default=30.0, title="Timeout (s)", description="Request/operation timeout in seconds.")
        system_prompt: str = Field(
            default="Extract JSON matching the provided schema. Reply with JSON only.",
            title="System prompt",
            description="System instruction for extraction; keep output JSON-only.",
        )
        connection_id: str = Field(
            default="",
            title="Credential connection id",
            description="Platform credential connection id. Empty → workspace default → env.",
        )

    def process(self, value):
        schema = self.config.json_schema or {"type": "object", "properties": {}}
        provider = (self.config.provider or "auto").strip().lower()
        text = _text_of(value)
        if provider in ("rule_based", "local_heuristic"):
            data, unfilled = _rule_based_extract(text, schema)
            return StructuredDocument(
                data=data,
                schema_name=self.config.schema_name,
                provider="rule_based",
                raw_text=text,
                metadata={"mode": "rule_based", "is_llm": False, "unfilled": unfilled},
            )
        selected_by = "explicit"
        if provider == "auto":
            from app.core.ml.llm_client import NeedsCredentialsError, resolve_auto_provider

            try:
                provider, selected_by = resolve_auto_provider(
                    (getattr(self.config, "connection_id", "") or "") or None
                )
            except NeedsCredentialsError as exc:
                raise NeedsCredentialsError(f"structured_llm: {exc}") from exc

        if provider in ("ollama", "anthropic", "gemini"):
            from app.core.ml.llm_client import chat_completion
            import json as _json
            model = self.config.model or ""
            if provider == "ollama" and str(model).startswith("gpt-"):
                model = ""  # llm_client picks OLLAMA_MODEL / connection default
            schema = self.config.json_schema or {"type": "object", "properties": {}}
            sys_prompt = (
                (self.config.system_prompt or "Extract JSON matching the schema. Reply with JSON only.")
                + " Schema: " + _json.dumps(schema)
            )
            _msgs = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": text or ""},
            ]
            _t0 = time.monotonic()
            result = chat_completion(
                messages=_msgs,
                provider=provider,
                model=model,
                temperature=0.0,
                base_url=(self.config.base_url or "") or None,
                api_secret_name="",
                connection_id=(getattr(self.config, "connection_id", "") or "") or None,
                timeout_s=float(self.config.timeout_s or 30.0),
            )
            content = result.get("content") or "{}"
            self.record_external_call(
                "llm", "POST", str(result.get("base_url") or f"llm://{provider}"), 200,
                request_sha256=self.body_sha256({"model": model, "messages": _msgs}),
                response_sha256=str(content), duration_ms=(time.monotonic() - _t0) * 1000.0,
                connection_id=(getattr(self.config, "connection_id", "") or "") or None,
            )
            data = _parse_json_object(content)
            return StructuredDocument(
                data=data,
                schema_name=self.config.schema_name,
                provider=provider,
                raw_text=text,
                metadata={"mode": provider, "is_llm": True, "model": str(result.get("model") or model),
                          "provider_selected_by": selected_by},
            )
        if provider != "openai_compat":

            raise RuntimeError(
                f"StructuredLlmNode: unknown provider {provider!r}. "
                "Use auto, openai_compat, ollama, anthropic, gemini, or rule_based."
            )
        # Same credential precedence + endpoint binding as llm_client.chat_completion:
        # a resolved key is never sent to a node base_url it is not bound to.
        from app.core.ml.llm_client import NeedsCredentialsError, resolve_llm_endpoint
        node_base = (self.config.base_url or "").strip().rstrip("/")
        if node_base:
            # Egress policy first (fail before any credential is resolved).
            validate_http_egress_url(f"{node_base}/chat/completions")
        try:
            endpoint = resolve_llm_endpoint(
                provider="openai_compat",
                base_url=(self.config.base_url or "").strip() or None,
                api_secret_name="OPENAI_API_KEY",
                connection_id=(getattr(self.config, "connection_id", "") or "") or None,
            )
        except NeedsCredentialsError as exc:
            raise RuntimeError(
                f"StructuredLlmNode: {exc} For a non-LLM keyword extractor use provider='rule_based'."
            ) from exc
        api_key = endpoint["api_key"]
        base = endpoint["base_url"]
        data = self._openai_extract(api_key, text, schema, base=base)
        return StructuredDocument(
            data=data,
            schema_name=self.config.schema_name,
            provider="openai_compat",
            raw_text=text,
            metadata={"mode": "openai_compat", "is_llm": True, "provider_selected_by": selected_by},
        )

    def _post_audited(self, httpx: Any, url: str, api_key: str, payload: dict) -> Any:
        """POST to the LLM endpoint and record the call for the run audit (G6)."""
        t0 = time.monotonic()
        conn = (getattr(self.config, "connection_id", "") or "") or None
        try:
            from app.core.trust import egress as _egress

            # F19: egress-checked, IP-pinned POST (DNS-rebinding safe).
            resp = _egress.egress_post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=self.config.timeout_s,
            )
        except Exception as exc:
            self.record_external_call(
                "llm", "POST", url, None, request_sha256=self.body_sha256(payload),
                duration_ms=(time.monotonic() - t0) * 1000.0, connection_id=conn,
                error=type(exc).__name__,
            )
            raise
        body = getattr(resp, "content", None)
        self.record_external_call(
            "llm", "POST", url, getattr(resp, "status_code", None),
            request_sha256=self.body_sha256(payload),
            response_sha256=body if isinstance(body, (bytes, bytearray)) else None,
            duration_ms=(time.monotonic() - t0) * 1000.0, connection_id=conn,
        )
        return resp

    def _openai_extract(self, api_key: str, text: str, schema: dict, *, base: str) -> dict:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "StructuredLlmNode: openai_compat requires the 'httpx' package. "
                "Install httpx (e.g. pip install httpx)."
            ) from exc
        base = (base or "").rstrip("/")
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
        validate_http_egress_url(url)
        resp = self._post_audited(httpx, url, api_key, payload)
        status_code = int(getattr(resp, "status_code", 200) or 200)
        if status_code >= 400 and _base_looks_like_groq(base):
            payload["response_format"] = {"type": "json_object"}
            payload["messages"][0]["content"] = (
                self.config.system_prompt
                + " Schema: "
                + json.dumps(schema)
            )
            validate_http_egress_url(url)
            resp = self._post_audited(httpx, url, api_key, payload)
        resp.raise_for_status()
        body = resp.json()
        content = (((body.get("choices") or [{}])[0].get("message") or {}).get("content")) or "{}"
        return _parse_json_object(content)
