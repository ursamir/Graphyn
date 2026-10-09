"""ToolRouterNode — Route tool-calls to registered tools

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

try:  # canonical inter-node payload contract (F-06)
    from app.core.nodes.payload import unwrap_payload as _unwrap_payload, wrapper_field as _wrapper_field

    def _unwrap(v):
        """Unwrap known wrappers (python_code / csv_table / http_request …); keep typed inputs as-is."""
        return _unwrap_payload(v) if _wrapper_field(v) is not None else v
except Exception:  # pragma: no cover - older core
    def _unwrap(v):
        return v


try:
    _pkg = __name__.rsplit(".", 1)[0] if "." in __name__ else __name__
    _types = importlib.import_module(f"{_pkg}.types")
except (ImportError, ModuleNotFoundError):
    try:
        _types = importlib.import_module("tool_router.types")
    except (ImportError, ModuleNotFoundError):
        from . import types as _types  # type: ignore

ToolCallRequest = _types.ToolCallRequest
ToolCallResult = _types.ToolCallResult

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


_NEGATION = re.compile(r"\b(?:not|never|no|don'?t|dont|do not|without|avoid)\W+(?:\w+\W+){0,2}$", re.I)


_CLAUSE_BREAK = re.compile(r"[;,.!?\n]|\b(?:but|instead|rather|then|and)\b", re.I)


def _negated(prefix: str) -> bool:
    """True when the current clause (text before the match) negates it."""
    parts = _CLAUSE_BREAK.split(prefix)
    clause = parts[-1] if parts else prefix
    return bool(_NEGATION.search(clause))


def _tool_specs(tools: list) -> list[tuple[str, list[str]]]:
    """Normalize config.tools → [(name, match_terms)]."""
    out: list[tuple[str, list[str]]] = []
    for tool in tools:
        data = tool if isinstance(tool, str) else (_dump(tool) or {})
        if isinstance(data, str):
            name, keywords = data, []
        elif isinstance(data, dict):
            name = str(data.get("name") or "")
            keywords = [str(k) for k in (data.get("keywords") or []) if str(k).strip()]
        else:
            continue
        name = name.strip()
        if not name:
            continue
        terms = {name.lower(), name.lower().replace("_", " "), *(k.lower() for k in keywords)}
        out.append((name, sorted(terms, key=len, reverse=True)))
    return out


def _parse_request(raw: Any) -> tuple[str, dict, str]:
    """Return ``(explicit_tool, arguments, text)`` from a ToolCallRequest / dict / text."""
    data = _dump(raw)
    if isinstance(data, dict) and ("tool" in data or "arguments" in data):
        args = data.get("arguments")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            args = {"input": args}
        text = _text(args) if args else ""
        return str(data.get("tool") or "").strip(), dict(args), text
    text = _text(raw)
    return "", {"input": text}, text


def _keyword_match(text: str, specs: list[tuple[str, list[str]]]) -> tuple[str | None, str]:
    """Longest non-negated word-boundary match wins; ties between tools → ambiguous."""
    best_len = 0
    best: set[str] = set()
    for name, terms in specs:
        for term in terms:
            pat = re.compile(r"(?<![\w])" + re.escape(term).replace(r"\ ", r"[\s_]+") + r"(?![\w])", re.I)
            for m in pat.finditer(text):
                if _negated(text[: m.start()]):
                    continue
                if len(term) > best_len:
                    best_len, best = len(term), {name}
                elif len(term) == best_len:
                    best.add(name)
                break
    if len(best) == 1:
        return next(iter(best)), "keyword"
    if len(best) > 1:
        return None, f"ambiguous keyword match: {sorted(best)}"
    return None, "no tool matched"


def _tool_router(config, inputs, types) -> dict:
    specs = _tool_specs(list(config.tools or []))
    names = {n.lower(): n for n, _ in specs}
    explicit, arguments, text = _parse_request(_unwrap(inputs.get("input")))

    chosen: str | None = None
    reason = ""
    if explicit:
        chosen = names.get(explicit.lower())
        reason = "exact" if chosen else f"tool {explicit!r} is not registered"
    else:
        chosen, reason = _keyword_match(text, specs)
        if chosen is None and specs and not bool(config.strict):
            chosen, reason = specs[0][0], "fallback (strict=False)"

    if chosen is None:
        unmatched = ToolCallRequest(tool=explicit, arguments=arguments)
        log.info("tool_router: unmatched (%s)", reason)
        return {"output": None, "unmatched": unmatched}
    return {"output": ToolCallRequest(tool=chosen, arguments=arguments), "unmatched": None}



class ToolRouterNode(Node):
    """Route tool-calls to registered tools"""

    node_type: ClassVar[str] = "tool_router"

    metadata: ClassVar[NodeMetadata] = NodeMetadata(
        node_type="tool_router",
        label="Tool Router",
        description="Route tool-calls to registered tools",
        category="Agents",
        version="0.1.0",
        tags=["agents"],
        requires_gpu=False,
        supports_cpu=True,
        supports_edge=True,
        deterministic=True,
        cacheable=False,
    )

    input_ports: ClassVar[dict[str, InputPort]] = {
        "input": InputPort(name="input", data_type=object, required=True, description="ToolCallRequest (tool + arguments) or free text"),
    }

    output_ports: ClassVar[dict[str, OutputPort]] = {
        "output": OutputPort(name="output", data_type=object, description="ToolCallRequest routed to a registered tool (None when unmatched)"),
        "unmatched": OutputPort(name="unmatched", data_type=object, description="ToolCallRequest that matched no tool (None when routed)"),
    }

    class Config(NodeConfig):
        tools: list = Field(default_factory=list, title="Tools", description="Tool names or {name, keywords[]} dicts.")
        strict: bool = Field(default=True, title="Strict", description="When false, unmatched text falls back to the first tool.")

    def process(self, inputs=None, **kwargs):
        """Run the node."""
        if inputs is None:
            inputs = kwargs
        if not isinstance(inputs, dict):
            inputs = {"input": inputs}

        try:
            return self._process_real(inputs)
        except ImportError as exc:
            raise ImportError(f"tool_router: required dependency missing ({exc}). Install the plugin dependencies.") from exc



    def _process_real(self, inputs: dict):
        """Run this node's real implementation."""
        return _tool_router(self.config, inputs, _types)
